# Slack CVウォッチ

Slackチャンネル `#all-vc-tai-recruit` に投稿されたCV（PDF / Word）を検知し、共有ドライブへ自動保存するGoogle Apps Script。保存結果は内部のバッチ通知チャンネル（Incoming Webhook）へ通知する。

- **完全無音方式**: Userトークン（自分自身の権限）でチャンネルを読むため、Bot招待が不要で対象チャンネルには一切何も表示されない。相手側（TAI）メンバーから自動化の存在は見えない
- 保存先・命名規則はGmail版「レジュメ自動保存」と同一（共有ドライブ `0AADK2UzmdjokUk9PVA` ルート直下・`YYYYMMDD_元ファイル名`）
- サイズ→MD5の二段階比較で重複判定するため、同じCVがGmailとSlackの両方で届いても1回だけ保存される
- Recruitlineへの自動アップロードは取り込みAPIが無いため未対応（フェーズ2）。当面は通知のリンクから手動アップロード

## セットアップ

### 1. Slack Appの設定（5分・無料）

1. https://api.slack.com/apps → 対象App（VC-TAI Recruit ワークスペースに作成済みのもの）を開く
   （新規の場合: **Create New App** → **Blank app** → ワークスペース選択）
2. 左メニュー **OAuth & Permissions** → **Scopes** → **User Token Scopes** に `files:read` を追加
   （**Bot Token Scopes ではない**ので注意。Botは使わない。誤って追加したBotスコープは削除してよい）
3. ページ上部の **Install to Workspace** → 許可
4. 表示される **User OAuth Token**（`xoxp-` で始まる）を控える（`xoxb-` のBotトークンではない）
5. Slackで `#all-vc-tai-recruit` のチャンネル名クリック → 詳細画面の最下部にある **チャンネルID**（`C` で始まる）を控える

> Bot招待（/invite）は**不要**。自分がチャンネルメンバーであれば読める。
> Userトークンは自分のアカウント権限そのものなので、Apps Scriptのスクリプトプロパティ以外の場所（チャット・リポジトリ等）に貼らないこと。

### 2. Apps Scriptの作成

1. https://script.google.com → **新しいプロジェクト** → 名前を「Slack CVウォッチ」に変更
2. `slack_cv_watch.gs` の中身をエディタへ全文貼り付け（`pbcopy < slack_cv_watch.gs` でコピーすると早い）
3. 左メニュー **プロジェクトの設定** → **スクリプト プロパティ** に以下を追加:

| プロパティ | 値 | 必須 |
|---|---|---|
| `SLACK_USER_TOKEN` | `xoxp-...`（手順1-4） | ✅ |
| `SLACK_CHANNEL_ID` | `C...`（手順1-5） | ✅ |
| `SLACK_WEBHOOK_URL` | 保存通知＋エラー通知用Incoming Webhook（ATSウォッチと同じでよい・Keychain `biz-batch-webhook`） | 推奨 |

### 3. 動作確認 → トリガー設置

エディタ上部の関数選択メニューから順に実行する（初回はGoogleの権限承認ダイアログが出る）:

1. **`dryRun`** — 保存せずに検知結果をログ表示。過去14日分のCVが対象として出るか確認
2. **`checkSlackCvs`** — 本実行。Driveへの保存とWebhookチャンネルへの通知を確認
3. **`setupTrigger`** — 1時間おきの自動実行トリガーを設置

## 運用メモ

- **コード修正時は再貼り付けが必要**（ATSウォッチと同じ運用。リポジトリの `.gs` が正本）
- 状態はDriveの `slack_cv_watch_state.json`（最終取得時刻・処理済みSlackファイルID）。壊れたら削除すれば作り直される（過去14日を再走査するが、重複判定があるので二重保存はされない）
- 除外パターン（JD・求人票・請求書など）はスクリプト冒頭の `EXCLUDE_PATTERNS` を編集
- Userトークンは自分がワークスペースから抜ける・トークンを revoke すると失効する。エラー通知（⚠️）が続いたら **OAuth & Permissions → Reinstall** でトークンを再発行して差し替える

## フェーズ2（未着手）: Recruitline自動アップロード

RecruitlineにはCV取り込みAPIが無い（アップロードはWeb UIの手動操作のみ）。Foundry Labsに以下いずれかを依頼し、提供され次第 `saveCvToDrive` の後段に自動アップロードを追加する:

- 候補者CV取り込みAPI（multipart POST）
- 共有ドライブの保存先フォルダをRecruitline側で監視して自動取り込み

（ATSウォッチのフェーズ3「求人取り込みAPI」依頼と同じ宛先のため、1通にまとめて依頼する）
