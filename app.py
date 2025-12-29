"""
GlobalMatch Assistant - 人材紹介業務効率化アプリ

外国人エンジニアのレジュメと日本企業の求人票を相互変換・最適化するStreamlitアプリ
"""

import streamlit as st
import streamlit.components.v1
from groq import Groq
import time
import re
from datetime import datetime
import pdfplumber
import io
import secrets
from datetime import timedelta

# Supabase設定（オプション）
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# 定数
MAX_INPUT_CHARS = 15000  # 最大入力文字数
MIN_INPUT_CHARS = 100    # 最小入力文字数
MAX_RETRIES = 3          # API最大リトライ回数
MAX_PDF_SIZE_MB = 10     # 最大PDFサイズ（MB）


def extract_text_from_pdf(uploaded_file) -> tuple[str, str]:
    """PDFファイルからテキストを抽出

    Returns:
        tuple: (extracted_text, error_message)
    """
    try:
        # ファイルサイズチェック
        file_size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
        if file_size_mb > MAX_PDF_SIZE_MB:
            return "", f"ファイルサイズが大きすぎます（{file_size_mb:.1f}MB）。{MAX_PDF_SIZE_MB}MB以下にしてください"

        # PDFを読み込み
        pdf_bytes = io.BytesIO(uploaded_file.getvalue())
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
        return "", f"PDF読み込みエラー: {str(e)[:100]}"


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
    expires_at = datetime.now() + timedelta(days=7)

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
        st.info("💡 共有リンクの有効期限は7日間です")
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
    """共有ビュー用のスタイリングされたHTMLを生成"""

    # MarkdownをHTMLに変換
    html_content = content

    # 見出し変換
    html_content = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)

    # 太字・斜体
    html_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_content)
    html_content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html_content)

    # リスト
    html_content = re.sub(r'^- (.+)$', r'<li>\1</li>', html_content, flags=re.MULTILINE)

    # テーブル変換
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

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: "Hiragino Kaku Gothic ProN", "Hiragino Sans", "Yu Gothic", sans-serif;
            font-size: 14px;
            line-height: 1.8;
            color: #333;
            padding: 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #1e3a5f 0%, #2d4a6f 100%);
            color: white;
            padding: 25px 30px;
            text-align: center;
        }}
        .header h1 {{
            font-size: 22px;
            margin-bottom: 8px;
        }}
        .header .meta {{
            font-size: 12px;
            opacity: 0.8;
        }}
        .badge {{
            display: inline-block;
            background: rgba(255,255,255,0.2);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            margin: 0 5px;
        }}
        .content {{
            padding: 30px;
        }}
        h2 {{
            font-size: 16px;
            color: #1e3a5f;
            background: #f0f4f8;
            padding: 10px 15px;
            margin: 25px 0 15px 0;
            border-left: 4px solid #1e3a5f;
            border-radius: 0 8px 8px 0;
        }}
        h3 {{
            font-size: 14px;
            color: #374151;
            margin: 18px 0 10px 0;
            padding-left: 12px;
            border-left: 3px solid #ddd;
        }}
        p {{ margin: 10px 0; }}
        li {{ margin: 6px 0; margin-left: 20px; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            border-radius: 8px;
            overflow: hidden;
        }}
        th, td {{
            border: 1px solid #e5e7eb;
            padding: 12px;
            text-align: left;
        }}
        th {{
            background: #1e3a5f;
            color: white;
            font-weight: 600;
        }}
        tr:nth-child(even) {{ background: #f9fafb; }}
        strong {{ color: #1e3a5f; }}
        .footer {{
            background: #f8fafc;
            padding: 15px 30px;
            text-align: center;
            font-size: 11px;
            color: #6b7280;
            border-top: 1px solid #e5e7eb;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌏 {title}</h1>
            <div class="meta">
                <span class="badge">📅 有効期限: {expires_at}</span>
                <span class="badge">👁 閲覧数: {view_count}</span>
            </div>
        </div>
        <div class="content">
            {html_content}
        </div>
        <div class="footer">
            Powered by GlobalMatch Assistant
        </div>
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

    return f"""あなたは人材紹介会社のエキスパートコンサルタントです。
外国人エンジニアの英語レジュメを、日本企業の採用担当者向けに最適化された日本語ドキュメントに変換してください。

{anonymize_instruction}

【出力フォーマット - 厳守】
以下の「日本企業向け標準フォーマット」に必ず従って出力してください。
元のレジュメのフォーマットに関わらず、この構造で統一してください。

---

## 1. 基本情報
{"- 氏名：（イニシャルで表記。例：T.Y.）\n- 連絡先：[非公開]\n- 所在地：（都道府県のみ）" if anonymize in ["full", "light"] else "- 氏名：\n- 連絡先：\n- 所在地："}

## 2. 推薦サマリ
*（300文字程度で、この候補者の経歴の要約と強みを記載。採用担当者が最初に読む部分として魅力的に）*

## 3. 技術スタック
| カテゴリ | スキル |
|---------|--------|
| プログラミング言語 | |
| フレームワーク | |
| データベース | |
| インフラ/クラウド | |
| ツール/その他 | |

## 4. 語学・ビザ
- **日本語レベル**: （JLPTレベル、日本滞在歴、実務での使用経験から推定）
- **英語レベル**:
- **ビザステータス**: （記載があれば、なければ「要確認」）

## 5. 職務経歴
*（新しい順に記載）*

### 【会社名】（期間：YYYY年MM月 〜 YYYY年MM月）
**役職/ポジション**

**担当業務・成果:**
- （具体的な成果を箇条書きで）
- （数値があれば積極的に記載）

---

【入力レジュメ】
{resume_text}

上記のレジュメを解析し、指定フォーマットで日本語に変換してください。
不明な項目は「記載なし」または「要確認」としてください。
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

    return f"""You are an expert HR consultant.
Anonymize the following English resume while keeping it in English and maintaining a professional format.

{anonymize_instruction}

【OUTPUT FORMAT - STRICTLY FOLLOW】
Maintain the resume in English with this standardized structure:

---

## 1. Basic Information
{"- Name: (Initials only, e.g., J.S.)\n- Contact: [Confidential]\n- Location: (State/Country only)" if anonymize in ["full", "light"] else "- Name:\n- Contact:\n- Location:"}

## 2. Professional Summary
*(2-3 sentences highlighting key qualifications and strengths)*

## 3. Technical Skills
| Category | Skills |
|----------|--------|
| Programming Languages | |
| Frameworks & Libraries | |
| Databases | |
| Cloud & Infrastructure | |
| Tools & Others | |

## 4. Work Experience
*(Most recent first)*

### [Company Description] (Period: MMM YYYY – MMM YYYY)
**Position/Role**

**Key Responsibilities & Achievements:**
- (Specific achievements with metrics where available)
- (Impact and results)

## 5. Education
- **Degree** - [University Description], Year

## 6. Certifications
- Certification names (without ID numbers)

---

【INPUT RESUME】
{resume_text}

Parse the above resume and output in the specified format in English.
Mark unknown items as "Not specified" or "To be confirmed".
"""


def get_jd_transformation_prompt(jd_text: str) -> str:
    """求人票変換用のプロンプトを生成"""

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

## 🎯 Quick Facts
| | |
|---|---|
| **Visa Sponsorship** | (Yes/No/Available for qualified candidates) |
| **Remote Work** | (Full Remote/Hybrid/On-site - specify policy) |
| **Language Requirements** | (English OK/Japanese N2+/Bilingual environment) |
| **Salary Range** | (If available, convert to USD range as reference) |
| **Location** | |

## 💡 Why Join Us?
*(2-3 compelling sentences about the company culture, growth opportunity, or unique value proposition)*

## 🚀 What You'll Do
*(Key responsibilities in bullet points - focus on impact, not just tasks)*

## ✅ What We're Looking For
**Must-have:**
-

**Nice-to-have:**
-

## 🎁 Benefits & Perks
*(Highlight benefits that appeal to international candidates)*

## 📝 About the Company
*(Brief company introduction)*

## 📧 How to Apply
*(Application process)*

---

【元の求人票】
{jd_text}

上記を解析し、外国人エンジニアに魅力的な英語JDに変換してください。
不明な項目は「To be discussed」または「Contact for details」としてください。
ビザサポートが明記されていない場合は「Please inquire」と記載してください。
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

    return True, ""


def call_groq_api(api_key: str, prompt: str) -> str:
    """Groq APIを呼び出してテキストを生成（リトライ機能付き）"""

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
    raise ValueError(f"🔄 処理に失敗しました（{MAX_RETRIES}回試行）: {str(last_error)[:100]}")


def generate_html(content: str, title: str) -> str:
    """MarkdownテキストからHTMLを生成（印刷用スタイル付き）"""

    # MarkdownをHTMLに変換
    html_content = content

    # 見出し変換
    html_content = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)

    # 太字・斜体・コード
    html_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_content)
    html_content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html_content)
    html_content = re.sub(r'`(.+?)`', r'<code>\1</code>', html_content)

    # リスト
    html_content = re.sub(r'^- (.+)$', r'<li>\1</li>', html_content, flags=re.MULTILINE)

    # テーブル変換
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

    # HTMLテンプレート
    html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
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
        <h1>{title}</h1>
    </div>
    <div class="generated">{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
    <div class="content">
        {html_content}
    </div>
</body>
</html>'''

    return html


def process_batch_resumes(api_key: str, resumes: list[str], anonymize: str) -> list[dict]:
    """複数のレジュメを一括処理"""

    results = []
    for i, resume in enumerate(resumes):
        result = {"index": i + 1, "status": "pending", "output": None, "error": None}

        # バリデーション
        is_valid, error_msg = validate_input(resume, "resume")
        if not is_valid:
            result["status"] = "error"
            result["error"] = error_msg
            results.append(result)
            continue

        try:
            prompt = get_resume_optimization_prompt(resume, anonymize)
            output = call_groq_api(api_key, prompt)
            result["status"] = "success"
            result["output"] = output
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        results.append(result)

    return results


def main():
    """メインアプリケーション"""

    # URLパラメータで共有IDがあれば共有ビューを表示
    share_id = st.query_params.get("share")
    if share_id:
        show_shared_view(share_id)
        return  # 通常のUIは表示しない

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

        # 機能選択
        st.subheader("📋 機能選択")
        feature = st.radio(
            "変換モードを選択",
            options=[
                "レジュメ最適化（英→日）",
                "レジュメ匿名化（英→英）",
                "求人票魅力化（日→英）",
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
                        with st.spinner("🤖 AIがレジュメを解析・構造化しています..."):
                            try:
                                start_time = time.time()
                                prompt = get_resume_optimization_prompt(resume_input, anonymize)
                                result = call_groq_api(api_key, prompt)
                                elapsed_time = time.time() - start_time

                                st.session_state['resume_result'] = result
                                st.session_state['resume_time'] = elapsed_time
                                st.success(f"✅ 変換完了！（{elapsed_time:.1f}秒）")

                            except ValueError as e:
                                st.error(str(e))
                            except Exception as e:
                                st.error(f"❌ 予期せぬエラー: {str(e)[:200]}")

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
                        st.components.v1.html(f"""
                            <script>
                            navigator.clipboard.writeText(`{st.session_state['resume_result'].replace('`', '\\`').replace('$', '\\$')}`);
                            </script>
                        """, height=0)

                if show_formatted:
                    st.markdown(st.session_state['resume_result'])
                else:
                    st.code(st.session_state['resume_result'], language="markdown")

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

                # 共有リンク作成ボタン
                if get_supabase_client():
                    st.divider()
                    if st.button("🔗 共有リンク作成", key="share_resume_jp", help="7日間有効の共有リンクを作成"):
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
                            st.success("✅ 共有リンクを作成しました（7日間有効）")
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
                        with st.spinner("🤖 AIがレジュメを匿名化しています..."):
                            try:
                                start_time = time.time()
                                prompt = get_english_anonymization_prompt(resume_en_input, anonymize_en)
                                result = call_groq_api(api_key, prompt)
                                elapsed_time = time.time() - start_time

                                st.session_state['resume_en_result'] = result
                                st.session_state['resume_en_time'] = elapsed_time
                                st.success(f"✅ 匿名化完了！（{elapsed_time:.1f}秒）")

                            except ValueError as e:
                                st.error(str(e))
                            except Exception as e:
                                st.error(f"❌ 予期せぬエラー: {str(e)[:200]}")

            # 結果表示
            if 'resume_en_result' in st.session_state:
                col_view, col_copy = st.columns([2, 1])
                with col_view:
                    show_formatted_en = st.checkbox("📖 整形表示", value=False, key="resume_en_formatted")
                with col_copy:
                    if st.button("📋 コピー", key="copy_resume_en", use_container_width=True):
                        st.toast("✅ クリップボードにコピーしました")
                        st.components.v1.html(f"""
                            <script>
                            navigator.clipboard.writeText(`{st.session_state['resume_en_result'].replace('`', '\\`').replace('$', '\\$')}`);
                            </script>
                        """, height=0)

                if show_formatted_en:
                    st.markdown(st.session_state['resume_en_result'])
                else:
                    st.code(st.session_state['resume_en_result'], language="markdown")

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

                # 共有リンク作成ボタン
                if get_supabase_client():
                    st.divider()
                    if st.button("🔗 共有リンク作成", key="share_resume_en", help="7日間有効の共有リンクを作成"):
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
                            st.success("✅ 共有リンクを作成しました（7日間有効）")
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
                        with st.spinner("🤖 AIが求人票を解析・魅力化しています..."):
                            try:
                                start_time = time.time()
                                prompt = get_jd_transformation_prompt(jd_input)
                                result = call_groq_api(api_key, prompt)
                                elapsed_time = time.time() - start_time

                                st.session_state['jd_result'] = result
                                st.session_state['jd_time'] = elapsed_time
                                st.success(f"✅ 変換完了！（{elapsed_time:.1f}秒）")

                            except ValueError as e:
                                st.error(str(e))
                            except Exception as e:
                                st.error(f"❌ 予期せぬエラー: {str(e)[:200]}")

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
                        st.components.v1.html(f"""
                            <script>
                            navigator.clipboard.writeText(`{st.session_state['jd_result'].replace('`', '\\`').replace('$', '\\$')}`);
                            </script>
                        """, height=0)

                if show_formatted:
                    st.markdown(st.session_state['jd_result'])
                else:
                    st.code(st.session_state['jd_result'], language="markdown")

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
                    if st.button("🔗 共有リンク作成", key="share_jd", help="7日間有効の共有リンクを作成"):
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
                            st.success("✅ 共有リンクを作成しました（7日間有効）")
                            st.code(share_url)
                            st.info("💡 上のURLをコピーしてクライアントに共有してください")
                        else:
                            st.error("❌ 共有リンクの作成に失敗しました")

    else:  # バッチ処理
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
                results = []
                for i, resume in enumerate(resumes):
                    status_text.text(f"🔄 処理中... ({i + 1}/{len(resumes)})")
                    progress_bar.progress((i + 1) / len(resumes))

                    result = {"index": i + 1, "status": "pending", "output": None, "error": None, "time": 0}

                    is_valid, error_msg = validate_input(resume, "resume")
                    if not is_valid:
                        result["status"] = "error"
                        result["error"] = error_msg
                    else:
                        try:
                            item_start = time.time()
                            prompt = get_resume_optimization_prompt(resume, batch_anonymize)
                            output = call_groq_api(api_key, prompt)
                            result["status"] = "success"
                            result["output"] = output
                            result["time"] = time.time() - item_start
                        except Exception as e:
                            result["status"] = "error"
                            result["error"] = str(e)

                    results.append(result)
                    time.sleep(1)  # レート制限対策

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
                                st.components.v1.html(f"""
                                    <script>
                                    navigator.clipboard.writeText(`{result['output'].replace('`', '\\`').replace('$', '\\$')}`);
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
