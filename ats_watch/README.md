# ATS求人ウォッチ（ats_watch）

HERP / Workable の通知メールから求人のオープン/クローズを検知し、**Recruitline への反映漏れ**を毎朝 Slack に通知する Google Apps Script。

## なぜ Apps Script か

- gog CLI は Workspace ポリシーで認証が定期的に失効し（`invalid_rapt`）、依存バッチが**黙って止まる**事故が実際に起きている
- このバッチの目的は「気づけないことの解消」なので、黙って死ぬ構成は採用しない
- Apps Script は Google 側で動くため、ローカルMacの電源・認証状態に依存しない（レジュメ自動保存と同じ方式）
- エラー時は Slack にエラー通知、毎週月曜に生存報告（💓）を送るため、停止に気づける

## 検知の仕組み

| ATS | 検知ソース | カバレッジ |
|---|---|---|
| HERP（大半の企業） | `noreply@v1.herp.cloud` の新規/クローズ通知。**毎回オープン求人の全リスト付き**なので、前回スナップショットとの差分で判定（メールを取りこぼしても次のメールで自己修復） | 新規＋クローズ |
| Workable（AIRoA） | `@jobs.workablemail.com` の「invites you to submit candidates for the ... job」件名 | 新規のみ（クローズ通知が存在しない） |
| Ashby（ai&） | — 候補者関連の通知しか来ない | 対象外（フェーズ2でポータル巡回） |
| Zookeep（Recursive） | — 候補者関連の通知しか来ない | 対象外（フェーズ2でポータル巡回） |

処理済みメールには Gmail ラベル `ats-watch-processed` を付与して二重処理を防ぐ。
状態は Google Drive の `ats_watch_state.json`（マイドライブ直下に自動作成）に保存。

## セットアップ（初回のみ・約5分）

1. https://script.google.com で新規プロジェクト作成（名前: `ATS求人ウォッチ`）
2. `ats_watch.gs` の内容をエディタに貼り付けて保存
3. Slack Webhook URL をクリップボードにコピー:
   ```bash
   security find-generic-password -s biz-batch-webhook -w | pbcopy
   ```
4. プロジェクトの設定（⚙）→ スクリプト プロパティ → `SLACK_WEBHOOK_URL` に貼り付け
5. エディタで関数 `dryRun` を選んで実行 → 権限承認（Gmail / Drive / 外部リクエスト）→ ログで検知内容を確認
6. 関数 `checkAtsEmails` を一度手動実行 → Slack に「📥 初回スナップショット登録」が届くことを確認
7. 関数 `setupTrigger` を実行 → 毎朝8時台の日次トリガーが作成される

## 通知の読み方

- 🆕 **新規求人** → Recruitline の Jobs 画面に JD をアップロードする
- 🔒 **クローズ** → Recruitline で該当求人を CLOSED にする
- 📥 **初回スナップショット登録** → その企業の差分監視が始まった合図（既存分は通知しない）
- 💓 **月曜の生存報告** → バッチが生きている証明。来なくなったら停止を疑う
- ⚠️ **エラー通知** → script.google.com の実行ログを確認

## 開発

パーサは純関数として実装してあり、実メールデータでローカルテストできる:

```bash
node test/test_parse.mjs
```

## 既知の制約・今後（フェーズ2以降）

- Ashby / Zookeep はメールでは検知不能 → エージェントポータルの定期巡回（ブラウザ自動化）で対応予定
- 検知後の JD PDF 取得 → Drive 保存 → Recruitline 一括アップロードの半自動化はフェーズ2
- Recruitline への完全自動反映は Foundry Labs への依頼が必要（取り込みAPI or Drive フォルダ監視）
