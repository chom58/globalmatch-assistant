"""
GlobalMatch Assistant - 人材紹介業務効率化アプリ

外国人エンジニアのレジュメと日本企業の求人票を相互変換・最適化するStreamlitアプリ
"""

import streamlit as st
from groq import Groq
import time
import re
from datetime import datetime

# 定数
MAX_INPUT_CHARS = 15000  # 最大入力文字数
MIN_INPUT_CHARS = 100    # 最小入力文字数
MAX_RETRIES = 3          # API最大リトライ回数

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
            1. 英語のレジュメをペースト
            2. 匿名化オプションを設定
            3. 「変換実行」をクリック

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
            st.markdown("##### 入力：英語レジュメ")
            resume_input = st.text_area(
                "英語のレジュメをペースト",
                height=400,
                placeholder="Paste the English resume here...\n\nExample:\nJohn Doe\nSoftware Engineer with 5+ years of experience...",
                label_visibility="collapsed"
            )

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
                                prompt = get_resume_optimization_prompt(resume_input, anonymize)
                                result = call_groq_api(api_key, prompt)

                                st.session_state['resume_result'] = result
                                st.success("✅ 変換完了！")

                            except ValueError as e:
                                st.error(str(e))
                            except Exception as e:
                                st.error(f"❌ 予期せぬエラー: {str(e)[:200]}")

            # 結果表示
            if 'resume_result' in st.session_state:
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

    elif feature == "求人票魅力化（日→英）":
        st.subheader("📋 求人票魅力化（日本語 → 英語）")
        st.caption("日本企業の求人票を、外国人エンジニアに魅力的な英語JDに変換します")

        col1, col2 = st.columns([1, 1])

        with col1:
            st.markdown("##### 入力：日本語求人票")
            jd_input = st.text_area(
                "日本語の求人票をペースト",
                height=400,
                placeholder="求人票をここに貼り付けてください...\n\n例：\n【募集職種】バックエンドエンジニア\n【業務内容】自社サービスの開発...",
                label_visibility="collapsed"
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
                                prompt = get_jd_transformation_prompt(jd_input)
                                result = call_groq_api(api_key, prompt)

                                st.session_state['jd_result'] = result
                                st.success("✅ 変換完了！")

                            except ValueError as e:
                                st.error(str(e))
                            except Exception as e:
                                st.error(f"❌ 予期せぬエラー: {str(e)[:200]}")

            # 結果表示
            if 'jd_result' in st.session_state:
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

                results = []
                for i, resume in enumerate(resumes):
                    status_text.text(f"🔄 処理中... ({i + 1}/{len(resumes)})")
                    progress_bar.progress((i + 1) / len(resumes))

                    result = {"index": i + 1, "status": "pending", "output": None, "error": None}

                    is_valid, error_msg = validate_input(resume, "resume")
                    if not is_valid:
                        result["status"] = "error"
                        result["error"] = error_msg
                    else:
                        try:
                            prompt = get_resume_optimization_prompt(resume, batch_anonymize)
                            output = call_groq_api(api_key, prompt)
                            result["status"] = "success"
                            result["output"] = output
                        except Exception as e:
                            result["status"] = "error"
                            result["error"] = str(e)

                    results.append(result)
                    time.sleep(1)  # レート制限対策

                st.session_state['batch_results'] = results
                status_text.text("✅ 処理完了！")

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
                with st.expander(f"レジュメ #{result['index']} - {'✅ 成功' if result['status'] == 'success' else '❌ エラー'}"):
                    if result['status'] == 'success':
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
