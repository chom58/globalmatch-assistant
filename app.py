"""
GlobalMatch Assistant - 人材紹介業務効率化アプリ

外国人エンジニアのレジュメと日本企業の求人票を相互変換・最適化するStreamlitアプリ
"""

import streamlit as st
import streamlit.components.v1
from groq import Groq
import time
import re
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
RATE_LIMIT_WINDOW = 3600 # レート制限ウィンドウ（秒）
SESSION_TIMEOUT_MINUTES = 120  # セッションタイムアウト（分）


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


def extract_text_from_url(url: str) -> tuple[str, str]:
    """URLからWebページのテキストを抽出

    Returns:
        tuple: (extracted_text, error_message)
    """
    # SSRF対策: URL安全性チェック
    is_safe, safety_msg = _is_safe_url(url)
    if not is_safe:
        return "", safety_msg

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")

        # PDFの場合
        if "application/pdf" in content_type:
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
  "overview": "A concise 1-3 sentence summary of the company/role in English, suitable for an outreach email (max 300 chars)",
  "key_focus": "What the company is specifically looking for — key skills, experience, or focus areas in 1 sentence (in English, max 200 chars)"
}}

Important:
- All values must be in English
- Keep overview concise and appealing — this goes directly into an email to candidates
- For key_focus, highlight what makes this role unique or what specific expertise is sought
- Do not fabricate information not present in the source text
- Output valid JSON only — no extra text before or after"""


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
    """共有リンクを作成

    Args:
        content: 共有するコンテンツ（Markdown形式）
        title: タイトル

    Returns:
        share_id: 共有ID（32文字）、失敗時はNone
    """
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

    # ダウンロードボタン
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "📄 Markdownでダウンロード",
            content,
            f"resume_{share_id[:8]}.md",
            "text/markdown"
        )
    with col2:
        html_content = generate_html(content, title)
        st.download_button(
            "🌐 HTMLでダウンロード",
            html_content,
            f"resume_{share_id[:8]}.html",
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

# カスタムCSS - プロフェッショナルデザイン
st.markdown("""
<style>
    /* フォント */
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;600;700&display=swap');

    /* 全体設定 */
    .stApp {
        background-color: #f5f7fa;
    }

    .main .block-container {
        background: #ffffff;
        padding: 2rem 2.5rem !important;
        max-width: 1200px;
    }

    /* サイドバー */
    [data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid #e5e7eb;
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        color: #374151;
    }

    /* ヘッダー */
    h1 {
        color: #1e3a5f;
        font-family: 'Noto Sans JP', sans-serif;
        font-weight: 700;
        font-size: 1.8rem;
        border-bottom: 3px solid #1e3a5f;
        padding-bottom: 0.5rem;
        margin-bottom: 1rem;
    }

    h2 {
        color: #1e3a5f;
        font-family: 'Noto Sans JP', sans-serif;
        font-weight: 600;
        font-size: 1.2rem;
        margin-top: 1.5rem;
    }

    h3 {
        color: #374151;
        font-family: 'Noto Sans JP', sans-serif;
        font-weight: 600;
        font-size: 1rem;
    }

    /* テキストエリア */
    .stTextArea textarea {
        font-family: 'Noto Sans JP', sans-serif;
        font-size: 14px;
        line-height: 1.6;
        border: 1px solid #d1d5db;
        border-radius: 8px;
        background: #fafbfc;
    }

    .stTextArea textarea:focus {
        border-color: #1e3a5f;
        box-shadow: 0 0 0 2px rgba(30, 58, 95, 0.1);
    }

    /* メインボタン */
    .stButton > button {
        background: #1e3a5f;
        color: white;
        border: none;
        border-radius: 6px;
        padding: 0.6rem 1.5rem;
        font-weight: 600;
        font-family: 'Noto Sans JP', sans-serif;
        font-size: 14px;
        transition: background 0.2s ease;
    }

    .stButton > button:hover {
        background: #2d4a6f;
    }

    .stButton > button:disabled {
        background: #9ca3af;
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
        border: 1px solid #e5e7eb;
    }

    .stCodeBlock code {
        font-size: 13px;
        line-height: 1.5;
    }

    /* 成功メッセージ */
    .stSuccess {
        background: #ecfdf5;
        color: #065f46;
        border: 1px solid #a7f3d0;
        border-radius: 6px;
    }

    /* 情報メッセージ */
    .stInfo {
        background: #eff6ff;
        color: #1e40af;
        border: 1px solid #bfdbfe;
        border-radius: 6px;
    }

    /* 警告メッセージ */
    .stWarning {
        background: #fffbeb;
        color: #92400e;
        border: 1px solid #fde68a;
        border-radius: 6px;
    }

    /* エラーメッセージ */
    .stError {
        background: #fef2f2;
        color: #991b1b;
        border: 1px solid #fecaca;
        border-radius: 6px;
    }

    /* ラジオボタン */
    .stRadio > div {
        background: #fafbfc;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 0.75rem 1rem;
    }

    .stRadio label {
        font-size: 14px;
        color: #374151;
    }

    /* メトリクス */
    [data-testid="stMetricValue"] {
        font-size: 1.5rem;
        font-weight: 700;
        color: #1e3a5f;
    }

    [data-testid="stMetricLabel"] {
        color: #6b7280;
    }

    /* プログレスバー */
    .stProgress > div > div {
        background: #1e3a5f;
        border-radius: 4px;
    }

    /* 区切り線 */
    hr {
        border: none;
        border-top: 1px solid #e5e7eb;
        margin: 1.5rem 0;
    }

    /* エクスパンダー */
    .streamlit-expanderHeader {
        background: #fafbfc;
        border: 1px solid #e5e7eb;
        border-radius: 6px;
        font-weight: 500;
        font-size: 14px;
    }

    /* キャプション */
    .stCaption {
        color: #6b7280;
        font-size: 13px;
    }

    /* テキスト入力 */
    .stTextInput input {
        border: 1px solid #d1d5db;
        border-radius: 6px;
        font-size: 14px;
    }

    .stTextInput input:focus {
        border-color: #1e3a5f;
        box-shadow: 0 0 0 2px rgba(30, 58, 95, 0.1);
    }

    /* セレクトボックス */
    .stSelectbox > div > div {
        border-radius: 6px;
    }

    /* 全体のテキスト */
    .stMarkdown {
        font-family: 'Noto Sans JP', sans-serif;
        color: #374151;
        line-height: 1.6;
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
    }
</style>
""", unsafe_allow_html=True)


def get_resume_optimization_prompt(resume_text: str, anonymize: str) -> str:
    """レジュメ最適化用のプロンプトを生成"""

    if anonymize == "full":
        anonymize_instruction = """
【完全匿名化処理 - 必須】
以下の情報を必ず匿名化してください：

■ 個人情報 → イニシャル表記
- 氏名 → イニシャルに変換（例：田中太郎 → T.T.、John Smith → J.S.）
- メールアドレス → 記載しない
- 電話番号 → 記載しない
- 住所 → 都道府県名のみ（例：「東京都」）
- LinkedIn、GitHub、Portfolio、SNSのURL → 記載しない

■ 企業情報 → 業界・規模で表現
- 具体的な企業名 → 業界+規模に変換（例：「Google」→「米国大手テック企業」「楽天」→「国内大手IT企業」）
- スタートアップ → 「〇〇領域スタートアップ」
- 受託/SIer → 「大手SIer」「中堅SI企業」など
- 外資系 → 「外資系〇〇企業」

■ プロジェクト情報 → 汎用化
- 具体的なプロダクト名 → 「大規模ECサイト」「FinTechアプリ」など汎用表現に
- クライアント名 → 「大手小売業クライアント」など業界で表現
- 特定可能なプロジェクトコード → 削除

■ その他
- 大学名 → 「国内有名私立大学」「海外工科大学」など
- 資格の発行番号 → 削除（資格名は残す）
"""
    elif anonymize == "light":
        anonymize_instruction = """
【軽度匿名化処理 - 必須】
以下の個人情報のみ匿名化してください（企業名は残す）：

- 氏名 → イニシャルに変換（例：田中太郎 → T.T.、John Smith → J.S.）
- メールアドレス → 記載しない
- 電話番号 → 記載しない
- 詳細住所 → 都道府県名まで残す
- LinkedIn、GitHub、SNSのURL → 記載しない

※ 企業名、大学名、プロジェクト名はそのまま残してください。
"""
    else:
        anonymize_instruction = "【匿名化処理】不要です。すべての情報をそのまま残してください。"

    # 基本情報フォーマットの準備
    if anonymize in ["full", "light"]:
        basic_info_format = "- 氏名：（イニシャルで表記。例：T.Y.）\n- 連絡先：[非公開]\n- 所在地：（都道府県のみ）"
    else:
        basic_info_format = "- 氏名：\n- 連絡先：\n- 所在地："

    return f"""あなたは人材紹介会社のエキスパートコンサルタントです。
外国人エンジニアの英語レジュメを、日本企業の採用担当者向けに最適化された日本語ドキュメントに変換してください。

{anonymize_instruction}

【出力フォーマット - 厳守】
以下の「日本企業向け標準フォーマット」に必ず従って出力してください。
元のレジュメのフォーマットに関わらず、この構造で統一してください。

---

## 1. 基本情報
{basic_info_format}

## 2. 推薦サマリ
*（300文字程度で、この候補者の経歴の要約と強みを記載。採用担当者が最初に読む部分として魅力的に）*

## 3. 技術スタック・習熟度
| カテゴリ | スキル | 経験年数 | 習熟度 |
|---------|--------|----------|--------|
| プログラミング言語 | | | |
| フレームワーク | | | |
| データベース | | | |
| インフラ/クラウド | | | |
| ツール/その他 | | | |

*習熟度: Expert（専門家レベル）/ Advanced（上級）/ Intermediate（中級）/ Beginner（初級）*

## 4. 語学・ビザ
- **日本語レベル**: （JLPTレベル、日本滞在歴、実務での使用経験から推定）
- **英語レベル**:
- **ビザステータス**: （記載があれば、なければ「要確認」）

## 5. リーダーシップ・ソフトスキル
*（該当する経験がある場合のみ記載）*
- メンタリング・チーム管理経験
- クロスファンクショナルチームでの協業
- 技術プレゼンテーション・登壇
- 採用面接への参加

## 6. 職務経歴
*（新しい順に記載）*

### 【会社名】（期間：YYYY年MM月 〜 YYYY年MM月）
**役職/ポジション**

**プロジェクト概要:**
- プロダクト/サービスの種類・規模（例：月間100万ユーザーのECプラットフォーム）

**担当業務・成果:**
- （具体的な成果を数値付きで記載：ユーザー数増加、パフォーマンス改善率、コスト削減額など）
- （チーム規模、技術的チャレンジ、ビジネスインパクトを含める）

## 7. オープンソース・副業プロジェクト
*（該当する活動がある場合のみ記載）*
- OSS貢献（プロジェクト名、貢献内容、影響度）
- 個人プロジェクト（概要、技術スタック、ユーザー数など）
- 技術コミュニティ活動（登壇、記事執筆、コミュニティ運営など）

## 8. 受賞歴・表彰
*（該当する実績がある場合のみ記載）*
- 社内表彰、ハッカソン受賞、競技プログラミング、特許など

## 9. 継続的学習
*（最近の学習活動がある場合のみ記載）*
- 最近取得した資格・修了したコース
- カンファレンス参加・登壇
- 技術ブログ・記事執筆

---

【入力レジュメ】
{resume_text}

---

【重要な抽出指示】
上記のレジュメを解析し、指定フォーマットで日本語に変換してください。
以下の点に特に注意してください：

1. **成果には必ず数値を含める**: ユーザー数、パフォーマンス改善率、コスト削減額、チーム規模など
2. **技術スキルには経験年数と習熟度を併記**: 可能な限り推定して記載
3. **リーダーシップ経験を見逃さない**: メンター、チームリード、採用関与など
4. **プロジェクトの規模感を記載**: ユーザー数、売上、予算、チーム規模など
5. **OSS貢献・副業があれば必ず記載**: GitHub、個人プロジェクト、登壇、記事執筆など
6. **受賞歴・表彰があれば記載**: 社内賞、ハッカソン、競技プログラミングなど
7. **最近の学習活動を記載**: 資格取得、コース修了、カンファレンス参加など

**重要**: レジュメに情報が全くない場合のみ「記載なし」とし、少しでも関連する記述があれば必ず抽出して記載してください。
**重要**: 該当するセクション（OSS、受賞歴など）に情報がない場合は、そのセクション自体を省略してください。
"""


def get_english_anonymization_prompt(resume_text: str, anonymize: str) -> str:
    """英文レジュメを英文のまま匿名化するプロンプトを生成"""

    if anonymize == "full":
        anonymize_instruction = """
【FULL ANONYMIZATION - REQUIRED】
You MUST anonymize the following information:

■ Personal Information → Use Initials
- Full name → Convert to initials (e.g., John Smith → J.S., Maria Garcia → M.G.)
- Email address → Do not include
- Phone number → Do not include
- Address → State/Country only (e.g., "California, USA" or "Tokyo, Japan")
- LinkedIn, GitHub, Portfolio, Social media URLs → Do not include

■ Company Information → Use Industry/Size Description
- Specific company names → Convert to industry + size (e.g., "Google" → "Major US Tech Company", "Toyota" → "Leading Japanese Automotive Corporation")
- Startups → "[Industry] Startup" (e.g., "FinTech Startup", "AI/ML Startup")
- Consulting firms → "Global Consulting Firm", "Big 4 Consulting"
- Specific product names → Generic descriptions (e.g., "Gmail" → "Large-scale Email Platform")

■ Project Information → Generalize
- Specific product names → "Large-scale E-commerce Platform", "Mobile Banking App", etc.
- Client names → "Major Retail Client", "Fortune 500 Financial Services Company", etc.
- Project codes or internal names → Remove

■ Education
- University names → "Top US University", "Prestigious Engineering School", "Ivy League University", etc.
- Certification IDs/numbers → Remove (keep certification names)
"""
    elif anonymize == "light":
        anonymize_instruction = """
【LIGHT ANONYMIZATION - REQUIRED】
Only anonymize personal contact information (keep company names):

- Full name → Convert to initials (e.g., John Smith → J.S.)
- Email address → Do not include
- Phone number → Do not include
- Detailed address → Keep only city/state level
- LinkedIn, GitHub, Social media URLs → Do not include

※ Keep company names, university names, and project names as-is.
"""
    else:
        anonymize_instruction = "【NO ANONYMIZATION】Keep all information as-is."

    # 基本情報フォーマットの準備
    if anonymize in ["full", "light"]:
        basic_info_format_en = "- Name: (Initials only, e.g., J.S.)\n- Contact: [Confidential]\n- Location: (State/Country only)"
    else:
        basic_info_format_en = "- Name:\n- Contact:\n- Location:"

    return f"""You are an expert HR consultant.
Anonymize the following English resume while keeping it in English and maintaining a professional format.

{anonymize_instruction}

【OUTPUT FORMAT - STRICTLY FOLLOW】
Maintain the resume in English with this standardized structure:

---

## 1. Basic Information
{basic_info_format_en}

## 2. Professional Summary
*(2-3 sentences highlighting key qualifications and strengths)*

## 3. Technical Skills & Proficiency
| Category | Skills | Years of Experience | Proficiency Level |
|----------|--------|---------------------|-------------------|
| Programming Languages | | | |
| Frameworks & Libraries | | | |
| Databases | | | |
| Cloud & Infrastructure | | | |
| Tools & Others | | | |

*Proficiency Levels: Expert / Advanced / Intermediate / Beginner*

## 4. Leadership & Soft Skills
*(Include only if applicable)*
- Mentoring & team management experience
- Cross-functional collaboration
- Technical presentations & speaking
- Interview participation

## 5. Work Experience
*(Most recent first)*

### [Company Description] (Period: MMM YYYY – MMM YYYY)
**Position/Role**

**Project Context:**
- Product/service type and scale (e.g., E-commerce platform with 1M+ monthly users)

**Key Responsibilities & Achievements:**
- (Specific achievements with metrics: user growth, performance improvements, cost savings, etc.)
- (Team size, technical challenges, business impact)

## 6. Open Source & Side Projects
*(Include only if applicable)*
- OSS contributions (project name, contribution type, impact metrics)
- Personal projects (overview, tech stack, user metrics)
- Technical community involvement (speaking, writing, organizing)

## 7. Awards & Recognition
*(Include only if applicable)*
- Company awards, hackathon wins, competitive programming, patents, etc.

## 8. Continuous Learning
*(Include only if applicable)*
- Recent certifications or completed courses
- Conference attendance or speaking
- Technical blog posts or articles

## 9. Education
- **Degree** - [University Description], Year

## 10. Certifications
- Certification names (without ID numbers)

---

【INPUT RESUME】
{resume_text}

---

【IMPORTANT EXTRACTION INSTRUCTIONS】
Parse the above resume and output in the specified format in English.
Pay special attention to the following:

1. **Always include metrics in achievements**: User numbers, performance improvement %, cost savings, team size, etc.
2. **Specify experience years and proficiency for technical skills**: Estimate if necessary
3. **Don't miss leadership experience**: Mentoring, team lead, hiring involvement, etc.
4. **Include project scale information**: User count, revenue, budget, team size, etc.
5. **Extract OSS contributions & side projects**: GitHub, personal projects, speaking, writing, etc.
6. **Include awards & recognition**: Company awards, hackathons, competitive programming, etc.
7. **Capture recent learning activities**: Certifications, courses, conference attendance, etc.

**IMPORTANT**: Only use "Not specified" when there is absolutely NO related information in the resume. If there's any relevant mention, extract and include it.
**IMPORTANT**: Omit entire sections (OSS, Awards, etc.) if there's no information, rather than listing them as empty.
"""


def get_jd_transformation_prompt(jd_text: str) -> str:
    """求人票変換用のプロンプトを生成（日本語→英語）"""

    return f"""あなたは外国人エンジニア採用に精通したリクルーターです。
日本企業の求人票（JD）を、海外のエンジニアにとって魅力的な英語の求人票に変換してください。

【変換のポイント】
1. **構成の再構築**: 外国人エンジニアが重視する項目を冒頭に配置
2. **トーンの調整**: 堅苦しい日本語表現を避け、魅力的で親しみやすい英語に
3. **重要情報の明確化**: ビザ、リモートワーク、言語サポートを明示

【出力フォーマット】
以下の構造で出力してください：

---

# [Position Title] at [Company Name]

## Quick Facts
| | |
|---|---|
| **Visa Sponsorship** | Available (supported for qualified candidates) |
| **Remote Work** | (Full Remote/Hybrid/On-site - specify policy) |
| **Language Requirements** | (English OK/Japanese N2+/Bilingual environment) |
| **Salary Range** | (If available, convert to USD range as reference) |
| **Location** | |

## Why Join Us?
(2-3 compelling sentences about the company culture, growth opportunity, or unique value proposition)

## What You'll Do
(Key responsibilities in bullet points - focus on impact, not just tasks)

## What We're Looking For
**Must-have:**
・

**Nice-to-have:**
・

## Benefits & Perks
(Highlight benefits that appeal to international candidates)

## About the Company
(Brief company introduction)

## How to Apply
**※このセクションは以下の固定文言を必ず使用してください（元の求人票の連絡先は無視）：**

Interested in this position? Value Create will recommend you directly to the company's hiring team.
Please reach out to one of our team members to express your interest:
・**Ilya**
・**Hiroshi**
・**Shu**
We'll take care of the introduction and guide you through the process!

---

【元の求人票】
{jd_text}

上記を解析し、外国人エンジニアに魅力的な英語JDに変換してください。
不明な項目は「To be discussed」または「Contact for details」としてください。
**重要**: Visa Sponsorshipは、元の求人票に記載がなくても「Available (supported for qualified candidates)」と記載してください。Value Createが扱う求人は全てビザサポート対応企業です。
**重要**: 「How to Apply」セクションは、元の求人票に記載されている連絡先やメールアドレスを無視し、上記フォーマットの固定文言（Value Createチームへの連絡）を必ず使用してください。
**重要**: リスト項目の行頭記号は中黒（・）を使用し、各項目の文頭は大文字で始めてください。アスタリスク（*）は使用しないでください。
**重要**: 見出しに絵文字は使用しないでください。シンプルなテキストのみで出力してください。
"""


def get_jd_en_to_jp_prompt(jd_text: str) -> str:
    """求人票変換用のプロンプトを生成（英語→日本語）"""

    return f"""あなたは人材紹介のエキスパートコンサルタントです。
海外企業や外資系企業の英語求人票（Job Description）を、日本人エンジニアにとって分かりやすく魅力的な日本語の求人票に変換してください。

【変換のポイント】
1. **情報の整理**: 日本の求人票フォーマットに合わせて構造化
2. **トーンの調整**: 自然な日本語表現で、親しみやすく魅力的に
3. **重要情報の明確化**: 勤務条件、待遇、技術スタックを分かりやすく

【出力フォーマット】
以下の構造で出力してください：

---

# [会社名] - [職種名]

## 概要
| 項目 | 内容 |
|------|------|
| **勤務形態** | （フルリモート/ハイブリッド/出社） |
| **勤務地** | |
| **雇用形態** | （正社員/契約社員など） |
| **想定年収** | （円換算の目安も併記） |
| **英語力** | （必須/あれば尚可/不要） |

## 会社について
（会社の事業内容、規模、特徴を2-3文で）

## 仕事内容
（具体的な業務内容を箇条書きで）
・
・

## 必須スキル・経験
・
・

## 歓迎スキル・経験
・
・

## 技術スタック
| カテゴリ | 技術 |
|---------|------|
| 言語 | |
| フレームワーク | |
| インフラ | |
| ツール | |

## 福利厚生・働き方
・
・

## 選考プロセス
（記載があれば）

## 応募方法
**※このセクションは以下の固定文言を必ず使用してください（元の求人票の連絡先は無視）：**

この求人に興味がある方は、Value Createが直接企業へ推薦いたします。
以下のチームメンバーまでお気軽にご連絡ください：
・**Ilya（イリヤ）**
・**Hiroshi（ヒロシ）**
・**Shu（シュウ）**
面談調整から選考サポートまで、一貫してお手伝いいたします！

---

【元の求人票（英語）】
{jd_text}

上記を解析し、日本人エンジニアに分かりやすい日本語求人票に変換してください。
不明な項目は「要確認」または「詳細はお問い合わせください」としてください。
**重要**: 給与がUSDなどの外貨の場合は、参考として日本円換算も併記してください（1USD≒150円目安）。
**重要**: 「応募方法」セクションは、元の求人票に記載されている連絡先やメールアドレスを無視し、上記フォーマットの固定文言（Value Createチームへの連絡）を必ず使用してください。
**重要**: リスト項目の行頭記号は中黒（・）を使用してください。アスタリスク（*）は使用しないでください。
**重要**: 見出しに絵文字は使用しないでください。シンプルなテキストのみで出力してください。
"""


def get_jd_jp_to_jp_prompt(jd_text: str) -> str:
    """求人票フォーマット化用のプロンプトを生成（日本語→日本語）"""

    return f"""あなたは人材紹介のエキスパートコンサルタントです。
日本語の求人票を、統一された見やすいフォーマットの魅力的な日本語求人票に変換してください。

【変換のポイント】
1. **フォーマットの統一**: 読みやすく整理された構造に再構成
2. **情報の明確化**: 勤務条件、待遇、技術スタックを分かりやすく整理
3. **魅力的な表現**: エンジニアが興味を持つポイントを強調

【出力フォーマット】
以下の構造で出力してください：

---

# [会社名] - [職種名]

## 概要
| 項目 | 内容 |
|------|------|
| **勤務形態** | （フルリモート/ハイブリッド/出社） |
| **勤務地** | |
| **雇用形態** | （正社員/契約社員など） |
| **想定年収** | |
| **英語力** | （必須/あれば尚可/不要） |

## 会社について
（会社の事業内容、規模、特徴を2-3文で）

## 仕事内容
（具体的な業務内容を箇条書きで）
・
・

## 必須スキル・経験
・
・

## 歓迎スキル・経験
・
・

## 技術スタック
| カテゴリ | 技術 |
|---------|------|
| 言語 | |
| フレームワーク | |
| インフラ | |
| ツール | |

## 福利厚生・働き方
・
・

## 選考プロセス
（記載があれば）

## 応募方法
**※このセクションは以下の固定文言を必ず使用してください（元の求人票の連絡先は無視）：**

この求人に興味がある方は、Value Createが直接企業へ推薦いたします。
以下のチームメンバーまでお気軽にご連絡ください：
・**Ilya（イリヤ）**
・**Hiroshi（ヒロシ）**
・**Shu（シュウ）**
面談調整から選考サポートまで、一貫してお手伝いいたします！

---

【元の求人票（日本語）】
{jd_text}

上記を解析し、統一されたフォーマットの魅力的な日本語求人票に変換してください。
不明な項目は「要確認」または「詳細はお問い合わせください」としてください。
**重要**: 「応募方法」セクションは、元の求人票に記載されている連絡先やメールアドレスを無視し、上記フォーマットの固定文言（Value Createチームへの連絡）を必ず使用してください。
**重要**: リスト項目の行頭記号は中黒（・）を使用してください。アスタリスク（*）は使用しないでください。
**重要**: 見出しに絵文字は使用しないでください。シンプルなテキストのみで出力してください。
"""


def get_jd_en_to_en_prompt(jd_text: str) -> str:
    """求人票フォーマット化用のプロンプトを生成（英語→英語）"""

    return f"""You are an expert recruiter specializing in international engineer recruitment.
Transform the provided English job description into an attractive, well-structured English JD that appeals to international engineers.

【Key Transformation Points】
1. **Restructure the format**: Place information that international engineers prioritize at the top
2. **Enhance readability**: Use clear, engaging language with consistent formatting
3. **Clarify key information**: Explicitly state visa support, remote work policy, and language requirements
4. **Highlight appeal**: Emphasize growth opportunities, tech stack, and company culture

【Output Format】
Please output in the following structure:

---

# [Position Title] at [Company Name]

## Quick Facts
| | |
|---|---|
| **Visa Sponsorship** | Available (supported for qualified candidates) |
| **Remote Work** | (Full Remote/Hybrid/On-site - specify policy) |
| **Language Requirements** | (English OK/Japanese N2+/Bilingual environment) |
| **Salary Range** | (If available, include in USD) |
| **Location** | |

## Why Join Us?
(2-3 compelling sentences about company culture, growth opportunity, or unique value proposition)

## What You'll Do
(Key responsibilities in bullet points - focus on impact, not just tasks)
・
・

## What We're Looking For
**Must-have:**
・
・

**Nice-to-have:**
・
・

## Benefits & Perks
(Highlight benefits that appeal to international candidates)
・
・

## About the Company
(Brief company introduction)

## How to Apply
**※Please use this fixed template (ignore any contact information in the original JD):**

Interested in this position? Value Create will recommend you directly to the company's hiring team.
Please reach out to one of our team members to express your interest:
・**Ilya**
・**Hiroshi**
・**Shu**
We'll take care of the introduction and guide you through the process!

---

【Original Job Description】
{jd_text}

Please analyze the above JD and transform it into an attractive English job description for international engineers.
For unclear items, use "To be discussed" or "Contact for details".
**IMPORTANT**: For Visa Sponsorship, even if not mentioned in the original JD, state "Available (supported for qualified candidates)". All positions handled by Value Create offer visa support.
**IMPORTANT**: For the "How to Apply" section, ignore any contact information or email addresses in the original JD and use the fixed template above (contact Value Create team).
**IMPORTANT**: Use middle dots (・) for list items and capitalize the first letter of each item. Do not use asterisks (*).
**IMPORTANT**: Do not use emojis in headings. Output simple text only.
"""


def get_company_intro_prompt(company_text: str) -> str:
    """会社紹介資料から企業紹介文を生成するプロンプト"""

    return f"""あなたは人材紹介会社のエキスパートコンサルタントです。
会社紹介資料（PDF等から抽出したテキスト）を読み取り、求職者に向けた簡潔で魅力的な企業紹介文を作成してください。

【作成のポイント】
1. **簡潔さ**: 長くても500文字程度に要約
2. **魅力的な表現**: 求職者が興味を持つポイントを強調
3. **事実ベース**: 資料に記載された情報のみを使用

【出力フォーマット】
以下の構造で出力してください：

---

## 企業概要

### 基本情報
| 項目 | 内容 |
|------|------|
| 会社名 | |
| 設立 | |
| 従業員数 | |
| 本社所在地 | |
| 事業内容 | |

### 企業の特徴・強み
（2-3つの箇条書きで、会社の特徴や魅力を記載）
・
・

### こんな方におすすめ
（どんなタイプの求職者に向いているか）
・
・

### 紹介文（求職者向け）
（150-200文字程度の簡潔な紹介文）

---

【会社紹介資料の内容】
{company_text}

上記の資料を解析し、求職者向けの企業紹介文を作成してください。
資料に記載がない項目は「資料に記載なし」としてください。
**重要**: リスト項目の行頭記号は中黒（・）を使用してください。
**重要**: 見出しに絵文字は使用しないでください。
**重要**: 誇張や推測は避け、資料の内容に基づいた正確な情報のみを記載してください。
"""


def get_matching_analysis_prompt(resume_text: str, jd_text: str) -> str:
    """レジュメ×求人票マッチング分析用のプロンプトを生成"""

    return f"""あなたは人材紹介のマッチングエキスパートです。
候補者のレジュメと企業の求人票を詳細に分析し、マッチング評価レポートを作成してください。

【出力フォーマット - 厳守】
以下の構造で必ず出力してください：

---

# マッチング分析レポート

## マッチスコア: X/100

⭐⭐⭐⭐⭐（5段階評価も併記）

**総合判定**: ✅ 強く推奨 / ⚠️ 条件付き推奨 / ❌ 要検討

---

## スキルマッチ詳細

| 技術カテゴリ | 求人要件 | 候補者スキル | マッチ判定 |
|------------|---------|------------|----------|
| プログラミング言語 | | | ✅/⚠️/❌ |
| フレームワーク | | | |
| データベース | | | |
| インフラ/クラウド | | | |
| その他技術 | | | |

**判定記号の意味**:
- ✅ 完全マッチ（要件を満たしている）
- ⚠️ 部分マッチ（一部経験あり、要トレーニング）
- ❌ ギャップあり（未経験）

---

## 経験年数・キャリアレベル

| 項目 | 求人要件 | 候補者 | 評価 |
|-----|---------|--------|------|
| 総エンジニア経験 | | | |
| 該当領域の経験 | | | |
| リーダーシップ | | | |
| 言語レベル | | | |

---

## 強み・アピールポイント

候補者が求人票の要件に対して特に優れている点を3-5項目で記載：

1. **[強み1のタイトル]**
   - 詳細説明（具体的な経験・実績）
   - なぜこれが求人票にマッチするか

2. **[強み2のタイトル]**
   - 詳細説明
   - なぜこれが求人票にマッチするか

3. **[強み3のタイトル]**
   - 詳細説明
   - なぜこれが求人票にマッチするか

---

## ギャップ・改善提案

求人票の要件に対して不足している点と、その対応策：

### ギャップ1: [技術/経験の不足点]
- **影響度**: 高/中/低
- **対応策**: （トレーニング期間、OJT、並行学習など）

### ギャップ2: [技術/経験の不足点]
- **影響度**: 高/中/低
- **対応策**:

（ギャップがない場合は「特筆すべきギャップなし」と記載）

---

## 企業向け推薦コメント

（200-300文字程度）

企業の採用担当者に向けて、この候補者を推薦する理由を簡潔かつ魅力的に記載してください。
求人票の要件とのマッチング、候補者の強み、採用メリットを含めること。

---

## 候補者向けコメント

（200-300文字程度）

候補者に向けて、このポジションへの適性とアドバイスを記載してください。
強みを活かせる点、準備すべきスキル、面接でアピールすべきポイントを含めること。

---

【分析対象】

■ 候補者レジュメ:
{resume_text}

■ 求人票:
{jd_text}

---

【分析指示】
1. 上記フォーマットに厳密に従って出力してください
2. マッチスコアは以下の観点で総合的に評価:
   - 技術スキルのマッチ度（40点）
   - 経験年数・レベルのマッチ度（30点）
   - 言語・コミュニケーション能力（20点）
   - その他（文化フィット、志向性など）（10点）
3. 判定は楽観的すぎず、現実的に評価してください
4. ギャップがある場合でも、ポテンシャルや学習意欲を考慮してください
5. 数値や具体的な経験があれば積極的に引用してください
6. 見出しに絵文字は使用しないでください（判定記号としての絵文字は可）
7. リスト項目の行頭記号は中黒（・）ではなく、番号またはハイフン（-）を使用してください
"""


def get_translate_to_english_prompt(japanese_text: str) -> str:
    """日本語→英語翻訳用のプロンプトを生成"""
    return f"""あなたはプロフェッショナルな翻訳者です。
以下の日本語の文書を英語に翻訳してください。

【翻訳指示】
1. ビジネス文書として適切な英語表現を使用
2. Markdown形式を維持（見出し、表、リストなど）
3. 専門用語は適切な英語表現に翻訳
4. 絵文字や記号（✅⚠️❌など）はそのまま保持
5. 数値やスコアはそのまま保持
6. 表の構造を崩さないように注意
7. 自然で読みやすい英語にしてください

【翻訳対象の日本語文書】
{japanese_text}
"""


def get_translate_to_japanese_prompt(english_text: str) -> str:
    """英語→日本語翻訳用のプロンプトを生成"""
    return f"""あなたはプロフェッショナルな翻訳者です。
以下の英語の文書を日本語に翻訳してください。

【翻訳指示】
1. ビジネス文書として適切な日本語表現を使用
2. Markdown形式を維持（見出し、表、リストなど）
3. 専門用語は適切な日本語表現に翻訳
4. 絵文字や記号（✅⚠️❌など）はそのまま保持
5. 数値やスコアはそのまま保持
6. 表の構造を崩さないように注意
7. 自然で読みやすい日本語にしてください

【翻訳対象の英語文書】
{english_text}
"""


def get_anonymous_proposal_prompt(matching_result: str, resume_text: str, jd_text: str, language: str = "ja", anonymize_level: str = "full") -> str:
    """匿名提案資料生成用のプロンプトを生成

    anonymize_level: "full" = 完全匿名化, "light" = 企業名・大学名を表示（個人情報のみ匿名化）
    """

    if language == "ja":
        if anonymize_level == "light":
            anonymize_note = """【匿名化ルール（軽度匿名化モード）】
- 氏名・連絡先（メール、電話番号、住所）は匿名化する
- **企業名・大学名・プロジェクト名・製品名はそのまま記載してよい**
- 経歴の具体的な内容（役職、チーム規模、成果数値など）もそのまま記載してよい"""
        else:
            anonymize_note = """【匿名化ルール（完全匿名化モード）】
- 氏名、企業名、大学名、固有名詞は一切記載しない
- 企業名は「大手SIer」「外資系IT企業」などの一般表現に置換する
- 大学名は「国内トップ大学」「海外有名大学」などに置換する"""

        return f"""あなたは人材紹介のプロフェッショナルです。
以下のマッチング分析結果とレジュメ、求人票から、企業向けの**候補者提案資料**を作成してください。

【入力情報】
■ マッチング分析結果:
{matching_result}

■ レジュメ:
{resume_text}

■ 求人票:
{jd_text}

---

【出力フォーマット】※厳密に従ってください

# 候補者提案資料

## 1. Catch Copy（各100文字程度）
候補者の魅力を3つの視点で表現するキャッチコピーを生成してください。

### パターンA: スキル重視型
候補者の技術スキル・専門性を前面に出したキャッチコピー
例：「AWS/Kubernetes経験5年、大規模クラウド基盤構築のスペシャリスト」

### パターンB: 実績重視型
候補者の具体的な成果・実績を強調したキャッチコピー
例：「月間1000万PVサービスの開発リーダー、パフォーマンス改善で応答速度50%向上を達成」

### パターンC: ポテンシャル重視型
候補者の成長性・可能性・人物面を強調したキャッチコピー
例：「新技術習得に意欲的、チームリーダーとして組織を牽引できるフルスタックエンジニア」

---

## 2. Summary（200文字程度）
候補者の全体像を簡潔にまとめた概要
- 総エンジニア経験年数
- 専門領域・得意分野
- 主な開発実績
- 言語能力（レジュメに日本語能力の記載がある場合は必ず含める：N1-N5、conversational、native、business levelなど。記載がなければ省略）

---

## 3. Strength（200文字程度）
この求人に対する候補者の強み・アピールポイント
- 求人要件に対してマッチする具体的なスキル
- 特に優れている技術・経験
- 実績や成果（数値があれば記載）

---

## 4. Education / Research（200文字程度）
学歴・研究実績・資格
- 最終学歴（大学・専攻）
- 研究テーマ（ある場合）
- 関連資格
- 技術的なバックグラウンド

---

## 5. Assessment（200文字程度）
総合評価とコメント
- マッチング度の総合評価
- 推薦理由
- 留意点やギャップ（あれば）
- 面接時の確認ポイント

---

{anonymize_note}

【その他の注意事項】
1. **文字数厳守**: 各セクションの文字数制限を守る（Catch Copyは各パターン100文字程度、他は200文字程度）
2. **具体性**: 抽象的な表現を避け、具体的なスキル・経験を記載
3. **客観性**: 事実に基づいた評価を行う
4. **簡潔性**: 要点を絞って分かりやすく記載
"""
    else:  # English
        if anonymize_level == "light":
            anonymize_note_en = """【Anonymization Rules (Light Anonymization Mode)】
- Anonymize personal names and contact info (email, phone, address)
- **Company names, university names, project names, and product names may be included as-is**
- Specific career details (job titles, team sizes, achievement metrics) may also be included as-is"""
        else:
            anonymize_note_en = """【Anonymization Rules (Full Anonymization Mode)】
- No real names, company names, university names, or identifiable proper nouns
- Replace company names with generic terms (e.g., "a major global IT firm", "a leading SaaS company")
- Replace university names with generic terms (e.g., "a top US university", "a prestigious Japanese university")"""

        return f"""You are a professional recruitment consultant.
Create a **candidate proposal document** for the client company based on the matching analysis result, resume, and job description below.

【Input Information】
■ Matching Analysis Result:
{matching_result}

■ Resume:
{resume_text}

■ Job Description:
{jd_text}

---

【Output Format】※Strictly follow this format

# Candidate Proposal

## 1. Catch Copy (approximately 100 characters each)
Generate catchphrases from three different perspectives to express the candidate's appeal.

### Pattern A: Skill-focused
A catchphrase highlighting technical skills and expertise
Example: "AWS/Kubernetes Specialist with 5 Years Experience in Large-scale Cloud Infrastructure"

### Pattern B: Achievement-focused
A catchphrase emphasizing concrete results and accomplishments
Example: "Development Leader of 10M Monthly PV Service, Achieved 50% Performance Improvement"

### Pattern C: Potential-focused
A catchphrase emphasizing growth potential and personal qualities
Example: "Eager Learner of New Technologies, Full-stack Engineer Who Can Lead Teams"

---

## 2. Summary (approximately 200 characters)
Brief overview of the candidate
- Total engineering experience years
- Specialized areas and expertise
- Major development achievements
- Language proficiency (If Japanese proficiency is mentioned in resume, must include it: N1-N5, conversational, native, business level, etc. Omit if not mentioned)

---

## 3. Strength (approximately 200 characters)
Candidate's strengths for this position
- Specific skills matching job requirements
- Outstanding technical experience
- Achievements with metrics (if available)

---

## 4. Education / Research (approximately 200 characters)
Academic background and research
- Highest education (university, major)
- Research topics (if applicable)
- Relevant certifications
- Technical background

---

## 5. Assessment (approximately 200 characters)
Overall evaluation and comments
- Overall matching score evaluation
- Recommendation reasons
- Concerns or gaps (if any)
- Points to confirm in interview

---

{anonymize_note_en}

【Other Important Notes】
1. **Character Limit**: Strictly follow character limits (approximately 100 for each Catch Copy pattern, ~200 for others)
2. **Specificity**: Use concrete skills and experience, avoid abstract expressions
3. **Objectivity**: Provide fact-based evaluation
4. **Brevity**: Focus on key points for clarity
"""


def get_cv_proposal_extract_prompt(resume_text: str, anonymize_level: str = "full") -> str:
    """CV提案用コメント抽出プロンプトを生成（英語・各300文字以内・採用企業訴求型）"""

    if anonymize_level == "light":
        anonymize_rules = """1. **Light Anonymization**: Anonymize personal names and contact info (email, phone, address) only. **Company names, university names, project names, and product names may be kept as-is.** Use actual company/university names from the CV to add credibility."""
    else:
        anonymize_rules = """1. **Complete Anonymization**: No real names, company names, university names, or identifiable proper nouns. Use generic terms (e.g., "a major global IT firm", "a top US university")."""

    return f"""You are an elite recruitment consultant who writes compelling candidate proposals that make hiring managers eager to interview.

Your goal: Write a proposal that makes the hiring company think "We need to meet this person immediately." Stay strictly factual — every claim must be supported by the CV — but frame facts to maximize business appeal.

【CV/Resume】
{resume_text}

---

【Writing Principles — Apply to ALL sections】
- **Lead with business impact**: Instead of "Used Python and SQL", write "Reduced data processing time by 40% through optimized Python/SQL pipelines"
- **Quantify whenever possible**: Revenue impact, team size, scale (users/requests/data), cost savings, speed improvements
- **Show progression & ambition**: Highlight career growth trajectory — promotions, expanding scope, increasing responsibility
- **Use power verbs**: Led, Architected, Delivered, Scaled, Transformed, Pioneered, Spearheaded — not "worked on" or "was involved in"
- **Focus on problems solved**: Frame experience as "challenges tackled → results delivered", not just duties performed
- **Highlight rarity**: What makes this candidate hard to find? Unique skill combinations, cross-domain expertise, bilingual ability, etc.

---

【Output Format】※ Strictly follow this format. Each item MUST be within 300 characters (2-4 sentences). Output in English only.
※ **Sentence Length Rule**: Each sentence MUST be 50-80 characters. If a point is complex, split it into 2-3 shorter sentences instead of one long sentence. Avoid run-on sentences connected by commas or dashes. Each sentence should convey one clear idea. Never write sentences shorter than 50 characters — add specific context (numbers, scope, domain) to reach the minimum.

## 1. Catch Copy
A punchy, memorable headline that makes the reader want to learn more. MUST include: years of experience + role/title + the candidate's unique value proposition or differentiator. Frame it as what this person DELIVERS, not just what they ARE.
Example 1: "10-Year Full-Stack Architect Who Delivers Production-Grade AI Platforms from Zero to Scale"
Example 2: "Senior DevOps Lead | 12 Years Driving 99.99% Uptime Across Large-Scale Distributed Systems"
Example 3: "8-Year Data Scientist Turning NLP Research into Revenue-Generating Recommendation Engines"
※ MUST be 60-100 characters. Never shorter than 60 characters. No names or company names.

## 2. Summary
Paint a vivid picture of who this candidate is and what they bring to the table. Start with their most impressive achievement or defining trait, then build context with role, domain, and career highlights. The reader should immediately understand why this person stands out.
Example: "A Technical Architect who built an AI automation platform serving 2M+ users at a major global IT firm. Over 15 years, he progressed from backend engineer to leading a 30-person cross-functional team, delivering cloud-native solutions that reduced infrastructure costs by 35%."
※ 200-300 characters. Lead with the strongest fact. Include role, years, domain, and measurable achievements.

## 3. Strength
Highlight what this candidate can DO for the hiring company — not just what they know. Connect technical skills to business outcomes. Emphasize rare or hard-to-find skill combinations that justify immediate interest.
Example: "A rare engineer who spans from Linux kernel optimization to production AI systems — he architected a custom Agentic AI framework in Golang that cut deployment cycles by 60%. Proven ability to lead global teams (US, EU, APAC) and translate deep-tech R&D into shipping products."
※ 200-300 characters. Connect skills → outcomes. Highlight what's rare or hard to find.

## 4. Education / Research
Position academic background as evidence of intellectual depth and commitment to growth. Highlight any ongoing learning that signals the candidate stays ahead of industry trends.
Example: "M.Sc. in Computer Science with published research in distributed computing. Currently pursuing an executive technology program at a top US university (2026), signaling strong commitment to staying at the cutting edge. Active open-source contributor to container orchestration projects."
※ 200-300 characters. Frame education as evidence of growth mindset and expertise depth.

## 5. Assessment
Write a clear, confident recommendation that answers: "Why should we prioritize interviewing this candidate?" Address the specific value they would bring and what type of organization would benefit most. End with a forward-looking statement about their potential.
Example: "A builder who constructs AI platforms from scratch — not just an API consumer. His rare combination of low-level systems expertise and AI product delivery makes him ideal for organizations building proprietary AI capabilities. Expect him to elevate both technical standards and team capability."
※ 200-300 characters. Answer "Why this candidate NOW?" Be specific about fit and potential impact.

---

【Important Rules】
{anonymize_rules}
2. **Character Targets**: Each section (except Catch Copy) should be 200-300 characters (2-4 sentences). Catch Copy MUST be 60-100 characters — never shorter than 60. Always include years of experience, role, and domain. Write enough detail for a presentation slide.
3. **Sentence Length (50-80 characters)**: Each sentence MUST be 50-80 characters. Break long sentences into multiple shorter ones. One idea per sentence. Never chain multiple clauses with commas, semicolons, or dashes into a single sentence. Never write sentences shorter than 50 characters — if too short, add specific context such as numbers, scope, or domain. For example, instead of "He led a 20-person team across 3 regions, delivering a cloud migration that reduced costs by 40% while improving uptime to 99.99%", write: "Led a 20-person team across 3 regions. Delivered a cloud migration that cut costs by 40%. Improved system uptime from 99.9% to 99.99%." Instead of "Built cloud infrastructure." (too short), write: "Built cloud-native infrastructure serving 2M+ daily active users."
4. **English Only**: All output must be in English.
5. **Strictly Factual**: Every claim must be grounded in the CV. Do NOT invent metrics, achievements, or experiences not present in the source material. If the CV lacks specific numbers, describe impact qualitatively but accurately.
6. **No Markdown Headers in Values**: Output the value text directly after each header.
7. **Hiring Manager Perspective**: Write as if presenting to a CTO or VP of Engineering who sees dozens of proposals weekly. Make THIS candidate impossible to skip.
"""


def extract_name_from_cv(text: str) -> str:
    """CVテキストの先頭行から候補者名を抽出する"""
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # 明らかにセクション見出しや連絡先情報はスキップ
        lower = line.lower()
        if any(kw in lower for kw in [
            "resume", "curriculum vitae", "cv", "objective", "summary",
            "experience", "education", "skills", "phone", "email",
            "address", "http", "www.", "@", "linkedin"
        ]):
            continue
        # 数字が多い行（電話番号など）はスキップ
        if sum(c.isdigit() for c in line) > len(line) * 0.3:
            continue
        # 長すぎる行は名前ではない（50文字以下を想定）
        if len(line) > 50:
            continue
        return line
    return ""


def get_adjust_length_prompt(proposal_text: str, target_chars: int) -> str:
    """CV提案コメントの文章量を調整するプロンプトを生成"""

    if target_chars <= 150:
        style = "Very concise — keep only the single most impactful fact per section. 1-2 sentences max."
        catch_copy_range = "50-70"
    elif target_chars <= 200:
        style = "Concise — keep the strongest 2 facts per section. 2 sentences."
        catch_copy_range = "60-80"
    elif target_chars <= 250:
        style = "Moderately concise — keep key facts and brief context. 2-3 sentences."
        catch_copy_range = "60-90"
    elif target_chars <= 300:
        style = "Standard length — provide good detail with context. 3-4 sentences."
        catch_copy_range = "60-100"
    else:
        style = "Detailed — expand with additional context, examples, and qualitative descriptions. 4-5 sentences."
        catch_copy_range = "80-120"

    return f"""You are an elite recruitment consultant. Adjust the length of the following candidate proposal to match the target.

【Current Proposal】
{proposal_text}

---

【Instructions】
- **Target**: Each section (except Catch Copy) should be approximately {target_chars} characters.
- **Style**: {style}
- **Catch Copy**: Keep within {catch_copy_range} characters.
- Keep the same section headers (## 1. Catch Copy, ## 2. Summary, etc.)
- Maintain the same language and anonymization level as the original
- Prioritize: quantified achievements > rare skills > general descriptions
- The result must read naturally — do not sacrifice readability for length
- **Sentence Length (50-80 characters)**: Each sentence MUST be 50-80 characters. Break long sentences into shorter ones, but never shorter than 50 characters. Add specific context (numbers, scope, domain) to short sentences to reach the minimum. One idea per sentence. Do not chain clauses with commas or dashes.
- Output in English only
- Do NOT add any new information not present in the original. When expanding, elaborate on existing facts with more context, do not fabricate.
"""


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
    elif input_type == "company":
        # 会社紹介は最低限のテキストがあれば通す
        pass
    elif input_type == "matching":
        # マッチング分析は、レジュメと求人票の両方が必要だが、
        # それぞれの入力で個別にバリデーションされるため、ここでは最低限のチェックのみ
        pass

    return True, ""


def call_groq_api(api_key: str, prompt: str) -> str:
    """Groq APIを呼び出してテキストを生成（リトライ機能付き）"""

    # アプリレベルのレート制限チェック
    allowed, msg = _check_rate_limit()
    if not allowed:
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

    # すべてのリトライが失敗
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


def stream_to_container(api_key: str, prompt: str, container=None):
    """ストリーミングでコンテナにリアルタイム表示し、完成テキストを返す"""
    if container is None:
        container = st.empty()

    collected = []
    for chunk in call_groq_api_stream(api_key, prompt):
        collected.append(chunk)
        container.markdown("".join(collected) + "▍")

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
        # レジュメの場合：「氏名：J.S.」や名前を探す
        for line in lines[:10]:
            if '氏名' in line or 'Name:' in line:
                # 氏名行から名前部分を抽出
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
        .generated {{
            text-align: right;
            color: #999;
            font-size: 12px;
            margin-bottom: 20px;
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
    <div class="generated">{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
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
        result["output"] = output
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


def main():
    """メインアプリケーション"""

    # URLパラメータで共有IDがあれば共有ビューを表示
    share_id = st.query_params.get("share")
    if share_id:
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

    # ヘッダー
    st.markdown("# 🌏 GlobalMatch Assistant")
    st.markdown("*外国人エンジニア × 日本企業をつなぐ人材紹介業務効率化ツール*")
    st.divider()

    # サイドバー設定
    with st.sidebar:
        st.header("⚙️ 設定")

        # APIキー取得（secretsまたは入力）
        api_key = ""
        try:
            api_key = st.secrets.get("GROQ_API_KEY", "")
        except Exception:
            pass  # secrets.tomlがない場合は無視

        if not api_key:
            api_key = st.text_input(
                "Groq API Key",
                type="password",
                placeholder="gsk_...",
                help="APIキーは[Groq Console](https://console.groq.com/keys)から無料で取得できます"
            )
        else:
            st.success("✅ APIキー設定済み（secrets）")

        st.divider()

        # クイックインポート機能（履歴がない場合に表示）
        resume_count = len(st.session_state.get('resume_history', []))
        jd_count = len(st.session_state.get('jd_history', []))

        if resume_count == 0 and jd_count == 0:
            st.warning("📂 履歴がありません")
            st.caption("バックアップファイルをお持ちの場合、ここからインポートできます")

            uploaded_backup = st.file_uploader(
                "バックアップファイル（JSON）",
                type=["json"],
                key="sidebar_import_uploader",
                help="過去にエクスポートしたバックアップファイルを選択"
            )

            if uploaded_backup:
                try:
                    json_string = uploaded_backup.read().decode('utf-8')
                    if st.button("📥 復元する", key="sidebar_import_btn", use_container_width=True):
                        success, message = import_history_from_json(json_string)
                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)
                except Exception as e:
                    st.error(f"ファイル読み込みエラー: {str(e)}")

            st.divider()

        # 機能選択
        st.subheader("📋 機能選択")
        feature = st.radio(
            "変換モードを選択",
            options=[
                "レジュメ最適化（英→日）",
                "レジュメ匿名化（英→英）",
                "求人票魅力化（日→英）",
                "求人票翻訳（英→日）",
                "求人票フォーマット化（日→日）",
                "求人票フォーマット化（英→英）",
                "企業紹介文作成（PDF）",
                "🎯 レジュメ×求人票マッチング分析",
                "📝 CV提案コメント抽出",
                "✉️ 求人打診メール作成",
                "📦 バッチ処理（複数レジュメ）"
            ],
            index=0,
            help="変換したいドキュメントの種類を選択してください"
        )

        st.divider()

        # 使い方ガイド
        with st.expander("📖 使い方"):
            st.markdown("""
            **レジュメ最適化（英→日）**
            1. 英語のレジュメをペーストまたはPDFをアップロード
            2. 匿名化オプションを設定
            3. 「変換実行」をクリック

            **レジュメ匿名化（英→英）**
            1. 英語のレジュメをペーストまたはPDFをアップロード
            2. 匿名化レベルを選択
            3. 英語のまま匿名化されたレジュメを取得

            **求人票魅力化（日→英）**
            1. 日本語の求人票をペースト
            2. 「変換実行」をクリック

            **求人票翻訳（英→日）**
            1. 英語の求人票をペースト
            2. 「変換実行」をクリック
            3. 日本人エンジニア向けに最適化

            **求人票フォーマット化（日→日）**
            1. 日本語の求人票をペースト
            2. 「変換実行」をクリック
            3. 統一フォーマットの魅力的な日本語JDを取得

            **求人票フォーマット化（英→英）**
            1. 英語の求人票をペースト
            2. 「変換実行」をクリック
            3. 統一フォーマットの魅力的な英語JDを取得

            **企業紹介文作成（PDF）**
            1. 会社紹介PDFをアップロード
            2. 「紹介文作成」をクリック
            3. 求職者向けの簡潔な企業紹介文を取得

            **レジュメ×求人票マッチング分析**
            1. 最適化済みレジュメと求人票を入力
            2. テキスト直接入力、または過去の変換結果から選択可能
            3. 「マッチング分析を実行」をクリック
            4. マッチスコア、スキル比較、強み・ギャップ分析、推薦コメントを取得

            **CV提案コメント抽出**
            1. 英語のCVをテキスト入力またはPDFアップロード
            2. 「抽出実行」をクリック
            3. 匿名提案用の5項目コメント（各300文字以内・英語）を取得
            4. 複数CVの一括処理にも対応（---NEXT---で区切り）

            **求人打診メール作成**
            1. 候補者の名前と送信者名を入力
            2. 求人情報（ポジション名、企業名、URL等）を追加
            3. 「メール生成」をクリックでメール文面を自動作成
            4. コピーしてそのままメール送信に利用

            *生成結果は右上のコピーボタンで簡単にコピーできます*
            """)

    # メインコンテンツ
    if feature == "レジュメ最適化（英→日）":
        st.subheader("📄 レジュメ最適化（英語 → 日本語）")
        st.caption("外国人エンジニアの英語レジュメを、日本企業向けの統一フォーマットに変換します")

        col1, col2 = st.columns([1, 1])

        with col1:
            # 入力方法タブ
            input_tab1, input_tab2, input_tab3 = st.tabs(["📝 テキスト入力", "📄 PDF読み込み", "🔗 LinkedIn"])

            with input_tab1:
                # サンプルデータボタン
                col_label, col_sample = st.columns([3, 1])
                with col_label:
                    st.markdown("##### 入力：英語レジュメ")
                with col_sample:
                    if st.button("📝 サンプル", key="sample_resume_btn", help="サンプルレジュメを挿入"):
                        st.session_state['resume_text_input'] = SAMPLE_RESUME

                # テキストエリアの値を取得
                resume_input = st.text_area(
                    "英語のレジュメをペースト",
                    height=350,
                    placeholder="Paste the English resume here...\n\nExample:\nJohn Doe\nSoftware Engineer with 5+ years of experience...",
                    label_visibility="collapsed",
                    key="resume_text_input"
                )

            with input_tab2:
                st.markdown("##### PDFをアップロード")
                uploaded_pdf = st.file_uploader(
                    "PDFファイルを選択",
                    type=["pdf"],
                    key="resume_pdf",
                    help=f"最大{MAX_PDF_SIZE_MB}MB、20ページまで"
                )

                if uploaded_pdf:
                    with st.spinner("📄 PDFを読み込み中..."):
                        extracted_text, error = extract_text_from_pdf(uploaded_pdf)
                        if error:
                            st.error(f"❌ {error}")
                        else:
                            st.success(f"✅ テキスト抽出完了（{len(extracted_text):,}文字）")
                            resume_input = extracted_text
                            with st.expander("抽出されたテキストを確認"):
                                st.text(extracted_text[:2000] + ("..." if len(extracted_text) > 2000 else ""))
                else:
                    # PDFがない場合はテキスト入力を使用
                    if 'resume_input' not in dir():
                        resume_input = ""

            with input_tab3:
                st.markdown("##### LinkedInプロフィールをコピペ")
                st.info("💡 LinkedInページを開き、プロフィール全体をコピーして貼り付けてください")

                with st.expander("📖 コピー方法", expanded=False):
                    st.markdown("""
                    1. LinkedInでプロフィールページを開く
                    2. `Ctrl+A`（Mac: `Cmd+A`）で全選択
                    3. `Ctrl+C`（Mac: `Cmd+C`）でコピー
                    4. 下のテキストエリアに貼り付け
                    """)

                linkedin_input = st.text_area(
                    "LinkedInプロフィールをペースト",
                    height=300,
                    placeholder="LinkedInプロフィールページのテキストを貼り付けてください...\n\n例:\nJohn Smith\nSenior Software Engineer at Google\nSan Francisco Bay Area\n\nAbout\nExperienced software engineer with 7+ years...",
                    label_visibility="collapsed",
                    key="linkedin_text_input"
                )

                if linkedin_input:
                    resume_input = linkedin_input
                    st.success(f"✅ LinkedInテキスト読み込み完了（{len(linkedin_input):,}文字）")

            # 文字数カウンター
            char_count = len(resume_input) if resume_input else 0
            if char_count > MAX_INPUT_CHARS:
                st.error(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} 文字（超過）")
            elif char_count > 0:
                st.caption(f"📊 {char_count:,} / {MAX_INPUT_CHARS:,} 文字")

            anonymize = st.radio(
                "🔒 匿名化レベル",
                options=["full", "light", "none"],
                format_func=lambda x: {
                    "full": "完全匿名化（個人情報＋企業名＋プロジェクト）",
                    "light": "軽度匿名化（個人情報のみ）",
                    "none": "匿名化なし"
                }[x],
                index=0,
                help="完全：企業名・大学名も業界表現に変換 / 軽度：氏名・連絡先のみ匿名化"
            )

            process_btn = st.button(
                "🔄 変換実行",
                type="primary",
                use_container_width=True,
                disabled=not api_key or not resume_input
            )

        with col2:
            st.markdown("##### 出力：日本企業向けフォーマット")

            if process_btn:
                if not api_key:
                    st.error("❌ APIキーを入力してください")
                else:
                    # 入力バリデーション
                    is_valid, error_msg = validate_input(resume_input, "resume")
                    if not is_valid:
                        st.warning(f"⚠️ {error_msg}")
                    else:
                        try:
                            start_time = time.time()
                            prompt = get_resume_optimization_prompt(resume_input, anonymize)
                            st.caption("🤖 AIがレジュメを解析・構造化しています...")
                            stream_container = st.empty()
                            result = stream_to_container(api_key, prompt, stream_container)
                            elapsed_time = time.time() - start_time

                            st.session_state['resume_result'] = result
                            st.session_state['resume_time'] = elapsed_time
                            stream_container.empty()
                            st.success(f"✅ 変換完了！（{elapsed_time:.1f}秒）")

                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error("❌ 予期せぬエラーが発生しました。しばらく待ってから再試行してください")

            # 結果表示
            if 'resume_result' in st.session_state:
                # 表示切替とコピーボタン
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted = st.checkbox("📖 整形表示", value=False, key="resume_formatted",
                                                  help="Markdownをフォーマットして表示")
                with col_copy:
                    if st.button("📋 コピー", key="copy_resume", use_container_width=True):
                        st.toast("✅ クリップボードにコピーしました")
                        # JavaScriptでクリップボードにコピー
                        escaped_text = st.session_state['resume_result'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                        st.components.v1.html(f"""
                            <script>
                            navigator.clipboard.writeText(`{escaped_text}`);
                            </script>
                        """, height=0)

                if show_formatted:
                    st.markdown(st.session_state['resume_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_result = st.text_area(
                        "出力結果（編集可能）",
                        value=st.session_state['resume_result'],
                        height=400,
                        key="edit_resume_result_jp"
                    )
                    st.session_state['resume_result'] = edited_result

                # ダウンロードボタン
                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1:
                    st.download_button(
                        "📄 Markdown",
                        data=st.session_state['resume_result'],
                        file_name=f"resume_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                        mime="text/markdown"
                    )
                with col_dl2:
                    st.download_button(
                        "📝 テキスト",
                        data=st.session_state['resume_result'],
                        file_name=f"resume_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                        mime="text/plain"
                    )
                with col_dl3:
                    html_content = generate_html(st.session_state['resume_result'], "候補者レジュメ")
                    st.download_button(
                        "🌐 HTML",
                        data=html_content,
                        file_name=f"resume_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                        mime="text/html",
                        help="ブラウザで開いて印刷→PDF保存"
                    )

                # 追加変換ボタン
                st.divider()
                st.markdown("##### 🔄 追加変換")
                if st.button("📝 この結果を英語匿名化（English → English）", key="convert_to_en_anonymize", use_container_width=True, help="生成された日本語レジュメを基に英語匿名化レジュメを生成"):
                    try:
                        # 元の英語レジュメを取得
                        if 'resume_text_input' in st.session_state and st.session_state['resume_text_input']:
                            original_english_resume = st.session_state['resume_text_input']
                            prompt_en = get_english_anonymization_prompt(original_english_resume, "full")
                            st.caption("🤖 英語匿名化レジュメを生成中...")
                            stream_container = st.empty()
                            result_en = stream_to_container(api_key, prompt_en, stream_container)
                            st.session_state['resume_en_result'] = result_en
                            stream_container.empty()
                            st.success("✅ 英語匿名化レジュメの生成が完了しました")
                            st.info("💡 下にスクロールして結果を確認してください")
                            st.rerun()
                        else:
                            st.error("❌ 元の英語レジュメが見つかりません。最初から変換し直してください。")
                    except Exception as e:
                        st.error("❌ 生成エラーが発生しました。しばらく待ってから再試行してください")

                # 英語匿名化結果の表示
                if 'resume_en_result' in st.session_state and st.session_state.get('resume_result'):
                    st.divider()
                    st.markdown("##### 📄 英語匿名化レジュメ（追加生成）")

                    col_view_en2, col_copy_en2 = st.columns([2, 1])
                    with col_view_en2:
                        show_formatted_en2 = st.checkbox("📖 整形表示", value=False, key="resume_en2_formatted")
                    with col_copy_en2:
                        if st.button("📋 コピー", key="copy_resume_en2", use_container_width=True):
                            st.toast("✅ クリップボードにコピーしました")
                            escaped_text = st.session_state['resume_en_result'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                            st.components.v1.html(f"""
                                <script>
                                navigator.clipboard.writeText(`{escaped_text}`);
                                </script>
                            """, height=0)

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

                    # ダウンロードボタン
                    col_dl1_en2, col_dl2_en2, col_dl3_en2 = st.columns(3)
                    with col_dl1_en2:
                        st.download_button(
                            "📄 Markdown",
                            data=st.session_state['resume_en_result'],
                            file_name=f"resume_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                            mime="text/markdown",
                            key="en2_md"
                        )
                    with col_dl2_en2:
                        st.download_button(
                            "📝 テキスト",
                            data=st.session_state['resume_en_result'],
                            file_name=f"resume_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                            mime="text/plain",
                            key="en2_txt"
                        )
                    with col_dl3_en2:
                        html_content = generate_html(st.session_state['resume_en_result'], "Anonymized Resume")
                        st.download_button(
                            "🌐 HTML",
                            data=html_content,
                            file_name=f"resume_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                            mime="text/html",
                            key="en2_html",
                            help="ブラウザで開いて印刷→PDF保存"
                        )

                # 共有リンク作成ボタン
                if get_supabase_client():
                    st.divider()
                    if st.button("🔗 共有リンク作成", key="share_resume_jp", help="1ヶ月有効の共有リンクを作成"):
                        with st.spinner("共有リンクを作成中..."):
                            share_id = create_share_link(
                                st.session_state['resume_result'],
                                "候補者レジュメ（匿名化済み）"
                            )
                        if share_id:
                            # アプリのベースURLを取得
                            try:
                                base_url = st.secrets["APP_URL"]
                            except KeyError:
                                base_url = "https://globalmatch-assistant-zk6s2lwgkqp6xf6xuc9uvi.streamlit.app"
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                            st.code(share_url)
                            st.info("💡 上のURLをコピーしてクライアントに共有してください")
                        else:
                            st.error("❌ 共有リンクの作成に失敗しました")

    elif feature == "レジュメ匿名化（英→英）":
        st.subheader("🔒 レジュメ匿名化（英語 → 英語）")
        st.caption("英語レジュメを英語のまま匿名化します。海外クライアントへの提出に最適")

        col1, col2 = st.columns([1, 1])

        with col1:
            # 入力方法タブ
            input_tab1, input_tab2, input_tab3 = st.tabs(["📝 テキスト入力", "📄 PDF読み込み", "🔗 LinkedIn"])

            with input_tab1:
                # サンプルデータボタン
                col_label, col_sample = st.columns([3, 1])
                with col_label:
                    st.markdown("##### 入力：英語レジュメ")
                with col_sample:
                    if st.button("📝 サンプル", key="sample_resume_en_btn", help="サンプルレジュメを挿入"):
                        st.session_state['resume_en_text'] = SAMPLE_RESUME

                resume_en_input = st.text_area(
                    "英語のレジュメをペースト",
                    height=350,
                    placeholder="Paste the English resume here...",
                    label_visibility="collapsed",
                    key="resume_en_text"
                )

            with input_tab2:
                st.markdown("##### PDFをアップロード")
                uploaded_pdf_en = st.file_uploader(
                    "PDFファイルを選択",
                    type=["pdf"],
                    key="resume_en_pdf",
                    help=f"最大{MAX_PDF_SIZE_MB}MB、20ページまで"
                )

                if uploaded_pdf_en:
                    with st.spinner("📄 PDFを読み込み中..."):
                        extracted_text_en, error_en = extract_text_from_pdf(uploaded_pdf_en)
                        if error_en:
                            st.error(f"❌ {error_en}")
                        else:
                            st.success(f"✅ テキスト抽出完了（{len(extracted_text_en):,}文字）")
                            resume_en_input = extracted_text_en
                            with st.expander("抽出されたテキストを確認"):
                                st.text(extracted_text_en[:2000] + ("..." if len(extracted_text_en) > 2000 else ""))
                else:
                    if 'resume_en_input' not in dir():
                        resume_en_input = ""

            with input_tab3:
                st.markdown("##### LinkedInプロフィールをコピペ")
                st.info("💡 LinkedInページを開き、プロフィール全体をコピーして貼り付けてください")

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
                "🔒 匿名化レベル",
                options=["full", "light"],
                format_func=lambda x: {
                    "full": "完全匿名化（個人情報＋企業名＋プロジェクト）",
                    "light": "軽度匿名化（個人情報のみ）"
                }[x],
                index=0,
                key="anonymize_en",
                help="完全：企業名・大学名も業界表現に変換 / 軽度：氏名・連絡先のみ匿名化"
            )

            process_en_btn = st.button(
                "🔄 匿名化実行",
                type="primary",
                use_container_width=True,
                disabled=not api_key or not resume_en_input,
                key="process_en_btn"
            )

        with col2:
            st.markdown("##### 出力：匿名化された英語レジュメ")

            if process_en_btn:
                if not api_key:
                    st.error("❌ APIキーを入力してください")
                else:
                    is_valid_en, error_msg_en = validate_input(resume_en_input, "resume")
                    if not is_valid_en:
                        st.warning(f"⚠️ {error_msg_en}")
                    else:
                        try:
                            start_time = time.time()
                            prompt = get_english_anonymization_prompt(resume_en_input, anonymize_en)
                            st.caption("🤖 AIがレジュメを匿名化しています...")
                            stream_container = st.empty()
                            result = stream_to_container(api_key, prompt, stream_container)
                            elapsed_time = time.time() - start_time

                            st.session_state['resume_en_result'] = result
                            st.session_state['resume_en_time'] = elapsed_time
                            stream_container.empty()
                            st.success(f"✅ 匿名化完了！（{elapsed_time:.1f}秒）")

                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                                st.error("❌ 予期せぬエラーが発生しました。しばらく待ってから再試行してください")

            # 結果表示
            if 'resume_en_result' in st.session_state:
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted_en = st.checkbox("📖 整形表示", value=False, key="resume_en_formatted")
                with col_copy:
                    if st.button("📋 コピー", key="copy_resume_en", use_container_width=True):
                        st.toast("✅ クリップボードにコピーしました")
                        escaped_text = st.session_state['resume_en_result'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                        st.components.v1.html(f"""
                            <script>
                            navigator.clipboard.writeText(`{escaped_text}`);
                            </script>
                        """, height=0)

                if show_formatted_en:
                    st.markdown(st.session_state['resume_en_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_result_en = st.text_area(
                        "Output (Editable)",
                        value=st.session_state['resume_en_result'],
                        height=400,
                        key="edit_resume_result_en"
                    )
                    st.session_state['resume_en_result'] = edited_result_en

                # ダウンロードボタン
                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1:
                    st.download_button(
                        "📄 Markdown",
                        data=st.session_state['resume_en_result'],
                        file_name=f"resume_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                        mime="text/markdown",
                        key="en_md"
                    )
                with col_dl2:
                    st.download_button(
                        "📝 テキスト",
                        data=st.session_state['resume_en_result'],
                        file_name=f"resume_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                        mime="text/plain",
                        key="en_txt"
                    )
                with col_dl3:
                    html_content = generate_html(st.session_state['resume_en_result'], "Anonymized Resume")
                    st.download_button(
                        "🌐 HTML",
                        data=html_content,
                        file_name=f"resume_anonymized_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                        mime="text/html",
                        key="en_html",
                        help="ブラウザで開いて印刷→PDF保存"
                    )

                # 追加変換ボタン
                st.divider()
                st.markdown("##### 🔄 追加変換")
                if st.button("🌐 この結果を日本語に翻訳（English → Japanese）", key="convert_to_jp_translate", use_container_width=True, help="英語匿名化レジュメを日本語フォーマットに変換"):
                    try:
                        if 'resume_en_result' in st.session_state and st.session_state['resume_en_result']:
                            english_resume = st.session_state['resume_en_result']
                            prompt_jp = get_resume_optimization_prompt(english_resume, "full")
                            st.caption("🤖 日本語レジュメを生成中...")
                            stream_container = st.empty()
                            result_jp = stream_to_container(api_key, prompt_jp, stream_container)
                            st.session_state['resume_result'] = result_jp
                            stream_container.empty()
                            st.success("✅ 日本語レジュメの生成が完了しました")
                            st.info("💡 下にスクロールして結果を確認してください")
                            st.rerun()
                        else:
                            st.error("❌ 英語レジュメが見つかりません。最初から変換し直してください。")
                    except Exception as e:
                        st.error("❌ 生成エラーが発生しました。しばらく待ってから再試行してください")

                # 日本語変換結果の表示（英語匿名化後の追加変換）
                if 'resume_result' in st.session_state and st.session_state.get('resume_en_result') and not st.session_state.get('resume_text_input'):
                    st.divider()
                    st.markdown("##### 📄 日本語レジュメ（追加生成）")

                    col_view_jp2, col_copy_jp2 = st.columns([2, 1])
                    with col_view_jp2:
                        show_formatted_jp2 = st.checkbox("📖 整形表示", value=False, key="resume_jp2_formatted")
                    with col_copy_jp2:
                        if st.button("📋 コピー", key="copy_resume_jp2", use_container_width=True):
                            st.toast("✅ クリップボードにコピーしました")
                            escaped_text = st.session_state['resume_result'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                            st.components.v1.html(f"""
                                <script>
                                navigator.clipboard.writeText(`{escaped_text}`);
                                </script>
                            """, height=0)

                    if show_formatted_jp2:
                        st.markdown(st.session_state['resume_result'])
                    else:
                        edited_result_jp2 = st.text_area(
                            "出力結果（編集可能）",
                            value=st.session_state['resume_result'],
                            height=400,
                            key="edit_resume_result_jp2"
                        )
                        st.session_state['resume_result'] = edited_result_jp2

                    # ダウンロードボタン
                    col_dl1_jp2, col_dl2_jp2, col_dl3_jp2 = st.columns(3)
                    with col_dl1_jp2:
                        st.download_button(
                            "📄 Markdown",
                            data=st.session_state['resume_result'],
                            file_name=f"resume_jp_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                            mime="text/markdown",
                            key="jp2_md"
                        )
                    with col_dl2_jp2:
                        st.download_button(
                            "📝 テキスト",
                            data=st.session_state['resume_result'],
                            file_name=f"resume_jp_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                            mime="text/plain",
                            key="jp2_txt"
                        )
                    with col_dl3_jp2:
                        html_content = generate_html(st.session_state['resume_result'], "候補者レジュメ")
                        st.download_button(
                            "🌐 HTML",
                            data=html_content,
                            file_name=f"resume_jp_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                            mime="text/html",
                            key="jp2_html",
                            help="ブラウザで開いて印刷→PDF保存"
                        )

                # 共有リンク作成ボタン
                if get_supabase_client():
                    st.divider()
                    if st.button("🔗 共有リンク作成", key="share_resume_en", help="1ヶ月有効の共有リンクを作成"):
                        with st.spinner("共有リンクを作成中..."):
                            share_id = create_share_link(
                                st.session_state['resume_en_result'],
                                "Anonymized Resume"
                            )
                        if share_id:
                            try:
                                base_url = st.secrets["APP_URL"]
                            except KeyError:
                                base_url = "https://globalmatch-assistant-zk6s2lwgkqp6xf6xuc9uvi.streamlit.app"
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                            st.code(share_url)
                            st.info("💡 上のURLをコピーしてクライアントに共有してください")
                        else:
                            st.error("❌ 共有リンクの作成に失敗しました")

    elif feature == "求人票魅力化（日→英）":
        st.subheader("📋 求人票魅力化（日本語 → 英語）")
        st.caption("日本企業の求人票を、外国人エンジニアに魅力的な英語JDに変換します")

        col1, col2 = st.columns([1, 1])

        with col1:
            # サンプルデータボタン
            col_label, col_sample = st.columns([3, 1])
            with col_label:
                st.markdown("##### 入力：日本語求人票")
            with col_sample:
                if st.button("📝 サンプル", key="sample_jd_btn", help="サンプル求人票を挿入"):
                    st.session_state['jd_text_input'] = SAMPLE_JD

            jd_input = st.text_area(
                "日本語の求人票をペースト",
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

            process_btn = st.button(
                "🔄 変換実行",
                type="primary",
                use_container_width=True,
                disabled=not api_key or not jd_input,
                key="jd_btn"
            )

        with col2:
            st.markdown("##### 出力：外国人エンジニア向け英語JD")

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
                            st.caption("🤖 AIが求人票を解析・魅力化しています...")
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
                                st.error("❌ 予期せぬエラーが発生しました。しばらく待ってから再試行してください")

            # 結果表示
            if 'jd_result' in st.session_state:
                # 表示切替とコピーボタン
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted = st.checkbox("📖 整形表示", value=False, key="jd_formatted",
                                                  help="Markdownをフォーマットして表示")
                with col_copy:
                    if st.button("📋 コピー", key="copy_jd", use_container_width=True):
                        st.toast("✅ クリップボードにコピーしました")
                        escaped_text = st.session_state['jd_result'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                        st.components.v1.html(f"""
                            <script>
                            navigator.clipboard.writeText(`{escaped_text}`);
                            </script>
                        """, height=0)

                if show_formatted:
                    st.markdown(st.session_state['jd_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_jd_result = st.text_area(
                        "Output (Editable)",
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
                        "📝 テキスト",
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
                        help="ブラウザで開いて印刷→PDF保存"
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
                            try:
                                base_url = st.secrets["APP_URL"]
                            except KeyError:
                                base_url = "https://globalmatch-assistant-zk6s2lwgkqp6xf6xuc9uvi.streamlit.app"
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                            st.code(share_url)
                            st.info("💡 上のURLをコピーしてクライアントに共有してください")
                        else:
                            st.error("❌ 共有リンクの作成に失敗しました")

    elif feature == "求人票翻訳（英→日）":
        st.subheader("📋 求人票翻訳（英語 → 日本語）")
        st.caption("海外企業・外資系の英語求人票を、日本人エンジニア向けに最適化された日本語JDに変換します")

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
                    if st.button("📝 サンプル", key="sample_jd_en_btn", help="サンプル英語求人票を挿入"):
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

            process_btn = st.button(
                "🔄 変換実行",
                type="primary",
                use_container_width=True,
                disabled=not api_key or not jd_en_input,
                key="jd_en_btn"
            )

        with col2:
            st.markdown("##### 出力：日本人エンジニア向け求人票")

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
                            st.error("❌ 予期せぬエラーが発生しました。しばらく待ってから再試行してください")

            # 結果表示
            if 'jd_en_result' in st.session_state:
                # 表示切替とコピーボタン
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted = st.checkbox("📖 整形表示", value=False, key="jd_en_formatted",
                                                  help="Markdownをフォーマットして表示")
                with col_copy:
                    if st.button("📋 コピー", key="copy_jd_en", use_container_width=True):
                        st.toast("✅ クリップボードにコピーしました")
                        escaped_text = st.session_state['jd_en_result'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                        st.components.v1.html(f"""
                            <script>
                            navigator.clipboard.writeText(`{escaped_text}`);
                            </script>
                        """, height=0)

                if show_formatted:
                    st.markdown(st.session_state['jd_en_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_jd_en_result = st.text_area(
                        "出力結果（編集可能）",
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
                        "📝 テキスト",
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
                        help="ブラウザで開いて印刷→PDF保存"
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
                            try:
                                base_url = st.secrets["APP_URL"]
                            except KeyError:
                                base_url = "https://globalmatch-assistant-zk6s2lwgkqp6xf6xuc9uvi.streamlit.app"
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                            st.code(share_url)
                            st.info("💡 上のURLをコピーしてクライアントに共有してください")
                        else:
                            st.error("❌ 共有リンクの作成に失敗しました")

    elif feature == "求人票フォーマット化（日→日）":
        st.subheader("📋 求人票フォーマット化（日本語 → 日本語）")
        st.caption("日本語の求人票を、統一された見やすいフォーマットの魅力的な日本語JDに変換します")

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
                    if st.button("📝 サンプル", key="sample_jd_jp_jp_btn", help="サンプル求人票を挿入"):
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

            process_btn = st.button(
                "🔄 変換実行",
                type="primary",
                use_container_width=True,
                disabled=not api_key or not jd_jp_jp_input,
                key="jd_jp_jp_btn"
            )

        with col2:
            st.markdown("##### 出力：統一フォーマットの日本語JD")

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
                            st.caption("🤖 AIが求人票を解析・整形しています...")
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
                            st.error("❌ 予期せぬエラーが発生しました。しばらく待ってから再試行してください")

            # 結果表示
            if 'jd_jp_jp_result' in st.session_state:
                # 表示切替とコピーボタン
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted = st.checkbox("📖 整形表示", value=False, key="jd_jp_jp_formatted",
                                                  help="Markdownをフォーマットして表示")
                with col_copy:
                    if st.button("📋 コピー", key="copy_jd_jp_jp", use_container_width=True):
                        st.toast("✅ クリップボードにコピーしました")
                        escaped_text = st.session_state['jd_jp_jp_result'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                        st.components.v1.html(f"""
                            <script>
                            navigator.clipboard.writeText(`{escaped_text}`);
                            </script>
                        """, height=0)

                if show_formatted:
                    st.markdown(st.session_state['jd_jp_jp_result'])
                else:
                    # 編集可能なテキストエリア
                    edited_jd_jp_jp_result = st.text_area(
                        "出力結果（編集可能）",
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
                        "📝 テキスト",
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
                        help="ブラウザで開いて印刷→PDF保存"
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
                            try:
                                base_url = st.secrets["APP_URL"]
                            except KeyError:
                                base_url = "https://globalmatch-assistant-zk6s2lwgkqp6xf6xuc9uvi.streamlit.app"
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                            st.code(share_url)
                            st.info("💡 上のURLをコピーしてクライアントに共有してください")
                        else:
                            st.error("❌ 共有リンクの作成に失敗しました")

    elif feature == "求人票フォーマット化（英→英）":
        st.subheader("📋 求人票フォーマット化（English → English）")
        st.caption("Transform English job descriptions into an attractive, well-structured format for international engineers")

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

            process_btn = st.button(
                "🔄 Transform",
                type="primary",
                use_container_width=True,
                disabled=not api_key or not jd_en_en_input,
                key="jd_en_en_btn"
            )

        with col2:
            st.markdown("##### Output: Formatted English JD")

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
                        escaped_text = st.session_state['jd_en_en_result'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                        st.components.v1.html(f"""
                            <script>
                            navigator.clipboard.writeText(`{escaped_text}`);
                            </script>
                        """, height=0)

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
                            try:
                                base_url = st.secrets["APP_URL"]
                            except KeyError:
                                base_url = "https://globalmatch-assistant-zk6s2lwgkqp6xf6xuc9uvi.streamlit.app"
                            share_url = f"{base_url}/?share={share_id}"
                            st.success("✅ Share link created (valid for 1 month)")
                            st.code(share_url)
                            st.info("💡 Copy the URL above to share with clients")
                        else:
                            st.error("❌ Failed to create share link")

    elif feature == "企業紹介文作成（PDF）":
        st.subheader("🏢 企業紹介文作成（PDF読み取り）")
        st.caption("会社紹介資料（PDF）から求職者向けの簡潔な企業紹介文を自動生成します")

        col1, col2 = st.columns([1, 1])

        with col1:
            # 入力方法タブ
            input_tab1, input_tab2 = st.tabs(["📄 PDF読み込み", "📝 テキスト入力"])

            company_input = ""

            with input_tab1:
                st.markdown("##### 会社紹介PDFをアップロード")
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
                st.markdown("##### 会社紹介テキストをペースト")
                company_text_input = st.text_area(
                    "会社紹介テキストをペースト",
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

            st.info("💡 会社概要、事業内容、強みなどが含まれたPDFが理想的です")

            process_btn = st.button(
                "🔄 紹介文作成",
                type="primary",
                use_container_width=True,
                disabled=not api_key or not company_input,
                key="company_btn"
            )

        with col2:
            st.markdown("##### 出力：求職者向け企業紹介文")

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
                            st.caption("🤖 AIが会社紹介資料を解析しています...")
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
                            st.error("❌ 予期せぬエラーが発生しました。しばらく待ってから再試行してください")

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
                        escaped_text = st.session_state['company_result'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                        st.components.v1.html(f"""
                            <script>
                            navigator.clipboard.writeText(`{escaped_text}`);
                            </script>
                        """, height=0)

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

    elif feature == "🎯 レジュメ×求人票マッチング分析":
        st.subheader("🎯 レジュメ×求人票マッチング分析")
        st.caption("最適化済みレジュメと求人票を入力し、AIがマッチング度を多角的に分析します")

        # 2カラムレイアウト（入力エリア）
        col_input1, col_input2 = st.columns([1, 1])

        # 入力エリア1: レジュメ
        with col_input1:
            st.markdown("##### 📄 入力1: レジュメ")

            # 入力方法選択
            resume_source = st.radio(
                "レジュメの入力方法",
                options=["テキスト/PDF入力", "過去の最適化結果から選択", "📂 履歴から選択"],
                key="matching_resume_source",
                horizontal=True
            )

            matching_resume_input = ""

            if resume_source == "テキスト/PDF入力":
                # タブで切り替え
                input_tab1, input_tab2 = st.tabs(["📝 テキスト入力", "📄 PDF読み込み"])

                with input_tab1:
                    # サンプルボタン
                    col_label, col_sample = st.columns([3, 1])
                    with col_label:
                        st.markdown("レジュメをペースト")
                    with col_sample:
                        if st.button("📝 サンプル", key="sample_matching_resume_btn", help="サンプルレジュメを挿入"):
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
            elif resume_source == "過去の最適化結果から選択":
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
            st.markdown("##### 📋 入力2: 求人票")

            # 入力方法選択
            jd_source = st.radio(
                "求人票の入力方法",
                options=["テキスト/PDF入力", "過去の変換結果から選択", "📂 履歴から選択"],
                key="matching_jd_source",
                horizontal=True
            )

            matching_jd_input = ""

            if jd_source == "テキスト/PDF入力":
                # タブで切り替え
                input_tab1, input_tab2 = st.tabs(["📝 テキスト入力", "📄 PDF読み込み"])

                with input_tab1:
                    # サンプルボタン
                    col_label, col_sample = st.columns([3, 1])
                    with col_label:
                        st.markdown("求人票をペースト")
                    with col_sample:
                        if st.button("📝 サンプル", key="sample_matching_jd_btn", help="サンプル求人票を挿入"):
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
            elif jd_source == "過去の変換結果から選択":
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
            process_btn = st.button(
                "🎯 マッチング分析を実行",
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
        st.markdown("### 📊 分析結果")

        if process_btn:
            if not api_key:
                st.error("❌ APIキーを入力してください")
            elif not matching_resume_input or not matching_jd_input:
                st.warning("⚠️ レジュメと求人票の両方を入力してください")
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
                        st.caption("🤖 AIがレジュメと求人票を詳細分析しています...")
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
            # スコアの可視化
            import re
            score_match = re.search(r'マッチスコア[：:]\s*(\d+)/100', st.session_state['matching_result'])
            if score_match:
                score = int(score_match.group(1))
                st.divider()
                st.markdown("#### 📊 マッチング評価")

                # プログレスバーの色を決定
                if score >= 80:
                    color_text = "🟢 優秀なマッチング"
                elif score >= 60:
                    color_text = "🟡 良いマッチング"
                else:
                    color_text = "🟠 要検討"

                col_prog, col_score = st.columns([3, 1])
                with col_prog:
                    st.progress(score / 100)
                with col_score:
                    st.metric("スコア", f"{score}/100")

                st.caption(f"{color_text}")
                st.divider()

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
                    escaped_text = st.session_state['matching_result'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                    st.components.v1.html(f"""
                        <script>
                        navigator.clipboard.writeText(`{escaped_text}`);
                        </script>
                    """, height=0)

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
            st.markdown("#### 📄 候補者提案資料生成")
            st.caption("マッチング分析から企業向けの簡潔な候補者提案資料を生成します")

            proposal_anon_level = st.radio(
                "🔒 匿名化レベル",
                options=["full", "light"],
                format_func=lambda x: {
                    "full": "完全匿名化（企業名・大学名も伏せる）",
                    "light": "軽度匿名化（企業名・大学名は表示）"
                }[x],
                horizontal=True,
                key="proposal_anon_level",
                help="完全：企業名を「大手SIer」等に置換 / 軽度：企業名・大学名をそのまま表示（個人情報のみ匿名化）"
            )

            col_proposal1, col_proposal2 = st.columns(2)

            with col_proposal1:
                if st.button("📝 日本語版を生成", key="generate_proposal_ja", use_container_width=True, help="提案資料（日本語）を生成"):
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
                            st.session_state['anonymous_proposal'] = proposal
                            stream_container.empty()
                            st.success("✅ Candidate proposal (English) generated successfully")
                            st.rerun()
                        except Exception as e:
                            st.error("❌ Generation error. Please try again later")

            # 匿名提案資料の表示
            if 'anonymous_proposal' in st.session_state:
                st.divider()
                st.markdown("#### 📋 生成された候補者提案資料")

                # 表示切替とコピーボタン
                col_view_prop, col_copy_prop = st.columns([2, 1])
                with col_view_prop:
                    show_formatted_prop = st.checkbox(
                        "📖 整形表示",
                        value=True,
                        key="proposal_formatted",
                        help="Markdownをフォーマットして表示"
                    )
                with col_copy_prop:
                    if st.button("📋 コピー", key="copy_proposal", use_container_width=True):
                        st.toast("✅ クリップボードにコピーしました")
                        escaped_text = st.session_state['anonymous_proposal'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                        st.components.v1.html(f"""
                            <script>
                            navigator.clipboard.writeText(`{escaped_text}`);
                            </script>
                        """, height=0)

                if show_formatted_prop:
                    st.markdown(st.session_state['anonymous_proposal'])
                else:
                    # 編集可能なテキストエリア
                    edited_proposal = st.text_area(
                        "出力結果（編集可能）",
                        value=st.session_state['anonymous_proposal'],
                        height=600,
                        key="edit_proposal"
                    )
                    st.session_state['anonymous_proposal'] = edited_proposal

                # ダウンロードボタン
                st.divider()
                col_dl_prop1, col_dl_prop2, col_dl_prop3 = st.columns(3)
                with col_dl_prop1:
                    st.download_button(
                        "📄 Markdown",
                        data=st.session_state['anonymous_proposal'],
                        file_name=f"anonymous_proposal_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                        mime="text/markdown",
                        key="proposal_md"
                    )
                with col_dl_prop2:
                    st.download_button(
                        "📝 テキスト",
                        data=st.session_state['anonymous_proposal'],
                        file_name=f"anonymous_proposal_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                        mime="text/plain",
                        key="proposal_txt"
                    )
                with col_dl_prop3:
                    html_content = generate_html(
                        st.session_state['anonymous_proposal'],
                        "匿名候補者提案資料"
                    )
                    st.download_button(
                        "🌐 HTML",
                        data=html_content,
                        file_name=f"anonymous_proposal_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                        mime="text/html",
                        key="proposal_html",
                        help="ブラウザで開いて印刷→PDF保存"
                    )

            # 共有リンク作成ボタン
            if get_supabase_client():
                st.divider()
                if st.button("🔗 共有リンク作成", key="share_matching", help="1ヶ月有効の共有リンクを作成"):
                    with st.spinner("共有リンクを作成中..."):
                        share_id = create_share_link(
                            st.session_state['matching_result'],
                            "マッチング分析レポート"
                        )
                    if share_id:
                        try:
                            base_url = st.secrets["APP_URL"]
                        except KeyError:
                            base_url = "https://globalmatch-assistant-zk6s2lwgkqp6xf6xuc9uvi.streamlit.app"
                        share_url = f"{base_url}/?share={share_id}"
                        st.success("✅ 共有リンクを作成しました（1ヶ月有効）")
                        st.code(share_url)
                        st.info("💡 上のURLをコピーしてクライアントに共有してください")
                    else:
                        st.error("❌ 共有リンクの作成に失敗しました")

    elif feature == "📝 CV提案コメント抽出":
        st.subheader("📝 CV提案コメント抽出")
        st.caption("CVから提案用の5項目コメント（英語・各300文字以内）を抽出します。複数CVの一括処理にも対応。")

        # 匿名化レベル選択
        col_mode, col_anon = st.columns(2)
        with col_mode:
            # 入力モード選択
            cv_extract_mode = st.radio(
                "入力モード",
                options=["single", "batch"],
                format_func=lambda x: {
                    "single": "単体CV入力",
                    "batch": "複数CV一括処理"
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
                    st.markdown("##### 入力：英語CV")
                    cv_extract_input = st.text_area(
                        "英語のCVをペースト",
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

                cv_extract_btn = st.button(
                    "🔄 抽出実行",
                    type="primary",
                    use_container_width=True,
                    disabled=not api_key or not cv_extract_input,
                    key="cv_extract_btn"
                )

            with col2:
                st.markdown("##### 出力：提案コメント（英語・各300文字以内）")

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
                                st.caption("🤖 AIがCVからコメントを抽出しています...")
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
                                st.error("❌ 予期せぬエラーが発生しました。しばらく待ってから再試行してください")

                # 結果表示
                if 'cv_extract_result' in st.session_state:
                    col_view, col_copy = st.columns([3, 1])
                    with col_view:
                        show_formatted_cv = st.checkbox("📖 整形表示", value=True, key="cv_extract_formatted")
                    with col_copy:
                        if st.button("📋 コピー", key="copy_cv_extract", use_container_width=True):
                            st.toast("✅ クリップボードにコピーしました")
                            escaped_text = st.session_state['cv_extract_result'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                            st.components.v1.html(f"""
                                <script>
                                navigator.clipboard.writeText(`{escaped_text}`);
                                </script>
                            """, height=0)

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
                                    escaped_text = cv_r['output'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                                    st.components.v1.html(f"""
                                        <script>
                                        navigator.clipboard.writeText(`{escaped_text}`);
                                        </script>
                                    """, height=0)

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

    elif feature == "✉️ 求人打診メール作成":
        st.subheader("✉️ 求人打診メール作成")
        st.caption("面談後に候補者へ送る求人打診メールを簡単に作成できます")

        # saved_jobs / saved_job_sets 初期化
        if 'saved_jobs' not in st.session_state:
            st.session_state['saved_jobs'] = []
        if 'saved_job_sets' not in st.session_state:
            st.session_state['saved_job_sets'] = []

        # --- 基本情報 ---
        col_name, col_sender = st.columns(2)
        with col_name:
            candidate_name = st.text_input(
                "候補者の名前（First Name）",
                placeholder="e.g. Taro",
                key="email_candidate_name"
            )
        with col_sender:
            sender_name = st.selectbox(
                "送信者名",
                options=["Shu", "Ilya", "Hiroshi"],
                key="email_sender_name"
            )

        st.divider()

        # --- 保存済みデータから読み込み ---
        saved_jobs_list = st.session_state.get('saved_jobs', [])
        saved_sets_list = st.session_state.get('saved_job_sets', [])

        if saved_sets_list or saved_jobs_list:
            st.markdown("##### 📂 保存済みデータから読み込み")
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
            "📧 メール生成",
            type="primary",
            use_container_width=True,
            disabled=not candidate_name,
            key="generate_email_btn"
        )

        if generate_btn and candidate_name:
            # メール文面を組み立て
            lines = []
            lines.append(f"Hi {candidate_name}\n")
            lines.append("It was a pleasure speaking with you today.\n")
            lines.append("As discussed, please find the details of the opportunities below.")
            lines.append("If any of these align with your interests, please let me know, and I will proceed with your recommendation to the companies.\n")

            for idx, job in enumerate(jobs, 1):
                # ヘッダー行: タイトルと企業名の組み合わせ
                header_parts = []
                if job["title"]:
                    header_parts.append(job["title"])
                if job["company"]:
                    header_parts.append(job["company"])
                if header_parts:
                    lines.append(f"{idx}. {' | '.join(header_parts)}\n")
                else:
                    lines.append(f"{idx}. (TBD)\n")

                if job["website"]:
                    lines.append(f"Website: {job['website']}\n")
                if job["overview"]:
                    lines.append(f"Overview: {job['overview']}\n")
                if job["key_focus"]:
                    lines.append(f"Key Focus: {job['key_focus']}\n")
                if job["jd_note"]:
                    lines.append(f"JD: {job['jd_note']}\n")
                if job["fit_comment"]:
                    lines.append(f"{job['fit_comment']}\n")

                lines.append("")  # 求人間の空行

            lines.append("We have also attached a short memo regarding our firm's Commitment to Integrity. Simply put, we value your trust and will never submit your profile to any company without your explicit \"green light\". This approach ensures your candidacy is handled strategically and avoids any duplicate submissions that could complicate your search.")
            lines.append("Details: https://drive.google.com/file/d/11HQ42s-zJ_mGFf1D75rHb2mE3hjV21Ib/view?usp=drivesdk\n")
            lines.append("We look forward to hearing your thoughts on these opportunities.")
            lines.append("Best regards,")
            lines.append(sender_name)

            email_text = "\n".join(lines)
            st.session_state['generated_email'] = email_text

        # --- 結果表示 ---
        if 'generated_email' in st.session_state:
            st.divider()
            st.markdown("##### 生成されたメール")

            col_copy_e, col_dl_e = st.columns(2)
            with col_copy_e:
                if st.button("📋 コピー", key="copy_email_btn", use_container_width=True):
                    st.toast("✅ クリップボードにコピーしました")
                    escaped = st.session_state['generated_email'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                    st.components.v1.html(f"""
                        <script>
                        navigator.clipboard.writeText(`{escaped}`);
                        </script>
                    """, height=0)
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

    elif feature == "📦 バッチ処理（複数レジュメ）":
        st.subheader("📦 バッチ処理（複数レジュメ一括変換）")
        st.caption("複数の英語レジュメを一括で日本語に変換します。区切り文字で分割してください。")

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

        batch_btn = st.button(
            "🚀 一括変換実行",
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
                            result["output"] = output
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
                                escaped_text = result['output'].replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('<', '\\x3c')
                                st.components.v1.html(f"""
                                    <script>
                                    navigator.clipboard.writeText(`{escaped_text}`);
                                    </script>
                                """, height=0)

                        if show_formatted:
                            st.markdown(result['output'])
                        else:
                            st.code(result['output'], language="markdown")

                        # ダウンロードボタン
                        col_b1, col_b2 = st.columns(2)
                        with col_b1:
                            st.download_button(
                                "📄 Markdown",
                                data=result['output'],
                                file_name=f"resume_{result['index']}_{datetime.now().strftime('%Y%m%d')}.md",
                                mime="text/markdown",
                                key=f"batch_md_{result['index']}"
                            )
                        with col_b2:
                            html_content = generate_html(result['output'], f"候補者 #{result['index']}")
                            st.download_button(
                                "🌐 HTML",
                                data=html_content,
                                file_name=f"resume_{result['index']}_{datetime.now().strftime('%Y%m%d')}.html",
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
    st.caption("🌏 GlobalMatch Assistant")


if __name__ == "__main__":
    main()
