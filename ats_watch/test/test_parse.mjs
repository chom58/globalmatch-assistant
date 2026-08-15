// ats_watch.gs の純関数パーサを実メールデータで検証する（node test/test_parse.mjs で実行）
// GAS API（GmailApp等）は関数内でしか参照されないため、eval でそのまま読み込める。
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'ats_watch.gs'), 'utf8');
(0, eval)(src); // 間接eval: グローバルスコープで評価し関数宣言を globalThis に載せる
const { parseHerpEmail, parseWorkableSubject, computeDiff, dedupeEvents } = globalThis;

let failed = 0;
function assertEq(actual, expected, label) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) {
    console.log(`  ok: ${label}`);
  } else {
    failed++;
    console.error(`  FAIL: ${label}\n    expected: ${e}\n    actual:   ${a}`);
  }
}

// ---- 実データ: HERP 新規職種メール（2026-08-14 06:37 受信）----
const herpNewSubject = '【HERP Hire】株式会社Third Intelligenceから新規職種への推薦を依頼されました。';
const herpNewBody = `バリュークリエイト
小池 秀 様

株式会社Third Intelligenceから新規職種への推薦を依頼されました。

【新規に推薦を依頼された職種】
AI R&D - 07. Research Engineer - Applied / 顧客協業

【現在推薦を依頼されている職種】
Product - 02. Applied AI Engineer - BtoC Product
BizDev - 03. Applied AI Engineer - Business Development
Corporate - 03. Accounting Manager
AI R&D - 07. Research Engineer - Applied / 顧客協業
Product - 07. Senior Product Designer
AI R&D - 01. Research Director
_Open Position
Product - 11. Software Engineer (Early Career)
BizDev - 05. FDE [Forward Deployed Engineer]
AI R&D - 06. Research Engineer - Next-Gen Algorithm / 次世代アルゴリズム開発
AI R&D - 05. Research Engineer - Computer Vision / 画像
AI R&D - 03. Research Engineer - Post-training & Alignment / 事後学習
Product - 04. Staff Software Engineer - Backend
Product - 06. AI Product Manager
Corporate - 04. General Affairs
Infra - 01. Infrastructure Engineer
Product - 05. Staff Software Engineer - iOS
Product - 03. Staff Software Engineer - Harness / AI Orchestration
BizDev - 02. Staff Software Engineer - Business Development
AI R&D - 04. Research Engineer - Audio / 音声
Product - 01. Head of Customer Support
Corporate - 02. Talent Acquisition
AI R&D - 02. Research Scientist
BizDev - 04. Project Manager - Business Development

▼こちらから推薦を依頼されている職種の詳細情報の確認や、候補者の推薦ができます。
https://agent.herp.cloud/p/XXXX/

---------------------
求職者から選ばれるための人材紹介システム 「ジョブミル」のご案内
`;

// ---- 実データ: HERP クローズメール（2026-08-14 07:23 受信・上記の46分後）----
const herpClosedSubject = '【HERP Hire】株式会社Third Intelligenceから推薦を依頼されていた職種がクローズされました。';
const herpClosedBody = `バリュークリエイト
小池 秀 様

株式会社Third Intelligenceから推薦を依頼されていた職種がクローズされました。

【クローズされた職種】
Corporate - 04. General Affairs

【現在推薦を依頼されている職種】
Product - 02. Applied AI Engineer - BtoC Product
BizDev - 03. Applied AI Engineer - Business Development
Corporate - 03. Accounting Manager
AI R&D - 07. Research Engineer - Applied / 顧客協業
Product - 07. Senior Product Designer
AI R&D - 01. Research Director
_Open Position
Product - 11. Software Engineer (Early Career)
BizDev - 05. FDE [Forward Deployed Engineer]
AI R&D - 06. Research Engineer - Next-Gen Algorithm / 次世代アルゴリズム開発
AI R&D - 05. Research Engineer - Computer Vision / 画像
AI R&D - 03. Research Engineer - Post-training & Alignment / 事後学習
Product - 04. Staff Software Engineer - Backend
Product - 06. AI Product Manager
Infra - 01. Infrastructure Engineer
Product - 05. Staff Software Engineer - iOS
Product - 03. Staff Software Engineer - Harness / AI Orchestration
BizDev - 02. Staff Software Engineer - Business Development
AI R&D - 04. Research Engineer - Audio / 音声
Product - 01. Head of Customer Support
Corporate - 02. Talent Acquisition
AI R&D - 02. Research Scientist
BizDev - 04. Project Manager - Business Development

▼こちらから推薦を依頼されている職種の詳細情報の確認や、候補者の推薦ができます。
https://agent.herp.cloud/p/XXXX/
`;

console.log('parseHerpEmail (新規):');
const pNew = parseHerpEmail(herpNewSubject, herpNewBody);
assertEq(pNew.company, '株式会社Third Intelligence', '企業名');
assertEq(pNew.type, 'new', 'イベント種別');
assertEq(pNew.changed, ['AI R&D - 07. Research Engineer - Applied / 顧客協業'], '新規職種');
assertEq(pNew.snapshot.length, 24, 'スナップショット件数');
assertEq(pNew.snapshot[0], 'Product - 02. Applied AI Engineer - BtoC Product', 'スナップショット先頭');
assertEq(pNew.snapshot[23], 'BizDev - 04. Project Manager - Business Development', 'スナップショット末尾');

console.log('parseHerpEmail (クローズ):');
const pClosed = parseHerpEmail(herpClosedSubject, herpClosedBody);
assertEq(pClosed.company, '株式会社Third Intelligence', '企業名');
assertEq(pClosed.type, 'closed', 'イベント種別');
assertEq(pClosed.changed, ['Corporate - 04. General Affairs'], 'クローズ職種');
assertEq(pClosed.snapshot.length, 23, 'スナップショット件数');

console.log('parseHerpEmail (対象外メール):');
assertEq(parseHerpEmail('Muhammad Usman Akramさんを株式会社Third Intelligenceに推薦しました', 'body'), null, '候補者推薦通知は null');
assertEq(parseHerpEmail('【HERP Hire】株式会社Xから新規職種への推薦を依頼されました。', '本文にセクションなし'), { company: '株式会社X', type: 'new', changed: [], snapshot: [] }, 'セクション欠落は空配列');

console.log('computeDiff (実データの連続2通):');
const diff = computeDiff(pNew.snapshot, pClosed.snapshot);
assertEq(diff.added, [], '追加なし');
assertEq(diff.removed, ['Corporate - 04. General Affairs'], 'クローズ検知');

console.log('computeDiff (取りこぼし自己修復):');
const diff2 = computeDiff(['A', 'B'], ['B', 'C', 'D']);
assertEq(diff2.added, ['C', 'D'], 'メール取りこぼし分も追加検知');
assertEq(diff2.removed, ['A'], 'メール取りこぼし分もクローズ検知');

console.log('parseWorkableSubject:');
assertEq(
  parseWorkableSubject('AI Robot Association invites you to submit candidates for the R&D-037 Robotics Engineer (Teleoperation / UMI) job.'),
  { company: 'AI Robot Association', title: 'R&D-037 Robotics Engineer (Teleoperation / UMI)' },
  '実データ件名'
);
assertEq(parseWorkableSubject('New candidates since July 22, 2026'), null, '日次ダイジェストは null');
assertEq(parseWorkableSubject('New comment about candidate Sahal Hashim'), null, 'コメント通知は null');

console.log('dedupeEvents:');
const events = [
  { ats: 'HERP', company: 'X', type: 'new', position: 'P1' },
  { ats: 'HERP', company: 'X', type: 'new', position: 'P1' },
  { ats: 'HERP', company: 'X', type: 'closed', position: 'P1' }
];
dedupeEvents(events);
assertEq(events.length, 2, '同一イベントのみ除去');

if (failed > 0) {
  console.error(`\n${failed} 件失敗`);
  process.exit(1);
}
console.log('\n全テスト成功');
