# 🌏 GlobalMatch Assistant

外国人エンジニア × 日本企業をつなぐ人材紹介業務効率化ツール

## 機能

### 📄 レジュメ最適化（英→日）
外国人エンジニアの英語レジュメを、日本企業の採用担当者向けフォーマットに変換

- 統一フォーマットで出力
- 匿名化機能（完全/軽度/なし）
- 技術スキルのテーブル化

### 🗂 履歴書作成（JIS形式）
英語CVから AI が JIS 形式履歴書の下書きを作成。不足項目（ふりがな・生年月日・住所など）だけ入力すれば Excel / PDF で出力

- テンプレート: `templates/rirekisho_a4.xlsx`（A4 2枚）
- 学歴・職歴は「学歴 → 職歴 → 以上」の慣行で自動配置（最大22行）
- 証明写真のアップロード対応（3:4 に自動トリミング）
- PDF 出力はローカルの LibreOffice（`soffice`）がある環境のみ。Streamlit Cloud では Excel ダウンロードのみ

### 📋 求人票魅力化（日→英）
日本企業の求人票を、外国人エンジニアに魅力的な英語JDに変換

- ビザ・リモート情報の明確化
- グローバル基準のフォーマット

### 📦 バッチ処理
複数のレジュメを一括で変換（最大10件）

## セットアップ

### ローカル実行

```bash
# 依存関係インストール
pip install -r requirements.txt

# APIキー設定
mkdir -p .streamlit
echo 'GROQ_API_KEY = "your-api-key"' > .streamlit/secrets.toml

# 実行
streamlit run app.py
```

### Streamlit Cloud

1. GitHubにリポジトリをプッシュ
2. [Streamlit Cloud](https://share.streamlit.io/)でデプロイ
3. Secrets設定で`GROQ_API_KEY`を追加

## 技術スタック

- **Frontend**: Streamlit
- **AI**: Groq API (Llama 3.3 70B)
- **Language**: Python 3.9+

## ライセンス

Private - All rights reserved
