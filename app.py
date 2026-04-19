"""
GlobalMatch Assistant - 人材紹介業務効率化アプリ

外国人エンジニアのレジュメと日本企業の求人票を相互変換・最適化するStreamlitアプリ
"""

import streamlit as st
import streamlit.components.v1
from groq import Groq
import time
import re
import calendar
import html as html_module
from datetime import datetime
import pdfplumber
import io
import json
import secrets
import requests
from bs4 import BeautifulSoup
from datetime import timedelta
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import ipaddress
from translations import TRANSLATIONS, FEATURE_KEYS

# Supabase設定（オプション）
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# 定数
MAX_INPUT_CHARS = 40000  # 最大入力文字数
MIN_INPUT_CHARS = 100    # 最小入力文字数
MAX_RETRIES = 3          # API最大リトライ回数
MAX_PDF_SIZE_MB = 10     # 最大PDFサイズ（MB）
RATE_LIMIT_CALLS = 30    # セッションあたりのAPI呼び出し上限（1時間）
RATE_LIMIT_SHARES = 10   # セッションあたりの共有リンク作成上限（1時間）
RATE_LIMIT_WINDOW = 3600 # レート制限ウィンドウ（秒）
SESSION_TIMEOUT_MINUTES = 120  # セッションタイムアウト（分）
DEFAULT_APP_URL = "https://globalmatch-assistant-zk6s2lwgkqp6xf6xuc9uvi.streamlit.app"


def _check_rate_limit() -> tuple[bool, str]:
    """アプリレベルのレート制限チェック"""
    now = time.time()

    if 'api_call_timestamps' not in st.session_state:
        st.session_state['api_call_timestamps'] = []

    # 期限切れのタイムスタンプを除去
    st.session_state['api_call_timestamps'] = [
        ts for ts in st.session_state['api_call_timestamps']
        if now - ts < RATE_LIMIT_WINDOW
    ]

    if len(st.session_state['api_call_timestamps']) >= RATE_LIMIT_CALLS:
        remaining = int(RATE_LIMIT_WINDOW - (now - st.session_state['api_call_timestamps'][0]))
        return False, f"API呼び出し上限に達しました。{remaining}秒後に再試行してください"

    return True, ""


def _record_api_call():
    """API呼び出しを記録"""
    if 'api_call_timestamps' not in st.session_state:
        st.session_state['api_call_timestamps'] = []
    st.session_state['api_call_timestamps'].append(time.time())


def _check_session_timeout() -> bool:
    """セッションタイムアウトをチェック。タイムアウトの場合Trueを返す"""
    now = datetime.now()

    if 'session_last_activity' not in st.session_state:
        st.session_state['session_last_activity'] = now
        return False

    elapsed = now - st.session_state['session_last_activity']
    if elapsed > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
        return True

    st.session_state['session_last_activity'] = now
    return False


def _check_authentication() -> bool:
    """オプション認証チェック。secrets.tomlにAPP_PASSWORDが設定されている場合のみ認証を要求"""
    try:
        app_password = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        return True  # secrets未設定なら認証不要

    if not app_password:
        return True  # パスワード未設定なら認証不要

    if st.session_state.get('authenticated'):
        return True

    st.markdown("# 🔒 認証が必要です")
    password = st.text_input("パスワードを入力してください", type="password", key="auth_password")
    if st.button("ログイン", key="auth_login"):
        if secrets.compare_digest(password, app_password):
            st.session_state['authenticated'] = True
            st.rerun()
        else:
            st.error("パスワードが正しくありません")
    return False


@st.cache_data(show_spinner=False)
def _extract_text_from_pdf_bytes(pdf_raw: bytes) -> tuple[str, str]:
    """PDFバイナリからテキストを抽出（キャッシュ対応）"""
    try:
        file_size_mb = len(pdf_raw) / (1024 * 1024)
        if file_size_mb > MAX_PDF_SIZE_MB:
            return "", f"ファイルサイズが大きすぎます（{file_size_mb:.1f}MB）。{MAX_PDF_SIZE_MB}MB以下にしてください"

        if not pdf_raw[:5].startswith(b"%PDF-"):
            return "", "有効なPDFファイルではありません"

        pdf_bytes = io.BytesIO(pdf_raw)
        text_parts = []

        with pdfplumber.open(pdf_bytes) as pdf:
            if len(pdf.pages) > 20:
                return "", "ページ数が多すぎます（最大20ページ）"

            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

        extracted_text = "\n\n".join(text_parts)

        if not extracted_text.strip():
            return "", "PDFからテキストを抽出できませんでした。画像ベースのPDFの可能性があります"

        return extracted_text, ""

    except Exception as e:
        return "", "PDF読み込みエラー: ファイルの読み込みに失敗しました"


def extract_text_from_pdf(uploaded_file) -> tuple[str, str]:
    """PDFファイルからテキストを抽出（同一ファイルはキャッシュから即時返却）"""
    return _extract_text_from_pdf_bytes(uploaded_file.getvalue())


def _is_safe_url(url: str) -> tuple[bool, str]:
    """URLが安全かどうかを検証（SSRF対策）"""
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "無効なURLです"

    # スキーム検証: http/httpsのみ許可
    if parsed.scheme not in ('http', 'https'):
        return False, "http または https のURLのみ対応しています"

    # ホスト名検証
    hostname = parsed.hostname
    if not hostname:
        return False, "無効なURLです"

    # ローカルホスト・プライベートIPの拒否
    blocked_hosts = {'localhost', '127.0.0.1', '0.0.0.0', '::1', '[::1]'}
    if hostname.lower() in blocked_hosts:
        return False, "ローカルアドレスへのアクセスは許可されていません"

    # IPアドレスの場合、プライベート範囲を拒否
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False, "プライベートネットワークへのアクセスは許可されていません"
    except ValueError:
        pass  # ホスト名（非IP）の場合はそのまま通す

    return True, ""


def _convert_google_drive_url(url: str) -> str | None:
    """Google DriveのURLを直接ダウンロードURLに変換

    対応形式:
        - https://drive.google.com/file/d/{FILE_ID}/view...
        - https://drive.google.com/open?id={FILE_ID}
        - https://docs.google.com/document/d/{FILE_ID}/...
        - https://docs.google.com/spreadsheets/d/{FILE_ID}/...

    Returns:
        変換後のURL、Google DriveのURLでない場合はNone
    """
    # /file/d/{ID}/ パターン
    match = re.match(r'https?://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)', url)
    if match:
        return f"https://drive.google.com/uc?export=download&id={match.group(1)}"

    # /open?id={ID} パターン
    match = re.match(r'https?://drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)', url)
    if match:
        return f"https://drive.google.com/uc?export=download&id={match.group(1)}"

    # Google Docs → PDF export
    match = re.match(r'https?://docs\.google\.com/document/d/([a-zA-Z0-9_-]+)', url)
    if match:
        return f"https://docs.google.com/document/d/{match.group(1)}/export?format=pdf"

    # Google Sheets → PDF export
    match = re.match(r'https?://docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)', url)
    if match:
        return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=pdf"

    return None


def extract_text_from_url(url: str) -> tuple[str, str]:
    """URLからWebページのテキストを抽出（Google Drive対応）

    Returns:
        tuple: (extracted_text, error_message)
    """
    # Google DriveのURLを直接ダウンロードURLに変換
    drive_url = _convert_google_drive_url(url)
    is_google_drive = drive_url is not None
    if is_google_drive:
        url = drive_url

    # SSRF対策: URL安全性チェック
    is_safe, safety_msg = _is_safe_url(url)
    if not is_safe:
        return "", safety_msg

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if is_google_drive:
            # Google Driveはリダイレクトを自動追跡（googleusercontent.comへ転送される）
            resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        else:
            resp = requests.get(url, headers=headers, timeout=15, allow_redirects=False)

            # リダイレクト先もSSRF検証（最大5回まで追跡）
            redirect_count = 0
            while resp.is_redirect and redirect_count < 5:
                redirect_url = resp.headers.get("Location", "")
                is_safe_redirect, redirect_msg = _is_safe_url(redirect_url)
                if not is_safe_redirect:
                    return "", f"リダイレクト先が安全ではありません: {redirect_msg}"
                resp = requests.get(redirect_url, headers=headers, timeout=15, allow_redirects=False)
                redirect_count += 1

        resp.raise_for_status()

        # Google Drive: 大きいファイルのウイルススキャン確認ページ対応
        if is_google_drive and "text/html" in resp.headers.get("Content-Type", ""):
            # 確認ページからダウンロードトークンを取得して再リクエスト
            confirm_match = re.search(r'confirm=([0-9A-Za-z_-]+)', resp.text)
            if confirm_match:
                confirm_url = f"{url}&confirm={confirm_match.group(1)}"
                resp = requests.get(confirm_url, headers=headers, timeout=30, allow_redirects=True)
                resp.raise_for_status()
            elif "accounts.google.com" in resp.text or "ServiceLogin" in resp.text:
                return "", "このGoogle Driveファイルにはアクセス権がありません。共有設定を「リンクを知っている全員」に変更してください"

        content_type = resp.headers.get("Content-Type", "")

        # PDFの場合
        if "application/pdf" in content_type:
            if not resp.content[:5].startswith(b"%PDF-"):
                return "", "有効なPDFファイルではありません"
            pdf_bytes = io.BytesIO(resp.content)
            text_parts = []
            with pdfplumber.open(pdf_bytes) as pdf:
                if len(pdf.pages) > 20:
                    return "", "ページ数が多すぎます（最大20ページ）"
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            extracted = "\n\n".join(text_parts)
            if not extracted.strip():
                return "", "PDFからテキストを抽出できませんでした"
            return extracted, ""

        # HTMLの場合
        soup = BeautifulSoup(resp.text, "html.parser")
        # 不要要素を除去
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            tag.decompose()

        # メインコンテンツを探す
        main = soup.find("main") or soup.find("article") or soup.find("div", {"role": "main"})
        target = main if main else soup.body if soup.body else soup
        text = target.get_text(separator="\n", strip=True)

        if not text.strip():
            return "", "ページからテキストを抽出できませんでした"

        # 長すぎる場合は切り詰め
        if len(text) > MAX_INPUT_CHARS:
            text = text[:MAX_INPUT_CHARS]

        return text, ""

    except requests.exceptions.Timeout:
        return "", "タイムアウトしました。URLを確認してください"
    except requests.exceptions.ConnectionError:
        return "", "接続エラー。URLを確認してください"
    except requests.exceptions.HTTPError as e:
        return "", f"HTTPエラー: {e.response.status_code}"
    except Exception:
        return "", "URL読み込みエラー: ページの取得に失敗しました"


def get_job_extraction_prompt(text: str) -> str:
    """求人テキストからメールテンプレート用の項目を抽出するプロンプト"""
    return f"""You are an expert recruitment consultant. Extract structured job information from the following text for use in a candidate outreach email.

【Input Text】
{text}

---

【Instructions】
Analyze the text above and extract the following fields. If a field cannot be determined from the text, leave it as an empty string "".

Output ONLY a valid JSON object with these exact keys (no markdown, no explanation):
{{
  "title": "The job position/role name (in English, e.g. 'Senior Backend Engineer')",
  "company": "The company name",
  "website": "The company or job posting URL if mentioned in the text, otherwise empty",
  "overview": "A concise 1-3 sentence summary of the company/role in English from a third-person perspective (use 'They' not 'We'), suitable for an outreach email sent by a recruiting agent (max 300 chars)",
  "key_focus": "What the company is specifically looking for — key skills, experience, or focus areas in 1 sentence (in English, max 200 chars)"
}}

Important:
- All values must be in English
- Keep overview concise and appealing — this goes directly into an email to candidates sent by a recruiting agent
- Always use third-person perspective in overview (e.g. 'They are looking for...' NOT 'We are looking for...')
- For key_focus, highlight what makes this role unique or what specific expertise is sought
- Do not fabricate information not present in the source text
- Output valid JSON only — no extra text before or after"""


def _extract_job_from_source(api_key: str, source_name: str, text: str) -> dict:
    """求人テキストからJSON情報を抽出する（バッチ用ヘルパー）

    Returns:
        dict with keys: name, success, data (or error)
    """
    try:
        prompt = get_job_extraction_prompt(text)
        result = call_groq_api(api_key, prompt)
        result = result.strip()
        if result.startswith("```"):
            result = re.sub(r'^```(?:json)?\s*', '', result)
            result = re.sub(r'\s*```$', '', result)
        job_data = json.loads(result)
        return {"name": source_name, "success": True, "data": job_data}
    except json.JSONDecodeError:
        return {"name": source_name, "success": False, "error": "JSON parse error"}
    except Exception as e:
        return {"name": source_name, "success": False, "error": str(e)}


def _build_email_text(candidate_name: str, sender_name: str, jobs: list[dict], email_lang: str = "en") -> str:
    """求人打診メール文面を組み立てる（英語/日本語対応）

    Args:
        candidate_name: 候補者の名前
        sender_name: 送信者の名前
        jobs: 求人情報のリスト（title, company, website, overview, key_focus, jd_note, fit_comment）
        email_lang: "en" or "ja"
    """
    lines = []

    if email_lang == "ja":
        lines.append(f"{candidate_name} 様\n")
        lines.append("本日はお話しできて大変うれしく思います。\n")
        lines.append("お話しした通り、以下の求人情報をお送りいたします。")
        lines.append("ご興味のあるポジションがございましたらお知らせください。企業への推薦手続きを進めさせていただきます。\n")
    else:
        lines.append(f"Hi {candidate_name}\n")
        lines.append("It was a pleasure speaking with you today.\n")
        if len(jobs) == 1:
            lines.append("As discussed, please find the details of the opportunity below.")
            lines.append("If this aligns with your interests, please let me know, and I will proceed with your recommendation to the company.\n")
        else:
            lines.append("As discussed, please find the details of the opportunities below.")
            lines.append("If any of these align with your interests, please let me know, and I will proceed with your recommendation to the companies.\n")

    for idx, job in enumerate(jobs, 1):
        header_parts = []
        if job.get("title"):
            header_parts.append(job["title"])
        if job.get("company"):
            header_parts.append(job["company"])
        if header_parts:
            lines.append(f"{idx}. {' | '.join(header_parts)}\n")
        else:
            lines.append(f"{idx}. (TBD)\n")

        if email_lang == "ja":
            if job.get("website"):
                lines.append(f"ウェブサイト: {job['website']}\n")
            if job.get("overview"):
                lines.append(f"概要: {job['overview']}\n")
            if job.get("key_focus"):
                lines.append(f"注力ポイント: {job['key_focus']}\n")
            if job.get("jd_note"):
                lines.append(f"JD備考: {job['jd_note']}\n")
            if job.get("fit_comment"):
                lines.append(f"{job['fit_comment']}\n")
        else:
            if job.get("website"):
                lines.append(f"Website: {job['website']}\n")
            if job.get("overview"):
                lines.append(f"Overview: {job['overview']}\n")
            if job.get("key_focus"):
                lines.append(f"Key Focus: {job['key_focus']}\n")
            if job.get("jd_note"):
                lines.append(f"JD: {job['jd_note']}\n")
            if job.get("fit_comment"):
                lines.append(f"{job['fit_comment']}\n")

        lines.append("")

    if email_lang == "ja":
        lines.append("また、弊社の「誠実さへのコミットメント」に関する簡単なメモを添付しております。端的に申し上げますと、お客様の信頼を大切にし、明確な「ゴーサイン」をいただくまで、いかなる企業にもプロフィールを提出することはございません。このアプローチにより、候補者様の推薦は戦略的に行われ、重複応募による混乱を避けることができます。")
        lines.append("詳細: https://drive.google.com/file/d/11HQ42s-zJ_mGFf1D75rHb2mE3hjV21Ib/view?usp=drivesdk\n")
        if len(jobs) == 1:
            lines.append("こちらの求人についてのご意見をお待ちしております。")
        else:
            lines.append("これらの求人についてのご意見をお待ちしております。")
        lines.append("よろしくお願いいたします。")
        lines.append(sender_name)
    else:
        lines.append("We have also attached a short memo regarding our firm's Commitment to Integrity. Simply put, we value your trust and will never submit your profile to any company without your explicit \"green light\". This approach ensures your candidacy is handled strategically and avoids any duplicate submissions that could complicate your search.")
        lines.append("Details: https://drive.google.com/file/d/11HQ42s-zJ_mGFf1D75rHb2mE3hjV21Ib/view?usp=drivesdk\n")
        if len(jobs) == 1:
            lines.append("We look forward to hearing your thoughts on this opportunity.")
        else:
            lines.append("We look forward to hearing your thoughts on these opportunities.")
        lines.append("Best regards,")
        lines.append(sender_name)

    return "\n".join(lines)


# ========================================
# Supabase URL共有機能
# ========================================

def get_supabase_client():
    """Supabaseクライアントを取得"""
    if not SUPABASE_AVAILABLE:
        return None
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_ANON_KEY"]
        if url and key:
            return create_client(url, key)
    except (KeyError, Exception):
        pass
    return None


def create_share_link(content: str, title: str = "Anonymized Resume") -> str | None:
    """共有リンクを作成（レート制限付き）

    Args:
        content: 共有するコンテンツ（Markdown形式）
        title: タイトル

    Returns:
        share_id: 共有ID（32文字）、失敗時はNone
    """
    # 共有リンク作成のレート制限チェック
    now = time.time()
    if 'share_timestamps' not in st.session_state:
        st.session_state['share_timestamps'] = []
    st.session_state['share_timestamps'] = [
        ts for ts in st.session_state['share_timestamps']
        if now - ts < RATE_LIMIT_WINDOW
    ]
    if len(st.session_state['share_timestamps']) >= RATE_LIMIT_SHARES:
        st.warning("⏳ 共有リンクの作成数が上限に達しました。しばらく待ってから再試行してください")
        return None
    st.session_state['share_timestamps'].append(now)

    client = get_supabase_client()
    if not client:
        return None

    share_id = secrets.token_urlsafe(24)  # 32文字のランダムID
    expires_at = datetime.now() + timedelta(days=30)

    try:
        client.table("shared_resumes").insert({
            "id": share_id,
            "content": content,
            "title": title,
            "expires_at": expires_at.isoformat()
        }).execute()
        return share_id
    except Exception:
        return None


def get_shared_resume(share_id: str) -> dict | None:
    """共有されたレジュメを取得

    Args:
        share_id: 共有ID

    Returns:
        dict: レジュメデータ、見つからない場合はNone
    """
    client = get_supabase_client()
    if not client:
        return None

    try:
        result = client.table("shared_resumes")\
            .select("*")\
            .eq("id", share_id)\
            .gt("expires_at", datetime.now().isoformat())\
            .single()\
            .execute()

        # 閲覧カウント更新
        if result.data:
            client.table("shared_resumes")\
                .update({"view_count": result.data.get("view_count", 0) + 1})\
                .eq("id", share_id)\
                .execute()

        return result.data
    except Exception:
        return None


def show_shared_view(share_id: str):
    """共有されたレジュメを表示（スタイリング版）"""
    import streamlit.components.v1 as components

    resume = get_shared_resume(share_id)
    if not resume:
        st.markdown("# 🌏 GlobalMatch Assistant")
        st.error("❌ このリンクは無効か、有効期限が切れています")
        st.info("💡 共有リンクの有効期限は1ヶ月です")
        return

    # 有効期限・閲覧数
    expires_at = resume.get('expires_at', '')[:10]
    view_count = resume.get('view_count', 0)
    title = resume.get('title', '候補者レジュメ')
    content = resume.get('content', '')

    # スタイリングされたHTMLを生成
    styled_html = generate_shared_html(content, title, expires_at, view_count)

    # フルページHTMLとして表示
    components.html(styled_html, height=800, scrolling=True)

    # ダウンロードボタン — ファーストネームをファイル名に使用
    _shared_first = extract_first_name(content)
    _shared_fname = f"resume_{_shared_first}" if _shared_first else f"resume_{share_id[:8]}"
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "📄 Markdownでダウンロード",
            content,
            f"{_shared_fname}.md",
            "text/markdown"
        )
    with col2:
        html_content = generate_html(content, title)
        st.download_button(
            "🌐 HTMLでダウンロード",
            html_content,
            f"{_shared_fname}.html",
            "text/html"
        )


def generate_shared_html(content: str, title: str, expires_at: str, view_count: int) -> str:
    """共有ビュー用のスタイリングされたHTMLを生成（Human & Trust デザイン）"""

    # まずコンテンツ全体をHTMLエスケープ（XSS対策）
    html_content = html_module.escape(content)

    # 見出し変換（エスケープ済みテキストに対して適用）
    html_content = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)

    # 太字・斜体
    html_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_content)
    html_content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html_content)

    # リスト
    html_content = re.sub(r'^- (.+)$', r'<li>\1</li>', html_content, flags=re.MULTILINE)

    # テーブル変換（セル内容は既にエスケープ済み）
    def convert_table(match):
        rows = match.group(0).strip().split('\n')
        html_rows = []
        for i, row in enumerate(rows):
            cells = [c.strip() for c in row.split('|') if c.strip()]
            if not cells or all(c.replace('-', '') == '' for c in cells):
                continue
            tag = 'th' if i == 0 else 'td'
            html_cells = ''.join(f'<{tag}>{cell}</{tag}>' for cell in cells)
            html_rows.append(f'<tr>{html_cells}</tr>')
        return '<table>' + ''.join(html_rows) + '</table>' if html_rows else ''

    html_content = re.sub(r'(\|.+\|[\n])+', convert_table, html_content)

    # 段落
    html_content = re.sub(r'\n\n+', '</p><p>', html_content)
    html_content = f'<p>{html_content}</p>'
    html_content = re.sub(r'<p>\s*</p>', '', html_content)

    safe_title = html_module.escape(title)

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_title}</title>
    <style>
        /* ===== Reset & Base ===== */
        *, *::before, *::after {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        /* ===== カラーパレット（Human & Trust） ===== */
        :root {{
            --bg-page: #F9F8F4;
            --bg-card: #FFFFFF;
            --text-main: #333333;
            --text-sub: #666666;
            --accent: #5B7C73;
            --accent-light: #E8EFED;
            --border: #E0E0E0;
            --shadow: rgba(0, 0, 0, 0.05);
        }}

        body {{
            font-family: "Hiragino Kaku Gothic ProN", "Hiragino Sans", "Yu Gothic", "Meiryo", "Noto Sans JP", sans-serif;
            font-size: 15px;
            line-height: 1.75;
            color: var(--text-main);
            background-color: var(--bg-page);
            padding: 40px 20px;
            min-height: 100vh;
        }}

        /* ===== メインコンテナ（紙のメタファー） ===== */
        .resume-container {{
            max-width: 800px;
            margin: 0 auto;
            background: var(--bg-card);
            border-radius: 12px;
            box-shadow: 0 4px 20px var(--shadow);
            overflow: hidden;
        }}

        /* ===== ヘッダー ===== */
        .resume-header {{
            padding: 40px;
            border-bottom: 1px solid var(--border);
            text-align: center;
        }}

        .resume-header h1 {{
            font-size: 24px;
            font-weight: 600;
            color: var(--text-main);
            margin-bottom: 16px;
            letter-spacing: 0.02em;
        }}

        .meta-info {{
            display: flex;
            justify-content: center;
            gap: 20px;
            flex-wrap: wrap;
        }}

        .meta-badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 14px;
            background: var(--accent-light);
            color: var(--accent);
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
        }}

        /* ===== コンテンツエリア ===== */
        .resume-content {{
            padding: 40px;
        }}

        /* ===== セクション見出し ===== */
        h2 {{
            font-size: 17px;
            font-weight: 600;
            color: var(--accent);
            margin: 40px 0 20px 0;
            padding-bottom: 10px;
            border-bottom: 2px solid var(--accent);
            letter-spacing: 0.03em;
        }}

        h2:first-child {{
            margin-top: 0;
        }}

        h3 {{
            font-size: 15px;
            font-weight: 600;
            color: var(--text-main);
            margin: 28px 0 12px 0;
            padding-left: 14px;
            border-left: 3px solid var(--accent);
        }}

        /* ===== テキスト ===== */
        p {{
            margin: 12px 0;
            color: var(--text-main);
        }}

        strong {{
            color: var(--accent);
            font-weight: 600;
        }}

        /* ===== リスト ===== */
        ul, ol {{
            list-style: none !important;
            margin: 12px 0;
            padding: 0;
        }}

        li {{
            position: relative;
            padding-left: 20px;
            margin: 10px 0;
            color: var(--text-main);
            list-style: none !important;
        }}

        li::before {{
            content: "";
            position: absolute;
            left: 0;
            top: 10px;
            width: 6px;
            height: 6px;
            background: var(--accent);
            border-radius: 50%;
        }}

        li::marker {{
            content: none;
        }}

        /* ===== テーブル（スキルセット用） ===== */
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--border);
        }}

        th, td {{
            padding: 14px 16px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}

        th {{
            background: var(--accent-light);
            color: var(--accent);
            font-weight: 600;
            font-size: 14px;
        }}

        td {{
            background: var(--bg-card);
            color: var(--text-main);
        }}

        tr:last-child td {{
            border-bottom: none;
        }}

        tr:nth-child(even) td {{
            background: #FAFAFA;
        }}

        /* ===== フッター ===== */
        .resume-footer {{
            padding: 20px 40px;
            background: var(--bg-page);
            text-align: center;
            font-size: 12px;
            color: var(--text-sub);
            border-top: 1px solid var(--border);
        }}

        /* ===== レスポンシブ対応 ===== */
        @media screen and (max-width: 600px) {{
            body {{
                padding: 20px 12px;
            }}
            .resume-header,
            .resume-content {{
                padding: 28px 20px;
            }}
            .meta-info {{
                flex-direction: column;
                gap: 10px;
            }}
            h2 {{
                font-size: 16px;
                margin: 32px 0 16px 0;
            }}
            table {{
                font-size: 13px;
            }}
            th, td {{
                padding: 10px 12px;
            }}
        }}

        /* ===== 印刷用スタイル ===== */
        @media print {{
            body {{
                background: white;
                padding: 0;
            }}
            .resume-container {{
                box-shadow: none;
                border-radius: 0;
            }}
            .resume-header,
            .resume-content {{
                padding: 30px;
            }}
            .meta-badge {{
                background: #f0f0f0;
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}
            h2 {{
                border-bottom-color: var(--accent);
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}
        }}
    </style>
</head>
<body>
    <div class="resume-container">
        <header class="resume-header">
            <h1>{safe_title}</h1>
        </header>

        <main class="resume-content">
            {html_content}
        </main>

    </div>
</body>
</html>'''


# サンプルデータ
SAMPLE_RESUME = """John Smith
Senior Software Engineer

Contact: john.smith@email.com | LinkedIn: linkedin.com/in/johnsmith | GitHub: github.com/jsmith
Location: San Francisco, CA

SUMMARY
Experienced software engineer with 7+ years of expertise in building scalable web applications.
Passionate about clean code and modern development practices. Fluent in Japanese (JLPT N2).

WORK EXPERIENCE

Google - Senior Software Engineer (2020 - Present)
- Led development of microservices architecture serving 10M+ daily users
- Reduced API latency by 40% through optimization and caching strategies
- Mentored 5 junior engineers and conducted 100+ code reviews

Amazon - Software Engineer (2017 - 2020)
- Built real-time inventory management system using Python and AWS
- Implemented CI/CD pipeline reducing deployment time by 60%
- Collaborated with cross-functional teams across 3 time zones

SKILLS
Languages: Python, JavaScript, TypeScript, Go, Java
Frameworks: React, Node.js, Django, FastAPI
Cloud: AWS (certified), GCP, Docker, Kubernetes
Database: PostgreSQL, MongoDB, Redis

EDUCATION
Stanford University - M.S. Computer Science (2017)
UC Berkeley - B.S. Computer Science (2015)

CERTIFICATIONS
- AWS Solutions Architect Professional
- Google Cloud Professional Data Engineer
"""

SAMPLE_JD = """【募集職種】
バックエンドエンジニア（シニア）

【会社概要】
当社は2015年設立のFinTechスタートアップです。累計資金調達額50億円、従業員数120名。
決済プラットフォーム事業を展開し、年間取扱高は1兆円を突破しました。

【業務内容】
・決済システムの設計・開発・運用
・マイクロサービスアーキテクチャの構築
・チームリーダーとして3-5名のメンバーマネジメント
・技術的な意思決定への参画

【必須スキル】
・Python, Go, Javaいずれかでの開発経験5年以上
・大規模システムの設計・開発経験
・AWSまたはGCPでのインフラ構築経験
・チームリーダー経験

【歓迎スキル】
・決済・金融システムの開発経験
・Kubernetes運用経験
・英語でのコミュニケーション能力

【待遇】
・年収：800万円〜1,500万円
・フレックスタイム制（コアタイム11:00-15:00）
・リモートワーク可（週2-3日出社）
・ストックオプション制度あり

【勤務地】
東京都渋谷区（渋谷駅徒歩5分）

【選考フロー】
書類選考 → 技術面接 → 最終面接 → オファー
"""

SAMPLE_MATCHING_RESUME = """## 1. 基本情報
- 氏名：J.S.
- 連絡先：[非公開]
- 所在地：カリフォルニア州

## 2. 推薦サマリ
Google、Amazonでの実務経験7年以上を持つシニアソフトウェアエンジニアです。マイクロサービスアーキテクチャの設計・開発に精通し、1,000万人以上のユーザーを抱えるシステムの構築実績があります。特にAPIの最適化、CI/CDパイプライン構築、チームマネジメントに強みを持ち、技術的リーダーシップを発揮できる人材です。日本語JLPT N2取得済みで、日本企業での勤務にも意欲的です。

## 3. 技術スタック
| カテゴリ | スキル |
|---------|--------|
| プログラミング言語 | Python, JavaScript, TypeScript, Go, Java |
| フレームワーク | React, Node.js, Django, FastAPI |
| データベース | PostgreSQL, MongoDB, Redis |
| インフラ/クラウド | AWS (認定資格保有), GCP, Docker, Kubernetes |
| ツール/その他 | Git, CI/CD, マイクロサービス設計 |

## 4. 語学・ビザ
- **日本語レベル**: JLPT N2取得済み（ビジネスレベル）
- **英語レベル**: ネイティブ
- **ビザステータス**: 日本での就労ビザサポート必要

## 5. 職務経歴

### Google（期間：2020年 〜 現在）
**シニアソフトウェアエンジニア**

**担当業務・成果:**
- 1,000万人以上の日間アクティブユーザーを持つマイクロサービスアーキテクチャの設計・開発をリード
- APIレイテンシを40%削減（最適化とキャッシング戦略の導入）
- 5名のジュニアエンジニアのメンター、100件以上のコードレビュー実施
- チーム横断での技術的意思決定に参画

### Amazon（期間：2017年 〜 2020年）
**ソフトウェアエンジニア**

**担当業務・成果:**
- PythonとAWSを使用したリアルタイム在庫管理システムの構築
- CI/CDパイプラインの実装によりデプロイ時間を60%短縮
- 3つのタイムゾーンをまたぐクロスファンクショナルチームとの協業

## 6. 学歴
- Stanford University - コンピュータサイエンス修士（2017年）
- UC Berkeley - コンピュータサイエンス学士（2015年）

## 7. 資格
- AWS Solutions Architect Professional
- Google Cloud Professional Data Engineer
"""

SAMPLE_MATCHING_JD = """【募集職種】
バックエンドエンジニア（シニア）

【会社概要】
当社は2015年設立のFinTechスタートアップです。累計資金調達額50億円、従業員数120名。
決済プラットフォーム事業を展開し、年間取扱高は1兆円を突破しました。

【業務内容】
- 決済システムの設計・開発・運用
- マイクロサービスアーキテクチャの構築
- チームリーダーとして3-5名のメンバーマネジメント
- 技術的な意思決定への参画

【必須スキル】
- Python, Go, Javaいずれかでの開発経験5年以上
- 大規模システムの設計・開発経験
- AWSまたはGCPでのインフラ構築経験
- チームリーダー経験

【歓迎スキル】
- 決済・金融システムの開発経験
- Kubernetes運用経験
- 英語でのコミュニケーション能力

【待遇】
- 年収：800万円〜1,500万円
- フレックスタイム制（コアタイム11:00-15:00）
- リモートワーク可（週2-3日出社）
- ストックオプション制度あり

【勤務地】
東京都渋谷区（渋谷駅徒歩5分）

【選考フロー】
書類選考 → 技術面接 → 最終面接 → オファー
"""

SAMPLE_JD_EN = """Senior Backend Engineer

About the Company:
TechFlow Inc. is a fast-growing SaaS company based in San Francisco, California. Founded in 2018, we've raised $50M in Series B funding and serve over 500 enterprise customers globally. Our platform helps companies streamline their workflow automation.

Location: San Francisco, CA (Hybrid - 2 days in office)
Salary Range: $180,000 - $250,000 + equity
Employment Type: Full-time

About the Role:
We're looking for a Senior Backend Engineer to join our Core Platform team. You'll be responsible for building and scaling our infrastructure that processes millions of workflow executions daily.

Responsibilities:
- Design and implement scalable microservices using Go and Python
- Lead technical architecture decisions for new features
- Mentor junior engineers and conduct code reviews
- Collaborate with product and design teams on feature development
- Participate in on-call rotation for production systems

Requirements:
- 5+ years of backend engineering experience
- Strong proficiency in Go, Python, or similar languages
- Experience with distributed systems and microservices
- Familiarity with AWS/GCP and containerization (Docker, Kubernetes)
- Excellent communication skills

Nice to have:
- Experience with event-driven architectures (Kafka, RabbitMQ)
- Previous experience at a high-growth startup
- Open source contributions

Benefits:
- Competitive salary + equity package
- Health, dental, and vision insurance (100% covered)
- Unlimited PTO policy
- $2,000 annual learning budget
- Home office setup allowance
- 401(k) matching

Interview Process:
1. Phone screen with recruiter (30 min)
2. Technical phone interview (60 min)
3. Virtual onsite (4 hours)
4. Final conversation with hiring manager

Apply at: careers@techflow.io
"""

# ページ設定
st.set_page_config(
    page_title="GlobalMatch Assistant",
    page_icon="🌏",
    layout="wide",
    initial_sidebar_state="expanded"
)

# カスタムCSS - Notion ハイブリッドデザイン
st.markdown("""
<style>
    /* フォント - Noto Serif JP（見出し）+ Noto Sans JP（本文） */
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;600;700&family=Noto+Serif+JP:wght@500;700&display=swap');

    /* 全体設定 - 暖色ベース */
    .stApp {
        background-color: #f6f5f4;
    }

    .main .block-container {
        background: #ffffff;
        padding: 2rem 2.5rem !important;
        max-width: 1200px;
        border-radius: 12px;
        box-shadow: rgba(0,0,0,0.04) 0px 4px 18px,
                    rgba(0,0,0,0.027) 0px 2px 8px,
                    rgba(0,0,0,0.02) 0px 0.8px 3px;
    }

    /* サイドバー */
    [data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid rgba(0,0,0,0.08);
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        color: rgba(0,0,0,0.8);
    }

    /* サイドバー - カテゴリナビゲーション */
    [data-testid="stSidebar"] .stButton > button {
        padding: 0.35rem 0.75rem !important;
        font-size: 13px !important;
        text-align: left !important;
        justify-content: flex-start !important;
        border-radius: 4px !important;
    }

    [data-testid="stSidebar"] .stButton > button[kind="primary"],
    [data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"] {
        background: #1e3a5f !important;
        color: #ffffff !important;
        border: 1px solid #1e3a5f !important;
        font-weight: 600 !important;
    }

    [data-testid="stSidebar"] .stButton > button[kind="primary"] *,
    [data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"] * {
        color: #ffffff !important;
    }

    [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover,
    [data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"]:hover {
        background: #2a4f7f !important;
        color: #ffffff !important;
    }

    /* ヘッダー - 明朝体 */
    h1 {
        color: #1e3a5f;
        font-family: 'Noto Serif JP', 'Hiragino Mincho ProN', 'Yu Mincho', serif;
        font-weight: 700;
        font-size: 1.8rem;
        border-bottom: 2px solid rgba(0,0,0,0.1);
        padding-bottom: 0.5rem;
        margin-bottom: 1rem;
    }

    h2 {
        color: #1e3a5f;
        font-family: 'Noto Serif JP', 'Hiragino Mincho ProN', 'Yu Mincho', serif;
        font-weight: 700;
        font-size: 1.2rem;
        margin-top: 1.5rem;
        border-left: 4px solid #1e3a5f;
        padding-left: 0.75rem;
    }

    h3 {
        color: rgba(0,0,0,0.85);
        font-family: 'Noto Sans JP', sans-serif;
        font-weight: 600;
        font-size: 1rem;
    }

    /* テキストエリア */
    .stTextArea textarea {
        font-family: 'Noto Sans JP', sans-serif;
        font-size: 14px;
        line-height: 1.7;
        border: 1px solid rgba(0,0,0,0.1);
        border-radius: 8px;
        background: #fafaf9;
    }

    .stTextArea textarea:focus {
        border-color: #1e3a5f;
        box-shadow: 0 0 0 2px rgba(30, 58, 95, 0.08);
    }

    /* メインボタン */
    .stButton > button {
        background: rgba(0,0,0,0.04) !important;
        color: rgba(0,0,0,0.85) !important;
        border: 1px solid rgba(0,0,0,0.1) !important;
        border-radius: 6px;
        padding: 0.6rem 1.5rem;
        font-weight: 500;
        font-family: 'Noto Sans JP', sans-serif;
        font-size: 14px;
        transition: all 0.15s ease;
    }

    .stButton > button:hover {
        background: rgba(0,0,0,0.08) !important;
        color: rgba(0,0,0,0.9) !important;
    }

    .stButton > button:disabled {
        background: rgba(0,0,0,0.03) !important;
        color: rgba(0,0,0,0.3) !important;
    }

    /* メインエリア - CTAボタン（primary） */
    .main .stButton > button[kind="primary"],
    .main .stButton > button[data-testid="stBaseButton-primary"] {
        background: linear-gradient(135deg, #1e3a5f 0%, #2a5f8f 100%) !important;
        color: #ffffff !important;
        border: none !important;
        font-weight: 600 !important;
        font-size: 15px !important;
        padding: 0.7rem 1.5rem !important;
        box-shadow: 0 2px 8px rgba(30, 58, 95, 0.2);
        border-radius: 8px !important;
        letter-spacing: 0.02em;
    }

    .main .stButton > button[kind="primary"] *,
    .main .stButton > button[data-testid="stBaseButton-primary"] * {
        color: #ffffff !important;
    }

    .main .stButton > button[kind="primary"]:hover,
    .main .stButton > button[data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(135deg, #2a4f7f 0%, #3570a0 100%) !important;
        color: #ffffff !important;
        box-shadow: 0 4px 12px rgba(30, 58, 95, 0.3);
        transform: translateY(-1px);
    }

    /* secondaryボタン */
    .stButton > button[kind="secondary"],
    .stButton > button[data-testid="stBaseButton-secondary"] {
        background: rgba(0,0,0,0.04) !important;
        color: rgba(0,0,0,0.85) !important;
        border: 1px solid rgba(0,0,0,0.1) !important;
    }

    /* ダウンロードボタン */
    .stDownloadButton > button {
        background: #ffffff;
        color: #1e3a5f;
        border: 1px solid #1e3a5f;
        border-radius: 6px;
        font-weight: 500;
        font-size: 13px;
        transition: all 0.2s ease;
    }

    .stDownloadButton > button:hover {
        background: #1e3a5f;
        color: white;
    }

    /* コード表示エリア */
    .stCodeBlock {
        border-radius: 8px;
        border: 1px solid rgba(0,0,0,0.1);
    }

    .stCodeBlock code {
        font-size: 13px;
        line-height: 1.5;
    }

    /* 成功メッセージ */
    .stSuccess {
        background: #f0faf4;
        color: #065f46;
        border: 1px solid rgba(42, 157, 153, 0.25);
        border-radius: 8px;
    }

    /* 情報メッセージ */
    .stInfo {
        background: #f2f9ff;
        color: #1e40af;
        border: 1px solid rgba(0, 117, 222, 0.2);
        border-radius: 8px;
    }

    /* 警告メッセージ */
    .stWarning {
        background: #fffcf0;
        color: #92400e;
        border: 1px solid rgba(221, 91, 0, 0.2);
        border-radius: 8px;
    }

    /* エラーメッセージ */
    .stError {
        background: #fef5f5;
        color: #991b1b;
        border: 1px solid rgba(220, 38, 38, 0.2);
        border-radius: 8px;
    }

    /* ラジオボタン */
    .stRadio > div {
        background: #fafaf9;
        border: 1px solid rgba(0,0,0,0.1);
        border-radius: 8px;
        padding: 0.75rem 1rem;
    }

    .stRadio label {
        font-size: 14px;
        color: rgba(0,0,0,0.85);
    }

    /* メトリクス */
    [data-testid="stMetricValue"] {
        font-size: 1.5rem;
        font-weight: 700;
        color: #1e3a5f;
    }

    [data-testid="stMetricLabel"] {
        color: rgba(0,0,0,0.5);
    }

    /* プログレスバー */
    .stProgress > div > div {
        background: #1e3a5f;
        border-radius: 4px;
    }

    /* 区切り線 - ウィスパーボーダー */
    hr {
        border: none;
        border-top: 1px solid rgba(0,0,0,0.08);
        margin: 1.5rem 0;
    }

    /* タブ */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        border-bottom: 1px solid rgba(0,0,0,0.1);
    }

    .stTabs [data-baseweb="tab"] {
        font-family: 'Noto Sans JP', sans-serif;
        font-size: 14px;
        font-weight: 500;
        color: rgba(0,0,0,0.45);
        padding: 0.75rem 1.25rem;
        border-bottom: 2px solid transparent;
        margin-bottom: -1px;
        transition: color 0.15s ease;
    }

    .stTabs [data-baseweb="tab"]:hover {
        color: rgba(0,0,0,0.8);
    }

    .stTabs [aria-selected="true"] {
        color: #1e3a5f !important;
        font-weight: 600;
        border-bottom-color: #1e3a5f !important;
    }

    /* エクスパンダー */
    .streamlit-expanderHeader {
        background: #fafaf9;
        border: 1px solid rgba(0,0,0,0.1);
        border-radius: 8px;
        font-weight: 500;
        font-size: 14px;
    }

    /* キャプション */
    .stCaption {
        color: rgba(0,0,0,0.45);
        font-size: 13px;
    }

    /* テキスト入力 */
    .stTextInput input {
        border: 1px solid rgba(0,0,0,0.1);
        border-radius: 6px;
        font-size: 14px;
    }

    .stTextInput input:focus {
        border-color: #1e3a5f;
        box-shadow: 0 0 0 2px rgba(30, 58, 95, 0.08);
    }

    /* セレクトボックス */
    .stSelectbox > div > div {
        border-radius: 6px;
    }

    /* 全体のテキスト */
    .stMarkdown {
        font-family: 'Noto Sans JP', sans-serif;
        color: rgba(0,0,0,0.85);
        line-height: 1.7;
    }

    /* カラム */
    [data-testid="column"] {
        padding: 0 0.5rem;
    }

    /* レスポンシブ対応 */
    @media (max-width: 768px) {
        .main .block-container {
            padding: 1rem 1rem !important;
        }

        h1 {
            font-size: 1.4rem;
        }

        h2 {
            font-size: 1.1rem;
        }

        .stTextArea textarea {
            font-size: 16px; /* iOS ズーム防止 */
        }

        .stButton > button {
            padding: 0.5rem 1rem;
            font-size: 13px;
        }

        .stDownloadButton > button {
            font-size: 12px;
            padding: 0.4rem 0.8rem;
        }

        [data-testid="column"] {
            padding: 0 0.25rem;
        }

        /* 縦並びに変更 */
        [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
        }

        [data-testid="stHorizontalBlock"] > div {
            flex: 1 1 100% !important;
            width: 100% !important;
            margin-bottom: 1rem;
        }
    }

    @media (max-width: 480px) {
        .main .block-container {
            padding: 0.75rem 0.75rem !important;
        }

        h1 {
            font-size: 1.2rem;
        }

        .stRadio > div {
            padding: 0.5rem;
        }

        .stRadio label {
            font-size: 13px;
        }

        /* モバイルではテキストエリアの高さを抑える */
        .stTextArea textarea {
            max-height: 200px;
        }
    }
</style>
""", unsafe_allow_html=True)

from prompts import *  # noqa: E402


def validate_input(text: str, input_type: str) -> tuple[bool, str]:
    """入力テキストのバリデーション"""

    if not text or not text.strip():
        return False, "テキストを入力してください"

    text = text.strip()

    if len(text) < MIN_INPUT_CHARS:
        return False, f"入力が短すぎます（最低{MIN_INPUT_CHARS}文字以上）"

    if len(text) > MAX_INPUT_CHARS:
        return False, f"入力が長すぎます（最大{MAX_INPUT_CHARS:,}文字まで）。現在: {len(text):,}文字"

    # 基本的な内容チェック
    if input_type == "resume":
        keywords = ["experience", "skill", "work", "education", "project", "develop", "engineer"]
        if not any(kw in text.lower() for kw in keywords):
            return False, "レジュメとして認識できません。英語のレジュメを入力してください"
    elif input_type == "jd":
        keywords = ["募集", "業務", "必須", "歓迎", "待遇", "給与", "仕事", "職種", "応募"]
        if not any(kw in text for kw in keywords):
            return False, "求人票として認識できません。日本語の求人票を入力してください"
    elif input_type == "jd_en":
        keywords = ["job", "position", "role", "responsibilities", "requirements", "salary", "benefits", "experience", "engineer", "developer"]
        if not any(kw in text.lower() for kw in keywords):
            return False, "求人票として認識できません。英語の求人票を入力してください"
    elif input_type == "jd_any":
        # 日本語または英語の求人票を受け付ける
        jp_keywords = ["募集", "業務", "必須", "歓迎", "待遇", "給与", "仕事", "職種", "応募"]
        en_keywords = ["job", "position", "role", "responsibilities", "requirements", "salary", "benefits", "experience", "engineer", "developer"]
        has_jp = any(kw in text for kw in jp_keywords)
        has_en = any(kw in text.lower() for kw in en_keywords)
        if not has_jp and not has_en:
            return False, "求人票として認識できません。日本語または英語の求人票を入力してください"
    elif input_type == "company":
        # 会社紹介は最低限のテキストがあれば通す
        pass
    elif input_type == "matching":
        # マッチング分析は、レジュメと求人票の両方が必要だが、
        # それぞれの入力で個別にバリデーションされるため、ここでは最低限のチェックのみ
        pass

    return True, ""


def _is_rate_limit_error(exc: Exception) -> bool:
    """GroqのレートリミットValueErrorを識別する"""
    msg = str(exc).lower()
    return (
        "api制限" in msg
        or "rate limit" in msg
        or "429" in msg
        or "quota" in msg
        or "resource_exhausted" in msg
    )


def _get_gemini_fallback_key() -> str:
    """UI/Secrets から Gemini フォールバックキーを取得"""
    key = st.session_state.get("gemini_api_key", "") or ""
    if not key:
        try:
            key = st.secrets.get("GEMINI_API_KEY", "") or ""
        except Exception:
            pass
    return key.strip()


def _notify_gemini_fallback() -> None:
    try:
        st.toast("⚡ Groqレート制限検知 → Geminiに自動フェイルオーバー中", icon="🔄")
    except Exception:
        pass


def _make_gemini_client(api_key: str):
    """Gemini クライアントを timeout 付きで生成する。SDKバージョン差異に備えてフォールバックあり。"""
    from google import genai
    from google.genai import types

    try:
        return genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=60_000),  # 60秒
        )
    except (TypeError, AttributeError):
        # 古い SDK は http_options 引数を受け取れない
        return genai.Client(api_key=api_key)


def _call_gemini_api(api_key: str, prompt: str, max_tokens: int = 4096) -> str:
    """Gemini 2.5 Flash でテキスト生成（フォールバック用）"""
    from google.genai import types

    client = _make_gemini_client(api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return response.text or ""


def _call_gemini_api_stream(api_key: str, prompt: str, max_tokens: int = 4096):
    """Gemini 2.5 Flash でストリーミング生成（フォールバック用）"""
    from google.genai import types

    client = _make_gemini_client(api_key)
    stream = client.models.generate_content_stream(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    for chunk in stream:
        text = getattr(chunk, "text", None)
        if text:
            yield text


def _call_gemini_api_json(api_key: str, prompt: str, max_tokens: int = 8192) -> dict:
    """Gemini 2.5 Flash で JSON 構造化出力を取得（フォールバック用）。

    - max_tokens を余裕ある値に設定（検証JSONは長くなりがち）
    - コードフェンス（```json ... ```）の混入を除去
    - JSONDecodeError 時は最大3回までリトライ
    """
    from google.genai import types

    client = _make_gemini_client(api_key)
    last_error: Exception | None = None

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=max_tokens,
                    temperature=0,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            content = (response.text or "{}").strip()

            # コードフェンス除去（```json ... ``` / ``` ... ```）
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*\n?", "", content)
                content = re.sub(r"\n?```\s*$", "", content)
                content = content.strip()

            # 前後の余計なテキストを除去し、最初の { から最後の } までを抽出
            if not content.startswith("{"):
                first_brace = content.find("{")
                last_brace = content.rfind("}")
                if 0 <= first_brace < last_brace:
                    content = content[first_brace:last_brace + 1]

            return json.loads(content)

        except json.JSONDecodeError as e:
            last_error = e
            continue
        except Exception as e:
            last_error = e
            break

    raise ValueError(f"Gemini JSONパース失敗（3回試行）: {last_error}")


def call_groq_api(api_key: str, prompt: str) -> str:
    """Groq APIを呼び出してテキストを生成（リトライ機能付き、Geminiフォールバック付き）"""

    # アプリレベルのレート制限チェック
    allowed, msg = _check_rate_limit()
    if not allowed:
        # アプリ側レート制限にぶつかった場合もGeminiにフォールバックを試みる
        gemini_key = _get_gemini_fallback_key()
        if gemini_key:
            _notify_gemini_fallback()
            try:
                return _call_gemini_api(gemini_key, prompt)
            except Exception as gemini_exc:
                raise ValueError(f"⏳ {msg}（Geminiフォールバックも失敗: {gemini_exc}）")
        raise ValueError(f"⏳ {msg}")
    _record_api_call()

    client = Groq(api_key=api_key)
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
                timeout=60  # 60秒タイムアウト
            )
            return response.choices[0].message.content

        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            # リトライ不要なエラー
            if "invalid api key" in error_str or "authentication" in error_str:
                raise ValueError("❌ APIキーが無効です。正しいキーを入力してください")

            if "rate limit" in error_str:
                # Gemini キーが設定済みなら即フォールバック（Groqリトライ待ちをスキップ）
                gemini_key = _get_gemini_fallback_key()
                if gemini_key:
                    _notify_gemini_fallback()
                    try:
                        return _call_gemini_api(gemini_key, prompt)
                    except Exception as gemini_exc:
                        raise ValueError(f"⏳ Groq制限＆Geminiフォールバックも失敗: {gemini_exc}")
                # Gemini未設定時のみ従来どおり Groq をリトライ
                if attempt < MAX_RETRIES - 1:
                    wait_time = (attempt + 1) * 5  # 5秒、10秒、15秒
                    time.sleep(wait_time)
                    continue
                raise ValueError("⏳ API制限に達しました。しばらく待ってから再試行してください")

            if "timeout" in error_str or "timed out" in error_str:
                if attempt < MAX_RETRIES - 1:
                    continue
                raise ValueError("⏱️ タイムアウトしました。入力を短くするか、再試行してください")

            # その他のエラーもリトライ
            if attempt < MAX_RETRIES - 1:
                time.sleep(2)
                continue

    # すべてのリトライが失敗 → 最終フォールバック
    gemini_key = _get_gemini_fallback_key()
    if gemini_key:
        _notify_gemini_fallback()
        try:
            return _call_gemini_api(gemini_key, prompt)
        except Exception as gemini_exc:
            raise ValueError(f"🔄 処理に失敗（Groq {MAX_RETRIES}回＋Gemini: {gemini_exc}）")
    raise ValueError(f"🔄 処理に失敗しました（{MAX_RETRIES}回試行）。しばらく待ってから再試行してください")


def call_groq_api_stream(api_key: str, prompt: str):
    """Groq APIをストリーミングで呼び出し、チャンクを逐次yieldする（リトライ機能付き）"""

    # アプリレベルのレート制限チェック
    allowed, msg = _check_rate_limit()
    if not allowed:
        raise ValueError(f"⏳ {msg}")
    _record_api_call()

    client = Groq(api_key=api_key)
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            stream = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
                temperature=0,
                timeout=60,
                stream=True
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
            return

        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            if "invalid api key" in error_str or "authentication" in error_str:
                raise ValueError("❌ APIキーが無効です。正しいキーを入力してください")

            if "rate limit" in error_str:
                # Gemini キーが設定済みなら即フォールバック（ストリーミング）
                gemini_key = _get_gemini_fallback_key()
                if gemini_key:
                    _notify_gemini_fallback()
                    try:
                        for gchunk in _call_gemini_api_stream(gemini_key, prompt):
                            yield gchunk
                        return
                    except Exception as gemini_exc:
                        raise ValueError(f"⏳ Groq制限＆Geminiフォールバックも失敗: {gemini_exc}")
                if attempt < MAX_RETRIES - 1:
                    wait_time = (attempt + 1) * 5
                    time.sleep(wait_time)
                    continue
                raise ValueError("⏳ API制限に達しました。しばらく待ってから再試行してください")

            if "timeout" in error_str or "timed out" in error_str:
                if attempt < MAX_RETRIES - 1:
                    continue
                raise ValueError("⏱️ タイムアウトしました。入力を短くするか、再試行してください")

            if attempt < MAX_RETRIES - 1:
                time.sleep(2)
                continue

    raise ValueError(f"🔄 処理に失敗しました（{MAX_RETRIES}回試行）。しばらく待ってから再試行してください")


def call_groq_api_json(api_key: str, prompt: str, max_tokens: int = 3072) -> dict:
    """Groq APIをJSONモードで呼び出し、dictを返す（リトライ機能付き）。

    PII削除の精度検証など、構造化された結果が必要な箇所で使用する。
    """

    allowed, msg = _check_rate_limit()
    if not allowed:
        # アプリ側レート制限でも Gemini にフォールバック
        gemini_key = _get_gemini_fallback_key()
        if gemini_key:
            _notify_gemini_fallback()
            try:
                return _call_gemini_api_json(gemini_key, prompt, max_tokens=max_tokens)
            except Exception as gemini_exc:
                raise ValueError(f"⏳ {msg}（Geminiフォールバックも失敗: {gemini_exc}）")
        raise ValueError(f"⏳ {msg}")
    _record_api_call()

    client = Groq(api_key=api_key)

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0,
                timeout=60,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            return json.loads(content)

        except json.JSONDecodeError:
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
                continue
            raise ValueError("🔄 検証結果のJSON解析に失敗しました。再試行してください")

        except Exception as e:
            error_str = str(e).lower()

            if "invalid api key" in error_str or "authentication" in error_str:
                raise ValueError("❌ APIキーが無効です。正しいキーを入力してください")

            if "rate limit" in error_str:
                # Gemini キーが設定済みなら即フォールバック（JSON）
                gemini_key = _get_gemini_fallback_key()
                if gemini_key:
                    _notify_gemini_fallback()
                    try:
                        return _call_gemini_api_json(gemini_key, prompt, max_tokens=max_tokens)
                    except Exception as gemini_exc:
                        raise ValueError(f"⏳ Groq制限＆Geminiフォールバックも失敗: {gemini_exc}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep((attempt + 1) * 5)
                    continue
                raise ValueError("⏳ API制限に達しました。しばらく待ってから再試行してください")

            if "timeout" in error_str or "timed out" in error_str:
                if attempt < MAX_RETRIES - 1:
                    continue
                raise ValueError("⏱️ 検証がタイムアウトしました。再試行してください")

            if attempt < MAX_RETRIES - 1:
                time.sleep(2)
                continue

    # 全リトライ失敗 → Gemini にフォールバック
    gemini_key = _get_gemini_fallback_key()
    if gemini_key:
        _notify_gemini_fallback()
        try:
            return _call_gemini_api_json(gemini_key, prompt, max_tokens=max_tokens)
        except Exception as gemini_exc:
            raise ValueError(f"🔄 検証失敗（Groq {MAX_RETRIES}回＋Gemini: {gemini_exc}）")
    raise ValueError(f"🔄 検証に失敗しました（{MAX_RETRIES}回試行）")


# PII残存を決定的に検出するための正規表現セット
_PII_REGEX_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    "phone_intl": re.compile(r"\+\d{1,3}[\s\-]?\d{1,4}[\s\-]?\d{3,4}[\s\-]?\d{3,4}"),
    "phone_jp": re.compile(r"\b0\d{1,4}[\-(\s]\d{2,4}[\-)\s]\d{3,4}\b"),
    "linkedin": re.compile(r"linkedin\.com/[A-Za-z0-9\-_/]+", re.I),
    "github": re.compile(r"github\.com/[A-Za-z0-9\-_/]+", re.I),
    "twitter": re.compile(r"(?:twitter\.com|x\.com)/[A-Za-z0-9_]+", re.I),
    "postal_jp": re.compile(r"\b\d{3}-\d{4}\b"),
}


def normalize_resume_bullets(text: str) -> str:
    """レジュメ出力に残る inline `*` 箇条書き圧縮を検出し、`-` 行リストに正規化する。

    LLMが複数項目を `* 課題: ... * 解決策: ... * 成果: ...` のように
    1行に圧縮して出力した場合、Markdown上で literal な `*` として表示されてしまう。
    これを `- **課題**: ...` の改行リストへ決定的に変換する後処理。

    `**bold**` マーカーは保護される。純粋なイタリック `*foo*` には影響しない
    （スペースで挟まれた ` * ` のみ分割対象）。
    """
    if not text:
        return text

    # 1) `**bold**` をプレースホルダへ退避
    bold_store: list[str] = []

    def _stash_bold(m: re.Match) -> str:
        bold_store.append(m.group(0))
        return f"\x00BOLD{len(bold_store) - 1}\x01"

    protected = re.sub(r"\*\*[^*\n]+?\*\*", _stash_bold, text)

    # 2) 行単位で走査
    out_lines: list[str] = []
    for line in protected.split("\n"):
        # 行頭の `* ` を `- ` に置換（`*（...）*` のようなイタリックは空白なしで通常はマッチしない）
        line = re.sub(r"^(\s*)\*(\s+)", r"\1-\2", line)

        # 行頭が `- ` のリスト項目で、inline に ` * ` が混入している場合、分割
        m = re.match(r"^(\s*- )(.*)$", line)
        if m and " * " in m.group(2):
            prefix, body = m.group(1), m.group(2)
            parts = re.split(r"\s+\*\s+", body)
            for p in parts:
                p = p.strip()
                if p:
                    out_lines.append(prefix + p)
            continue

        out_lines.append(line)

    result = "\n".join(out_lines)

    # 3) bold を復元
    for i, bold in enumerate(bold_store):
        result = result.replace(f"\x00BOLD{i}\x01", bold)

    return result


# スキルメタデータ除去用の正規表現
_SKILLS_HEADING_RE = re.compile(
    r"^\s*#{1,4}\s*(?:Skills?|スキル|Technical Skills?|技術スキル|Tech Stack|Skill Set)\b",
    re.IGNORECASE,
)
_MAJOR_HEADING_RE = re.compile(r"^\s*#{1,2}\s+\S")
_SKILL_YEAR_RE = re.compile(r"\s*\|?\s*\d+\s*年(?:\s*\d+\s*ヶ月)?\b")
_SKILL_YEAR_EN_RE = re.compile(
    r"\s*\|?\s*\d+(?:\.\d+)?\s*(?:years?|yrs?|months?|mos?)\b",
    re.IGNORECASE,
)
_SKILL_LEVEL_RE = re.compile(
    r"\s*[|/]\s*(?:Expert|Advanced|Intermediate|Beginner|Native|"
    r"専門家(?:レベル)?|上級|中級|初級)(?:\s*（[^）]+）)?",
    re.IGNORECASE,
)
_PROFICIENCY_LEGEND_RE = re.compile(
    r"習熟度[:：].*(?:Expert|Advanced|Intermediate|Beginner)",
    re.IGNORECASE,
)
_ENGINEER_TOTAL_RE = re.compile(r"エンジニア歴\s*\d+\s*年")

# 候補者スナップショット等のテーブル行で使う「エンジニア歴」「現在のレベル」系の行全体を
# 機械的に除去するための正規表現。LLM が厳守ルールに違反して出力した場合の最終防衛線。
# プロンプトから該当行を削除済みだが、LLM の慣性で出力されるケースを抑制する。
_ENGINEER_YEARS_ROW_RE = re.compile(
    r"^\s*(?:\|\s*\*{0,2})?\s*"
    r"(?:エンジニア歴|総(?:エンジニア)?経験(?:年数)?|Engineering\s+Experience|Total\s+(?:Years?\s+of\s+)?Experience|Years?\s+of\s+Experience)"
    r"\s*\*{0,2}\s*(?:[|:：].*)?$",
    re.IGNORECASE,
)
_SENIORITY_LEVEL_ROW_RE = re.compile(
    r"^\s*(?:\|\s*\*{0,2})?\s*"
    r"(?:現在のレベル|キャリアレベル|Current\s+Level|Seniority(?:\s+Level)?)"
    r"\s*\*{0,2}\s*(?:[|:：].*)?$",
    re.IGNORECASE,
)

_YEAR_CELL_FULL_RE = re.compile(r"^\s*\d+\s*年(?:\s*\d+\s*ヶ月)?\s*$")
_YEAR_CELL_EN_FULL_RE = re.compile(
    r"^\s*\d+(?:\.\d+)?\s*(?:years?|yrs?|months?|mos?)\s*$", re.IGNORECASE
)
_LEVEL_CELL_FULL_RE = re.compile(
    r"^\s*(?:Expert|Advanced|Intermediate|Beginner|Native|"
    r"専門家(?:レベル)?|上級|中級|初級)(?:\s*（[^）]+）)?\s*$",
    re.IGNORECASE,
)


def finalize_resume_output(text: str) -> str:
    """レジュメ最適化の最終出力に適用する後処理チェーン。

    1. normalize_resume_bullets — inline `*` 箇条書きの正規化
    2. strip_engineer_years_and_seniority — エンジニア歴／現在のレベル行の機械除去
    3. strip_skill_metadata — スキル欄の推測メタデータ（年数・習熟度）除去
    """
    text = normalize_resume_bullets(text)
    text = strip_engineer_years_and_seniority(text)
    text = strip_skill_metadata(text)
    return text


def strip_engineer_years_and_seniority(text: str) -> str:
    """文書全体から「エンジニア歴」「総経験年数」「現在のレベル」行を機械的に除去する。

    プロンプトから該当行は削除済みだが、LLM が慣性で出力するケースを抑制するための
    最終防衛線。行ごと削除することで、候補者スナップショット等のテーブル行も
    クリーンに消える。表の区切り行（|---|）は自動的に整合性が保たれる。
    """
    if not text:
        return text

    out: list[str] = []
    for line in text.split("\n"):
        if _ENGINEER_YEARS_ROW_RE.match(line):
            continue
        if _SENIORITY_LEVEL_ROW_RE.match(line):
            continue
        out.append(line)
    return "\n".join(out)


def strip_skill_metadata(text: str) -> str:
    """Skills セクション内からスキル単位の経験年数・習熟度ラベルを除去する。

    LLM が原文に無い `Python 9年2ヶ月` / `Python | Advanced` / `習熟度: Expert ...` 等の
    推測メタデータを付与するハルシネーション対策の決定論的な後処理。
    Experience セクションは触らない（日数ベースの業務記述を保護するため）。
    """
    if not text:
        return text

    lines = text.split("\n")
    in_skills = False
    out: list[str] = []

    for line in lines:
        # セクション境界の検出
        if _SKILLS_HEADING_RE.match(line):
            in_skills = True
            out.append(line)
            continue
        if in_skills and _MAJOR_HEADING_RE.match(line) and not _SKILLS_HEADING_RE.match(line):
            in_skills = False

        if in_skills:
            # 凡例・合計行は丸ごと削除
            if _PROFICIENCY_LEGEND_RE.search(line):
                continue
            if _ENGINEER_TOTAL_RE.search(line):
                continue

            # Markdown テーブル行（`| A | B | C |`）から年数・習熟度セルを落とす
            stripped = line.strip()
            if stripped.startswith("|") and stripped.count("|") >= 2:
                parts = line.split("|")
                new_parts = []
                for p in parts:
                    tok = p.strip()
                    if not tok:
                        new_parts.append(p)
                        continue
                    if (
                        _YEAR_CELL_FULL_RE.match(tok)
                        or _YEAR_CELL_EN_FULL_RE.match(tok)
                        or _LEVEL_CELL_FULL_RE.match(tok)
                    ):
                        continue
                    new_parts.append(p)
                line = "|".join(new_parts)

            # インラインの " | 9年2ヶ月" / "9年2ヶ月" / " | Advanced" を除去
            line = _SKILL_YEAR_RE.sub("", line)
            line = _SKILL_YEAR_EN_RE.sub("", line)
            line = _SKILL_LEVEL_RE.sub("", line)

        out.append(line)

    return "\n".join(out)


def regex_pii_scan(text: str) -> list[dict]:
    """正規表現でPII残存を決定的に検出する。LLM検証を補完する最終防衛線。"""
    findings = []
    seen = set()
    for pii_type, pattern in _PII_REGEX_PATTERNS.items():
        for m in pattern.finditer(text or ""):
            value = m.group(0)
            key = (pii_type, value)
            if key in seen:
                continue
            seen.add(key)
            findings.append({"type": pii_type, "text": value, "severity": "high"})
    return findings


# ---------------------------------------------------------------------------
# 決定論的 PII 削除（LLM を使わずに PII のみを除去する高速パス）
# ---------------------------------------------------------------------------

# 個人属性・注釈・住所の行単位削除パターン
_PII_LINE_PATTERNS = [
    # 個人属性（ラベル付き行）
    re.compile(r"^\s*(?:Date\s+of\s+Birth|DOB|Birth\s*Date|Birthdate|生年月日)\b.*$", re.I),
    re.compile(r"^\s*(?:Age|年齢)\s*[:：].*$", re.I),
    re.compile(r"^\s*(?:Nationality|国籍|Citizenship)\s*[:：].*$", re.I),
    re.compile(r"^\s*(?:Gender|Sex|性別)\s*[:：].*$", re.I),
    re.compile(r"^\s*(?:Marital\s*Status|配偶者|婚姻状況|婚姻).*$", re.I),
    re.compile(r"^\s*(?:Religion|宗教)\s*[:：].*$", re.I),
    re.compile(r"^\s*(?:Photo|写真|Picture)\s*[:：].*$", re.I),
    # 住所ラベル行（詳細住所が後続）
    re.compile(r"^\s*(?:Address|住所|Home\s*Address|現住所|本籍)\s*[:：].*$", re.I),
    # 注釈・タイムスタンプ
    re.compile(r"^\s*Resume\s*\(.*PII.*\).*$", re.I),
    re.compile(r"^\s*Generated\s+\d{4}[\-/]\d{1,2}[\-/]\d{1,2}.*$", re.I),
    re.compile(r"^\s*Last\s+Updated\s*[:：].*$", re.I),
]

# 詳細住所を含む行（番地＋区/市/丁目 or US style）
# 順序非依存: 番地パターンと地名語が同一行にあれば住所行とみなす
_JP_ADDRESS_NUMBER_RE = re.compile(r"\d+[\-−–]\d+[\-−–]?\d*")
_JP_ADDRESS_LOCALITY_RE = re.compile(
    r"(?:区|市|町|村|丁目|番地|番\b|号\b|Tokyo|Osaka|Kyoto|Yokohama|Nagoya|Fukuoka|Sapporo|Kobe|"
    r"ku\b|-ku\b|Minato|Shibuya|Shinjuku|Chiyoda|Chuo|Setagaya|Meguro|Shinagawa|Nakano|Suginami)",
    re.I,
)
_US_ADDRESS_LINE_RE = re.compile(
    r"^\s*\d+\s+[A-Z][\w\s]+(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Lane|Ln\.?|Drive|Dr\.?|Way|Court|Ct\.?)\b",
    re.I,
)

# 削除対象セクション（見出し〜次の見出し）
_DELETE_HEADINGS = {
    "objective", "career objective", "job objective",
    "summary", "professional summary", "executive summary",
    "profile", "professional profile",
    "about", "about me", "about the candidate", "overview",
    "references", "reference",
    "personal information", "personal details", "personal data",
    "目的", "要約", "職務要約", "自己pr", "自己ｐｒ",
    "自己紹介", "自己概要", "概要",
    "照会先", "個人情報", "パーソナル情報",
}

# 保持対象セクション（これが出たら削除モードを解除）
_KEEP_HEADINGS = {
    "experience", "work experience", "professional experience",
    "employment", "employment history", "work history",
    "career", "career history",
    "skills", "technical skills", "skill", "core competencies", "key skills",
    "education", "academic background", "educational background",
    "certifications", "certification", "licenses", "licenses and certifications",
    "languages", "language", "language proficiency", "language skills",
    "visa", "visa status",
    "projects", "project", "key projects", "selected projects", "notable projects",
    "publications", "awards", "achievements", "accomplishments",
    "interests", "hobbies",
    "contact", "contact information",
    "職歴", "業務経歴", "職務経歴", "経歴",
    "学歴", "スキル", "技術スキル",
    "資格", "受賞", "資格・受賞", "保有資格",
    "言語", "語学", "ビザ",
    "プロジェクト", "代表プロジェクト", "業務内容", "業績",
}


def _norm_heading(line: str) -> str:
    s = line.strip()
    if not s:
        return ""
    s = re.sub(r"^#{1,6}\s+", "", s)
    s = s.rstrip(":：").rstrip()
    return s.lower()


def _looks_like_generic_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if re.match(r"^#{1,6}\s+\S", s):
        return True
    core = re.sub(r"^#{1,6}\s+", "", s).rstrip(":：").rstrip()
    if re.fullmatch(r"[A-Z][A-Z0-9\s&/\-\.]{2,40}", core) and not re.search(r"\d{4,}", core):
        return True
    return False


def _is_personal_url_line(stripped: str) -> bool:
    """個人系URLのみで構成された行（bullet/dash付き含む）"""
    s = re.sub(r"^[\-\*\•・]\s*", "", stripped).strip()
    known = re.compile(
        r"^(?:https?://)?(?:www\.)?(?:linkedin\.com|github\.com|twitter\.com|x\.com|"
        r"qiita\.com|medium\.com|zenn\.dev|dev\.to|stackoverflow\.com|note\.com)"
        r"/[\w\-_/\.]+/?$",
        re.I,
    )
    if known.match(s):
        return True
    if re.fullmatch(r"https?://[^\s]+", s):
        return True
    # 裸のドメイン+パス（blog/me/io/dev 等）。企業URLは誤爆しうるので保守的に個人TLDのみ
    if re.fullmatch(r"[\w\-]+\.(?:me|blog|dev|io|page|work|tech)(?:/[\w\-_/\.]+)?", s, re.I):
        return True
    return False


def _reduce_to_first_name(lines: list[str]) -> list[str]:
    """先頭付近のフルネーム行を「名のみ」に短縮する。最初の該当行のみ変換して停止する。

    対応: "John Smith", "Wei-Lin Chen", "John A. Smith", "Mary-Jane Watson"
    未対応: 連続漢字の姓名（山田太郎）— 区切りが不定のため。
    """
    out = list(lines)
    scanned = 0
    name_re = re.compile(
        r"^([A-Z][a-z]+(?:[\-'][A-Z][a-z]+)?)"       # First
        r"(?:\s+[A-Z]\.?)*"                           # optional middle initials
        r"\s+[A-Z][a-z]+(?:[\-'][A-Z][a-z]+)?"        # Last
        r"(?:\s+[A-Z][a-z]+(?:[\-'][A-Z][a-z]+)?)*$"  # optional extra last names
    )
    # 和名: 「姓 名」(半角/全角スペース区切り) の 2-4 漢字 + 2-4 漢字
    # 区切りが無い「山田太郎」型は辞書なしで分割不能なので対象外
    jp_name_re = re.compile(
        r"^([\u4E00-\u9FFF]{1,4})[\s　]+([\u4E00-\u9FFF]{1,4})$"
    )
    for i, line in enumerate(out):
        if scanned >= 6:
            break
        s = line.strip()
        if not s:
            continue
        scanned += 1
        core = re.sub(r"^#+\s+", "", s).strip()
        # 既知の見出しやセクション名は触らない
        h = core.rstrip(":：").lower()
        if h in _KEEP_HEADINGS or h in _DELETE_HEADINGS:
            continue
        m = name_re.match(core)
        if m:
            first = m.group(1)
            out[i] = line.replace(core, first, 1)
            return out
        jm = jp_name_re.match(core)
        if jm:
            # 姓を削除して名のみ残す（日本の履歴書慣行: 姓が先）
            given = jm.group(2)
            out[i] = line.replace(core, given, 1)
            return out
    return out


def redact_pii_deterministic(text: str) -> str:
    """LLM を使わず正規表現とヒューリスティックだけで PII を削除する。

    高速（<1秒）・幻覚ゼロ・再現性100%。原文の文章は一切書き換えず、
    PII に該当する箇所のみ削除する。

    削除対象:
    - Email / 電話番号 / 各種SNS URL / 郵便番号（_PII_REGEX_PATTERNS）
    - 個人属性行: 生年月日・年齢・国籍・性別・婚姻・宗教・写真
    - 住所行: 「Address:」「住所:」ラベル行、JP/US詳細住所
    - 注釈行: "Resume (PII Removed)" 等のバナー、Generated timestamp
    - 個人URL専用行: LinkedIn/GitHub/Twitter/個人ブログ
    - セクション削除: Objective / Summary / Profile / About Me / References / Personal Information
    - 先頭のフルネーム → 名のみ（Latin限定のヒューリスティック）
    """
    if not text:
        return text

    lines = text.split("\n")

    # Stage 1: 行単位の削除
    filtered: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and _is_personal_url_line(stripped):
            continue
        if any(p.match(line) for p in _PII_LINE_PATTERNS):
            continue
        if (_JP_ADDRESS_NUMBER_RE.search(line) and _JP_ADDRESS_LOCALITY_RE.search(line)) \
                or _US_ADDRESS_LINE_RE.match(line):
            continue
        filtered.append(line)

    # Stage 2: 先頭フルネーム → 名のみ
    filtered = _reduce_to_first_name(filtered)

    # Stage 3: インライントークン削除（email / 電話 / URL / 郵便番号）
    inline: list[str] = []
    for line in filtered:
        new_line = line
        for pat in _PII_REGEX_PATTERNS.values():
            new_line = pat.sub("", new_line)
        # 削除で残った余分な空白・区切り記号を整理（行頭行末のみ）
        new_line = re.sub(r"[ \t]+", " ", new_line)
        # 行頭末の「| 」「, 」等を掃除
        new_line = re.sub(r"^[\s|,・•]+", "", new_line)
        new_line = re.sub(r"[\s|,・•]+$", "", new_line)
        inline.append(new_line)

    # Stage 4: セクション単位削除（Objective / References 等）
    section_cleaned: list[str] = []
    in_delete = False
    for line in inline:
        h = _norm_heading(line)
        if h and h in _DELETE_HEADINGS:
            in_delete = True
            continue
        if h and h in _KEEP_HEADINGS:
            in_delete = False
            section_cleaned.append(line)
            continue
        # 未知の見出しが現れたら削除モードを解除（暴走防止）
        if in_delete and _looks_like_generic_heading(line):
            in_delete = False
            section_cleaned.append(line)
            continue
        if in_delete:
            continue
        section_cleaned.append(line)

    # Stage 5: 連続空行の圧縮
    collapsed: list[str] = []
    prev_blank = False
    for line in section_cleaned:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = is_blank

    return "\n".join(collapsed).strip() + "\n"


# ---------------------------------------------------------------------------
# 決定論的エンティティ比較 (PII 幻覚検出補助)
# ---------------------------------------------------------------------------

def _normalize_month_year(raw: str):
    """月+年表記を 'YYYY-MM' 形式に正規化する純粋関数。失敗したら None を返す。

    対応フォーマット:
    - 2022/04  /  04/2022
    - Apr 2022 / 2022 Apr
    - 2022年4月 / 2022年04月
    """
    raw = raw.strip()

    # 2022/04 or 04/2022
    m = re.fullmatch(r"((?:19|20)\d{2})[/\-](\d{1,2})", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"

    m = re.fullmatch(r"(\d{1,2})[/\-]((?:19|20)\d{2})", raw)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"

    # Apr 2022 / 2022 Apr (月名3文字 or フル)
    month_abbrs = {v.lower(): i for i, v in enumerate(calendar.month_abbr) if v}
    month_names = {v.lower(): i for i, v in enumerate(calendar.month_name) if v}
    month_map = {**month_abbrs, **month_names}

    m = re.fullmatch(r"([A-Za-z]+)\s+((?:19|20)\d{2})", raw)
    if m:
        mn = month_map.get(m.group(1).lower())
        if mn:
            return f"{m.group(2)}-{mn:02d}"

    m = re.fullmatch(r"((?:19|20)\d{2})\s+([A-Za-z]+)", raw)
    if m:
        mn = month_map.get(m.group(2).lower())
        if mn:
            return f"{m.group(1)}-{mn:02d}"

    # 2022年4月 / 2022年04月
    m = re.search(r"((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"

    return None


def extract_resume_entities(text: str) -> dict:
    """テキストから事実単位の集合を抽出する純粋関数（IO/Streamlit 呼び出し禁止）。

    Returns:
        {
            "numbers": set[str],        # 通貨・パーセント・倍率・人数
            "years": set[str],          # 西暦年
            "month_years": set[str],    # YYYY-MM 形式に正規化した月年
            "companies": set[str],      # 組織名トークン（best-effort）
            "certifications": set[str], # 資格・スコア名
        }
    """
    if not text:
        return {"numbers": set(), "years": set(), "month_years": set(),
                "companies": set(), "certifications": set()}

    # ── numbers ──────────────────────────────────────────────────────────────
    number_patterns = [
        # 通貨付き: $240K, ¥5M, 5M JPY, $8.1M, 5M JPY
        r"(?:[\$¥€£]\s?\d[\d,]*(?:\.\d+)?[KMBkmb]?|\d[\d,]*(?:\.\d+)?[KMBkmb]?\s?(?:JPY|USD|EUR|GBP))",
        # パーセント: 60%, 99.95%
        r"\d+(?:\.\d+)?%",
        # 倍率・大規模: 2M+, 240K, 3.5B
        r"\b\d+(?:\.\d+)?[KMBkmb]\+?\b",
        # 人数: 18 engineers, 5 junior engineers
        r"\b\d+\s+(?:engineers?|people|members?|users?|clients?|customers?|teams?)\b",
    ]
    numbers: set = set()
    for pat in number_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            numbers.add(re.sub(r"\s+", " ", m.group(0).strip()))

    # ── years ────────────────────────────────────────────────────────────────
    years: set = set()
    for m in re.finditer(r"\b((?:19|20)\d{2})\b", text):
        years.add(m.group(1))

    # ── month_years ──────────────────────────────────────────────────────────
    month_years: set = set()

    # 候補パターンを列挙して _normalize_month_year に渡す
    my_patterns = [
        r"(?:19|20)\d{2}[/\-]\d{1,2}",           # 2022/04
        r"\d{1,2}[/\-](?:19|20)\d{2}",            # 04/2022
        r"(?:[A-Za-z]+)\s+(?:19|20)\d{2}",        # Apr 2022
        r"(?:19|20)\d{2}\s+(?:[A-Za-z]+)",        # 2022 Apr
        r"(?:19|20)\d{2}\s*年\s*\d{1,2}\s*月",    # 2022年4月
    ]
    for pat in my_patterns:
        for m in re.finditer(pat, text):
            normalized = _normalize_month_year(m.group(0))
            if normalized:
                month_years.add(normalized)

    # ── companies ────────────────────────────────────────────────────────────
    company_keywords = re.compile(
        r"\b(?:Inc\.|Ltd\.|Corp\.|Co\.|LLC|LLP|株式会社|University|College|Group|Holdings|Technologies|Solutions|Services)\b",
        re.IGNORECASE,
    )
    companies: set = set()
    for line in text.splitlines():
        if company_keywords.search(line):
            # 行全体を 1 トークンとして保持（空白正規化）
            token = re.sub(r"\s+", " ", line.strip())
            if token:
                companies.add(token)

    # ── certifications ───────────────────────────────────────────────────────
    cert_patterns = [
        r"\bCISSP\b", r"\bCPA\b", r"\bPMP\b",
        r"\bCFA\b", r"\bCMA\b",
        r"\bAWS\s+(?:Solutions?\s+Architect|Developer|SysOps|DevOps)[^\s,]*",
        r"\bTOEIC\s+\d{3,4}\b",
        r"\bJLPT\s+N\d\b",
        r"\bISO\s+\d+\b",
    ]
    certifications: set = set()
    for pat in cert_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            certifications.add(re.sub(r"\s+", " ", m.group(0).strip()))

    return {
        "numbers": numbers,
        "years": years,
        "month_years": month_years,
        "companies": companies,
        "certifications": certifications,
    }


def compare_resume_entities(original_text: str, generated_text: str) -> dict:
    """原文と生成物のエンティティを比較し、捏造・欠落を検出する。

    Returns:
        {
            "fabrications": [{"field": str, "anonymized": str}, ...],
            "missing_facts": [{"field": str, "original": str}, ...],
        }
    各リストは最大 20 件。
    """
    orig = extract_resume_entities(original_text)
    gen = extract_resume_entities(generated_text)

    fabrications: list = []
    missing_facts: list = []

    # ── fabrications 判定 ────────────────────────────────────────────────────
    # numbers: generated にあって original にない
    for val in gen["numbers"]:
        if val not in orig["numbers"]:
            fabrications.append({"field": "metric", "anonymized": val})

    # month_years: generated にあって original にない
    for val in gen["month_years"]:
        if val not in orig["month_years"]:
            fabrications.append({"field": "period", "anonymized": val})

    # certifications: generated にあって original にない
    for val in gen["certifications"]:
        # 大文字小文字正規化で再確認
        if not any(val.lower() == o.lower() for o in orig["certifications"]):
            fabrications.append({"field": "certification", "anonymized": val})

    # companies: 部分一致 (generated トークンが original の任意行に含まれるか)
    for val in gen["companies"]:
        if not any(val.lower() in o.lower() or o.lower() in val.lower()
                   for o in orig["companies"]):
            fabrications.append({"field": "company", "anonymized": val})

    # years はスキップ（表記揺れ・抽出ノイズが多いため誤報回避）

    # ── missing_facts 判定 ───────────────────────────────────────────────────
    # 年齢っぽい数値を original から除外するためのヘルパー
    age_context_re = re.compile(
        r"born|birth|dob|age|\d{1,2}\s*歳|生年", re.IGNORECASE
    )

    for val in orig["numbers"]:
        if val not in gen["numbers"]:
            # 2 桁数値で前後 30 文字に年齢コンテキストがあればスキップ
            m = re.search(re.escape(val), original_text)
            if m:
                ctx_start = max(0, m.start() - 30)
                ctx_end = min(len(original_text), m.end() + 30)
                ctx = original_text[ctx_start:ctx_end]
                if age_context_re.search(ctx):
                    continue
            missing_facts.append({"field": "metric", "original": val})

    for val in orig["month_years"]:
        if val not in gen["month_years"]:
            missing_facts.append({"field": "period", "original": val})

    for val in orig["certifications"]:
        if not any(val.lower() == g.lower() for g in gen["certifications"]):
            missing_facts.append({"field": "certification", "original": val})

    for val in orig["companies"]:
        if not any(val.lower() in g.lower() or g.lower() in val.lower()
                   for g in gen["companies"]):
            missing_facts.append({"field": "company", "original": val})

    # 重複除去と上限
    def _dedup(lst: list) -> list:
        seen: set = set()
        out = []
        for item in lst:
            key = (item.get("field"), item.get("anonymized", item.get("original")))
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out

    return {
        "fabrications": _dedup(fabrications)[:20],
        "missing_facts": _dedup(missing_facts)[:20],
    }


def run_resume_transform_loop(
    api_key: str,
    *,
    original_text: str,
    base_prompt: str,
    verification_mode: str,
    status_container,
    status_generating: str,
    status_regenerating: str,
    status_verifying: str,
    max_iterations: int = 2,
    apply_regex_pii: bool = True,
    post_processor=None,
) -> tuple[str, list[dict], bool]:
    """レジュメ変換を「生成 → 検証 → (不合格なら)再生成」する共通ループ。

    Args:
        original_text: 検証で比較する原文（元レジュメ等）
        base_prompt: 初回に渡すプロンプト（フィードバック無し版）
        verification_mode: get_resume_transform_verification_prompt() の mode 引数
        status_container: st.empty() で作ったキャプション表示用コンテナ
        status_generating / status_regenerating / status_verifying: 進捗メッセージ
        apply_regex_pii: 正規表現PII残存チェックを適用するか（翻訳モードは False 推奨）
        post_processor: 生成結果に適用する後処理関数（例: normalize_resume_bullets）

    Returns:
        (最終出力, iterations のリスト, 合格したかどうか)
    """

    iterations: list[dict] = []
    current_output = ""
    feedback_json = ""

    for iter_num in range(1, max_iterations + 1):
        if iter_num == 1:
            status_container.caption(status_generating)
            prompt = base_prompt
        else:
            status_container.caption(
                status_regenerating.format(n=iter_num, max=max_iterations)
            )
            prompt = append_feedback_to_prompt(base_prompt, current_output, feedback_json)

        stream_container = st.empty()
        current_output = stream_to_container(api_key, prompt, stream_container)
        stream_container.empty()

        if post_processor:
            current_output = post_processor(current_output)

        # LLM検証
        status_container.caption(
            status_verifying.format(n=iter_num, max=max_iterations)
        )
        try:
            verify_prompt = get_resume_transform_verification_prompt(
                original_text, current_output, verification_mode
            )
            verification = call_groq_api_json(api_key, verify_prompt)
        except ValueError as ve:
            st.warning(f"⚠️ {ve}")
            verification = {
                "passed": False,
                "pii_leaks": [],
                "fact_mismatches": [],
                "missing_facts": [],
                "fabrications": [],
                "summary": "検証エラー（結果は未検証）",
            }

        # 正規表現PII検証（匿名化モード時のみ）
        if apply_regex_pii:
            regex_leaks = regex_pii_scan(current_output)
            if regex_leaks:
                verification.setdefault("pii_leaks", [])
                existing = {
                    (l.get("type"), l.get("text"))
                    for l in verification["pii_leaks"]
                }
                for leak in regex_leaks:
                    if (leak["type"], leak["text"]) not in existing:
                        verification["pii_leaks"].append(leak)
                verification["passed"] = False

        iterations.append({
            "iter": iter_num,
            "output": current_output,
            "verification": verification,
        })

        if verification.get("passed"):
            break

        feedback_json = json.dumps(
            {
                "pii_leaks": verification.get("pii_leaks", []),
                "fact_mismatches": verification.get("fact_mismatches", []),
                "missing_facts": verification.get("missing_facts", []),
                "fabrications": verification.get("fabrications", []),
            },
            ensure_ascii=False,
            indent=2,
        )

    passed = iterations[-1]["verification"].get("passed") if iterations else False
    return current_output, iterations, passed


def _render_verification_step(v: dict) -> None:
    """検証ステップ 1 件分の issue リストを描画する内部ヘルパー。"""
    issue_rendered = False

    for leak in v.get("pii_leaks") or []:
        issue_rendered = True
        st.markdown(
            f"- 🔴 {t('pii_v_leak')} "
            f"[`{leak.get('type', '?')}`]: "
            f"`{leak.get('text', '')}`"
        )
    for mm in v.get("fact_mismatches") or []:
        issue_rendered = True
        gen_val = mm.get('generated') or mm.get('anonymized') or ''
        st.markdown(
            f"- 🟡 {t('pii_v_mismatch')} "
            f"[`{mm.get('field', '?')}`]: "
            f"{t('pii_v_original')}「{mm.get('original', '')}」 → "
            f"{t('pii_v_anonymized')}「{gen_val}」 "
            f"({mm.get('issue', '')})"
        )
    for miss in v.get("missing_facts") or []:
        issue_rendered = True
        st.markdown(
            f"- 🟠 {t('pii_v_missing')} "
            f"[`{miss.get('field', '?')}`]: "
            f"「{miss.get('original', '')}」"
        )
    for fab in v.get("fabrications") or []:
        issue_rendered = True
        gen_val = fab.get('generated') or fab.get('anonymized') or ''
        st.markdown(
            f"- 🔵 {t('pii_v_fabricated')} "
            f"[`{fab.get('field', '?')}`]: "
            f"「{gen_val}」"
        )

    if not issue_rendered and v.get("passed"):
        st.markdown(f"- {t('pii_v_all_clear')}")


def render_verification_details(iterations: list[dict], key_suffix: str = "") -> None:
    """検証結果のアコーディオンUIを描画する共通関数。

    表示は「最終結果の残存 issue」のみ既定で展開し、過去の全試行は入れ子の
    expander に折り畳む。最終結果が合格済みなら全体を閉じる。
    """
    if not iterations:
        return

    last_v = iterations[-1]["verification"]
    icon = "✅" if last_v.get("passed") else "⚠️"
    label = t("pii_verify_details_label").format(icon=icon, iters=len(iterations))

    with st.expander(label, expanded=not last_v.get("passed")):
        # 最終結果の summary と残存 issue のみを目立たせる
        st.markdown(
            f"**{icon} {t('pii_iter_final_label')}** — "
            f"{last_v.get('summary') or ''}"
        )
        _render_verification_step(last_v)

        # 過去の試行は折り畳んでノイズを減らす
        if len(iterations) > 1:
            history_label = t("pii_iter_history_label").format(n=len(iterations) - 1)
            with st.expander(history_label, expanded=False):
                for step in iterations[:-1]:
                    v = step["verification"]
                    step_icon = "✅" if v.get("passed") else "⚠️"
                    st.markdown(
                        f"**{step_icon} {t('pii_iter_label').format(n=step['iter'])}** — "
                        f"{v.get('summary') or ''}"
                    )
                    _render_verification_step(v)
                    if step["iter"] < len(iterations) - 1:
                        st.divider()


def stream_to_container(api_key: str, prompt: str, container=None):
    """ストリーミングでコンテナにリアルタイム表示し、完成テキストを返す。

    Groq レート制限時は Gemini に自動フェイルオーバーする（キーが設定されている場合）。
    """
    if container is None:
        container = st.empty()

    collected: list[str] = []

    try:
        for chunk in call_groq_api_stream(api_key, prompt):
            collected.append(chunk)
            container.markdown("".join(collected) + "▍")
    except ValueError as e:
        if _is_rate_limit_error(e):
            gemini_key = _get_gemini_fallback_key()
            if gemini_key:
                _notify_gemini_fallback()
                # バッファをリセットして Gemini で最初から生成し直す
                collected = []
                container.markdown("")
                for chunk in _call_gemini_api_stream(gemini_key, prompt):
                    collected.append(chunk)
                    container.markdown("".join(collected) + "▍")
            else:
                raise
        else:
            raise

    full_text = "".join(collected)
    container.markdown(full_text)
    return full_text


# ========================================
# 履歴管理機能（ローカルストレージ版）
# ========================================

def init_history(history_type: str):
    """履歴を初期化"""
    key = f"{history_type}_history"
    if key not in st.session_state:
        st.session_state[key] = []


def add_to_history(history_type: str, content: str, title: str = None):
    """履歴に追加（最大200件）+ localStorage同期"""
    init_history(history_type)
    key = f"{history_type}_history"

    # タイトルを自動生成（提供されていない場合）
    if not title:
        # 日付 + コンテンツの最初の30文字
        timestamp = datetime.now().strftime('%Y/%m/%d %H:%M')
        preview = content[:30].replace('\n', ' ')
        title = f"{timestamp} - {preview}..."

    # 新しいエントリを作成
    entry = {
        'id': datetime.now().strftime('%Y%m%d%H%M%S%f'),
        'title': title,
        'content': content,
        'timestamp': datetime.now().isoformat()
    }

    # 履歴の先頭に追加
    st.session_state[key].insert(0, entry)

    # 最大200件まで保持（localStorage版は容量増）
    if len(st.session_state[key]) > 200:
        st.session_state[key] = st.session_state[key][:200]

    # localStorageに自動同期
    sync_to_localstorage(history_type)


def get_history(history_type: str) -> list:
    """履歴を取得"""
    init_history(history_type)
    key = f"{history_type}_history"
    return st.session_state[key]


def delete_history_item(history_type: str, item_id: str):
    """履歴の個別アイテムを削除"""
    key = f"{history_type}_history"
    if key in st.session_state:
        st.session_state[key] = [
            item for item in st.session_state[key]
            if item['id'] != item_id
        ]


def clear_history(history_type: str):
    """履歴を全削除"""
    key = f"{history_type}_history"
    if key in st.session_state:
        st.session_state[key] = []


def extract_title_from_content(content: str, content_type: str) -> str:
    """コンテンツからタイトルを抽出"""
    lines = content.split('\n')

    if content_type == "resume":
        # レジュメの場合：まずextract_first_nameで抽出を試みる
        first_name = extract_first_name(content)
        if first_name:
            return f"候補者: {first_name}"
        # フォールバック：「氏名：J.S.」や名前を探す
        for line in lines[:10]:
            if '氏名' in line or 'Name:' in line:
                name = line.split('：')[-1].split(':')[-1].strip()
                if name and name != '[非公開]':
                    return f"候補者: {name}"
        # 見つからない場合は日付
        return f"レジュメ {datetime.now().strftime('%m/%d %H:%M')}"

    elif content_type == "jd":
        # 求人票の場合：職種名を探す
        for line in lines[:10]:
            if '募集職種' in line or 'Position' in line or '【' in line:
                title = line.replace('募集職種', '').replace('【', '').replace('】', '').strip()
                if title:
                    return f"求人: {title[:20]}"
        return f"求人票 {datetime.now().strftime('%m/%d %H:%M')}"

    return f"{content_type} {datetime.now().strftime('%m/%d %H:%M')}"


# ========================================
# localStorage統合とエクスポート/インポート
# ========================================

def sync_to_localstorage(history_type: str):
    """履歴をlocalStorageに同期（JavaScript経由）"""
    key = f"{history_type}_history"
    if key in st.session_state:
        # JSON.parseで安全にデータを渡す（XSS対策）
        json_data = json.dumps(json.dumps(st.session_state[key], ensure_ascii=True))

        st.components.v1.html(f"""
            <script>
            try {{
                localStorage.setItem('{key}', {json_data});
            }} catch(e) {{
                console.error('Failed to save to localStorage:', e);
            }}
            </script>
        """, height=0)


def sync_saved_jobs_to_localstorage():
    """保存済み求人をlocalStorageに同期"""
    if 'saved_jobs' in st.session_state:
        json_data = json.dumps(json.dumps(st.session_state['saved_jobs'], ensure_ascii=True))

        st.components.v1.html(f"""
            <script>
            try {{
                localStorage.setItem('saved_jobs', {json_data});
            }} catch(e) {{
                console.error('Failed to save jobs to localStorage:', e);
            }}
            </script>
        """, height=0)


def sync_saved_job_sets_to_localstorage():
    """保存済み求人セットをlocalStorageに同期"""
    if 'saved_job_sets' in st.session_state:
        json_data = json.dumps(json.dumps(st.session_state['saved_job_sets'], ensure_ascii=True))

        st.components.v1.html(f"""
            <script>
            try {{
                localStorage.setItem('saved_job_sets', {json_data});
            }} catch(e) {{
                console.error('Failed to save job sets to localStorage:', e);
            }}
            </script>
        """, height=0)


def load_from_localstorage_script():
    """localStorageから履歴を復元するJavaScriptを返す"""
    return """
        <script>
        // localStorageから履歴を読み込んでStreamlitに送信
        function loadHistory() {
            const resumeHistory = localStorage.getItem('resume_history');
            const jdHistory = localStorage.getItem('jd_history');
            const savedJobs = localStorage.getItem('saved_jobs');
            const savedJobSets = localStorage.getItem('saved_job_sets');

            if (resumeHistory || jdHistory || savedJobs || savedJobSets) {
                // Streamlitに送信するためのカスタムイベント
                const event = new CustomEvent('localStorageData', {
                    detail: {
                        resume_history: resumeHistory,
                        jd_history: jdHistory,
                        saved_jobs: savedJobs,
                        saved_job_sets: savedJobSets
                    }
                });
                window.dispatchEvent(event);
            }
        }

        // ページロード時に実行
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', loadHistory);
        } else {
            loadHistory();
        }
        </script>
    """


def export_history_to_json(history_type: str = "all") -> str:
    """履歴をJSON形式でエクスポート"""
    import json

    export_data = {
        'export_date': datetime.now().isoformat(),
        'app_version': '1.0.0',
        'data': {}
    }

    if history_type == "all":
        # すべての履歴をエクスポート
        if 'resume_history' in st.session_state:
            export_data['data']['resume_history'] = st.session_state['resume_history']
        if 'jd_history' in st.session_state:
            export_data['data']['jd_history'] = st.session_state['jd_history']
        if 'saved_jobs' in st.session_state:
            export_data['data']['saved_jobs'] = st.session_state['saved_jobs']
        if 'saved_job_sets' in st.session_state:
            export_data['data']['saved_job_sets'] = st.session_state['saved_job_sets']
    else:
        # 特定の履歴のみエクスポート
        key = f"{history_type}_history"
        if key in st.session_state:
            export_data['data'][key] = st.session_state[key]

    return json.dumps(export_data, ensure_ascii=False, indent=2)


def import_history_from_json(json_string: str) -> tuple[bool, str]:
    """JSON文字列から履歴をインポート"""
    import json

    try:
        data = json.loads(json_string)

        # 型チェック
        if not isinstance(data, dict):
            return False, "無効なファイル形式です"

        # バージョンチェック（将来的な互換性のため）
        if 'data' not in data or not isinstance(data['data'], dict):
            return False, "無効なファイル形式です"

        # 許可されたキーのみインポート
        allowed_keys = {'resume_history', 'jd_history', 'saved_jobs', 'saved_job_sets'}

        imported_count = 0

        # 履歴をインポート
        for key, history in data['data'].items():
            if key not in allowed_keys:
                continue
            if not isinstance(history, list):
                continue
            if key in ['resume_history', 'jd_history']:
                st.session_state[key] = history
                imported_count += len(history)

                # localStorageにも同期
                sync_to_localstorage(key.replace('_history', ''))
            elif key == 'saved_jobs':
                st.session_state['saved_jobs'] = history
                imported_count += len(history)
                sync_saved_jobs_to_localstorage()
            elif key == 'saved_job_sets':
                st.session_state['saved_job_sets'] = history
                imported_count += len(history)
                sync_saved_job_sets_to_localstorage()

        return True, f"✅ {imported_count}件の履歴をインポートしました"

    except json.JSONDecodeError:
        return False, "JSONファイルの解析に失敗しました"
    except Exception:
        return False, "インポートエラー: ファイルの読み込みに失敗しました"


def generate_html(content: str, title: str) -> str:
    """MarkdownテキストからHTMLを生成（印刷用スタイル付き）"""

    # まずコンテンツ全体をHTMLエスケープ（XSS対策）
    html_content = html_module.escape(content)

    # 見出し変換（エスケープ済みテキストに対して適用）
    html_content = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)

    # 太字・斜体・コード
    html_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_content)
    html_content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html_content)
    html_content = re.sub(r'`(.+?)`', r'<code>\1</code>', html_content)

    # リスト
    html_content = re.sub(r'^- (.+)$', r'<li>\1</li>', html_content, flags=re.MULTILINE)

    # テーブル変換（セル内容は既にエスケープ済み）
    def convert_table(match):
        rows = match.group(0).strip().split('\n')
        html_rows = []
        for i, row in enumerate(rows):
            cells = [c.strip() for c in row.split('|') if c.strip()]
            if not cells or all(c.replace('-', '') == '' for c in cells):
                continue
            tag = 'th' if i == 0 else 'td'
            html_cells = ''.join(f'<{tag}>{cell}</{tag}>' for cell in cells)
            html_rows.append(f'<tr>{html_cells}</tr>')
        return '<table>' + ''.join(html_rows) + '</table>' if html_rows else ''

    html_content = re.sub(r'(\|.+\|[\n])+', convert_table, html_content)

    # 区切り線
    html_content = re.sub(r'^-{3,}$', '<hr>', html_content, flags=re.MULTILINE)

    # 段落
    html_content = re.sub(r'\n\n+', '</p><p>', html_content)
    html_content = f'<p>{html_content}</p>'

    # 空のタグを削除
    html_content = re.sub(r'<p>\s*</p>', '', html_content)

    safe_title = html_module.escape(title)

    # HTMLテンプレート
    html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_title}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: "Hiragino Kaku Gothic ProN", "Hiragino Sans", "Yu Gothic", "Meiryo", sans-serif;
            font-size: 14px;
            line-height: 1.8;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 40px 20px;
            background: #fff;
        }}
        h1 {{
            font-size: 24px;
            color: #1a73e8;
            border-bottom: 3px solid #1a73e8;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        h2 {{
            font-size: 18px;
            color: #333;
            background: #f5f5f5;
            padding: 8px 12px;
            margin: 25px 0 15px 0;
            border-left: 4px solid #1a73e8;
        }}
        h3 {{
            font-size: 16px;
            color: #555;
            margin: 20px 0 10px 0;
            padding-left: 10px;
            border-left: 3px solid #ddd;
        }}
        p {{
            margin: 10px 0;
        }}
        ul, ol {{
            margin: 10px 0 10px 25px;
        }}
        li {{
            margin: 5px 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 10px 12px;
            text-align: left;
        }}
        th {{
            background: #f8f9fa;
            font-weight: bold;
        }}
        tr:nth-child(even) {{
            background: #fafafa;
        }}
        strong {{
            color: #1a73e8;
        }}
        code {{
            background: #f5f5f5;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: monospace;
        }}
        hr {{
            border: none;
            border-top: 1px solid #ddd;
            margin: 20px 0;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        @media print {{
            body {{
                padding: 20px;
                font-size: 12px;
            }}
            h1 {{ font-size: 20px; }}
            h2 {{ font-size: 16px; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{safe_title}</h1>
    </div>
    <!-- timestamp removed for clean output -->
    <div class="content">
        {html_content}
    </div>
</body>
</html>'''

    return html


def _process_single_resume(api_key: str, index: int, resume: str, anonymize: str) -> dict:
    """単一レジュメを処理（スレッド内で実行）"""
    result = {"index": index, "status": "pending", "output": None, "error": None, "time": 0}

    is_valid, error_msg = validate_input(resume, "resume")
    if not is_valid:
        result["status"] = "error"
        result["error"] = error_msg
        return result

    try:
        item_start = time.time()
        prompt = get_resume_optimization_prompt(resume, anonymize)
        output = call_groq_api(api_key, prompt)
        result["status"] = "success"
        result["output"] = finalize_resume_output(output)
        result["time"] = time.time() - item_start
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def process_batch_resumes(api_key: str, resumes: list[str], anonymize: str) -> list[dict]:
    """複数のレジュメを並列処理（最大3並列）"""

    results = [None] * len(resumes)
    max_workers = min(3, len(resumes))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_single_resume, api_key, i + 1, resume, anonymize): i
            for i, resume in enumerate(resumes)
        }
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()

    return results


def t(key: str) -> str:
    """UI翻訳ヘルパー。session_stateの言語設定に応じた翻訳文字列を返す"""
    lang = st.session_state.get('ui_lang', 'ja')
    return TRANSLATIONS.get(lang, TRANSLATIONS['ja']).get(key, key)


def _get_app_base_url() -> str:
    """アプリのベースURLを取得（secrets優先、なければデフォルト）"""
    try:
        return st.secrets["APP_URL"]
    except (KeyError, FileNotFoundError):
        return DEFAULT_APP_URL


def _copy_to_clipboard(text: str) -> None:
    """テキストをクリップボードにコピーするJSを安全に実行する。
    json.dumpsでエスケープすることでJS注入を防止。"""
    safe_json = json.dumps(text)
    st.components.v1.html(f"""
        <script>
        navigator.clipboard.writeText({safe_json});
        </script>
    """, height=0)


def _show_btn_hint(api_key: str, has_input: bool, has_input2: bool | None = None):
    """disabledボタンの理由をヒントとして表示"""
    if not api_key:
        st.caption(t("btn_hint_no_api"))
    elif has_input2 is not None and (not has_input or not has_input2):
        st.caption(t("btn_hint_no_both"))
    elif not has_input:
        st.caption(t("btn_hint_no_input"))


def main():
    """メインアプリケーション"""

    # URLパラメータで共有IDがあれば共有ビューを表示
    share_id = st.query_params.get("share")
    if share_id:
        # share_idのフォーマット検証（URL-safe base64, 20-40文字）
        if not re.match(r'^[A-Za-z0-9_-]{20,40}$', share_id):
            st.error("無効な共有リンクです")
            return
        show_shared_view(share_id)
        return  # 通常のUIは表示しない

    # オプション認証チェック（secrets.tomlにAPP_PASSWORDがある場合のみ）
    if not _check_authentication():
        return

    # セッションタイムアウトチェック
    if _check_session_timeout():
        # セッション情報をクリア（履歴以外）
        for key in ['authenticated', 'api_call_timestamps', 'session_last_activity']:
            st.session_state.pop(key, None)
        st.warning("セッションがタイムアウトしました。ページを再読み込みしてください。")
        st.stop()

    # localStorage復元スクリプトを実行（初回のみ）
    if 'localstorage_loaded' not in st.session_state:
        st.components.v1.html("""
            <script>
            // localStorageから履歴を読み込み
            function loadFromLocalStorage() {
                try {
                    const resumeHistory = localStorage.getItem('resume_history');
                    const jdHistory = localStorage.getItem('jd_history');

                    if (resumeHistory) {
                        console.log('Found resume_history in localStorage');
                    }
                    if (jdHistory) {
                        console.log('Found jd_history in localStorage');
                    }
                } catch(e) {
                    console.error('Failed to load from localStorage:', e);
                }
            }

            // ページロード時に実行
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', loadFromLocalStorage);
            } else {
                loadFromLocalStorage();
            }
            </script>
        """, height=0)
        st.session_state['localstorage_loaded'] = True

    # ヘッダー（グラデーションバナー）
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #2a5f8f 100%);
                padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem;">
        <div style="display: flex; align-items: center; gap: 0.75rem;">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.9)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink: 0;">
                <circle cx="12" cy="12" r="10"/>
                <line x1="2" y1="12" x2="22" y2="12"/>
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
            <div>
                <h1 style="color: white; margin: 0; font-size: 1.5rem; border: none;
                           padding: 0; line-height: 1.3; letter-spacing: 0.01em;">
                    {t("app_name")}
                </h1>
                <p style="color: rgba(255,255,255,0.8); margin: 0.3rem 0 0; font-size: 0.85rem;
                          line-height: 1.4; font-weight: 400;">
                    {t("app_tagline")}
                </p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # サイドバー設定
    with st.sidebar:
        # 言語切り替え（常に表示）
        if 'ui_lang' not in st.session_state:
            st.session_state['ui_lang'] = 'ja'
        lang_choice = st.radio(
            t("lang_label"),
            options=["ja", "en"],
            format_func=lambda x: "日本語" if x == "ja" else "English",
            index=0 if st.session_state.get('ui_lang', 'ja') == 'ja' else 1,
            key="ui_lang_radio",
            horizontal=True
        )
        if lang_choice != st.session_state.get('ui_lang'):
            st.session_state['ui_lang'] = lang_choice
            st.rerun()

        # 設定（API・インポート）折りたたみ
        with st.expander(t("settings"), expanded=False):
            api_key = ""
            try:
                api_key = st.secrets.get("GROQ_API_KEY", "")
            except Exception:
                pass

            if not api_key:
                api_key = st.text_input(
                    t("api_key_label"),
                    type="password",
                    placeholder=t("api_key_placeholder"),
                    help=t("api_key_help")
                )
            else:
                st.success(t("api_key_set"))

            # Gemini フォールバックキー（任意）
            st.markdown(f"**{t('gemini_fallback_label')}**")
            existing_gemini_key = st.session_state.get("gemini_api_key", "") or ""
            try:
                if not existing_gemini_key:
                    existing_gemini_key = st.secrets.get("GEMINI_API_KEY", "") or ""
            except Exception:
                pass

            gemini_api_key_input = st.text_input(
                t("gemini_fallback_placeholder"),
                value=existing_gemini_key,
                type="password",
                placeholder="AIza...",
                help=t("gemini_fallback_help"),
                key="gemini_api_key_input",
            )
            if gemini_api_key_input:
                st.session_state["gemini_api_key"] = gemini_api_key_input.strip()
                st.caption(f"✅ {t('gemini_fallback_active')}")
            else:
                st.session_state.pop("gemini_api_key", None)

            # クイックインポート（履歴がない場合のみ表示）
            resume_count = len(st.session_state.get('resume_history', []))
            jd_count = len(st.session_state.get('jd_history', []))

            if resume_count == 0 and jd_count == 0:
                st.divider()
                st.caption(t("import_hint"))
                uploaded_backup = st.file_uploader(
                    t("backup_file"),
                    type=["json"],
                    key="sidebar_import_uploader",
                    help=t("backup_file_help")
                )
                if uploaded_backup:
                    try:
                        json_string = uploaded_backup.read().decode('utf-8')
                        if st.button(t("restore_btn"), key="sidebar_import_btn", use_container_width=True):
                            success, message = import_history_from_json(json_string)
                            if success:
                                st.success(message)
                                st.rerun()
                            else:
                                st.error(message)
                    except Exception as e:
                        st.error(t("file_read_error").format(error=str(e)))

        st.divider()

        # 機能選択（カテゴリ別エクスパンダー）
        st.subheader(t("feature_select"))

        _feature_categories = {
            "resume": ["resume_optimize", "resume_anonymize", "resume_pii"],
            "jd": ["jd_jp_en", "jd_en_jp", "jd_jp_jp", "jd_en_en", "jd_anonymize", "company_intro"],
            "analysis": ["matching", "cv_extract", "email", "batch"],
        }

        if 'selected_feature' not in st.session_state:
            st.session_state['selected_feature'] = "resume_optimize"

        for cat_key, cat_features in _feature_categories.items():
            _cat_has_selected = st.session_state['selected_feature'] in cat_features
            with st.expander(t(f"feature_cat_{cat_key}"), expanded=_cat_has_selected):
                for feat_key in cat_features:
                    is_selected = st.session_state['selected_feature'] == feat_key
                    if st.button(
                        t(f"feature.{feat_key}"),
                        key=f"feat_btn_{feat_key}",
                        use_container_width=True,
                        type="primary" if is_selected else "secondary",
                    ):
                        st.session_state['selected_feature'] = feat_key
                        st.rerun()

        feature = st.session_state['selected_feature']

        st.divider()

        # 使い方ガイド（初回は展開状態）
        _is_first_visit = not bool(st.session_state.get('resume_history')) and not bool(st.session_state.get('jd_history'))
        with st.expander(t("usage_guide"), expanded=_is_first_visit):
            st.markdown(t("usage_guide_content"))

    # メインコンテンツ
    if feature == "resume_optimize":
        st.subheader(t("resume_opt_title"))
        st.caption(t("resume_opt_desc"))

        col1, col2 = st.columns([1, 1])

        with col1:
            # 入力方法タブ
            input_tab1, input_tab2, input_tab3 = st.tabs([t("tab_text_input"), t("tab_pdf"), t("tab_linkedin")])

            with input_tab1:
                # サンプルデータボタン
                col_label, col_sample = st.columns([3, 1])
                with col_label:
                    st.markdown(t("input_resume"))
                with col_sample:
                    if st.button(t("sample_btn"), key="sample_resume_btn", help=t("sample_help"), type="tertiary"):
                        st.session_state['resume_text_input'] = SAMPLE_RESUME

                # テキストエリアの値を取得
                resume_input = st.text_area(
                    t("paste_resume"),
                    height=350,
                    placeholder=t("paste_resume_placeholder"),
                    label_visibility="collapsed",
                    key="resume_text_input"
                )

            with input_tab2:
                st.markdown(t("upload_pdf"))
                uploaded_pdf = st.file_uploader(
                    t("select_pdf"),
                    type=["pdf"],
                    key="resume_pdf",
                    help=t("pdf_help").format(size=MAX_PDF_SIZE_MB)
                )

                if uploaded_pdf:
                    with st.spinner(t("reading_pdf")):
                        extracted_text, error = extract_text_from_pdf(uploaded_pdf)
                        if error:
                            st.error(f"❌ {error}")
                        else:
                            st.success(t("text_extracted").format(count=f"{len(extracted_text):,}"))
                            resume_input = extracted_text
                            with st.expander(t("view_extracted")):
                                st.text(extracted_text[:2000] + ("..." if len(extracted_text) > 2000 else ""))
                else:
                    # PDFがない場合はテキスト入力を使用
                    if 'resume_input' not in dir():
                        resume_input = ""

            with input_tab3:
                st.markdown(t("linkedin_header"))
                st.info(t("linkedin_hint"))

                with st.expander(t("linkedin_how"), expanded=False):
                    st.markdown(t("linkedin_instructions"))

                linkedin_input = st.text_area(
                    t("paste_linkedin"),
                    height=300,
                    placeholder=t("linkedin_placeholder"),
                    label_visibility="collapsed",
                    key="linkedin_text_input"
                )

                if linkedin_input:
                    resume_input = linkedin_input
                    st.success(t("linkedin_loaded").format(count=f"{len(linkedin_input):,}"))

            # 文字数カウンター
            char_count = len(resume_input) if resume_input else 0
            if char_count > MAX_INPUT_CHARS:
                st.error(t("char_count_exceeded").format(count=f"{char_count:,}", max=f"{MAX_INPUT_CHARS:,}"))
            elif char_count > 0:
                st.caption(t("char_count").format(count=f"{char_count:,}", max=f"{MAX_INPUT_CHARS:,}"))

            processing_mode = st.radio(
                t("mode_label"),
                options=["deterministic", "llm_optimize"],
                format_func=lambda x: {
                    "deterministic": t("mode_deterministic"),
                    "llm_optimize": t("mode_llm_optimize"),
                }[x],
                index=0,
                help=t("mode_help"),
                key="resume_processing_mode",
            )

            if processing_mode == "llm_optimize":
                anonymize = st.radio(
                    t("anon_label"),
                    options=["full", "light", "none"],
                    format_func=lambda x: {
                        "full": t("anon_full"),
                        "light": t("anon_light"),
                        "none": t("anon_none")
                    }[x],
                    index=0,
                    help=t("anon_help")
                )
            else:
                # 決定論モードでは匿名化オプション不要（常に PII 全削除）
                anonymize = "light"

            # 決定論モードは API キー不要
            _needs_api_key = processing_mode == "llm_optimize"
            if _needs_api_key:
                _show_btn_hint(api_key, bool(resume_input))
            process_btn = st.button(
                t("transform_btn"),
                type="primary",
                use_container_width=True,
                disabled=(_needs_api_key and not api_key) or not resume_input,
            )

        with col2:
            st.markdown(t("resume_opt_output"))

            if not process_btn and 'resume_result' not in st.session_state:
                st.info(t("output_placeholder"))

            if process_btn:
                # 決定論モード: LLM 不使用・即座に PII 削除
                if processing_mode == "deterministic":
                    is_valid, error_msg = validate_input(resume_input, "resume")
                    if not is_valid:
                        st.warning(f"⚠️ {error_msg}")
                    else:
                        start_time = time.time()
                        result = redact_pii_deterministic(resume_input)
                        elapsed_time = time.time() - start_time
                        st.session_state['resume_result'] = result
                        st.session_state['resume_time'] = elapsed_time
                        st.session_state['resume_iterations'] = []

                        residuals = regex_pii_scan(result)
                        if residuals:
                            st.warning(t("mode_det_residual"))
                            for r in residuals:
                                st.code(f"[{r['type']}] {r['text']}")
                        else:
                            st.success(t("mode_det_done").format(time=f"{elapsed_time:.2f}"))
                elif not api_key:
                    st.error(t("no_api_key"))
                else:
                    # 入力バリデーション
                    is_valid, error_msg = validate_input(resume_input, "resume")
                    if not is_valid:
                        st.warning(f"⚠️ {error_msg}")
                    else:
                        try:
                            start_time = time.time()
                            base_prompt = get_resume_optimization_prompt(resume_input, anonymize)
                            status_container = st.empty()

                            verification_mode = f"optimize_{anonymize}" if anonymize in ("full", "light") else "optimize_none"

                            result, iterations, passed = run_resume_transform_loop(
                                api_key,
                                original_text=resume_input,
                                base_prompt=base_prompt,
                                verification_mode=verification_mode,
                                status_container=status_container,
                                status_generating=t("resume_opt_ai"),
                                status_regenerating=t("pii_regenerating"),
                                status_verifying=t("pii_verifying"),
                                apply_regex_pii=(anonymize in ("full", "light")),
                                post_processor=finalize_resume_output,
                            )
                            elapsed_time = time.time() - start_time
                            status_container.empty()

                            st.session_state['resume_result'] = result
                            st.session_state['resume_time'] = elapsed_time
                            st.session_state['resume_iterations'] = iterations

                            if passed:
                                st.success(t("pii_done_verified").format(
                                    time=f"{elapsed_time:.1f}",
                                    iters=len(iterations),
                                ))
                            else:
                                st.warning(t("pii_max_iter").format(
                                    time=f"{elapsed_time:.1f}",
                                    iters=len(iterations),
                                ))

                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"❌ {t('unexpected_error')}\n\n[詳細] {type(e).__name__}: {e}")
                            import traceback
                            with st.expander("🐛 スタックトレース（開発者向け）"):
                                st.code(traceback.format_exc())

            # 結果表示
            if 'resume_result' in st.session_state:
                # 表示切替とコピーボタン
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted = st.checkbox(t("formatted_view"), value=False, key="resume_formatted",
                                                  help=t("formatted_help"))
                with col_copy:
                    if st.button(t("copy_btn"), key="copy_resume", use_container_width=True):
                        st.toast(t("copied"))
                        _copy_to_clipboard(st.session_state['resume_result'])

                if show_formatted:
                    st.markdown(st.session_state['resume_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_result = st.text_area(
                        t("editable_output"),
                        value=st.session_state['resume_result'],
                        height=400,
                        key="edit_resume_result_jp"
                    )
                    st.session_state['resume_result'] = edited_result

                # 精度検証の詳細パネル
                if st.session_state.get('resume_iterations'):
                    render_verification_details(
                        st.session_state['resume_iterations'],
                        key_suffix="opt",
                    )

                # ファーストネームをタイトル・ファイル名に使用
                _opt_first = extract_first_name(st.session_state['resume_result'])
                _opt_label = f"候補者レジュメ - {_opt_first}" if _opt_first else "候補者レジュメ"
                _opt_fname = f"resume_{_opt_first}_{datetime.now().strftime('%Y%m%d_%H%M')}" if _opt_first else f"resume_{datetime.now().strftime('%Y%m%d_%H%M')}"

                # ダウンロードボタン
                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1:
                    st.download_button(
                        t("dl_markdown"),
                        data=st.session_state['resume_result'],
                        file_name=f"{_opt_fname}.md",
                        mime="text/markdown"
                    )
                with col_dl2:
                    st.download_button(
                        t("dl_text"),
                        data=st.session_state['resume_result'],
                        file_name=f"{_opt_fname}.txt",
                        mime="text/plain"
                    )
                with col_dl3:
                    html_content = generate_html(st.session_state['resume_result'], _opt_label)
                    st.download_button(
                        t("dl_html"),
                        data=html_content,
                        file_name=f"{_opt_fname}.html",
                        mime="text/html",
                        help=t("dl_html_help")
                    )

                # 追加変換ボタン
                st.divider()
                st.markdown(t("additional_convert"))
                if st.button(t("convert_to_en"), key="convert_to_en_anonymize", use_container_width=True, help=t("convert_to_en_help")):
                    try:
                        # 手直し済みの日本語レジュメを翻訳（編集内容を保持）+ 検証ループ
                        edited_jp_resume = st.session_state.get('resume_result', '').strip()
                        if edited_jp_resume:
                            base_prompt_en = get_translate_to_english_prompt(edited_jp_resume)
                            status_container = st.empty()

                            result_en, iterations_en, passed_en = run_resume_transform_loop(
                                api_key,
                                original_text=edited_jp_resume,
                                base_prompt=base_prompt_en,
                                verification_mode="translate_to_en",
                                status_container=status_container,
                                status_generating=t("generating_en"),
                                status_regenerating=t("pii_regenerating"),
                                status_verifying=t("pii_verifying"),
                                apply_regex_pii=False,
                                post_processor=None,
                            )
                            status_container.empty()

                            st.session_state['resume_en_result'] = result_en
                            st.session_state['resume_en_iterations'] = iterations_en
                            st.success(t("en_done"))
                            st.info(t("scroll_hint"))
                            st.rerun()
                        else:
                            st.error(t("no_original_resume"))
                    except Exception as e:
                        st.error(f"❌ {t('generation_error')}\n\n[詳細] {type(e).__name__}: {e}")
                        import traceback
                        with st.expander("🐛 スタックトレース（開発者向け）"):
                            st.code(traceback.format_exc())

                # 英語匿名化結果の表示
                if 'resume_en_result' in st.session_state and st.session_state.get('resume_result'):
                    st.divider()
                    st.markdown(t("en_result_header"))

                    col_view_en2, col_copy_en2 = st.columns([2, 1])
                    with col_view_en2:
                        show_formatted_en2 = st.checkbox(t("formatted_view"), value=False, key="resume_en2_formatted")
                    with col_copy_en2:
                        if st.button(t("copy_btn"), key="copy_resume_en2", use_container_width=True):
                            st.toast(t("copied"))
                            _copy_to_clipboard(st.session_state['resume_en_result'])

                    if show_formatted_en2:
                        st.markdown(st.session_state['resume_en_result'])
                    else:
                        edited_result_en2 = st.text_area(
                            "Output (Editable)",
                            value=st.session_state['resume_en_result'],
                            height=400,
                            key="edit_resume_result_en2"
                        )
                        st.session_state['resume_en_result'] = edited_result_en2

                    # 精度検証の詳細パネル（JP→EN翻訳）
                    if st.session_state.get('resume_en_iterations'):
                        render_verification_details(
                            st.session_state['resume_en_iterations'],
                            key_suffix="tr_en",
                        )

                    # ファーストネームをタイトル・ファイル名に使用
                    _en2_first = extract_first_name(st.session_state['resume_en_result'])
                    _en2_label = f"Anonymized Resume - {_en2_first}" if _en2_first else "Anonymized Resume"
                    _en2_fname = f"resume_{_en2_first}_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}" if _en2_first else f"resume_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}"

                    # ダウンロードボタン
                    col_dl1_en2, col_dl2_en2, col_dl3_en2 = st.columns(3)
                    with col_dl1_en2:
                        st.download_button(
                            "📄 Markdown",
                            data=st.session_state['resume_en_result'],
                            file_name=f"{_en2_fname}.md",
                            mime="text/markdown",
                            key="en2_md"
                        )
                    with col_dl2_en2:
                        st.download_button(
                            "📝 テキスト",
                            data=st.session_state['resume_en_result'],
                            file_name=f"{_en2_fname}.txt",
                            mime="text/plain",
                            key="en2_txt"
                        )
                    with col_dl3_en2:
                        html_content = generate_html(st.session_state['resume_en_result'], _en2_label)
                        st.download_button(
                            "🌐 HTML",
                            data=html_content,
                            file_name=f"{_en2_fname}.html",
                            mime="text/html",
                            key="en2_html",
                            help="ブラウザで開いて印刷→PDF保存"
                        )

                # 共有リンク作成ボタン — ファーストネームをタイトルに使用
                _share_first = extract_first_name(st.session_state.get('resume_result', ''))
                _share_title = f"候補者レジュメ（匿名化済み）- {_share_first}" if _share_first else "候補者レジュメ（匿名化済み）"
                if get_supabase_client():
                    st.divider()
                    if st.button("🔗 共有リンク作成", key="share_resume_jp", help="1ヶ月有効の共有リンクを作成"):
                        with st.spinner("共有リンクを作成中..."):
                            share_id = create_share_link(
                                st.session_state['resume_result'],
                                _share_title
                            )
                        if share_id:
                            base_url = _get_app_base_url()
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                            st.code(share_url)
                            st.info("💡 上のURLをコピーしてクライアントに共有してください")
                        else:
                            st.error("❌ 共有リンクの作成に失敗しました")

    elif feature == "resume_anonymize":
        st.subheader(t("resume_anon_title"))
        st.caption(t("resume_anon_desc"))

        col1, col2 = st.columns([1, 1])

        with col1:
            # 入力方法タブ
            input_tab1, input_tab2, input_tab3 = st.tabs([t("tab_text_input"), t("tab_pdf"), t("tab_linkedin")])

            with input_tab1:
                # サンプルデータボタン
                col_label, col_sample = st.columns([3, 1])
                with col_label:
                    st.markdown(t("input_resume"))
                with col_sample:
                    if st.button(t("sample_btn"), key="sample_resume_en_btn", help=t("sample_help"), type="tertiary"):
                        st.session_state['resume_en_text'] = SAMPLE_RESUME

                resume_en_input = st.text_area(
                    t("paste_resume"),
                    height=350,
                    placeholder="Paste the English resume here...",
                    label_visibility="collapsed",
                    key="resume_en_text"
                )

            with input_tab2:
                st.markdown(t("upload_pdf"))
                uploaded_pdf_en = st.file_uploader(
                    t("select_pdf"),
                    type=["pdf"],
                    key="resume_en_pdf",
                    help=t("pdf_help").format(size=MAX_PDF_SIZE_MB)
                )

                if uploaded_pdf_en:
                    with st.spinner(t("reading_pdf")):
                        extracted_text_en, error_en = extract_text_from_pdf(uploaded_pdf_en)
                        if error_en:
                            st.error(f"❌ {error_en}")
                        else:
                            st.success(t("text_extracted").format(count=f"{len(extracted_text_en):,}"))
                            resume_en_input = extracted_text_en
                            with st.expander(t("view_extracted")):
                                st.text(extracted_text_en[:2000] + ("..." if len(extracted_text_en) > 2000 else ""))
                else:
                    if 'resume_en_input' not in dir():
                        resume_en_input = ""

            with input_tab3:
                st.markdown(t("linkedin_header"))
                st.info(t("linkedin_hint"))

                with st.expander("📖 コピー方法", expanded=False):
                    st.markdown("""
                    1. LinkedInでプロフィールページを開く
                    2. `Ctrl+A`（Mac: `Cmd+A`）で全選択
                    3. `Ctrl+C`（Mac: `Cmd+C`）でコピー
                    4. 下のテキストエリアに貼り付け
                    """)

                linkedin_en_input = st.text_area(
                    "LinkedInプロフィールをペースト",
                    height=300,
                    placeholder="LinkedInプロフィールページのテキストを貼り付けてください...",
                    label_visibility="collapsed",
                    key="linkedin_en_text"
                )

                if linkedin_en_input:
                    resume_en_input = linkedin_en_input
                    st.success(f"✅ LinkedInテキスト読み込み完了（{len(linkedin_en_input):,}文字）")

            # 文字数カウンター
            char_count_en = len(resume_en_input) if resume_en_input else 0
            if char_count_en > MAX_INPUT_CHARS:
                st.error(f"📊 {char_count_en:,} / {MAX_INPUT_CHARS:,} 文字（超過）")
            elif char_count_en > 0:
                st.caption(f"📊 {char_count_en:,} / {MAX_INPUT_CHARS:,} 文字")

            anonymize_en = st.radio(
                t("anon_label"),
                options=["full", "light"],
                format_func=lambda x: {
                    "full": t("anon_full"),
                    "light": t("anon_light")
                }[x],
                index=0,
                key="anonymize_en",
                help="完全：企業名・大学名も業界表現に変換 / 軽度：氏名・連絡先のみ匿名化"
            )

            _show_btn_hint(api_key, bool(resume_en_input))
            process_en_btn = st.button(
                t("resume_anon_btn"),
                type="primary",
                use_container_width=True,
                disabled=not api_key or not resume_en_input,
                key="process_en_btn"
            )

        with col2:
            st.markdown(t("resume_anon_output"))

            if not process_en_btn and 'resume_en_result' not in st.session_state:
                st.info(t("output_placeholder"))

            if process_en_btn:
                if not api_key:
                    st.error(t("no_api_key"))
                else:
                    is_valid_en, error_msg_en = validate_input(resume_en_input, "resume")
                    if not is_valid_en:
                        st.warning(f"⚠️ {error_msg_en}")
                    else:
                        try:
                            start_time = time.time()
                            base_prompt = get_english_anonymization_prompt(resume_en_input, anonymize_en)
                            status_container = st.empty()

                            result, iterations, passed = run_resume_transform_loop(
                                api_key,
                                original_text=resume_en_input,
                                base_prompt=base_prompt,
                                verification_mode=f"anonymize_{anonymize_en}",
                                status_container=status_container,
                                status_generating=t("resume_anon_ai"),
                                status_regenerating=t("pii_regenerating"),
                                status_verifying=t("pii_verifying"),
                                apply_regex_pii=True,
                                post_processor=finalize_resume_output,
                            )
                            elapsed_time = time.time() - start_time
                            status_container.empty()

                            st.session_state['resume_en_result'] = result
                            st.session_state['resume_en_time'] = elapsed_time
                            st.session_state['resume_en_iterations'] = iterations

                            if passed:
                                st.success(t("pii_done_verified").format(
                                    time=f"{elapsed_time:.1f}",
                                    iters=len(iterations),
                                ))
                            else:
                                st.warning(t("pii_max_iter").format(
                                    time=f"{elapsed_time:.1f}",
                                    iters=len(iterations),
                                ))

                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"❌ {t('unexpected_error')}\n\n[詳細] {type(e).__name__}: {e}")
                            import traceback
                            with st.expander("🐛 スタックトレース（開発者向け）"):
                                st.code(traceback.format_exc())

            # 結果表示
            if 'resume_en_result' in st.session_state:
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted_en = st.checkbox(t("formatted_view"), value=False, key="resume_en_formatted")
                with col_copy:
                    if st.button(t("copy_btn"), key="copy_resume_en", use_container_width=True):
                        st.toast(t("copied"))
                        _copy_to_clipboard(st.session_state['resume_en_result'])

                if show_formatted_en:
                    st.markdown(st.session_state['resume_en_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_result_en = st.text_area(
                        t("editable_output"),
                        value=st.session_state['resume_en_result'],
                        height=400,
                        key="edit_resume_result_en"
                    )
                    st.session_state['resume_en_result'] = edited_result_en

                # 精度検証の詳細パネル
                if st.session_state.get('resume_en_iterations'):
                    render_verification_details(
                        st.session_state['resume_en_iterations'],
                        key_suffix="anon",
                    )

                # ファーストネームをタイトル・ファイル名に使用
                _en_first = extract_first_name(st.session_state['resume_en_result'])
                _en_label = f"Anonymized Resume - {_en_first}" if _en_first else "Anonymized Resume"
                _en_fname = f"resume_{_en_first}_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}" if _en_first else f"resume_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}"

                # ダウンロードボタン
                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1:
                    st.download_button(
                        "📄 Markdown",
                        data=st.session_state['resume_en_result'],
                        file_name=f"{_en_fname}.md",
                        mime="text/markdown",
                        key="en_md"
                    )
                with col_dl2:
                    st.download_button(
                        t("dl_text"),
                        data=st.session_state['resume_en_result'],
                        file_name=f"{_en_fname}.txt",
                        mime="text/plain",
                        key="en_txt"
                    )
                with col_dl3:
                    html_content = generate_html(st.session_state['resume_en_result'], _en_label)
                    st.download_button(
                        "🌐 HTML",
                        data=html_content,
                        file_name=f"{_en_fname}.html",
                        mime="text/html",
                        key="en_html",
                        help=t("dl_html_help")
                    )

                # 追加変換ボタン
                st.divider()
                st.markdown("##### 🔄 追加変換")
                if st.button(t("convert_to_jp"), key="convert_to_jp_translate", use_container_width=True, help="手直し済みの英語レジュメを日本語に翻訳（編集内容を保持）"):
                    try:
                        # 手直し済みの英語レジュメを翻訳（編集内容を保持）+ 検証ループ
                        edited_en_resume = st.session_state.get('resume_en_result', '').strip()
                        if edited_en_resume:
                            base_prompt_jp = get_translate_to_japanese_prompt(edited_en_resume)
                            status_container = st.empty()

                            result_jp, iterations_jp, passed_jp = run_resume_transform_loop(
                                api_key,
                                original_text=edited_en_resume,
                                base_prompt=base_prompt_jp,
                                verification_mode="translate_to_jp",
                                status_container=status_container,
                                status_generating=t("generating_jp"),
                                status_regenerating=t("pii_regenerating"),
                                status_verifying=t("pii_verifying"),
                                apply_regex_pii=False,
                                post_processor=finalize_resume_output,
                            )
                            status_container.empty()

                            st.session_state['resume_result'] = result_jp
                            st.session_state['resume_iterations'] = iterations_jp
                            st.success(t("jp_done"))
                            st.info("💡 下にスクロールして結果を確認してください")
                            st.rerun()
                        else:
                            st.error("❌ 英語レジュメが見つかりません。最初から変換し直してください。")
                    except Exception as e:
                        st.error(f"❌ 生成エラーが発生しました。\n\n[詳細] {type(e).__name__}: {e}")
                        import traceback
                        with st.expander("🐛 スタックトレース（開発者向け）"):
                            st.code(traceback.format_exc())

                # 日本語変換結果の表示（英語匿名化後の追加変換）
                if 'resume_result' in st.session_state and st.session_state.get('resume_en_result') and not st.session_state.get('resume_text_input'):
                    st.divider()
                    st.markdown(t("jp_result_header"))

                    col_view_jp2, col_copy_jp2 = st.columns([2, 1])
                    with col_view_jp2:
                        show_formatted_jp2 = st.checkbox(t("formatted_view"), value=False, key="resume_jp2_formatted")
                    with col_copy_jp2:
                        if st.button(t("copy_btn"), key="copy_resume_jp2", use_container_width=True):
                            st.toast(t("copied"))
                            _copy_to_clipboard(st.session_state['resume_result'])

                    if show_formatted_jp2:
                        st.markdown(st.session_state['resume_result'])
                    else:
                        edited_result_jp2 = st.text_area(
                            t("editable_output"),
                            value=st.session_state['resume_result'],
                            height=400,
                            key="edit_resume_result_jp2"
                        )
                        st.session_state['resume_result'] = edited_result_jp2

                    # 精度検証の詳細パネル（EN→JP翻訳）
                    if st.session_state.get('resume_iterations'):
                        render_verification_details(
                            st.session_state['resume_iterations'],
                            key_suffix="tr_jp",
                        )

                    # ファーストネームをタイトル・ファイル名に使用
                    _jp2_first = extract_first_name(st.session_state['resume_result'])
                    _jp2_label = f"候補者レジュメ - {_jp2_first}" if _jp2_first else "候補者レジュメ"
                    _jp2_fname = f"resume_{_jp2_first}_jp_{datetime.now().strftime('%Y%m%d_%H%M')}" if _jp2_first else f"resume_jp_{datetime.now().strftime('%Y%m%d_%H%M')}"

                    # ダウンロードボタン
                    col_dl1_jp2, col_dl2_jp2, col_dl3_jp2 = st.columns(3)
                    with col_dl1_jp2:
                        st.download_button(
                            "📄 Markdown",
                            data=st.session_state['resume_result'],
                            file_name=f"{_jp2_fname}.md",
                            mime="text/markdown",
                            key="jp2_md"
                        )
                    with col_dl2_jp2:
                        st.download_button(
                            t("dl_text"),
                            data=st.session_state['resume_result'],
                            file_name=f"{_jp2_fname}.txt",
                            mime="text/plain",
                            key="jp2_txt"
                        )
                    with col_dl3_jp2:
                        html_content = generate_html(st.session_state['resume_result'], _jp2_label)
                        st.download_button(
                            "🌐 HTML",
                            data=html_content,
                            file_name=f"resume_jp_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                            mime="text/html",
                            key="jp2_html",
                            help=t("dl_html_help")
                        )

                # 共有リンク作成ボタン — ファーストネームをタイトルに使用
                _share_en_first = extract_first_name(st.session_state.get('resume_en_result', ''))
                _share_en_title = f"Anonymized Resume - {_share_en_first}" if _share_en_first else "Anonymized Resume"
                if get_supabase_client():
                    st.divider()
                    if st.button("🔗 共有リンク作成", key="share_resume_en", help="1ヶ月有効の共有リンクを作成"):
                        with st.spinner("共有リンクを作成中..."):
                            share_id = create_share_link(
                                st.session_state['resume_en_result'],
                                _share_en_title
                            )
                        if share_id:
                            base_url = _get_app_base_url()
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                            st.code(share_url)
                            st.info("💡 上のURLをコピーしてクライアントに共有してください")
                        else:
                            st.error("❌ 共有リンクの作成に失敗しました")

    elif feature == "resume_pii":
        st.subheader(t("pii_title"))
        st.caption(t("pii_desc"))

        col1, col2 = st.columns([1, 1])

        with col1:
            # 入力方法タブ
            input_tab1, input_tab2 = st.tabs([t("tab_text_input"), t("tab_pdf")])

            with input_tab1:
                st.markdown(t("pii_input"))

                resume_pii_input = st.text_area(
                    t("pii_paste"),
                    height=350,
                    placeholder=t("pii_placeholder"),
                    label_visibility="collapsed",
                    key="resume_pii_text"
                )

            with input_tab2:
                st.markdown(t("upload_pdf"))
                uploaded_pdf_pii = st.file_uploader(
                    t("select_pdf"),
                    type=["pdf"],
                    key="resume_pii_pdf",
                    help=t("pdf_help").format(size=MAX_PDF_SIZE_MB)
                )

                if uploaded_pdf_pii:
                    with st.spinner(t("reading_pdf")):
                        extracted_text_pii, error_pii = extract_text_from_pdf(uploaded_pdf_pii)
                        if error_pii:
                            st.error(f"❌ {error_pii}")
                        else:
                            st.success(t("text_extracted").format(count=f"{len(extracted_text_pii):,}"))
                            resume_pii_input = extracted_text_pii
                            with st.expander(t("view_extracted")):
                                st.text(extracted_text_pii[:2000] + ("..." if len(extracted_text_pii) > 2000 else ""))
                else:
                    if 'resume_pii_input' not in dir():
                        resume_pii_input = ""

            # 文字数カウンター
            char_count_pii = len(resume_pii_input) if resume_pii_input else 0
            if char_count_pii > MAX_INPUT_CHARS:
                st.error(f"📊 {char_count_pii:,} / {MAX_INPUT_CHARS:,} 文字（超過）")
            elif char_count_pii > 0:
                st.caption(f"📊 {char_count_pii:,} / {MAX_INPUT_CHARS:,} 文字")

            st.info(t("pii_info"))

            pii_mode = st.radio(
                t("pii_mode_label"),
                options=["redact_only", "redact_and_format"],
                format_func=lambda v: t("pii_mode_redact_only") if v == "redact_only" else t("pii_mode_redact_and_format"),
                horizontal=True,
                key="pii_mode",
                help=t("pii_mode_help"),
            )

            _show_btn_hint(api_key, bool(resume_pii_input))
            process_pii_btn = st.button(
                t("pii_btn"),
                type="primary",
                use_container_width=True,
                disabled=not api_key or not resume_pii_input,
                key="process_pii_btn"
            )

        with col2:
            st.markdown(t("pii_output"))

            if not process_pii_btn and 'resume_pii_result' not in st.session_state:
                st.info(t("output_placeholder"))

            if process_pii_btn:
                if not api_key:
                    st.error(t("no_api_key"))
                else:
                    is_valid_pii, error_msg_pii = validate_input(resume_pii_input, "resume")
                    if not is_valid_pii:
                        st.warning(f"⚠️ {error_msg_pii}")
                    else:
                        try:
                            start_time = time.time()
                            MAX_PII_ITERATIONS = 5

                            iterations = []
                            current_output = ""
                            feedback_json = ""
                            status_container = st.empty()

                            for iter_num in range(1, MAX_PII_ITERATIONS + 1):
                                # 1st: 通常生成 / 2nd以降: フィードバック付き再生成
                                # 「削除のみ」プロンプトを採用（整形・要約・翻訳を禁止しハルシネーションを抑制）
                                if iter_num == 1:
                                    status_container.caption(t("pii_ai"))
                                    prompt = get_resume_pii_redaction_only_prompt(resume_pii_input)
                                else:
                                    status_container.caption(
                                        t("pii_regenerating").format(n=iter_num, max=MAX_PII_ITERATIONS)
                                    )
                                    prompt = get_resume_pii_redaction_only_prompt(
                                        resume_pii_input,
                                        previous_output=current_output,
                                        issues_feedback=feedback_json,
                                    )

                                stream_container = st.empty()
                                current_output = stream_to_container(api_key, prompt, stream_container)
                                stream_container.empty()

                                # スキル欄の推測メタデータ（経験年数・習熟度）を機械的に除去
                                current_output = strip_skill_metadata(current_output)
                                # 候補者スナップショットに混入した「エンジニア歴」「現在のレベル」行も除去
                                current_output = strip_engineer_years_and_seniority(current_output)

                                # 精度検証 (LLM + regex)
                                status_container.caption(
                                    t("pii_verifying").format(n=iter_num, max=MAX_PII_ITERATIONS)
                                )
                                try:
                                    verify_prompt = get_resume_pii_verification_prompt(
                                        resume_pii_input, current_output
                                    )
                                    verification = call_groq_api_json(api_key, verify_prompt)
                                except ValueError as ve:
                                    # 検証失敗時は結果そのものは保持し、警告のみ出す
                                    st.warning(f"⚠️ {ve}")
                                    verification = {
                                        "passed": False,
                                        "pii_leaks": [],
                                        "fact_mismatches": [],
                                        "missing_facts": [],
                                        "fabrications": [],
                                        "summary": "検証エラー（結果は未検証）",
                                    }

                                # 正規表現による決定的PIIチェック
                                regex_leaks = regex_pii_scan(current_output)
                                if regex_leaks:
                                    verification.setdefault("pii_leaks", [])
                                    existing_leaks = {
                                        (l.get("type"), l.get("text"))
                                        for l in verification["pii_leaks"]
                                    }
                                    for leak in regex_leaks:
                                        if (leak["type"], leak["text"]) not in existing_leaks:
                                            verification["pii_leaks"].append(leak)
                                    verification["passed"] = False

                                # 決定論的な事実集合チェック（数値・月年・資格名・社名）
                                # LLM が創作した数値・日付を Python で突き合わせて検出する最終防衛線
                                entity_diff = compare_resume_entities(resume_pii_input, current_output)
                                if entity_diff.get("fabrications"):
                                    verification.setdefault("fabrications", [])
                                    existing_fab = {
                                        (f.get("field"), f.get("anonymized"))
                                        for f in verification["fabrications"]
                                    }
                                    for fab in entity_diff["fabrications"]:
                                        key = (fab.get("field"), fab.get("anonymized"))
                                        if key not in existing_fab:
                                            verification["fabrications"].append(fab)
                                    verification["passed"] = False
                                if entity_diff.get("missing_facts"):
                                    verification.setdefault("missing_facts", [])
                                    existing_miss = {
                                        (m.get("field"), m.get("original"))
                                        for m in verification["missing_facts"]
                                    }
                                    for miss in entity_diff["missing_facts"]:
                                        key = (miss.get("field"), miss.get("original"))
                                        if key not in existing_miss:
                                            verification["missing_facts"].append(miss)
                                    verification["passed"] = False

                                iterations.append({
                                    "iter": iter_num,
                                    "output": current_output,
                                    "verification": verification,
                                })

                                if verification.get("passed"):
                                    break

                                # 次イテレーションへのフィードバック
                                feedback_json = json.dumps(
                                    {
                                        "pii_leaks": verification.get("pii_leaks", []),
                                        "fact_mismatches": verification.get("fact_mismatches", []),
                                        "missing_facts": verification.get("missing_facts", []),
                                        "fabrications": verification.get("fabrications", []),
                                    },
                                    ensure_ascii=False,
                                    indent=2,
                                )

                            # 整形モード: 削除が通った後に 1 回だけ整形パスを走らせる
                            if (
                                pii_mode == "redact_and_format"
                                and iterations
                                and iterations[-1]["verification"].get("passed")
                            ):
                                status_container.caption(t("pii_formatting"))
                                format_prompt = get_resume_format_prompt(current_output)
                                format_stream_container = st.empty()
                                formatted_output = stream_to_container(
                                    api_key, format_prompt, format_stream_container
                                )
                                format_stream_container.empty()
                                formatted_output = finalize_resume_output(formatted_output)

                                status_container.caption(t("pii_format_verifying"))
                                try:
                                    fmt_verify_prompt = get_resume_pii_verification_prompt(
                                        resume_pii_input, formatted_output
                                    )
                                    fmt_verification = call_groq_api_json(
                                        api_key, fmt_verify_prompt
                                    )
                                except ValueError as ve:
                                    st.warning(f"⚠️ {ve}")
                                    fmt_verification = {
                                        "passed": False,
                                        "pii_leaks": [],
                                        "fact_mismatches": [],
                                        "missing_facts": [],
                                        "fabrications": [],
                                        "summary": "整形検証エラー（結果は未検証）",
                                    }

                                # 整形結果にも regex + 決定論チェックを再適用
                                fmt_regex = regex_pii_scan(formatted_output)
                                if fmt_regex:
                                    fmt_verification.setdefault("pii_leaks", []).extend(fmt_regex)
                                    fmt_verification["passed"] = False
                                fmt_diff = compare_resume_entities(resume_pii_input, formatted_output)
                                if fmt_diff.get("fabrications"):
                                    fmt_verification.setdefault("fabrications", []).extend(
                                        fmt_diff["fabrications"]
                                    )
                                    fmt_verification["passed"] = False
                                if fmt_diff.get("missing_facts"):
                                    fmt_verification.setdefault("missing_facts", []).extend(
                                        fmt_diff["missing_facts"]
                                    )
                                    fmt_verification["passed"] = False

                                iterations.append({
                                    "iter": len(iterations) + 1,
                                    "output": formatted_output,
                                    "verification": fmt_verification,
                                    "stage": "format",
                                })

                                if fmt_verification.get("passed"):
                                    current_output = formatted_output

                            elapsed_time = time.time() - start_time
                            status_container.empty()

                            st.session_state['resume_pii_result'] = current_output
                            st.session_state['resume_pii_time'] = elapsed_time
                            st.session_state['resume_pii_iterations'] = iterations

                            last_verification = iterations[-1]["verification"] if iterations else {}
                            if last_verification.get("passed"):
                                st.success(t("pii_done_verified").format(
                                    time=f"{elapsed_time:.1f}",
                                    iters=len(iterations),
                                ))
                            else:
                                st.warning(t("pii_max_iter").format(
                                    time=f"{elapsed_time:.1f}",
                                    iters=len(iterations),
                                ))

                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"❌ {t('unexpected_error')}\n\n[詳細] {type(e).__name__}: {e}")
                            import traceback
                            with st.expander("🐛 スタックトレース（開発者向け）"):
                                st.code(traceback.format_exc())

            # 結果表示
            if 'resume_pii_result' in st.session_state:
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted_pii = st.checkbox(t("formatted_view"), value=False, key="resume_pii_formatted")
                with col_copy:
                    if st.button(t("copy_btn"), key="copy_resume_pii", use_container_width=True):
                        st.toast(t("copied"))
                        _copy_to_clipboard(st.session_state['resume_pii_result'])

                if show_formatted_pii:
                    st.markdown(st.session_state['resume_pii_result'])
                else:
                    edited_result_pii = st.text_area(
                        t("editable_output"),
                        value=st.session_state['resume_pii_result'],
                        height=400,
                        key="edit_resume_result_pii"
                    )
                    st.session_state['resume_pii_result'] = edited_result_pii

                # 精度検証の詳細パネル
                if st.session_state.get('resume_pii_iterations'):
                    render_verification_details(
                        st.session_state['resume_pii_iterations'],
                        key_suffix="pii",
                    )

                # ファーストネームをタイトル・ファイル名に使用
                _pii_first = extract_first_name(st.session_state['resume_pii_result'])
                _pii_label = f"Resume - {_pii_first}" if _pii_first else "Candidate Resume"
                _pii_fname = f"resume_{_pii_first}_{datetime.now().strftime('%Y%m%d_%H%M')}" if _pii_first else f"resume_pii_removed_{datetime.now().strftime('%Y%m%d_%H%M')}"

                # ダウンロードボタン
                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1:
                    st.download_button(
                        "📄 Markdown",
                        data=st.session_state['resume_pii_result'],
                        file_name=f"{_pii_fname}.md",
                        mime="text/markdown",
                        key="pii_md"
                    )
                with col_dl2:
                    st.download_button(
                        t("dl_text"),
                        data=st.session_state['resume_pii_result'],
                        file_name=f"{_pii_fname}.txt",
                        mime="text/plain",
                        key="pii_txt"
                    )
                with col_dl3:
                    html_content = generate_html(st.session_state['resume_pii_result'], _pii_label)
                    st.download_button(
                        "🌐 HTML",
                        data=html_content,
                        file_name=f"{_pii_fname}.html",
                        mime="text/html",
                        key="pii_html",
                        help=t("dl_html_help")
                    )

    elif feature == "jd_jp_en":
        st.subheader(t("jd_jp_en_title"))
        st.caption(t("jd_jp_en_desc"))

        col1, col2 = st.columns([1, 1])

        with col1:
            # サンプルデータボタン
            col_label, col_sample = st.columns([3, 1])
            with col_label:
                st.markdown("##### 入力：日本語求人票")
            with col_sample:
                if st.button(t("sample_btn"), key="sample_jd_btn", help=t("sample_jd_help"), type="tertiary"):
                    st.session_state['jd_text_input'] = SAMPLE_JD

            jd_input = st.text_area(
                t("jd_paste"),
                height=400,
                placeholder="求人票をここに貼り付けてください...\n\n例：\n【募集職種】バックエンドエンジニア\n【業務内容】自社サービスの開発...",
                label_visibility="collapsed",
                key="jd_text_input"
            )

            # 文字数カウンター
            char_count = len(jd_input) if jd_input else 0
            if char_count > MAX_INPUT_CHARS:
                st.error(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} 文字（超過）")
            elif char_count > 0:
                st.caption(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} 文字")

            st.info("💡 ビザサポート、リモート可否、給与レンジが記載されていると、より魅力的なJDが生成されます")

            _show_btn_hint(api_key, bool(jd_input))
            process_btn = st.button(
                "🔄 変換実行",
                type="primary",
                use_container_width=True,
                disabled=not api_key or not jd_input,
                key="jd_btn"
            )

        with col2:
            st.markdown(t("jd_jp_en_output"))

            if not process_btn and 'jd_result' not in st.session_state:
                st.info(t("output_placeholder"))

            if process_btn:
                if not api_key:
                    st.error("❌ APIキーを入力してください")
                else:
                    # 入力バリデーション
                    is_valid, error_msg = validate_input(jd_input, "jd")
                    if not is_valid:
                        st.warning(f"⚠️ {error_msg}")
                    else:
                        try:
                            start_time = time.time()
                            prompt = get_jd_transformation_prompt(jd_input)
                            st.caption(t("jd_jp_en_ai"))
                            stream_container = st.empty()
                            result = stream_to_container(api_key, prompt, stream_container)
                            elapsed_time = time.time() - start_time

                            st.session_state['jd_result'] = result
                            st.session_state['jd_time'] = elapsed_time
                            stream_container.empty()
                            st.success(f"✅ 変換完了！（{elapsed_time:.1f}秒）")

                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                                st.error(f"❌ エラー: {type(e).__name__}: {e}")

            # 結果表示
            if 'jd_result' in st.session_state:
                # 表示切替とコピーボタン
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted = st.checkbox(t("formatted_view"), value=False, key="jd_formatted",
                                                  help="Markdownをフォーマットして表示")
                with col_copy:
                    if st.button(t("copy_btn"), key="copy_jd", use_container_width=True):
                        st.toast(t("copied"))
                        _copy_to_clipboard(st.session_state['jd_result'])

                if show_formatted:
                    st.markdown(st.session_state['jd_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_jd_result = st.text_area(
                        t("editable_output"),
                        value=st.session_state['jd_result'],
                        height=400,
                        key="edit_jd_result"
                    )
                    st.session_state['jd_result'] = edited_jd_result

                # ダウンロードボタン
                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1:
                    st.download_button(
                        "📄 Markdown",
                        data=st.session_state['jd_result'],
                        file_name=f"job_description_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                        mime="text/markdown",
                        key="jd_md"
                    )
                with col_dl2:
                    st.download_button(
                        t("dl_text"),
                        data=st.session_state['jd_result'],
                        file_name=f"job_description_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                        mime="text/plain",
                        key="jd_txt"
                    )
                with col_dl3:
                    html_content = generate_html(st.session_state['jd_result'], "Job Description")
                    st.download_button(
                        "🌐 HTML",
                        data=html_content,
                        file_name=f"job_description_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                        mime="text/html",
                        key="jd_html",
                        help=t("dl_html_help")
                    )

                # 共有リンク作成ボタン
                if get_supabase_client():
                    st.divider()
                    if st.button("🔗 共有リンク作成", key="share_jd", help="1ヶ月有効の共有リンクを作成"):
                        with st.spinner("共有リンクを作成中..."):
                            share_id = create_share_link(
                                st.session_state['jd_result'],
                                "Job Description"
                            )
                        if share_id:
                            base_url = _get_app_base_url()
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                            st.code(share_url)
                            st.info("💡 上のURLをコピーしてクライアントに共有してください")
                        else:
                            st.error("❌ 共有リンクの作成に失敗しました")

    elif feature == "jd_en_jp":
        st.subheader(t("jd_en_jp_title"))
        st.caption(t("jd_en_jp_desc"))

        col1, col2 = st.columns([1, 1])

        with col1:
            # 入力方法タブ
            input_tab1, input_tab2 = st.tabs(["📝 テキスト入力", "📄 PDF読み込み"])

            jd_en_input = ""

            with input_tab1:
                # サンプルデータボタン
                col_label, col_sample = st.columns([3, 1])
                with col_label:
                    st.markdown("##### 入力：英語求人票")
                with col_sample:
                    if st.button("📝 サンプル", key="sample_jd_en_btn", help="サンプル英語求人票を挿入", type="tertiary"):
                        st.session_state['jd_en_text_input'] = SAMPLE_JD_EN

                jd_en_text = st.text_area(
                    "英語の求人票をペースト",
                    height=350,
                    placeholder="Paste the English job description here...\n\nExample:\nSenior Software Engineer\n\nAbout the role:\nWe are looking for...",
                    label_visibility="collapsed",
                    key="jd_en_text_input"
                )
                if jd_en_text:
                    jd_en_input = jd_en_text

            with input_tab2:
                st.markdown("##### 求人票PDFをアップロード")
                uploaded_jd_en_pdf = st.file_uploader(
                    "PDFファイルを選択",
                    type=["pdf"],
                    key="jd_en_pdf",
                    help=f"最大{MAX_PDF_SIZE_MB}MB、20ページまで"
                )

                if uploaded_jd_en_pdf:
                    with st.spinner("📄 PDFを読み込み中..."):
                        extracted_text, error = extract_text_from_pdf(uploaded_jd_en_pdf)
                        if error:
                            st.error(f"❌ {error}")
                        else:
                            st.success(f"✅ テキスト抽出完了（{len(extracted_text):,}文字）")
                            jd_en_input = extracted_text
                            with st.expander("抽出されたテキストを確認"):
                                st.text(extracted_text[:2000] + ("..." if len(extracted_text) > 2000 else ""))

            # 文字数カウンター
            char_count = len(jd_en_input) if jd_en_input else 0
            if char_count > MAX_INPUT_CHARS:
                st.error(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} 文字（超過）")
            elif char_count > 0:
                st.caption(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} 文字")

            st.info("💡 給与がUSD等の外貨の場合、自動で円換算目安も併記されます")

            _show_btn_hint(api_key, bool(jd_en_input))
            process_btn = st.button(
                "🔄 変換実行",
                type="primary",
                use_container_width=True,
                disabled=not api_key or not jd_en_input,
                key="jd_en_btn"
            )

        with col2:
            st.markdown(t("jd_en_jp_output"))

            if not process_btn and 'jd_en_result' not in st.session_state:
                st.info(t("output_placeholder"))

            if process_btn:
                if not api_key:
                    st.error("❌ APIキーを入力してください")
                else:
                    # 入力バリデーション
                    is_valid, error_msg = validate_input(jd_en_input, "jd_en")
                    if not is_valid:
                        st.warning(f"⚠️ {error_msg}")
                    else:
                        try:
                            start_time = time.time()
                            prompt = get_jd_en_to_jp_prompt(jd_en_input)
                            st.caption("🤖 AIが求人票を解析・翻訳しています...")
                            stream_container = st.empty()
                            result = stream_to_container(api_key, prompt, stream_container)
                            elapsed_time = time.time() - start_time

                            st.session_state['jd_en_result'] = result
                            st.session_state['jd_en_time'] = elapsed_time
                            stream_container.empty()
                            st.success(f"✅ 変換完了！（{elapsed_time:.1f}秒）")

                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"❌ エラー: {type(e).__name__}: {e}")

            # 結果表示
            if 'jd_en_result' in st.session_state:
                # 表示切替とコピーボタン
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted = st.checkbox(t("formatted_view"), value=False, key="jd_en_formatted",
                                                  help="Markdownをフォーマットして表示")
                with col_copy:
                    if st.button(t("copy_btn"), key="copy_jd_en", use_container_width=True):
                        st.toast(t("copied"))
                        _copy_to_clipboard(st.session_state['jd_en_result'])

                if show_formatted:
                    st.markdown(st.session_state['jd_en_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_jd_en_result = st.text_area(
                        t("editable_output"),
                        value=st.session_state['jd_en_result'],
                        height=400,
                        key="edit_jd_en_result"
                    )
                    st.session_state['jd_en_result'] = edited_jd_en_result

                # ダウンロードボタン
                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1:
                    st.download_button(
                        "📄 Markdown",
                        data=st.session_state['jd_en_result'],
                        file_name=f"job_description_jp_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                        mime="text/markdown",
                        key="jd_en_md"
                    )
                with col_dl2:
                    st.download_button(
                        t("dl_text"),
                        data=st.session_state['jd_en_result'],
                        file_name=f"job_description_jp_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                        mime="text/plain",
                        key="jd_en_txt"
                    )
                with col_dl3:
                    html_content = generate_html(st.session_state['jd_en_result'], "求人票")
                    st.download_button(
                        "🌐 HTML",
                        data=html_content,
                        file_name=f"job_description_jp_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                        mime="text/html",
                        key="jd_en_html",
                        help=t("dl_html_help")
                    )

                # 共有リンク作成ボタン
                if get_supabase_client():
                    st.divider()
                    if st.button("🔗 共有リンク作成", key="share_jd_en", help="1ヶ月有効の共有リンクを作成"):
                        with st.spinner("共有リンクを作成中..."):
                            share_id = create_share_link(
                                st.session_state['jd_en_result'],
                                "求人票"
                            )
                        if share_id:
                            base_url = _get_app_base_url()
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                            st.code(share_url)
                            st.info("💡 上のURLをコピーしてクライアントに共有してください")
                        else:
                            st.error("❌ 共有リンクの作成に失敗しました")

    elif feature == "jd_jp_jp":
        st.subheader(t("jd_jp_jp_title"))
        st.caption(t("jd_jp_jp_desc"))

        col1, col2 = st.columns([1, 1])

        with col1:
            # 入力方法タブ
            input_tab1, input_tab2 = st.tabs(["📝 テキスト入力", "📄 PDF読み込み"])

            jd_jp_jp_input = ""

            with input_tab1:
                # サンプルデータボタン
                col_label, col_sample = st.columns([3, 1])
                with col_label:
                    st.markdown("##### 入力：日本語求人票")
                with col_sample:
                    if st.button("📝 サンプル", key="sample_jd_jp_jp_btn", help="サンプル求人票を挿入", type="tertiary"):
                        st.session_state['jd_jp_jp_text_input'] = SAMPLE_JD

                jd_jp_jp_text = st.text_area(
                    "日本語の求人票をペースト",
                    height=350,
                    placeholder="求人票をここに貼り付けてください...\n\n例：\n【募集職種】バックエンドエンジニア\n【業務内容】自社サービスの開発...",
                    label_visibility="collapsed",
                    key="jd_jp_jp_text_input"
                )
                if jd_jp_jp_text:
                    jd_jp_jp_input = jd_jp_jp_text

            with input_tab2:
                st.markdown("##### 求人票PDFをアップロード")
                uploaded_jd_jp_jp_pdf = st.file_uploader(
                    "PDFファイルを選択",
                    type=["pdf"],
                    key="jd_jp_jp_pdf",
                    help=f"最大{MAX_PDF_SIZE_MB}MB、20ページまで"
                )

                if uploaded_jd_jp_jp_pdf:
                    with st.spinner("📄 PDFを読み込み中..."):
                        extracted_text, error = extract_text_from_pdf(uploaded_jd_jp_jp_pdf)
                        if error:
                            st.error(f"❌ {error}")
                        else:
                            st.success(f"✅ テキスト抽出完了（{len(extracted_text):,}文字）")
                            jd_jp_jp_input = extracted_text
                            with st.expander("抽出されたテキストを確認"):
                                st.text(extracted_text[:2000] + ("..." if len(extracted_text) > 2000 else ""))

            # 文字数カウンター
            char_count = len(jd_jp_jp_input) if jd_jp_jp_input else 0
            if char_count > MAX_INPUT_CHARS:
                st.error(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} 文字（超過）")
            elif char_count > 0:
                st.caption(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} 文字")

            st.info("💡 統一フォーマットに整理され、見やすく魅力的な求人票が生成されます")

            _show_btn_hint(api_key, bool(jd_jp_jp_input))
            process_btn = st.button(
                "🔄 変換実行",
                type="primary",
                use_container_width=True,
                disabled=not api_key or not jd_jp_jp_input,
                key="jd_jp_jp_btn"
            )

        with col2:
            st.markdown(t("jd_jp_jp_output"))

            if not process_btn and 'jd_jp_jp_result' not in st.session_state:
                st.info(t("output_placeholder"))

            if process_btn:
                if not api_key:
                    st.error("❌ APIキーを入力してください")
                else:
                    # 入力バリデーション
                    is_valid, error_msg = validate_input(jd_jp_jp_input, "jd")
                    if not is_valid:
                        st.warning(f"⚠️ {error_msg}")
                    else:
                        try:
                            start_time = time.time()
                            prompt = get_jd_jp_to_jp_prompt(jd_jp_jp_input)
                            st.caption(t("jd_jp_jp_ai"))
                            stream_container = st.empty()
                            result = stream_to_container(api_key, prompt, stream_container)
                            elapsed_time = time.time() - start_time

                            st.session_state['jd_jp_jp_result'] = result
                            st.session_state['jd_jp_jp_time'] = elapsed_time
                            stream_container.empty()
                            st.success(f"✅ 変換完了！（{elapsed_time:.1f}秒）")

                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"❌ エラー: {type(e).__name__}: {e}")

            # 結果表示
            if 'jd_jp_jp_result' in st.session_state:
                # 表示切替とコピーボタン
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted = st.checkbox(t("formatted_view"), value=False, key="jd_jp_jp_formatted",
                                                  help="Markdownをフォーマットして表示")
                with col_copy:
                    if st.button(t("copy_btn"), key="copy_jd_jp_jp", use_container_width=True):
                        st.toast(t("copied"))
                        _copy_to_clipboard(st.session_state['jd_jp_jp_result'])

                if show_formatted:
                    st.markdown(st.session_state['jd_jp_jp_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_jd_jp_jp_result = st.text_area(
                        t("editable_output"),
                        value=st.session_state['jd_jp_jp_result'],
                        height=400,
                        key="edit_jd_jp_jp_result"
                    )
                    st.session_state['jd_jp_jp_result'] = edited_jd_jp_jp_result

                # ダウンロードボタン
                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1:
                    st.download_button(
                        "📄 Markdown",
                        data=st.session_state['jd_jp_jp_result'],
                        file_name=f"job_description_jp_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                        mime="text/markdown",
                        key="jd_jp_jp_md"
                    )
                with col_dl2:
                    st.download_button(
                        t("dl_text"),
                        data=st.session_state['jd_jp_jp_result'],
                        file_name=f"job_description_jp_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                        mime="text/plain",
                        key="jd_jp_jp_txt"
                    )
                with col_dl3:
                    html_content = generate_html(st.session_state['jd_jp_jp_result'], "求人票")
                    st.download_button(
                        "🌐 HTML",
                        data=html_content,
                        file_name=f"job_description_jp_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                        mime="text/html",
                        key="jd_jp_jp_html",
                        help=t("dl_html_help")
                    )

                # 共有リンク作成ボタン
                if get_supabase_client():
                    st.divider()
                    if st.button("🔗 共有リンク作成", key="share_jd_jp_jp", help="1ヶ月有効の共有リンクを作成"):
                        with st.spinner("共有リンクを作成中..."):
                            share_id = create_share_link(
                                st.session_state['jd_jp_jp_result'],
                                "求人票"
                            )
                        if share_id:
                            base_url = _get_app_base_url()
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                            st.code(share_url)
                            st.info("💡 上のURLをコピーしてクライアントに共有してください")
                        else:
                            st.error("❌ 共有リンクの作成に失敗しました")

    elif feature == "jd_en_en":
        st.subheader(t("jd_en_en_title"))
        st.caption(t("jd_en_en_desc"))

        col1, col2 = st.columns([1, 1])

        with col1:
            # 入力方法タブ
            input_tab1, input_tab2 = st.tabs(["📝 Text Input", "📄 PDF Upload"])

            jd_en_en_input = ""

            with input_tab1:
                # サンプルデータボタン
                col_label, col_sample = st.columns([3, 1])
                with col_label:
                    st.markdown("##### Input: English Job Description")
                with col_sample:
                    if st.button("📝 Sample", key="sample_jd_en_en_btn", help="Insert sample English JD"):
                        st.session_state['jd_en_en_text_input'] = SAMPLE_JD_EN

                jd_en_en_text = st.text_area(
                    "Paste English job description",
                    height=350,
                    placeholder="Paste the English job description here...\n\nExample:\nSenior Software Engineer\n\nAbout the role:\nWe are looking for...",
                    label_visibility="collapsed",
                    key="jd_en_en_text_input"
                )
                if jd_en_en_text:
                    jd_en_en_input = jd_en_en_text

            with input_tab2:
                st.markdown("##### Upload Job Description PDF")
                uploaded_jd_en_en_pdf = st.file_uploader(
                    "Select PDF file",
                    type=["pdf"],
                    key="jd_en_en_pdf",
                    help=f"Maximum {MAX_PDF_SIZE_MB}MB, up to 20 pages"
                )

                if uploaded_jd_en_en_pdf:
                    with st.spinner("📄 Reading PDF..."):
                        extracted_text, error = extract_text_from_pdf(uploaded_jd_en_en_pdf)
                        if error:
                            st.error(f"❌ {error}")
                        else:
                            st.success(f"✅ Text extracted ({len(extracted_text):,} characters)")
                            jd_en_en_input = extracted_text
                            with st.expander("View extracted text"):
                                st.text(extracted_text[:2000] + ("..." if len(extracted_text) > 2000 else ""))

            # 文字数カウンター
            char_count = len(jd_en_en_input) if jd_en_en_input else 0
            if char_count > MAX_INPUT_CHARS:
                st.error(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} characters (exceeded)")
            elif char_count > 0:
                st.caption(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} characters")

            st.info("💡 The output will follow a standardized format optimized for international recruitment")

            _show_btn_hint(api_key, bool(jd_en_en_input))
            process_btn = st.button(
                "🔄 Transform",
                type="primary",
                use_container_width=True,
                disabled=not api_key or not jd_en_en_input,
                key="jd_en_en_btn"
            )

        with col2:
            st.markdown("##### Output: Formatted English JD")

            if not process_btn and 'jd_en_en_result' not in st.session_state:
                st.info(t("output_placeholder"))

            if process_btn:
                if not api_key:
                    st.error("❌ Please enter API key")
                else:
                    # 入力バリデーション
                    is_valid, error_msg = validate_input(jd_en_en_input, "jd")
                    if not is_valid:
                        st.warning(f"⚠️ {error_msg}")
                    else:
                        try:
                            start_time = time.time()
                            prompt = get_jd_en_to_en_prompt(jd_en_en_input)
                            st.caption("🤖 AI is analyzing and transforming the job description...")
                            stream_container = st.empty()
                            result = stream_to_container(api_key, prompt, stream_container)
                            elapsed_time = time.time() - start_time

                            st.session_state['jd_en_en_result'] = result
                            st.session_state['jd_en_en_time'] = elapsed_time
                            stream_container.empty()
                            st.success(f"✅ Transformation complete! ({elapsed_time:.1f}s)")

                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error("❌ Unexpected error. Please try again later")

            # 結果表示
            if 'jd_en_en_result' in st.session_state:
                # 表示切替とコピーボタン
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted = st.checkbox("📖 Formatted View", value=False, key="jd_en_en_formatted",
                                                  help="Display with Markdown formatting")
                with col_copy:
                    if st.button("📋 Copy", key="copy_jd_en_en", use_container_width=True):
                        st.toast("✅ Copied to clipboard")
                        _copy_to_clipboard(st.session_state['jd_en_en_result'])

                if show_formatted:
                    st.markdown(st.session_state['jd_en_en_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_jd_en_en_result = st.text_area(
                        "Output (Editable)",
                        value=st.session_state['jd_en_en_result'],
                        height=400,
                        key="edit_jd_en_en_result"
                    )
                    st.session_state['jd_en_en_result'] = edited_jd_en_en_result

                # ダウンロードボタン
                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1:
                    st.download_button(
                        "📄 Markdown",
                        data=st.session_state['jd_en_en_result'],
                        file_name=f"job_description_en_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                        mime="text/markdown",
                        key="jd_en_en_md"
                    )
                with col_dl2:
                    st.download_button(
                        "📝 Text",
                        data=st.session_state['jd_en_en_result'],
                        file_name=f"job_description_en_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                        mime="text/plain",
                        key="jd_en_en_txt"
                    )
                with col_dl3:
                    html_content = generate_html(st.session_state['jd_en_en_result'], "Job Description")
                    st.download_button(
                        "🌐 HTML",
                        data=html_content,
                        file_name=f"job_description_en_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                        mime="text/html",
                        key="jd_en_en_html",
                        help="Open in browser and save as PDF via print"
                    )

                # 共有リンク作成ボタン
                if get_supabase_client():
                    st.divider()
                    if st.button("🔗 Create Share Link", key="share_jd_en_en", help="Create a shareable link (valid for 1 month)"):
                        with st.spinner("Creating share link..."):
                            share_id = create_share_link(
                                st.session_state['jd_en_en_result'],
                                "Job Description"
                            )
                        if share_id:
                            base_url = _get_app_base_url()
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ Share link created (valid for 1 month)")
                            st.code(share_url)
                            st.info("💡 Copy the URL above to share with clients")
                        else:
                            st.error("❌ Failed to create share link")

    # ===== JD Anonymization =====
    elif feature == "jd_anonymize":
        st.subheader(t("jd_anon_title"))
        st.caption(t("jd_anon_desc"))

        col1, col2 = st.columns([1, 1])

        with col1:
            # 入力方法タブ
            input_tab1, input_tab2 = st.tabs(["📝 テキスト入力", "📄 PDF読み込み"])

            jd_anon_input = ""

            with input_tab1:
                # サンプルデータボタン
                col_label, col_sample_jp, col_sample_en = st.columns([2, 1, 1])
                with col_label:
                    st.markdown(t("jd_anon_input"))
                with col_sample_jp:
                    if st.button("📝 JP Sample", key="sample_jd_anon_jp_btn", help="日本語サンプル求人票を挿入", type="tertiary"):
                        st.session_state['jd_anon_text_input'] = SAMPLE_JD
                with col_sample_en:
                    if st.button("📝 EN Sample", key="sample_jd_anon_en_btn", help="Insert English sample JD", type="tertiary"):
                        st.session_state['jd_anon_text_input'] = SAMPLE_JD_EN

                jd_anon_text = st.text_area(
                    "求人票をペースト / Paste job description",
                    height=300,
                    placeholder="求人票をここに貼り付けてください（日本語・英語どちらでもOK）...\nPaste a job description here (Japanese or English)...",
                    label_visibility="collapsed",
                    key="jd_anon_text_input"
                )
                if jd_anon_text:
                    jd_anon_input = jd_anon_text

            with input_tab2:
                st.markdown("##### 求人票PDFをアップロード / Upload JD PDF")
                uploaded_jd_anon_pdf = st.file_uploader(
                    "PDFファイルを選択",
                    type=["pdf"],
                    key="jd_anon_pdf",
                    help=f"最大{MAX_PDF_SIZE_MB}MB、20ページまで"
                )

                if uploaded_jd_anon_pdf:
                    with st.spinner("📄 PDFを読み込み中..."):
                        extracted_text, error = extract_text_from_pdf(uploaded_jd_anon_pdf)
                        if error:
                            st.error(f"❌ {error}")
                        else:
                            st.success(f"✅ テキスト抽出完了（{len(extracted_text):,}文字）")
                            jd_anon_input = extracted_text
                            with st.expander("抽出されたテキストを確認"):
                                st.text(extracted_text[:2000] + ("..." if len(extracted_text) > 2000 else ""))

            # 文字数カウンター
            char_count = len(jd_anon_input) if jd_anon_input else 0
            if char_count > MAX_INPUT_CHARS:
                st.error(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} 文字（超過）")
            elif char_count > 0:
                st.caption(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} 文字")

            # 出力言語選択
            st.markdown("---")
            jd_anon_output_lang = st.radio(
                t("jd_anon_output_lang_label"),
                options=["ja", "en"],
                format_func=lambda x: t(f"jd_anon_output_lang_{x}"),
                index=0,
                key="jd_anon_output_lang",
                horizontal=True,
            )

            # 匿名化レベル選択
            anonymize_jd_level = st.radio(
                t("jd_anon_level_label"),
                options=["full", "light", "none"],
                format_func=lambda x: t(f"jd_anon_level_{x}"),
                index=0,
                key="anonymize_jd_level",
            )

            st.info(t("jd_anon_info"))

            _show_btn_hint(api_key, bool(jd_anon_input))
            process_btn = st.button(
                t("jd_anon_btn"),
                type="primary",
                use_container_width=True,
                disabled=not api_key or not jd_anon_input,
                key="jd_anon_btn"
            )

        with col2:
            st.markdown(t("jd_anon_output"))

            if not process_btn and 'jd_anon_result' not in st.session_state:
                st.info(t("output_placeholder"))

            if process_btn:
                if not api_key:
                    st.error("❌ APIキーを入力してください")
                else:
                    # 入力バリデーション
                    is_valid, error_msg = validate_input(jd_anon_input, "jd_any")
                    if not is_valid:
                        st.warning(f"⚠️ {error_msg}")
                    else:
                        try:
                            start_time = time.time()
                            prompt = get_jd_anonymize_prompt(jd_anon_input, anonymize_jd_level, jd_anon_output_lang)
                            st.caption(t("jd_anon_ai"))
                            stream_container = st.empty()
                            result = stream_to_container(api_key, prompt, stream_container)
                            elapsed_time = time.time() - start_time

                            st.session_state['jd_anon_result'] = result
                            st.session_state['jd_anon_time'] = elapsed_time
                            stream_container.empty()
                            st.success(f"✅ 完了！（{elapsed_time:.1f}秒）")

                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"❌ エラー: {type(e).__name__}: {e}")

            # 結果表示
            if 'jd_anon_result' in st.session_state:
                # 表示切替とコピーボタン
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted = st.checkbox(t("formatted_view"), value=False, key="jd_anon_formatted",
                                                  help="Markdownをフォーマットして表示")
                with col_copy:
                    if st.button(t("copy_btn"), key="copy_jd_anon", use_container_width=True):
                        st.toast(t("copied"))
                        _copy_to_clipboard(st.session_state['jd_anon_result'])

                if show_formatted:
                    st.markdown(st.session_state['jd_anon_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_jd_anon_result = st.text_area(
                        t("editable_output"),
                        value=st.session_state['jd_anon_result'],
                        height=400,
                        key="edit_jd_anon_result"
                    )
                    st.session_state['jd_anon_result'] = edited_jd_anon_result

                # ダウンロードボタン
                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1:
                    st.download_button(
                        "📄 Markdown",
                        data=st.session_state['jd_anon_result'],
                        file_name=f"jd_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                        mime="text/markdown",
                        key="jd_anon_md"
                    )
                with col_dl2:
                    st.download_button(
                        t("dl_text"),
                        data=st.session_state['jd_anon_result'],
                        file_name=f"jd_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                        mime="text/plain",
                        key="jd_anon_txt"
                    )
                with col_dl3:
                    html_title = "Job Description" if jd_anon_output_lang == "en" else "求人票"
                    html_content = generate_html(st.session_state['jd_anon_result'], html_title)
                    st.download_button(
                        "🌐 HTML",
                        data=html_content,
                        file_name=f"jd_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                        mime="text/html",
                        key="jd_anon_html",
                        help=t("dl_html_help")
                    )

                # 共有リンク作成ボタン
                if get_supabase_client():
                    st.divider()
                    if st.button("🔗 共有リンク作成", key="share_jd_anon", help="1ヶ月有効の共有リンクを作成"):
                        with st.spinner("共有リンクを作成中..."):
                            share_id = create_share_link(
                                st.session_state['jd_anon_result'],
                                "求人票（匿名化）"
                            )
                        if share_id:
                            base_url = _get_app_base_url()
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                            st.code(share_url)
                            st.info("💡 上のURLをコピーしてクライアントに共有してください")

    elif feature == "company_intro":
        st.subheader(t("company_title"))
        st.caption(t("company_desc"))

        col1, col2 = st.columns([1, 1])

        with col1:
            # 入力方法タブ
            input_tab1, input_tab2 = st.tabs(["📄 PDF読み込み", "📝 テキスト入力"])

            company_input = ""

            with input_tab1:
                st.markdown(t("company_pdf_header"))
                uploaded_company_pdf = st.file_uploader(
                    "PDFファイルを選択",
                    type=["pdf"],
                    key="company_pdf",
                    help=f"最大{MAX_PDF_SIZE_MB}MB、20ページまで"
                )

                if uploaded_company_pdf:
                    with st.spinner("📄 PDFを読み込み中..."):
                        extracted_text, error = extract_text_from_pdf(uploaded_company_pdf)
                        if error:
                            st.error(f"❌ {error}")
                        else:
                            st.success(f"✅ テキスト抽出完了（{len(extracted_text):,}文字）")
                            company_input = extracted_text
                            with st.expander("抽出されたテキストを確認"):
                                st.text(extracted_text[:3000] + ("..." if len(extracted_text) > 3000 else ""))

            with input_tab2:
                st.markdown(t("company_text_header"))
                company_text_input = st.text_area(
                    t("company_paste"),
                    height=350,
                    placeholder="会社紹介資料のテキストを貼り付けてください...\n\n例：\n会社名：株式会社〇〇\n設立：2015年\n事業内容：...",
                    label_visibility="collapsed",
                    key="company_text_input"
                )
                if company_text_input:
                    company_input = company_text_input

            # 文字数カウンター
            char_count = len(company_input) if company_input else 0
            if char_count > MAX_INPUT_CHARS:
                st.error(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} 文字（超過）")
            elif char_count > 0:
                st.caption(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} 文字")

            st.info(t("company_hint"))

            _show_btn_hint(api_key, bool(company_input))
            process_btn = st.button(
                t("company_btn"),
                type="primary",
                use_container_width=True,
                disabled=not api_key or not company_input,
                key="company_btn"
            )

        with col2:
            st.markdown(t("company_output"))

            if not process_btn and 'company_result' not in st.session_state:
                st.info(t("output_placeholder"))

            if process_btn:
                if not api_key:
                    st.error("❌ APIキーを入力してください")
                else:
                    # 入力バリデーション
                    is_valid, error_msg = validate_input(company_input, "company")
                    if not is_valid:
                        st.warning(f"⚠️ {error_msg}")
                    else:
                        try:
                            start_time = time.time()
                            prompt = get_company_intro_prompt(company_input)
                            st.caption(t("company_ai"))
                            stream_container = st.empty()
                            result = stream_to_container(api_key, prompt, stream_container)
                            elapsed_time = time.time() - start_time

                            st.session_state['company_result'] = result
                            st.session_state['company_time'] = elapsed_time
                            stream_container.empty()
                            st.success(f"✅ 作成完了！（{elapsed_time:.1f}秒）")

                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"❌ エラー: {type(e).__name__}: {e}")

            # 結果表示
            if 'company_result' in st.session_state:
                # 表示切替とコピーボタン
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted = st.checkbox("📖 整形表示", value=False, key="company_formatted",
                                                  help="Markdownをフォーマットして表示")
                with col_copy:
                    if st.button("📋 コピー", key="copy_company", use_container_width=True):
                        st.toast("✅ クリップボードにコピーしました")
                        _copy_to_clipboard(st.session_state['company_result'])

                if show_formatted:
                    st.markdown(st.session_state['company_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_company_result = st.text_area(
                        "出力結果（編集可能）",
                        value=st.session_state['company_result'],
                        height=400,
                        key="edit_company_result"
                    )
                    st.session_state['company_result'] = edited_company_result

                # ダウンロードボタン
                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1:
                    st.download_button(
                        "📄 Markdown",
                        data=st.session_state['company_result'],
                        file_name=f"company_intro_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                        mime="text/markdown",
                        key="company_md"
                    )
                with col_dl2:
                    st.download_button(
                        "📝 テキスト",
                        data=st.session_state['company_result'],
                        file_name=f"company_intro_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                        mime="text/plain",
                        key="company_txt"
                    )
                with col_dl3:
                    html_content = generate_html(st.session_state['company_result'], "企業紹介")
                    st.download_button(
                        "🌐 HTML",
                        data=html_content,
                        file_name=f"company_intro_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                        mime="text/html",
                        key="company_html",
                        help="ブラウザで開いて印刷→PDF保存"
                    )

    elif feature == "matching":
        st.subheader(t("matching_title"))
        st.caption(t("matching_desc"))

        # 2カラムレイアウト（入力エリア）
        col_input1, col_input2 = st.columns([1, 1])

        # 入力エリア1: レジュメ
        with col_input1:
            st.markdown(t("matching_resume_header"))

            # 入力方法選択
            resume_source = st.radio(
                t("matching_resume_method"),
                options=[t("input_text_pdf"), t("input_from_results"), t("input_from_history")],
                key="matching_resume_source",
                horizontal=True
            )

            matching_resume_input = ""

            if resume_source == t("input_text_pdf"):
                # タブで切り替え
                input_tab1, input_tab2 = st.tabs(["📝 テキスト入力", "📄 PDF読み込み"])

                with input_tab1:
                    # サンプルボタン
                    col_label, col_sample = st.columns([3, 1])
                    with col_label:
                        st.markdown("レジュメをペースト")
                    with col_sample:
                        if st.button("📝 サンプル", key="sample_matching_resume_btn", help="サンプルレジュメを挿入", type="tertiary"):
                            st.session_state['matching_resume_text'] = SAMPLE_MATCHING_RESUME
                            st.rerun()

                    matching_resume_input = st.text_area(
                        "レジュメをペースト",
                        height=400,
                        placeholder="最適化済みレジュメを貼り付けてください...",
                        key="matching_resume_text",
                        label_visibility="collapsed"
                    )

                with input_tab2:
                    st.markdown("##### レジュメPDFをアップロード")
                    uploaded_resume_pdf = st.file_uploader(
                        "PDFファイルを選択",
                        type=["pdf"],
                        key="matching_resume_pdf",
                        help=f"最大{MAX_PDF_SIZE_MB}MB、20ページまで"
                    )

                    if uploaded_resume_pdf:
                        with st.spinner("📄 PDFを読み込み中..."):
                            extracted_text, error = extract_text_from_pdf(uploaded_resume_pdf)
                            if error:
                                st.error(f"❌ {error}")
                            else:
                                st.success(f"✅ テキスト抽出完了（{len(extracted_text):,}文字）")
                                matching_resume_input = extracted_text
                                with st.expander("抽出されたテキストを確認"):
                                    st.text(extracted_text[:3000] + ("..." if len(extracted_text) > 3000 else ""))
            elif resume_source == t("input_from_results"):
                # 過去の結果から選択
                if 'resume_result' in st.session_state:
                    if st.checkbox("直前のレジュメ最適化結果を使用", key="use_last_resume"):
                        matching_resume_input = st.session_state['resume_result']
                        with st.expander("選択されたレジュメを確認"):
                            st.text(matching_resume_input[:500] + ("..." if len(matching_resume_input) > 500 else ""))
                    else:
                        matching_resume_input = st.text_area(
                            "または手動入力",
                            height=300,
                            key="matching_resume_manual"
                        )
                else:
                    st.info("💡 先に「レジュメ最適化」機能を使用してレジュメを最適化してください")
                    matching_resume_input = st.text_area(
                        "または手動入力",
                        height=300,
                        key="matching_resume_manual2"
                    )
            else:  # 履歴から選択
                history = get_history("resume")
                if history:
                    st.markdown("##### 📂 保存された履歴")
                    selected_resume_id = st.radio(
                        "履歴を選択",
                        options=[item['id'] for item in history],
                        format_func=lambda x: next(item['title'] for item in history if item['id'] == x),
                        key="select_resume_history",
                        label_visibility="collapsed"
                    )

                    if selected_resume_id:
                        selected_item = next(item for item in history if item['id'] == selected_resume_id)
                        matching_resume_input = selected_item['content']

                        # プレビューと削除ボタン
                        with st.expander("📄 選択されたレジュメを確認"):
                            st.text(matching_resume_input[:500] + ("..." if len(matching_resume_input) > 500 else ""))

                        col_del1, col_del2 = st.columns([1, 1])
                        with col_del1:
                            if st.button("🗑️ この項目を削除", key="del_resume_history_item"):
                                delete_history_item("resume", selected_resume_id)
                                st.rerun()
                        with col_del2:
                            if st.button("🗑️ 全履歴を削除", key="clear_resume_history"):
                                clear_history("resume")
                                st.rerun()
                else:
                    st.info("💡 履歴がありません。マッチング分析を実行すると自動で保存されます。")
                    matching_resume_input = ""

            # 文字数カウンター
            resume_char_count = len(matching_resume_input) if matching_resume_input else 0
            if resume_char_count > 0:
                st.caption(f"📊 {resume_char_count:,} 文字")

        # 入力エリア2: 求人票
        with col_input2:
            st.markdown(t("matching_jd_header"))

            # 入力方法選択
            jd_source = st.radio(
                t("matching_jd_method"),
                options=[t("input_text_pdf"), t("input_from_results"), t("input_from_history")],
                key="matching_jd_source",
                horizontal=True
            )

            matching_jd_input = ""

            if jd_source == t("input_text_pdf"):
                # タブで切り替え
                input_tab1, input_tab2 = st.tabs(["📝 テキスト入力", "📄 PDF読み込み"])

                with input_tab1:
                    # サンプルボタン
                    col_label, col_sample = st.columns([3, 1])
                    with col_label:
                        st.markdown("求人票をペースト")
                    with col_sample:
                        if st.button("📝 サンプル", key="sample_matching_jd_btn", help="サンプル求人票を挿入", type="tertiary"):
                            st.session_state['matching_jd_text'] = SAMPLE_MATCHING_JD
                            st.rerun()

                    matching_jd_input = st.text_area(
                        "求人票をペースト",
                        height=400,
                        placeholder="求人票を貼り付けてください...",
                        key="matching_jd_text",
                        label_visibility="collapsed"
                    )

                with input_tab2:
                    st.markdown("##### 求人票PDFをアップロード")
                    uploaded_jd_pdf = st.file_uploader(
                        "PDFファイルを選択",
                        type=["pdf"],
                        key="matching_jd_pdf",
                        help=f"最大{MAX_PDF_SIZE_MB}MB、20ページまで"
                    )

                    if uploaded_jd_pdf:
                        with st.spinner("📄 PDFを読み込み中..."):
                            extracted_text, error = extract_text_from_pdf(uploaded_jd_pdf)
                            if error:
                                st.error(f"❌ {error}")
                            else:
                                st.success(f"✅ テキスト抽出完了（{len(extracted_text):,}文字）")
                                matching_jd_input = extracted_text
                                with st.expander("抽出されたテキストを確認"):
                                    st.text(extracted_text[:3000] + ("..." if len(extracted_text) > 3000 else ""))
            elif jd_source == t("input_from_results"):
                # 過去の結果から選択（複数の可能性）
                available_jds = []
                if 'jd_result' in st.session_state:
                    available_jds.append(("求人票魅力化（日→英）の結果", st.session_state['jd_result']))
                if 'jd_en_result' in st.session_state:
                    available_jds.append(("求人票翻訳（英→日）の結果", st.session_state['jd_en_result']))
                if 'jd_jp_jp_result' in st.session_state:
                    available_jds.append(("求人票フォーマット化（日→日）の結果", st.session_state['jd_jp_jp_result']))
                if 'jd_en_en_result' in st.session_state:
                    available_jds.append(("求人票フォーマット化（英→英）の結果", st.session_state['jd_en_en_result']))

                if available_jds:
                    selected_jd = st.radio(
                        "使用する求人票を選択",
                        options=[name for name, _ in available_jds],
                        key="select_jd"
                    )
                    matching_jd_input = next(content for name, content in available_jds if name == selected_jd)
                    with st.expander("選択された求人票を確認"):
                        st.text(matching_jd_input[:500] + ("..." if len(matching_jd_input) > 500 else ""))
                else:
                    st.info("💡 先に「求人票魅力化」または「求人票翻訳」機能を使用してください")
                    matching_jd_input = st.text_area(
                        "または手動入力",
                        height=300,
                        key="matching_jd_manual"
                    )
            else:  # 履歴から選択
                history = get_history("jd")
                if history:
                    st.markdown("##### 📂 保存された履歴")
                    selected_jd_id = st.radio(
                        "履歴を選択",
                        options=[item['id'] for item in history],
                        format_func=lambda x: next(item['title'] for item in history if item['id'] == x),
                        key="select_jd_history",
                        label_visibility="collapsed"
                    )

                    if selected_jd_id:
                        selected_item = next(item for item in history if item['id'] == selected_jd_id)
                        matching_jd_input = selected_item['content']

                        # プレビューと削除ボタン
                        with st.expander("📄 選択された求人票を確認"):
                            st.text(matching_jd_input[:500] + ("..." if len(matching_jd_input) > 500 else ""))

                        col_del1, col_del2 = st.columns([1, 1])
                        with col_del1:
                            if st.button("🗑️ この項目を削除", key="del_jd_history_item"):
                                delete_history_item("jd", selected_jd_id)
                                st.rerun()
                        with col_del2:
                            if st.button("🗑️ 全履歴を削除", key="clear_jd_history"):
                                clear_history("jd")
                                st.rerun()
                else:
                    st.info("💡 履歴がありません。マッチング分析を実行すると自動で保存されます。")
                    matching_jd_input = ""

            # 文字数カウンター
            jd_char_count = len(matching_jd_input) if matching_jd_input else 0
            if jd_char_count > 0:
                st.caption(f"📊 {jd_char_count:,} 文字")

        # 分析実行ボタン（中央配置）
        st.divider()
        col_center = st.columns([1, 2, 1])
        with col_center[1]:
            st.info("💡 両方の入力が完了したら、下のボタンで分析を開始します")
            _show_btn_hint(api_key, bool(matching_resume_input), bool(matching_jd_input))
            process_btn = st.button(
                t("matching_btn"),
                type="primary",
                use_container_width=True,
                disabled=not api_key or not matching_resume_input or not matching_jd_input,
                key="matching_btn"
            )

        # データ管理セクション（エクスポート/インポート）
        st.divider()
        with st.expander("💾 履歴データの管理（エクスポート/インポート）", expanded=False):
            st.markdown("""
            **履歴データのバックアップと復元**
            - **エクスポート**: すべての履歴をJSONファイルとしてダウンロード
            - **インポート**: 過去にエクスポートしたJSONファイルから履歴を復元
            - **自動保存**: 履歴はブラウザのlocalStorageに自動保存されます
            """)

            col_export, col_import = st.columns(2)

            with col_export:
                st.markdown("##### 📤 エクスポート")
                resume_count = len(st.session_state.get('resume_history', []))
                jd_count = len(st.session_state.get('jd_history', []))
                total_count = resume_count + jd_count

                if total_count > 0:
                    st.caption(f"レジュメ: {resume_count}件、求人票: {jd_count}件")
                    json_data = export_history_to_json("all")
                    st.download_button(
                        "📥 すべての履歴をダウンロード",
                        data=json_data,
                        file_name=f"globalmatch_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json",
                        use_container_width=True,
                        key="export_history_btn"
                    )
                else:
                    st.info("💡 履歴がありません")

            with col_import:
                st.markdown("##### 📥 インポート")
                uploaded_json = st.file_uploader(
                    "JSONファイルをアップロード",
                    type=["json"],
                    key="import_history_uploader",
                    help="過去にエクスポートした履歴ファイルを選択"
                )

                if uploaded_json:
                    try:
                        json_string = uploaded_json.read().decode('utf-8')
                        if st.button("📂 履歴をインポート", key="import_history_btn", use_container_width=True):
                            success, message = import_history_from_json(json_string)
                            if success:
                                st.success(message)
                                st.rerun()
                            else:
                                st.error(message)
                    except Exception as e:
                        st.error(f"ファイル読み込みエラー: {str(e)}")

        # 結果表示エリア
        st.divider()
        st.markdown(t("matching_result"))

        if process_btn:
            if not api_key:
                st.error("❌ APIキーを入力してください")
            elif not matching_resume_input or not matching_jd_input:
                st.warning(t("matching_both_required"))
            else:
                # 入力バリデーション
                is_valid_resume, error_msg_resume = validate_input(matching_resume_input, "matching")
                is_valid_jd, error_msg_jd = validate_input(matching_jd_input, "matching")

                if not is_valid_resume:
                    st.warning(f"⚠️ レジュメ入力エラー: {error_msg_resume}")
                elif not is_valid_jd:
                    st.warning(f"⚠️ 求人票入力エラー: {error_msg_jd}")
                else:
                    try:
                        start_time = time.time()
                        prompt = get_matching_analysis_prompt(matching_resume_input, matching_jd_input)
                        st.caption(t("matching_ai"))
                        stream_container = st.empty()
                        result = stream_to_container(api_key, prompt, stream_container)
                        elapsed_time = time.time() - start_time

                        st.session_state['matching_result'] = result
                        st.session_state['matching_time'] = elapsed_time
                        st.session_state['matching_resume_input'] = matching_resume_input
                        st.session_state['matching_jd_input'] = matching_jd_input

                        # 履歴に自動保存
                        resume_title = extract_title_from_content(matching_resume_input, "resume")
                        jd_title = extract_title_from_content(matching_jd_input, "jd")
                        add_to_history("resume", matching_resume_input, resume_title)
                        add_to_history("jd", matching_jd_input, jd_title)

                        stream_container.empty()
                        st.success(f"✅ 分析完了！（{elapsed_time:.1f}秒）")

                        # 自動バックアップ通知
                        st.info("💾 **データの保存を忘れずに！** スマホやタブを閉じると履歴が消える場合があります。")

                        # すぐにバックアップできるボタンを表示
                        resume_count = len(st.session_state.get('resume_history', []))
                        jd_count = len(st.session_state.get('jd_history', []))

                        col_backup1, col_backup2 = st.columns([2, 1])
                        with col_backup1:
                            st.caption(f"📊 現在の履歴: レジュメ {resume_count}件、求人票 {jd_count}件")
                        with col_backup2:
                            if resume_count > 0 or jd_count > 0:
                                json_data = export_history_to_json("all")
                                st.download_button(
                                    "💾 今すぐバックアップ",
                                    data=json_data,
                                    file_name=f"globalmatch_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                                    mime="application/json",
                                    use_container_width=True,
                                    key="quick_backup_btn",
                                    help="履歴をJSONファイルでダウンロード"
                                )

                    except ValueError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error("❌ 予期せぬエラーが発生しました。しばらく待ってから再試行してください")

        # 結果表示（セッションステートにある場合）
        if 'matching_result' in st.session_state:
            # 表示切替とコピーボタン
            col_view, col_copy = st.columns([2, 1])
            with col_view:
                show_formatted = st.checkbox(
                    "📖 整形表示",
                    value=True,  # デフォルトで整形表示
                    key="matching_formatted",
                    help="Markdownをフォーマットして表示"
                )
            with col_copy:
                if st.button("📋 コピー", key="copy_matching", use_container_width=True):
                    st.toast("✅ クリップボードにコピーしました")
                    _copy_to_clipboard(st.session_state['matching_result'])

            if show_formatted:
                st.markdown(st.session_state['matching_result'])
            else:
                # 編集可能なテキストエリア
                edited_matching_result = st.text_area(
                    "出力結果（編集可能）",
                    value=st.session_state['matching_result'],
                    height=600,
                    key="edit_matching_result"
                )
                st.session_state['matching_result'] = edited_matching_result

            # ダウンロードボタン
            st.divider()
            col_dl1, col_dl2, col_dl3 = st.columns(3)
            with col_dl1:
                st.download_button(
                    "📄 Markdown",
                    data=st.session_state['matching_result'],
                    file_name=f"matching_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                    mime="text/markdown",
                    key="matching_md"
                )
            with col_dl2:
                st.download_button(
                    "📝 テキスト",
                    data=st.session_state['matching_result'],
                    file_name=f"matching_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                    mime="text/plain",
                    key="matching_txt"
                )
            with col_dl3:
                html_content = generate_html(
                    st.session_state['matching_result'],
                    "マッチング分析レポート"
                )
                st.download_button(
                    "🌐 HTML",
                    data=html_content,
                    file_name=f"matching_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                    mime="text/html",
                    key="matching_html",
                    help="ブラウザで開いて印刷→PDF保存"
                )

            # 翻訳機能
            st.divider()
            st.markdown("#### 🌐 翻訳機能")
            col_trans1, col_trans2 = st.columns(2)

            with col_trans1:
                if st.button("🇯🇵→🇬🇧 日本語→英語", key="translate_to_en", use_container_width=True, help="マッチング分析結果を英語に翻訳"):
                    try:
                        prompt = get_translate_to_english_prompt(st.session_state['matching_result'])
                        st.caption("🤖 英語に翻訳中...")
                        stream_container = st.empty()
                        translated = stream_to_container(api_key, prompt, stream_container)
                        st.session_state['matching_result'] = translated
                        stream_container.empty()
                        st.success("✅ 英語への翻訳が完了しました")
                        st.rerun()
                    except Exception as e:
                        st.error("❌ 翻訳エラーが発生しました。しばらく待ってから再試行してください")

            with col_trans2:
                if st.button("🇬🇧→🇯🇵 英語→日本語", key="translate_to_ja", use_container_width=True, help="マッチング分析結果を日本語に翻訳"):
                    try:
                        prompt = get_translate_to_japanese_prompt(st.session_state['matching_result'])
                        st.caption("🤖 日本語に翻訳中...")
                        stream_container = st.empty()
                        translated = stream_to_container(api_key, prompt, stream_container)
                        st.session_state['matching_result'] = translated
                        stream_container.empty()
                        st.success("✅ 日本語への翻訳が完了しました")
                        st.rerun()
                    except Exception as e:
                        st.error("❌ 翻訳エラーが発生しました。しばらく待ってから再試行してください")

            # 匿名提案資料生成機能
            st.divider()
            st.markdown(t("proposal_header"))
            st.caption(t("proposal_desc"))

            proposal_anon_level = st.radio(
                "🔒 匿名化レベル",
                options=["full", "light"],
                format_func=lambda x: {
                    "full": t("anon_full_en"),
                    "light": t("anon_light_en")
                }[x],
                horizontal=True,
                key="proposal_anon_level",
                help="完全：企業名を「大手SIer」等に置換 / 軽度：企業名・大学名をそのまま表示（個人情報のみ匿名化）"
            )

            col_proposal1, col_proposal2 = st.columns(2)

            with col_proposal1:
                if st.button(t("proposal_ja_btn"), key="generate_proposal_ja", use_container_width=True, help=t("proposal_ja_help")):
                    if 'matching_resume_input' not in st.session_state or 'matching_jd_input' not in st.session_state:
                        st.error("❌ レジュメと求人票の入力情報が見つかりません。先にマッチング分析を実行してください。")
                    else:
                        try:
                            prompt = get_anonymous_proposal_prompt(
                                st.session_state['matching_result'],
                                st.session_state['matching_resume_input'],
                                st.session_state['matching_jd_input'],
                                language="ja",
                                anonymize_level=proposal_anon_level
                            )
                            st.caption("🤖 候補者提案資料（日本語）を生成中...")
                            stream_container = st.empty()
                            proposal = stream_to_container(api_key, prompt, stream_container)
                            st.session_state['anonymous_proposal_ja'] = proposal
                            # 後方互換: anonymous_proposalも更新
                            st.session_state['anonymous_proposal'] = proposal
                            stream_container.empty()
                            st.success("✅ 候補者提案資料（日本語）の生成が完了しました")
                            st.rerun()
                        except Exception as e:
                            st.error("❌ 生成エラーが発生しました。しばらく待ってから再試行してください")

            with col_proposal2:
                if st.button("📝 English Version", key="generate_proposal_en", use_container_width=True, help="Generate proposal (English)"):
                    if 'matching_resume_input' not in st.session_state or 'matching_jd_input' not in st.session_state:
                        st.error("❌ Resume and JD input not found. Please run matching analysis first.")
                    else:
                        try:
                            prompt = get_anonymous_proposal_prompt(
                                st.session_state['matching_result'],
                                st.session_state['matching_resume_input'],
                                st.session_state['matching_jd_input'],
                                language="en",
                                anonymize_level=proposal_anon_level
                            )
                            st.caption("🤖 Generating candidate proposal (English)...")
                            stream_container = st.empty()
                            proposal = stream_to_container(api_key, prompt, stream_container)
                            st.session_state['anonymous_proposal_en'] = proposal
                            # 後方互換: anonymous_proposalも更新
                            st.session_state['anonymous_proposal'] = proposal
                            stream_container.empty()
                            st.success("✅ Candidate proposal (English) generated successfully")
                            st.rerun()
                        except Exception as e:
                            st.error("❌ Generation error. Please try again later")

            # 匿名提案資料の表示
            _has_ja = 'anonymous_proposal_ja' in st.session_state
            _has_en = 'anonymous_proposal_en' in st.session_state
            # 後方互換: 旧anonymous_proposalのみ存在する場合
            _has_legacy = 'anonymous_proposal' in st.session_state and not _has_ja and not _has_en

            if _has_ja or _has_en or _has_legacy:
                st.divider()

                # 両言語ある場合はタブで切り替え
                if _has_ja and _has_en:
                    tab_ja, tab_en = st.tabs(["🇯🇵 日本語版", "🇬🇧 English Version"])

                    with tab_ja:
                        st.markdown("#### 📋 生成された候補者提案資料（日本語）")
                        col_view_ja, col_copy_ja = st.columns([2, 1])
                        with col_view_ja:
                            show_fmt_ja = st.checkbox("📖 整形表示", value=True, key="proposal_ja_formatted", help="Markdownをフォーマットして表示")
                        with col_copy_ja:
                            if st.button("📋 コピー", key="copy_proposal_ja", use_container_width=True):
                                st.toast("✅ クリップボードにコピーしました")
                                _copy_to_clipboard(st.session_state['anonymous_proposal_ja'])

                        if show_fmt_ja:
                            st.markdown(st.session_state['anonymous_proposal_ja'])
                        else:
                            edited_ja = st.text_area("出力結果（編集可能）", value=st.session_state['anonymous_proposal_ja'], height=600, key="edit_proposal_ja")
                            st.session_state['anonymous_proposal_ja'] = edited_ja

                        _prop_first_ja = extract_name_from_cv(st.session_state.get('matching_resume_input', ''))
                        _prop_label_ja = f"匿名候補者提案資料 - {_prop_first_ja}" if _prop_first_ja else "匿名候補者提案資料"
                        _prop_fname_ja = f"proposal_{_prop_first_ja}_ja_{datetime.now().strftime('%Y%m%d_%H%M')}" if _prop_first_ja else f"proposal_ja_{datetime.now().strftime('%Y%m%d_%H%M')}"

                        col_dl1_ja, col_dl2_ja, col_dl3_ja = st.columns(3)
                        with col_dl1_ja:
                            st.download_button("📄 Markdown", data=st.session_state['anonymous_proposal_ja'], file_name=f"{_prop_fname_ja}.md", mime="text/markdown", key="proposal_ja_md")
                        with col_dl2_ja:
                            st.download_button("📝 テキスト", data=st.session_state['anonymous_proposal_ja'], file_name=f"{_prop_fname_ja}.txt", mime="text/plain", key="proposal_ja_txt")
                        with col_dl3_ja:
                            html_ja = generate_html(st.session_state['anonymous_proposal_ja'], _prop_label_ja)
                            st.download_button("🌐 HTML", data=html_ja, file_name=f"{_prop_fname_ja}.html", mime="text/html", key="proposal_ja_html", help="ブラウザで開いて印刷→PDF保存")

                    with tab_en:
                        st.markdown("#### 📋 Generated Candidate Proposal (English)")
                        col_view_en, col_copy_en = st.columns([2, 1])
                        with col_view_en:
                            show_fmt_en = st.checkbox("📖 Formatted View", value=True, key="proposal_en_formatted", help="Display formatted Markdown")
                        with col_copy_en:
                            if st.button("📋 Copy", key="copy_proposal_en", use_container_width=True):
                                st.toast("✅ Copied to clipboard")
                                _copy_to_clipboard(st.session_state['anonymous_proposal_en'])

                        if show_fmt_en:
                            st.markdown(st.session_state['anonymous_proposal_en'])
                        else:
                            edited_en = st.text_area("Output (Editable)", value=st.session_state['anonymous_proposal_en'], height=600, key="edit_proposal_en")
                            st.session_state['anonymous_proposal_en'] = edited_en

                        _prop_first_en = extract_name_from_cv(st.session_state.get('matching_resume_input', ''))
                        _prop_label_en = f"Candidate Proposal - {_prop_first_en}" if _prop_first_en else "Candidate Proposal"
                        _prop_fname_en = f"proposal_{_prop_first_en}_en_{datetime.now().strftime('%Y%m%d_%H%M')}" if _prop_first_en else f"proposal_en_{datetime.now().strftime('%Y%m%d_%H%M')}"

                        col_dl1_en, col_dl2_en, col_dl3_en = st.columns(3)
                        with col_dl1_en:
                            st.download_button("📄 Markdown", data=st.session_state['anonymous_proposal_en'], file_name=f"{_prop_fname_en}.md", mime="text/markdown", key="proposal_en_md")
                        with col_dl2_en:
                            st.download_button("📝 Text", data=st.session_state['anonymous_proposal_en'], file_name=f"{_prop_fname_en}.txt", mime="text/plain", key="proposal_en_txt")
                        with col_dl3_en:
                            html_en = generate_html(st.session_state['anonymous_proposal_en'], _prop_label_en)
                            st.download_button("🌐 HTML", data=html_en, file_name=f"{_prop_fname_en}.html", mime="text/html", key="proposal_en_html", help="Open in browser and Print → Save as PDF")

                else:
                    # 片方のみ、または旧形式
                    _current_key = 'anonymous_proposal_ja' if _has_ja else ('anonymous_proposal_en' if _has_en else 'anonymous_proposal')
                    _is_en = _current_key == 'anonymous_proposal_en'
                    _header = "#### 📋 Generated Candidate Proposal (English)" if _is_en else "#### 📋 生成された候補者提案資料"

                    st.markdown(_header)

                    col_view_prop, col_copy_prop = st.columns([2, 1])
                    with col_view_prop:
                        show_formatted_prop = st.checkbox(
                            "📖 Formatted View" if _is_en else "📖 整形表示",
                            value=True,
                            key="proposal_formatted",
                            help="Display formatted Markdown" if _is_en else "Markdownをフォーマットして表示"
                        )
                    with col_copy_prop:
                        if st.button("📋 Copy" if _is_en else "📋 コピー", key="copy_proposal", use_container_width=True):
                            st.toast("✅ Copied to clipboard" if _is_en else "✅ クリップボードにコピーしました")
                            _copy_to_clipboard(st.session_state[_current_key])

                    if show_formatted_prop:
                        st.markdown(st.session_state[_current_key])
                    else:
                        edited_proposal = st.text_area(
                            "Output (Editable)" if _is_en else "出力結果（編集可能）",
                            value=st.session_state[_current_key],
                            height=600,
                            key="edit_proposal"
                        )
                        st.session_state[_current_key] = edited_proposal

                    _prop_first = extract_name_from_cv(st.session_state.get('matching_resume_input', ''))
                    _lang_suffix = "en" if _is_en else "ja"
                    _prop_label = (f"Candidate Proposal - {_prop_first}" if _prop_first else "Candidate Proposal") if _is_en else (f"匿名候補者提案資料 - {_prop_first}" if _prop_first else "匿名候補者提案資料")
                    _prop_fname = f"proposal_{_prop_first}_{_lang_suffix}_{datetime.now().strftime('%Y%m%d_%H%M')}" if _prop_first else f"proposal_{_lang_suffix}_{datetime.now().strftime('%Y%m%d_%H%M')}"

                    st.divider()
                    col_dl_prop1, col_dl_prop2, col_dl_prop3 = st.columns(3)
                    with col_dl_prop1:
                        st.download_button("📄 Markdown", data=st.session_state[_current_key], file_name=f"{_prop_fname}.md", mime="text/markdown", key="proposal_md")
                    with col_dl_prop2:
                        st.download_button("📝 Text" if _is_en else "📝 テキスト", data=st.session_state[_current_key], file_name=f"{_prop_fname}.txt", mime="text/plain", key="proposal_txt")
                    with col_dl_prop3:
                        html_content = generate_html(st.session_state[_current_key], _prop_label)
                        st.download_button("🌐 HTML", data=html_content, file_name=f"{_prop_fname}.html", mime="text/html", key="proposal_html", help="Open in browser and Print → Save as PDF" if _is_en else "ブラウザで開いて印刷→PDF保存")

            # 共有リンク作成ボタン — 候補者名をタイトルに使用
            _match_name = extract_name_from_cv(st.session_state.get('matching_resume_input', ''))
            _match_title = f"マッチング分析レポート - {_match_name}" if _match_name else "マッチング分析レポート"
            if get_supabase_client():
                st.divider()
                if st.button("🔗 共有リンク作成", key="share_matching", help="1ヶ月有効の共有リンクを作成"):
                    with st.spinner("共有リンクを作成中..."):
                        share_id = create_share_link(
                            st.session_state['matching_result'],
                            _match_title
                        )
                    if share_id:
                        base_url = _get_app_base_url()
                        share_url = f"{base_url}/?share={share_id}"
                        st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                        st.code(share_url)
                        st.info("💡 上のURLをコピーしてクライアントに共有してください")
                    else:
                        st.error("❌ 共有リンクの作成に失敗しました")

    elif feature == "cv_extract":
        st.subheader(t("cv_title"))
        st.caption(t("cv_desc"))

        # 匿名化レベル選択
        col_mode, col_anon = st.columns(2)
        with col_mode:
            # 入力モード選択
            cv_extract_mode = st.radio(
                t("cv_mode_label"),
                options=["single", "batch"],
                format_func=lambda x: {
                    "single": t("cv_mode_single"),
                    "batch": t("cv_mode_batch")
                }[x],
                horizontal=True,
                key="cv_extract_mode"
            )
        with col_anon:
            cv_anon_level = st.radio(
                "🔒 匿名化レベル",
                options=["full", "light"],
                format_func=lambda x: {
                    "full": "完全匿名化（企業名も伏せる）",
                    "light": "軽度匿名化（企業名は表示）"
                }[x],
                horizontal=True,
                key="cv_extract_anon_level",
                help="完全：企業名を「a major IT firm」等に置換 / 軽度：企業名・大学名をそのまま表示"
            )

        if cv_extract_mode == "single":
            col1, col2 = st.columns([1, 1])

            with col1:
                input_tab1, input_tab2 = st.tabs(["📝 テキスト入力", "📄 PDF読み込み"])

                with input_tab1:
                    st.markdown(t("cv_input"))
                    cv_extract_input = st.text_area(
                        t("cv_paste"),
                        height=350,
                        placeholder="Paste the English CV/Resume here...",
                        label_visibility="collapsed",
                        key="cv_extract_text"
                    )

                with input_tab2:
                    st.markdown("##### PDFをアップロード")
                    uploaded_pdf_cv = st.file_uploader(
                        "PDFファイルを選択",
                        type=["pdf"],
                        key="cv_extract_pdf",
                        help=f"最大{MAX_PDF_SIZE_MB}MB、20ページまで"
                    )

                    if uploaded_pdf_cv:
                        with st.spinner("📄 PDFを読み込み中..."):
                            extracted_cv_text, cv_pdf_error = extract_text_from_pdf(uploaded_pdf_cv)
                            if cv_pdf_error:
                                st.error(f"❌ {cv_pdf_error}")
                            else:
                                st.success(f"✅ テキスト抽出完了（{len(extracted_cv_text):,}文字）")
                                cv_extract_input = extracted_cv_text
                                with st.expander("抽出されたテキストを確認"):
                                    st.text(extracted_cv_text[:2000] + ("..." if len(extracted_cv_text) > 2000 else ""))
                    else:
                        if 'cv_extract_input' not in dir():
                            cv_extract_input = ""

                # 文字数カウンター
                cv_char_count = len(cv_extract_input) if cv_extract_input else 0
                if cv_char_count > MAX_INPUT_CHARS:
                    st.error(f"📊 {cv_char_count:,} / {MAX_INPUT_CHARS:,} 文字（超過）")
                elif cv_char_count > 0:
                    st.caption(f"📊 {cv_char_count:,} / {MAX_INPUT_CHARS:,} 文字")

                _show_btn_hint(api_key, bool(cv_extract_input))
                cv_extract_btn = st.button(
                    t("cv_extract_btn"),
                    type="primary",
                    use_container_width=True,
                    disabled=not api_key or not cv_extract_input,
                    key="cv_extract_btn"
                )

            with col2:
                st.markdown(t("cv_output"))

                if cv_extract_btn:
                    if not api_key:
                        st.error("❌ APIキーを入力してください")
                    else:
                        is_valid_cv, error_msg_cv = validate_input(cv_extract_input, "resume")
                        if not is_valid_cv:
                            st.warning(f"⚠️ {error_msg_cv}")
                        else:
                            try:
                                start_time = time.time()
                                prompt = get_cv_proposal_extract_prompt(cv_extract_input, anonymize_level=cv_anon_level)
                                st.caption(t("cv_ai"))
                                stream_container = st.empty()
                                result = stream_to_container(api_key, prompt, stream_container)
                                elapsed_time = time.time() - start_time

                                st.session_state['cv_extract_result'] = result
                                st.session_state['cv_extract_time'] = elapsed_time
                                stream_container.empty()
                                st.success(f"✅ 抽出完了！（{elapsed_time:.1f}秒）")

                            except ValueError as e:
                                st.error(str(e))
                            except Exception as e:
                                st.error(f"❌ エラー: {type(e).__name__}: {e}")

                # 結果表示
                if 'cv_extract_result' in st.session_state:
                    col_view, col_copy = st.columns([3, 1])
                    with col_view:
                        show_formatted_cv = st.checkbox("📖 整形表示", value=True, key="cv_extract_formatted")
                    with col_copy:
                        if st.button("📋 コピー", key="copy_cv_extract", use_container_width=True):
                            st.toast("✅ クリップボードにコピーしました")
                            _copy_to_clipboard(st.session_state['cv_extract_result'])

                    # 文章量調整スライダー
                    col_slider, col_adjust = st.columns([3, 1])
                    with col_slider:
                        target_chars = st.slider(
                            "📏 文章量（各セクションの目安文字数）",
                            min_value=100, max_value=400, value=250, step=50,
                            key="cv_extract_length_slider",
                            help="小さい値＝簡潔、大きい値＝詳細"
                        )
                    with col_adjust:
                        st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
                        if st.button("✏️ 文章量を調整", key="adjust_cv_extract", use_container_width=True):
                            with st.spinner("🤖 調整中..."):
                                try:
                                    prompt = get_adjust_length_prompt(st.session_state['cv_extract_result'], target_chars)
                                    adjusted = call_groq_api(api_key, prompt)
                                    st.session_state['cv_extract_result'] = adjusted
                                    st.success("✅ 調整完了！")
                                    st.rerun()
                                except Exception as e:
                                    st.error("❌ 調整エラーが発生しました。しばらく待ってから再試行してください")

                    if show_formatted_cv:
                        st.markdown(st.session_state['cv_extract_result'])
                    else:
                        edited_cv_result = st.text_area(
                            "Output (Editable)",
                            value=st.session_state['cv_extract_result'],
                            height=400,
                            key="edit_cv_extract_result"
                        )
                        st.session_state['cv_extract_result'] = edited_cv_result

                    # ダウンロードボタン
                    col_dl1, col_dl2 = st.columns(2)
                    with col_dl1:
                        st.download_button(
                            "📄 Markdown",
                            data=st.session_state['cv_extract_result'],
                            file_name=f"cv_proposal_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                            mime="text/markdown",
                            key="cv_extract_md"
                        )
                    with col_dl2:
                        st.download_button(
                            "📝 テキスト",
                            data=st.session_state['cv_extract_result'],
                            file_name=f"cv_proposal_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                            mime="text/plain",
                            key="cv_extract_txt"
                        )

        else:  # batch mode
            batch_input_tab1, batch_input_tab2 = st.tabs(["📝 テキスト入力", "📄 複数PDF読み込み"])

            # PDFから抽出したCVリストを保持
            if 'batch_cv_pdf_texts' not in st.session_state:
                st.session_state['batch_cv_pdf_texts'] = []

            with batch_input_tab1:
                st.info("💡 **区切り方法**: `---NEXT---` を各CVの間に入れてください")

                batch_cv_input = st.text_area(
                    "複数の英語CVを貼り付け",
                    height=400,
                    placeholder="""John Doe
Software Engineer with 5+ years experience...
[CV 1]

---NEXT---

Jane Smith
Full-stack Developer...
[CV 2]

---NEXT---

[Add more CVs...]""",
                    label_visibility="collapsed",
                    key="batch_cv_extract_text"
                )

            with batch_input_tab2:
                st.markdown("##### 複数PDFをアップロード（最大10件）")
                uploaded_pdfs = st.file_uploader(
                    "PDFファイルを選択（複数選択可）",
                    type=["pdf"],
                    accept_multiple_files=True,
                    key="batch_cv_pdfs",
                    help=f"各ファイル最大{MAX_PDF_SIZE_MB}MB、20ページまで。最大10ファイル。"
                )

                if uploaded_pdfs:
                    if len(uploaded_pdfs) > 10:
                        st.error("❌ 一度にアップロードできるのは最大10件までです")
                    else:
                        pdf_texts = []
                        for j, pdf_file in enumerate(uploaded_pdfs):
                            extracted_text, pdf_error = extract_text_from_pdf(pdf_file)
                            if pdf_error:
                                st.warning(f"⚠️ {pdf_file.name}: {pdf_error}")
                            else:
                                pdf_texts.append(extracted_text)
                                st.success(f"✅ {pdf_file.name}（{len(extracted_text):,}文字）")
                        st.session_state['batch_cv_pdf_texts'] = pdf_texts
                        # PDFテキストをbatch_cv_inputにマージ
                        if pdf_texts:
                            batch_cv_input = "\n\n---NEXT---\n\n".join(pdf_texts)

            # CV数カウント
            if batch_cv_input:
                cv_list = [r.strip() for r in batch_cv_input.split("---NEXT---") if r.strip()]
                st.metric("検出されたCV数", len(cv_list))
            else:
                cv_list = []
                st.metric("検出されたCV数", 0)

            _show_btn_hint(api_key, bool(batch_cv_input))
            batch_cv_btn = st.button(
                "🚀 一括抽出実行",
                type="primary",
                use_container_width=True,
                disabled=not api_key or not batch_cv_input,
                key="batch_cv_extract_btn"
            )

            if batch_cv_btn and batch_cv_input:
                cv_list = [r.strip() for r in batch_cv_input.split("---NEXT---") if r.strip()]

                if len(cv_list) == 0:
                    st.warning("⚠️ CVが検出されませんでした")
                elif len(cv_list) > 10:
                    st.error("❌ 一度に処理できるのは最大10件までです")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    batch_cv_start_time = time.time()

                    # CV名を先に抽出
                    cv_names = [extract_name_from_cv(cv_text) for cv_text in cv_list]

                    def _process_single_cv(index, cv_text, cv_name):
                        cv_result = {"index": index, "name": cv_name, "status": "pending", "output": None, "error": None, "time": 0}
                        is_valid, error_msg = validate_input(cv_text, "resume")
                        if not is_valid:
                            cv_result["status"] = "error"
                            cv_result["error"] = error_msg
                        else:
                            try:
                                item_start = time.time()
                                prompt = get_cv_proposal_extract_prompt(cv_text, anonymize_level=cv_anon_level)
                                output = call_groq_api(api_key, prompt)
                                cv_result["status"] = "success"
                                cv_result["output"] = output
                                cv_result["time"] = time.time() - item_start
                            except Exception as e:
                                cv_result["status"] = "error"
                                cv_result["error"] = str(e)
                        return cv_result

                    cv_results = [None] * len(cv_list)
                    max_workers = min(3, len(cv_list))
                    completed_count = 0

                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = {
                            executor.submit(_process_single_cv, i + 1, cv_text, cv_names[i]): i
                            for i, cv_text in enumerate(cv_list)
                        }
                        for future in as_completed(futures):
                            idx = futures[future]
                            cv_results[idx] = future.result()
                            completed_count += 1
                            name_label = f" - {cv_names[idx]}" if cv_names[idx] else ""
                            status_text.text(f"🔄 処理中... ({completed_count}/{len(cv_list)}){name_label}")
                            progress_bar.progress(completed_count / len(cv_list))

                    batch_cv_elapsed = time.time() - batch_cv_start_time
                    st.session_state['batch_cv_extract_results'] = cv_results
                    st.session_state['batch_cv_extract_time'] = batch_cv_elapsed
                    status_text.text(f"✅ 処理完了！（合計 {batch_cv_elapsed:.1f}秒）")

            # バッチ結果表示
            if 'batch_cv_extract_results' in st.session_state:
                st.divider()
                st.subheader("📊 抽出結果")

                success_count = sum(1 for r in st.session_state['batch_cv_extract_results'] if r['status'] == 'success')
                error_count = sum(1 for r in st.session_state['batch_cv_extract_results'] if r['status'] == 'error')

                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    st.metric("✅ 成功", success_count)
                with col_m2:
                    st.metric("❌ エラー", error_count)

                # 個別結果
                for cv_r in st.session_state['batch_cv_extract_results']:
                    time_str = f"（{cv_r['time']:.1f}秒）" if cv_r['time'] > 0 else ""
                    cv_label = cv_r.get('name') or f"CV #{cv_r['index']}"
                    with st.expander(f"{cv_label} - {'✅ 成功' + time_str if cv_r['status'] == 'success' else '❌ エラー'}"):
                        if cv_r['status'] == 'success':
                            col_view_b, col_copy_b = st.columns([3, 1])
                            with col_view_b:
                                show_fmt = st.checkbox("📖 整形表示", value=True, key=f"batch_cv_fmt_{cv_r['index']}")
                            with col_copy_b:
                                if st.button("📋 コピー", key=f"copy_batch_cv_{cv_r['index']}", use_container_width=True):
                                    st.toast("✅ クリップボードにコピーしました")
                                    _copy_to_clipboard(cv_r['output'])

                            # 文章量調整スライダー
                            col_slider_b, col_adjust_b = st.columns([3, 1])
                            with col_slider_b:
                                batch_target = st.slider(
                                    "📏 文章量（各セクションの目安文字数）",
                                    min_value=100, max_value=400, value=250, step=50,
                                    key=f"batch_cv_length_{cv_r['index']}",
                                    help="小さい値＝簡潔、大きい値＝詳細"
                                )
                            with col_adjust_b:
                                st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
                                if st.button("✏️ 文章量を調整", key=f"adjust_batch_cv_{cv_r['index']}", use_container_width=True):
                                    with st.spinner("🤖 調整中..."):
                                        try:
                                            prompt = get_adjust_length_prompt(cv_r['output'], batch_target)
                                            adjusted = call_groq_api(api_key, prompt)
                                            cv_r['output'] = adjusted
                                            st.success("✅ 調整完了！")
                                            st.rerun()
                                        except Exception as e:
                                            st.error("❌ 調整エラーが発生しました。しばらく待ってから再試行してください")

                            if show_fmt:
                                st.markdown(cv_r['output'])
                            else:
                                st.code(cv_r['output'], language="markdown")
                        else:
                            st.error(f"エラー: {cv_r['error']}")

                # 全件まとめてダウンロード
                if success_count > 0:
                    st.divider()
                    all_cv_content = "\n\n---\n\n".join([
                        f"# {r.get('name') or 'CV #' + str(r['index'])}\n\n{r['output']}"
                        for r in st.session_state['batch_cv_extract_results']
                        if r['status'] == 'success'
                    ])
                    st.download_button(
                        "📦 全件ダウンロード（Markdown）",
                        data=all_cv_content,
                        file_name=f"cv_proposals_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                        mime="text/markdown",
                        use_container_width=True,
                        key="batch_cv_extract_download"
                    )

    elif feature == "email":
        st.subheader(t("email_title"))
        st.caption(t("email_desc"))

        # saved_jobs / saved_job_sets 初期化
        if 'saved_jobs' not in st.session_state:
            st.session_state['saved_jobs'] = []
        if 'saved_job_sets' not in st.session_state:
            st.session_state['saved_job_sets'] = []

        # --- 基本情報 ---
        col_name, col_sender, col_email_lang = st.columns(3)
        with col_name:
            candidate_name = st.text_input(
                t("email_candidate_name"),
                placeholder="e.g. Taro",
                key="email_candidate_name"
            )
        with col_sender:
            sender_name = st.selectbox(
                t("email_sender"),
                options=["Shu", "Ilya", "Hiroshi"],
                key="email_sender_name"
            )
        with col_email_lang:
            email_lang = st.selectbox(
                t("email_lang_label"),
                options=["en", "ja"],
                format_func=lambda x: t("email_lang_en") if x == "en" else t("email_lang_ja"),
                key="email_output_lang"
            )

        st.divider()

        # --- モード切替タブ ---
        email_manual_tab, email_batch_tab = st.tabs([t("email_tab_manual"), t("email_tab_batch")])

        # ============================================================
        # 一括PDFモード
        # ============================================================
        with email_batch_tab:
            st.caption(t("email_batch_desc"))

            # PDF一括アップロード
            batch_pdfs = st.file_uploader(
                t("email_batch_upload"),
                type=["pdf"],
                accept_multiple_files=True,
                key="email_batch_pdfs",
                help=t("email_batch_upload_help"),
            )

            # URL一括入力
            batch_urls_text = st.text_area(
                t("email_batch_url_label"),
                placeholder=t("email_batch_url_placeholder"),
                height=100,
                key="email_batch_urls",
            )

            # 入力件数カウント
            batch_url_list = [u.strip() for u in batch_urls_text.split("\n") if u.strip()] if batch_urls_text else []
            total_sources = len(batch_pdfs or []) + len(batch_url_list)

            if total_sources > 10:
                st.error(t("email_batch_max_error"))

            # 抽出ボタン
            batch_extract_btn = st.button(
                t("email_batch_extract_btn"),
                type="primary",
                use_container_width=True,
                disabled=not api_key or total_sources == 0 or total_sources > 10,
                key="email_batch_extract_btn",
            )

            if batch_extract_btn and api_key:
                sources = []
                # PDFからテキスト抽出
                for pdf_file in (batch_pdfs or []):
                    text, err = extract_text_from_pdf(pdf_file)
                    if err:
                        st.warning(t("email_batch_extract_error").format(name=pdf_file.name) + f" - {err}")
                    elif text:
                        sources.append((pdf_file.name, text))

                # URLからテキスト抽出
                for url in batch_url_list:
                    text, err = extract_text_from_url(url)
                    if err:
                        st.warning(t("email_batch_extract_error").format(name=url) + f" - {err}")
                    elif text:
                        sources.append((url, text))

                if sources:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    start_time = time.time()
                    results = []

                    with ThreadPoolExecutor(max_workers=min(3, len(sources))) as executor:
                        futures = {
                            executor.submit(_extract_job_from_source, api_key, name, text): idx
                            for idx, (name, text) in enumerate(sources)
                        }
                        done_count = 0
                        for future in as_completed(futures):
                            done_count += 1
                            status_text.text(t("email_batch_extracting").format(done=done_count, total=len(sources)))
                            progress_bar.progress(done_count / len(sources))
                            results.append(future.result())

                    elapsed = round(time.time() - start_time, 1)
                    progress_bar.empty()
                    status_text.empty()

                    # 成功した結果をセッションに保存
                    extracted_jobs = []
                    error_names = []
                    for r in results:
                        if r["success"]:
                            extracted_jobs.append(r["data"])
                        else:
                            error_names.append(r["name"])

                    if error_names:
                        for en in error_names:
                            st.warning(t("email_batch_extract_error").format(name=en))

                    if extracted_jobs:
                        st.session_state['batch_extracted_jobs'] = extracted_jobs
                        st.toast(t("email_batch_extract_done").format(count=len(extracted_jobs), time=elapsed))
                        st.rerun()
                else:
                    st.warning(t("email_batch_no_input"))

            # --- 抽出結果の表示・編集 ---
            if st.session_state.get('batch_extracted_jobs'):
                batch_jobs = st.session_state['batch_extracted_jobs']
                st.markdown(t("email_batch_results").format(count=len(batch_jobs)))
                st.caption(t("email_batch_edit_hint"))

                edited_batch_jobs = []
                for idx, bj in enumerate(batch_jobs):
                    with st.expander(
                        f"#{idx + 1} {bj.get('company', '?')} | {bj.get('title', '?')}",
                        expanded=True,
                    ):
                        bcol1, bcol2 = st.columns(2)
                        with bcol1:
                            b_title = st.text_input(
                                t("email_position"),
                                value=bj.get("title", ""),
                                key=f"batch_job_title_{idx}",
                            )
                        with bcol2:
                            b_company = st.text_input(
                                t("email_company"),
                                value=bj.get("company", ""),
                                key=f"batch_job_company_{idx}",
                            )
                        b_website = st.text_input(
                            "Website URL",
                            value=bj.get("website", ""),
                            key=f"batch_job_website_{idx}",
                        )
                        b_overview = st.text_area(
                            t("email_overview"),
                            value=bj.get("overview", ""),
                            height=80,
                            key=f"batch_job_overview_{idx}",
                        )
                        b_keyfocus = st.text_input(
                            t("email_keyfocus"),
                            value=bj.get("key_focus", ""),
                            key=f"batch_job_keyfocus_{idx}",
                        )
                        b_jdnote = st.text_input(
                            t("email_jdnote"),
                            value="",
                            key=f"batch_job_jdnote_{idx}",
                        )
                        b_fit = st.text_area(
                            t("email_recommendation"),
                            value="",
                            height=68,
                            key=f"batch_job_fit_{idx}",
                        )

                        edited_batch_jobs.append({
                            "title": b_title,
                            "company": b_company,
                            "website": b_website,
                            "overview": b_overview,
                            "key_focus": b_keyfocus,
                            "jd_note": b_jdnote,
                            "fit_comment": b_fit,
                        })

                # 一括メール生成ボタン
                col_gen_b, col_clear_b = st.columns([3, 1])
                with col_gen_b:
                    batch_gen_btn = st.button(
                        t("email_batch_generate_btn").format(count=len(batch_jobs)),
                        type="primary",
                        use_container_width=True,
                        disabled=not candidate_name,
                        key="batch_generate_email_btn",
                    )
                with col_clear_b:
                    if st.button(t("email_batch_clear"), use_container_width=True, key="batch_clear_btn"):
                        del st.session_state['batch_extracted_jobs']
                        st.rerun()

                if batch_gen_btn and candidate_name:
                    email_text = _build_email_text(candidate_name, sender_name, edited_batch_jobs, email_lang)
                    st.session_state['generated_email_batch'] = email_text

                # --- バッチ結果表示 ---
                if 'generated_email_batch' in st.session_state:
                    st.divider()
                    st.markdown(t("email_output"))

                    col_copy_b, col_dl_b = st.columns(2)
                    with col_copy_b:
                        if st.button("📋 コピー", key="copy_batch_email_btn", use_container_width=True):
                            st.toast("✅ クリップボードにコピーしました")
                            _copy_to_clipboard(st.session_state['generated_email_batch'])
                    with col_dl_b:
                        st.download_button(
                            t("email_dl_text"),
                            data=st.session_state['generated_email_batch'],
                            file_name=f"job_email_batch_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                            mime="text/plain",
                            use_container_width=True,
                            key="dl_batch_email_btn",
                        )

                    st.code(st.session_state['generated_email_batch'], language=None)

        # ============================================================
        # 手動入力モード（既存機能）
        # ============================================================
        with email_manual_tab:

            # --- 保存済みデータから読み込み ---
            saved_jobs_list = st.session_state.get('saved_jobs', [])
            saved_sets_list = st.session_state.get('saved_job_sets', [])

            if saved_sets_list or saved_jobs_list:
                st.markdown(t("email_saved_data"))
                load_tab_set, load_tab_individual = st.tabs(["📦 セットから読み込み", "📄 個別求人から選択"])

                with load_tab_set:
                    if saved_sets_list:
                        set_options = [f"{s['name']}（{len(s['jobs'])}件）" for s in saved_sets_list]
                        selected_set_idx = st.selectbox(
                            "求人セットを選択",
                            options=range(len(set_options)),
                            format_func=lambda x: set_options[x],
                            key="selected_job_set"
                        )

                        # 選択中のセット内容をプレビュー
                        selected_set = saved_sets_list[selected_set_idx]
                        preview_lines = [f"- {j.get('company', '')} | {j.get('title', '')}" for j in selected_set['jobs']]
                        st.caption("\n".join(preview_lines))

                        if st.button("📥 このセットを読み込み", key="load_set_btn", use_container_width=True):
                            set_jobs = selected_set['jobs']
                            st.session_state['email_job_count'] = len(set_jobs)
                            for idx, sj in enumerate(set_jobs):
                                st.session_state[f'job_title_{idx}'] = sj.get('title', '')
                                st.session_state[f'company_name_{idx}'] = sj.get('company', '')
                                st.session_state[f'job_website_{idx}'] = sj.get('website', '')
                                st.session_state[f'job_overview_{idx}'] = sj.get('overview', '')
                                st.session_state[f'job_keyfocus_{idx}'] = sj.get('key_focus', '')
                                st.session_state[f'job_jdnote_{idx}'] = sj.get('jd_note', '')
                                st.session_state[f'job_fit_{idx}'] = sj.get('fit_comment', '')
                            st.rerun()
                    else:
                        st.info("保存済みセットはありません。下の求人フォームを入力後「💾 セットとして保存」で作成できます。")

                with load_tab_individual:
                    if saved_jobs_list:
                        saved_options = [f"{sj['company']} - {sj['title']}" for sj in saved_jobs_list]
                        selected_saved = st.multiselect(
                            "メールに含める求人を選択",
                            options=range(len(saved_options)),
                            format_func=lambda x: saved_options[x],
                            key="selected_saved_jobs"
                        )

                        if selected_saved:
                            if st.button("📥 選択した求人を読み込み", key="load_saved_jobs_btn", use_container_width=True):
                                st.session_state['email_job_count'] = len(selected_saved)
                                for idx, sj_idx in enumerate(selected_saved):
                                    sj = saved_jobs_list[sj_idx]
                                    st.session_state[f'job_title_{idx}'] = sj.get('title', '')
                                    st.session_state[f'company_name_{idx}'] = sj.get('company', '')
                                    st.session_state[f'job_website_{idx}'] = sj.get('website', '')
                                    st.session_state[f'job_overview_{idx}'] = sj.get('overview', '')
                                    st.session_state[f'job_keyfocus_{idx}'] = sj.get('key_focus', '')
                                    st.session_state[f'job_jdnote_{idx}'] = sj.get('jd_note', '')
                                    st.session_state[f'job_fit_{idx}'] = sj.get('fit_comment', '')
                                st.rerun()
                    else:
                        st.info("保存済みの個別求人はありません。各求人エントリ内の「💾 この求人を保存」で追加できます。")

                st.divider()

            # --- 求人エントリ管理 ---
            st.markdown("##### 求人情報")

            # 求人数を管理
            if 'email_job_count' not in st.session_state:
                st.session_state['email_job_count'] = 1

            col_add, col_remove = st.columns(2)
            with col_add:
                if st.button("＋ 求人を追加", key="add_job_btn", use_container_width=True):
                    if st.session_state['email_job_count'] < 10:
                        st.session_state['email_job_count'] += 1
                        st.rerun()
            with col_remove:
                if st.button("－ 最後の求人を削除", key="remove_job_btn", use_container_width=True,
                             disabled=st.session_state['email_job_count'] <= 1):
                    st.session_state['email_job_count'] -= 1
                    st.rerun()

            st.caption(f"現在の求人数: {st.session_state['email_job_count']}件（最大10件）")

            jobs = []
            for i in range(st.session_state['email_job_count']):
                with st.expander(f"求人 #{i + 1}", expanded=True):
                    # --- 自動読み取り（PDF / URL） ---
                    st.markdown("📎 **求人を自動読み取り**（PDFまたはURLを入力）")
                    auto_col1, auto_col2 = st.columns(2)
                    with auto_col1:
                        uploaded_jd_pdf = st.file_uploader(
                            "求人PDF",
                            type=["pdf"],
                            key=f"job_pdf_{i}",
                            label_visibility="collapsed"
                        )
                    with auto_col2:
                        jd_url = st.text_input(
                            "求人URL",
                            placeholder="https://... 求人ページのURLを貼り付け",
                            key=f"job_url_{i}",
                            label_visibility="collapsed"
                        )

                    extract_btn = st.button(
                        "🔍 読み取り → 自動入力",
                        key=f"extract_job_{i}",
                        use_container_width=True,
                        disabled=not api_key or (not uploaded_jd_pdf and not jd_url)
                    )

                    if extract_btn and api_key:
                        extracted_text = ""
                        error_msg = ""

                        if uploaded_jd_pdf:
                            extracted_text, error_msg = extract_text_from_pdf(uploaded_jd_pdf)
                        elif jd_url:
                            extracted_text, error_msg = extract_text_from_url(jd_url)

                        if error_msg:
                            st.error(error_msg)
                        elif extracted_text:
                            with st.spinner("求人情報を解析中..."):
                                try:
                                    prompt = get_job_extraction_prompt(extracted_text)
                                    result = call_groq_api(api_key, prompt)
                                    # JSON部分を抽出
                                    result = result.strip()
                                    if result.startswith("```"):
                                        result = re.sub(r'^```(?:json)?\s*', '', result)
                                        result = re.sub(r'\s*```$', '', result)
                                    job_data = json.loads(result)

                                    # フィールドに反映
                                    if job_data.get("title"):
                                        st.session_state[f'job_title_{i}'] = job_data["title"]
                                    if job_data.get("company"):
                                        st.session_state[f'company_name_{i}'] = job_data["company"]
                                    if job_data.get("website"):
                                        st.session_state[f'job_website_{i}'] = job_data["website"]
                                    elif jd_url:
                                        # URLから読み取った場合、そのURLをwebsiteに設定
                                        st.session_state[f'job_website_{i}'] = jd_url
                                    if job_data.get("overview"):
                                        st.session_state[f'job_overview_{i}'] = job_data["overview"]
                                    if job_data.get("key_focus"):
                                        st.session_state[f'job_keyfocus_{i}'] = job_data["key_focus"]

                                    st.toast(f"✅ 求人 #{i + 1} の情報を自動入力しました")
                                    st.rerun()
                                except json.JSONDecodeError:
                                    st.error("解析結果のパースに失敗しました。再度お試しください。")
                                except ValueError as e:
                                    st.error(str(e))

                    if not api_key and (uploaded_jd_pdf or jd_url):
                        st.caption("⚠️ 自動読み取りにはサイドバーでAPIキーの設定が必要です")

                    st.markdown("---")

                    # --- 手動入力フィールド ---
                    jcol1, jcol2 = st.columns(2)
                    with jcol1:
                        job_title = st.text_input(
                            "ポジション名",
                            placeholder="e.g. Robot Deployment / Research Engineer",
                            key=f"job_title_{i}"
                        )
                    with jcol2:
                        company_name = st.text_input(
                            "企業名",
                            placeholder="e.g. RLWRLD",
                            key=f"company_name_{i}"
                        )
                    website = st.text_input(
                        "Website URL",
                        placeholder="e.g. https://www.example.com/",
                        key=f"job_website_{i}"
                    )
                    overview = st.text_area(
                        "概要 / Overview（任意）",
                        placeholder="e.g. A national-scale project aiming to build one of the world's largest VLA models.",
                        height=80,
                        key=f"job_overview_{i}"
                    )
                    key_focus = st.text_input(
                        "Key Focus（任意）",
                        placeholder='e.g. They are specifically looking for expertise in "real-world implementation."',
                        key=f"job_keyfocus_{i}"
                    )
                    jd_note = st.text_input(
                        "JD備考（任意）",
                        placeholder="e.g. Please refer to the attached file.",
                        key=f"job_jdnote_{i}"
                    )
                    fit_comment = st.text_area(
                        "おすすめコメント（任意）",
                        placeholder="e.g. Given your expertise in AI and computer vision, I believe this would be an excellent match.",
                        height=68,
                        key=f"job_fit_{i}"
                    )

                    # 💾 この求人を保存ボタン
                    if job_title or company_name:
                        if st.button("💾 この求人を保存", key=f"save_job_{i}", use_container_width=True):
                            new_job = {
                                'id': datetime.now().strftime('%Y%m%d%H%M%S%f'),
                                'title': job_title,
                                'company': company_name,
                                'website': website,
                                'overview': overview,
                                'key_focus': key_focus,
                                'jd_note': jd_note,
                                'fit_comment': fit_comment,
                                'saved_at': datetime.now().isoformat()
                            }
                            # 同じ企業+ポジション名の重複チェック
                            existing = [
                                sj for sj in st.session_state['saved_jobs']
                                if sj['title'] == job_title and sj['company'] == company_name
                            ]
                            if existing:
                                # 既存エントリを更新
                                for sj in st.session_state['saved_jobs']:
                                    if sj['title'] == job_title and sj['company'] == company_name:
                                        sj.update(new_job)
                                        break
                                st.toast(f"✅ 「{company_name} - {job_title}」を更新しました")
                            else:
                                st.session_state['saved_jobs'].append(new_job)
                                st.toast(f"✅ 「{company_name} - {job_title}」を保存しました")
                            sync_saved_jobs_to_localstorage()

                    jobs.append({
                        "title": job_title,
                        "company": company_name,
                        "website": website,
                        "overview": overview,
                        "key_focus": key_focus,
                        "jd_note": jd_note,
                        "fit_comment": fit_comment,
                    })

            st.divider()

            # --- セットとして保存 ---
            has_any_job = any(j["title"] or j["company"] for j in jobs)
            if has_any_job:
                with st.expander("💾 現在の求人をセットとして保存"):
                    set_name = st.text_input(
                        "セット名",
                        placeholder="e.g. Robotics系3社セット",
                        key="save_set_name"
                    )
                    if st.button("💾 セットを保存", key="save_set_btn", use_container_width=True, disabled=not set_name):
                        # 入力されている求人のみ保存
                        valid_jobs = [j for j in jobs if j["title"] or j["company"]]
                        new_set = {
                            'id': datetime.now().strftime('%Y%m%d%H%M%S%f'),
                            'name': set_name,
                            'jobs': valid_jobs,
                            'saved_at': datetime.now().isoformat()
                        }
                        # 同名セットの重複チェック
                        existing_idx = next(
                            (i for i, s in enumerate(st.session_state['saved_job_sets']) if s['name'] == set_name),
                            None
                        )
                        if existing_idx is not None:
                            st.session_state['saved_job_sets'][existing_idx] = new_set
                            st.toast(f"✅ セット「{set_name}」を更新しました（{len(valid_jobs)}件）")
                        else:
                            st.session_state['saved_job_sets'].append(new_set)
                            st.toast(f"✅ セット「{set_name}」を保存しました（{len(valid_jobs)}件）")
                        sync_saved_job_sets_to_localstorage()

            # --- メール生成 ---
            generate_btn = st.button(
                t("email_generate_btn"),
                type="primary",
                use_container_width=True,
                disabled=not candidate_name,
                key="generate_email_btn"
            )

            if generate_btn and candidate_name:
                email_text = _build_email_text(candidate_name, sender_name, jobs, email_lang)
                st.session_state['generated_email'] = email_text

            # --- 結果表示 ---
            if 'generated_email' in st.session_state:
                st.divider()
                st.markdown(t("email_output"))

                col_copy_e, col_dl_e = st.columns(2)
                with col_copy_e:
                    if st.button("📋 コピー", key="copy_email_btn", use_container_width=True):
                        st.toast("✅ クリップボードにコピーしました")
                        _copy_to_clipboard(st.session_state['generated_email'])
                with col_dl_e:
                    st.download_button(
                        "📄 テキストファイルDL",
                        data=st.session_state['generated_email'],
                        file_name=f"job_email_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                        mime="text/plain",
                        use_container_width=True,
                        key="dl_email_btn"
                    )

                st.code(st.session_state['generated_email'], language=None)

            # --- 保存済みデータの管理 ---
            has_saved_sets = bool(st.session_state.get('saved_job_sets'))
            has_saved_jobs = bool(st.session_state.get('saved_jobs'))

            if has_saved_sets or has_saved_jobs:
                st.divider()
                manage_tab_sets, manage_tab_jobs = st.tabs(["📦 セット管理", "📄 個別求人管理"])

                with manage_tab_sets:
                    if has_saved_sets:
                        for ss_idx, ss in enumerate(st.session_state['saved_job_sets']):
                            saved_date = ""
                            if ss.get('saved_at'):
                                try:
                                    dt = datetime.fromisoformat(ss['saved_at'])
                                    saved_date = dt.strftime('%Y/%m/%d')
                                except Exception:
                                    pass
                            col_info, col_del = st.columns([4, 1])
                            with col_info:
                                job_names = ", ".join([j.get('company', '?') for j in ss.get('jobs', [])])
                                st.markdown(f"**{ss.get('name', '')}**（{len(ss.get('jobs', []))}件）  \n"
                                            f"{job_names}　📅 {saved_date}")
                            with col_del:
                                if st.button("🗑️", key=f"del_saved_set_{ss_idx}", help="このセットを削除"):
                                    st.session_state['saved_job_sets'].pop(ss_idx)
                                    sync_saved_job_sets_to_localstorage()
                                    st.rerun()

                        if st.button("🗑️ すべてのセットを削除", key="clear_all_saved_sets"):
                            st.session_state['saved_job_sets'] = []
                            sync_saved_job_sets_to_localstorage()
                            st.rerun()
                    else:
                        st.caption("保存済みセットはありません")

                with manage_tab_jobs:
                    if has_saved_jobs:
                        for sj_idx, sj in enumerate(st.session_state['saved_jobs']):
                            saved_date = ""
                            if sj.get('saved_at'):
                                try:
                                    dt = datetime.fromisoformat(sj['saved_at'])
                                    saved_date = dt.strftime('%Y/%m/%d')
                                except Exception:
                                    pass
                            col_info, col_del = st.columns([4, 1])
                            with col_info:
                                st.markdown(f"**{sj.get('company', '')} - {sj.get('title', '')}**  \n"
                                            f"🔗 {sj.get('website', '-')}　📅 {saved_date}")
                            with col_del:
                                if st.button("🗑️", key=f"del_saved_job_{sj_idx}", help="この求人を削除"):
                                    st.session_state['saved_jobs'].pop(sj_idx)
                                    sync_saved_jobs_to_localstorage()
                                    st.rerun()

                        if st.button("🗑️ すべての個別求人を削除", key="clear_all_saved_jobs"):
                            st.session_state['saved_jobs'] = []
                            sync_saved_jobs_to_localstorage()
                            st.rerun()
                    else:
                        st.caption("保存済みの個別求人はありません")

    elif feature == "batch":
        st.subheader(t("batch_title"))
        st.caption(t("batch_desc"))

        # 区切り文字の説明
        st.info("💡 **区切り方法**: `---NEXT---` を各レジュメの間に入れてください")

        batch_input = st.text_area(
            "複数の英語レジュメを貼り付け",
            height=400,
            placeholder="""John Doe
Software Engineer with 5+ years experience...
[レジュメ1の内容]

---NEXT---

Jane Smith
Full-stack Developer...
[レジュメ2の内容]

---NEXT---

[さらにレジュメを追加...]""",
            label_visibility="collapsed"
        )

        col_opt1, col_opt2 = st.columns(2)
        with col_opt1:
            batch_anonymize = st.radio(
                "🔒 匿名化レベル",
                options=["full", "light", "none"],
                format_func=lambda x: {
                    "full": "完全匿名化",
                    "light": "軽度匿名化",
                    "none": "なし"
                }[x],
                index=0,
                key="batch_anon"
            )

        with col_opt2:
            if batch_input:
                resumes = [r.strip() for r in batch_input.split("---NEXT---") if r.strip()]
                st.metric("検出されたレジュメ数", len(resumes))
            else:
                st.metric("検出されたレジュメ数", 0)

        _show_btn_hint(api_key, bool(batch_input))
        batch_btn = st.button(
            t("batch_btn"),
            type="primary",
            use_container_width=True,
            disabled=not api_key or not batch_input
        )

        if batch_btn and batch_input:
            resumes = [r.strip() for r in batch_input.split("---NEXT---") if r.strip()]

            if len(resumes) == 0:
                st.warning("⚠️ レジュメが検出されませんでした")
            elif len(resumes) > 10:
                st.error("❌ 一度に処理できるのは最大10件までです")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()

                batch_start_time = time.time()

                def _process_single_batch_resume(index, resume_text):
                    result = {"index": index, "status": "pending", "output": None, "error": None, "time": 0}
                    is_valid, error_msg = validate_input(resume_text, "resume")
                    if not is_valid:
                        result["status"] = "error"
                        result["error"] = error_msg
                    else:
                        try:
                            item_start = time.time()
                            prompt = get_resume_optimization_prompt(resume_text, batch_anonymize)
                            output = call_groq_api(api_key, prompt)
                            result["status"] = "success"
                            result["output"] = finalize_resume_output(output)
                            result["time"] = time.time() - item_start
                        except Exception as e:
                            result["status"] = "error"
                            result["error"] = str(e)
                    return result

                results = [None] * len(resumes)
                max_workers = min(3, len(resumes))
                completed_count = 0

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(_process_single_batch_resume, i + 1, resume): i
                        for i, resume in enumerate(resumes)
                    }
                    for future in as_completed(futures):
                        idx = futures[future]
                        results[idx] = future.result()
                        completed_count += 1
                        status_text.text(f"🔄 処理中... ({completed_count}/{len(resumes)})")
                        progress_bar.progress(completed_count / len(resumes))

                batch_elapsed = time.time() - batch_start_time
                st.session_state['batch_results'] = results
                st.session_state['batch_time'] = batch_elapsed
                status_text.text(f"✅ 処理完了！（合計 {batch_elapsed:.1f}秒）")

        # バッチ結果表示
        if 'batch_results' in st.session_state:
            st.divider()
            st.subheader("📊 処理結果")

            success_count = sum(1 for r in st.session_state['batch_results'] if r['status'] == 'success')
            error_count = sum(1 for r in st.session_state['batch_results'] if r['status'] == 'error')

            col_m1, col_m2 = st.columns(2)
            with col_m1:
                st.metric("✅ 成功", success_count)
            with col_m2:
                st.metric("❌ エラー", error_count)

            # 個別結果
            for result in st.session_state['batch_results']:
                time_str = f"（{result['time']:.1f}秒）" if result['time'] > 0 else ""
                with st.expander(f"レジュメ #{result['index']} - {'✅ 成功' + time_str if result['status'] == 'success' else '❌ エラー'}"):
                    if result['status'] == 'success':
                        # 表示切替とコピーボタン
                        col_view, col_copy = st.columns([2, 1])
                        with col_view:
                            show_formatted = st.checkbox("📖 整形表示", value=False, key=f"batch_fmt_{result['index']}")
                        with col_copy:
                            if st.button("📋 コピー", key=f"copy_batch_{result['index']}", use_container_width=True):
                                st.toast("✅ クリップボードにコピーしました")
                                _copy_to_clipboard(result['output'])

                        if show_formatted:
                            st.markdown(result['output'])
                        else:
                            st.code(result['output'], language="markdown")

                        # ファーストネームをファイル名に使用
                        _batch_first = extract_first_name(result['output'])
                        _batch_label = f"候補者 #{result['index']} - {_batch_first}" if _batch_first else f"候補者 #{result['index']}"
                        _batch_fname = f"resume_{_batch_first}_{datetime.now().strftime('%Y%m%d')}" if _batch_first else f"resume_{result['index']}_{datetime.now().strftime('%Y%m%d')}"

                        # ダウンロードボタン
                        col_b1, col_b2 = st.columns(2)
                        with col_b1:
                            st.download_button(
                                "📄 Markdown",
                                data=result['output'],
                                file_name=f"{_batch_fname}.md",
                                mime="text/markdown",
                                key=f"batch_md_{result['index']}"
                            )
                        with col_b2:
                            html_content = generate_html(result['output'], _batch_label)
                            st.download_button(
                                "🌐 HTML",
                                data=html_content,
                                file_name=f"{_batch_fname}.html",
                                mime="text/html",
                                key=f"batch_html_{result['index']}"
                            )
                    else:
                        st.error(f"エラー: {result['error']}")

            # 全件ダウンロード
            if success_count > 0:
                st.divider()
                all_content = "\n\n---\n\n".join([
                    f"# レジュメ #{r['index']}\n\n{r['output']}"
                    for r in st.session_state['batch_results']
                    if r['status'] == 'success'
                ])
                st.download_button(
                    "📦 全件ダウンロード（Markdown）",
                    data=all_content,
                    file_name=f"batch_resumes_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                    mime="text/markdown",
                    use_container_width=True
                )

    # フッター
    st.divider()
    st.caption(t("footer"))


if __name__ == "__main__":
    main()
