/**
 * ATS求人ウォッチ — HERP / Workable の通知メールから求人のオープン/クローズを検知し、
 * Recruitline への反映漏れを毎朝 Slack に通知する Google Apps Script。
 *
 * 仕組み:
 *  - HERP: 「新規職種への推薦を依頼されました」「職種がクローズされました」メールに
 *    毎回「現在推薦を依頼されている職種」の全リストが載っているため、
 *    前回スナップショットとの差分で新規/クローズを確定する（メールを取りこぼしても自己修復する）。
 *  - Workable: 「invites you to submit candidates for the ... job」メールの件名から新規求人を検知。
 *  - 公開求人ボードのポーリング: Workable(AIRoA)・Ashby(ai&)は公開JSON API、
 *    Zookeep(Recursive)は公開採用ページの JSON-LD から全求人リストを毎日取得し、
 *    スナップショット差分で新規/クローズを検知する（メール通知が無いATSをカバー）。
 *  - JD PDF自動取得（フェーズ2）: ボード経由で検知した新規求人はJD本文を取得してPDF化し、
 *    共有ドライブの企業フォルダへ保存。Slack通知にDriveリンクを載せる。
 *    HERPはログイン必須のため自動取得不可（通知に手動取得と明記）。
 *
 * 状態: Google Drive 上の ats_watch_state.json に保存。
 * 設定: スクリプトプロパティ SLACK_WEBHOOK_URL が必須。セットアップ手順は README.md 参照。
 */

var CONFIG = {
  PROCESSED_LABEL: 'ats-watch-processed',
  STATE_FILE_NAME: 'ats_watch_state.json',
  LOOKBACK: 'newer_than:14d',
  PROP_WEBHOOK: 'SLACK_WEBHOOK_URL',
  PROP_STATE_FILE_ID: 'ATS_WATCH_STATE_FILE_ID',
  TIMEZONE: 'Asia/Tokyo',
  JD_ROOT_FOLDER_ID: '0ACk_5dIhVkGlUk9PVA', // 共有ドライブ「JD格納」ルート（直下に企業名フォルダ）
  JD_MAX_ATTEMPTS: 3 // JD取得の失敗リトライ上限（日次実行ごとに1回）
};

/**
 * ポーリング対象の公開求人ボード。追加するときはここに1行足すだけ
 * （kind は 'workable' | 'ashby' | 'zookeep' のいずれか）。
 * 注意: 公開ボードに載らない非公開求人（エージェント限定案件）は検知できない。
 */
var BOARDS = [
  { ats: 'Workable', company: 'AI Robot Association', kind: 'workable', folder: 'AIRoA',
    url: 'https://www.workable.com/api/accounts/ai-robot-association?details=true' }, // details=true でJD本文込み
  { ats: 'Ashby', company: 'ai&', kind: 'ashby', folder: 'ai&',
    url: 'https://api.ashbyhq.com/posting-api/job-board/aiand' },
  { ats: 'Zookeep', company: 'Recursive', kind: 'zookeep', folder: 'Recursive',
    url: 'https://app.zookeep.com/career/Recursive/' }
];

// ============================================================
// エントリポイント
// ============================================================

/** 毎日のトリガーで実行するメイン関数 */
function checkAtsEmails() {
  runWatch(false);
}

/** 動作確認用: ラベル付与・状態保存・Slack送信をせずログに出すだけ */
function dryRun() {
  runWatch(true);
}

/** 手動実行用: 現在監視中の全求人一覧をSlackに送る */
function sendSnapshot() {
  var state = loadState();
  var today = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyy-MM-dd');
  var lines = ['📚 *現在の監視対象求人一覧* (' + today + ')'];
  Object.keys(state.herp || {}).forEach(function (company) {
    var entry = state.herp[company];
    lines.push('');
    lines.push('*[HERP] ' + company + '* (' + entry.open.length + '求人)');
    entry.open.forEach(function (t) { lines.push('• ' + t); });
  });
  Object.keys(state.boards || {}).forEach(function (key) {
    var entry = state.boards[key];
    var parts = key.split('|'); // "ats|company"
    lines.push('');
    lines.push('*[' + parts[0] + '] ' + parts[1] + '* (' + entry.open.length + '求人)');
    entry.open.forEach(function (t) { lines.push('• ' + t); });
  });
  lines.push('');
  lines.push(summaryLine(state));
  postSlack(lines.join('\n'));
}

/** 初回セットアップ用: 毎朝8時台の日次トリガーを作成する（多重登録は自動でスキップ） */
function setupTrigger() {
  var exists = ScriptApp.getProjectTriggers().some(function (t) {
    return t.getHandlerFunction() === 'checkAtsEmails';
  });
  if (exists) {
    Logger.log('トリガーは既に存在します');
    return;
  }
  ScriptApp.newTrigger('checkAtsEmails').timeBased().everyDays(1).atHour(8).create();
  Logger.log('毎日8時台のトリガーを作成しました');
}

function runWatch(isDryRun) {
  try {
    var state = loadState();
    var events = [];    // {ats, company, type: 'new'|'closed', position, jdUrl?}
    var firstRuns = []; // {ats, company, count}
    var warnings = [];  // ボード取得失敗など、人間に見せるべき異常
    var jdTasks = [];   // ボードで検知した新規求人のJD取得タスク

    var herpThreads = processHerp(state, events, firstRuns);
    var workableThreads = processWorkable(state, events, firstRuns);
    processBoards(state, events, firstRuns, warnings, jdTasks);
    dedupeEvents(events); // メールとボードの両方で検知された同一求人を1件にまとめる

    var recovered = fetchAndSaveJds(jdTasks, state, events, warnings, isDryRun);

    var message = buildMessage(events, firstRuns, state, warnings, recovered);

    if (isDryRun) {
      Logger.log(message || '(通知イベントなし)');
      Logger.log('state: ' + JSON.stringify(state, null, 2));
      return;
    }

    if (message) {
      postSlack(message);
    } else if (isMonday()) {
      postSlack(buildHeartbeat(state)); // 週1の生存報告（黙って死んでいないことの証明）
    }

    markProcessed(herpThreads.concat(workableThreads));
    saveState(state);
  } catch (e) {
    if (!isDryRun) {
      try {
        postSlack('⚠️ ATS求人ウォッチでエラーが発生しました: ' + e.message);
      } catch (ignored) {}
    }
    throw e;
  }
}

// ============================================================
// HERP
// ============================================================

function processHerp(state, events, firstRuns) {
  var threads = GmailApp.search(
    'from:noreply@v1.herp.cloud -label:' + CONFIG.PROCESSED_LABEL + ' ' + CONFIG.LOOKBACK
  );
  if (!state.herp) state.herp = {};

  // 全メッセージをパースして日付昇順に整列（同一企業の複数通知を正しい順で反映する）
  var parsed = [];
  threads.forEach(function (thread) {
    thread.getMessages().forEach(function (msg) {
      var p = parseHerpEmail(msg.getSubject(), msg.getPlainBody());
      if (p && p.snapshot.length > 0) { // スナップショット欠落時は判定不能なのでスキップ
        p.date = msg.getDate();
        parsed.push(p);
      }
    });
  });
  parsed.sort(function (a, b) { return a.date - b.date; });

  // 企業ごとに処理。未知の企業は最新スナップショットで初期化のみ行い、
  // 過去メールの履歴をイベントとして再生しない（初回通知が過去の増減で汚れるのを防ぐ）
  var byCompany = {};
  parsed.forEach(function (p) {
    (byCompany[p.company] = byCompany[p.company] || []).push(p);
  });

  Object.keys(byCompany).forEach(function (company) {
    var msgs = byCompany[company];
    var entry = state.herp[company];
    if (!entry) {
      var latest = msgs[msgs.length - 1];
      state.herp[company] = { open: latest.snapshot, updatedAt: latest.date.toISOString() };
      firstRuns.push({ ats: 'HERP', company: company, count: latest.snapshot.length, titles: latest.snapshot });
      return;
    }
    msgs.forEach(function (p) {
      var diff = computeDiff(entry.open, p.snapshot);
      diff.added.forEach(function (pos) {
        events.push({ ats: 'HERP', company: company, type: 'new', position: pos });
      });
      diff.removed.forEach(function (pos) {
        events.push({ ats: 'HERP', company: company, type: 'closed', position: pos });
      });
      entry.open = p.snapshot;
      entry.updatedAt = p.date.toISOString();
    });
  });

  return threads;
}

/**
 * HERP通知メールをパースする（純関数）。
 * 対象外のメール（候補者推薦通知など）は null を返す。
 */
function parseHerpEmail(subject, body) {
  var m = subject.match(
    /【HERP Hire】(.+?)から(新規職種への推薦を依頼されました|推薦を依頼されていた職種がクローズされました)/
  );
  if (!m) return null;
  var type = m[2].indexOf('クローズ') >= 0 ? 'closed' : 'new';
  var changedHeader = type === 'new' ? '【新規に推薦を依頼された職種】' : '【クローズされた職種】';
  return {
    company: m[1],
    type: type,
    changed: extractSection(body, changedHeader),
    snapshot: extractSection(body, '【現在推薦を依頼されている職種】')
  };
}

/** 「【見出し】」直後の行リストを、空行または次のセクションまで読む（純関数） */
function extractSection(body, header) {
  var idx = body.indexOf(header);
  if (idx < 0) return [];
  var lines = body.slice(idx + header.length).split('\n');
  var out = [];
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim();
    if (!line) {
      if (out.length > 0) break; // リスト終端の空行
      continue; // 見出し直後の空行
    }
    if (line.charAt(0) === '【' || line.charAt(0) === '▼') break;
    out.push(line);
  }
  return out;
}

/**
 * 職種ラベルから連番を除去して比較キーにする（純関数）。
 * HERP は職種がクローズされると残りの番号を振り直すため
 * （例: "Product - 04. Applied AI Engineer" → "Product - 02. ..."）、
 * 番号込みで比較すると同一求人がクローズ＋新規のペアとして誤検知される。
 * "DZSA-01-..." のような固定の求人コード形式には触れない。
 * 同名職種が複数枠ある場合はキーが衝突し増減を検知できないが、リナンバリング誤検知の方が実害が大きい。
 */
function normalizePosition(label) {
  return label.replace(/^(.+? - )\d+\.\s*/, '$1');
}

/** 前回オープン一覧と最新スナップショットの差分（純関数・番号リナンバリング耐性あり） */
function computeDiff(prevOpen, snapshot) {
  var prevKeys = {};
  var snapKeys = {};
  prevOpen.forEach(function (p) { prevKeys[normalizePosition(p)] = true; });
  snapshot.forEach(function (p) { snapKeys[normalizePosition(p)] = true; });
  return {
    added: snapshot.filter(function (p) { return !prevKeys[normalizePosition(p)]; }),
    removed: prevOpen.filter(function (p) { return !snapKeys[normalizePosition(p)]; })
  };
}

// ============================================================
// Workable
// ============================================================

function processWorkable(state, events, firstRuns) {
  var threads = GmailApp.search(
    'from:(jobs.workablemail.com) subject:("invites you to submit candidates") ' +
    '-label:' + CONFIG.PROCESSED_LABEL + ' ' + CONFIG.LOOKBACK
  );
  if (!state.workableSeen) state.workableSeen = {};
  var isFirstRun = Object.keys(state.workableSeen).length === 0;
  var firstRunTitles = [];

  threads.forEach(function (thread) {
    thread.getMessages().forEach(function (msg) {
      var p = parseWorkableSubject(msg.getSubject());
      if (!p) return;
      var key = p.company + '|' + p.title;
      if (state.workableSeen[key]) return;
      state.workableSeen[key] = msg.getDate().toISOString();
      if (isFirstRun) {
        firstRunTitles.push(p.title);
      } else {
        events.push({ ats: 'Workable', company: p.company, type: 'new', position: p.title });
      }
    });
  });

  if (isFirstRun && firstRunTitles.length > 0) {
    firstRuns.push({ ats: 'Workable', company: '(直近14日の打診メール)', count: firstRunTitles.length, titles: firstRunTitles });
  }
  return threads;
}

/** Workable の打診メール件名をパースする（純関数） */
function parseWorkableSubject(subject) {
  var m = subject.match(/^(.+?) invites you to submit candidates for the (.+?) job\.?$/);
  if (!m) return null;
  return { company: m[1], title: m[2] };
}

// ============================================================
// 公開求人ボードのポーリング（Workable / Ashby / Zookeep）
// ============================================================

function processBoards(state, events, firstRuns, warnings, jdTasks) {
  if (!state.boards) state.boards = {};
  BOARDS.forEach(function (board) {
    var jobs;
    try {
      var resp = UrlFetchApp.fetch(board.url, {
        muteHttpExceptions: true,
        headers: { 'User-Agent': 'Mozilla/5.0' }
      });
      if (resp.getResponseCode() !== 200) throw new Error('HTTP ' + resp.getResponseCode());
      jobs = parseBoard(board.kind, resp.getContentText());
    } catch (e) {
      warnings.push('[' + board.ats + '] ' + board.company + ' のボード取得に失敗: ' + e.message);
      return;
    }
    var titles = jobs.map(function (j) { return j.title; });
    var key = board.ats + '|' + board.company;
    var entry = state.boards[key];
    if (titles.length === 0 && entry && entry.open.length > 0) {
      // ページ改修やAPI仕様変更で0件になった可能性が高い。全件クローズと誤検知しないよう保留して警告
      warnings.push('[' + board.ats + '] ' + board.company + ' のボードが突然0件になりました（要確認・差分判定はスキップ）');
      return;
    }
    if (!entry) {
      state.boards[key] = { open: titles, updatedAt: new Date().toISOString() };
      firstRuns.push({ ats: board.ats, company: board.company, count: titles.length, titles: titles });
      return;
    }
    var diff = computeDiff(entry.open, titles);
    diff.added.forEach(function (pos) {
      events.push({ ats: board.ats, company: board.company, type: 'new', position: pos });
      var job = null;
      for (var i = 0; i < jobs.length; i++) {
        if (jobs[i].title === pos) { job = jobs[i]; break; }
      }
      jdTasks.push({
        ats: board.ats, company: board.company, folder: board.folder, kind: board.kind,
        title: pos, url: job && job.url || '', descHtml: job && job.descHtml || '', attempts: 0
      });
    });
    diff.removed.forEach(function (pos) {
      events.push({ ats: board.ats, company: board.company, type: 'closed', position: pos });
    });
    entry.open = titles;
    entry.updatedAt = new Date().toISOString();
  });
}

/**
 * ボードの生レスポンスから求人一覧 {title, url, descHtml} を取り出す（純関数）。
 * descHtml が空の求人は fetchAndSaveJds が url の詳細ページから本文を取りに行く（Zookeep）。
 */
function parseBoard(kind, content) {
  if (kind === 'workable') {
    return (JSON.parse(content).jobs || []).map(function (j) {
      return { title: j.title, url: j.url || '', descHtml: j.description || '' };
    });
  }
  if (kind === 'ashby') {
    return (JSON.parse(content).jobs || [])
      .filter(function (j) { return j.isListed !== false; })
      .map(function (j) {
        return { title: j.title, url: j.jobUrl || '', descHtml: j.descriptionHtml || '' };
      });
  }
  if (kind === 'zookeep') {
    return parseZookeepHtml(content);
  }
  throw new Error('未知のボード種別: ' + kind);
}

/** Zookeep公開採用ページに埋め込まれた schema.org ItemList (JSON-LD) から求人一覧を抽出（純関数） */
function parseZookeepHtml(html) {
  var out = [];
  var re = /<script type="application\/ld\+json">([\s\S]*?)<\/script>/g;
  var m;
  while ((m = re.exec(html)) !== null) {
    try {
      var data = JSON.parse(m[1]);
      if (data['@type'] === 'ItemList' && data.itemListElement) {
        data.itemListElement.forEach(function (item) {
          if (item.name) out.push({ title: item.name, url: item.url || '', descHtml: '' });
        });
      }
    } catch (e) {
      // JSON-LDでないscriptブロックは無視
    }
  }
  return out;
}

/** Zookeep求人詳細ページの JSON-LD (schema.org JobPosting) からJD本文HTMLを抽出。無ければ null（純関数） */
function parseZookeepJobPosting(html) {
  var re = /<script type="application\/ld\+json">([\s\S]*?)<\/script>/g;
  var m;
  while ((m = re.exec(html)) !== null) {
    try {
      var data = JSON.parse(m[1]);
      if (data['@type'] === 'JobPosting' && data.description) return data.description;
    } catch (e) {
      // JSON-LDでないscriptブロックは無視
    }
  }
  return null;
}

// ============================================================
// JD PDF自動取得（フェーズ2）
// ============================================================

/**
 * 新規検知した求人＋前回失敗して持ち越したタスク（state.jdPending）のJDをPDF化して
 * 共有ドライブの企業フォルダへ保存する。成功した新規分は events に jdUrl を書き込み、
 * 持ち越し分の成功は戻り値（recovered）として返して通知の別セクションに載せる。
 * 失敗はJD取得だけを警告して検知通知自体は止めない（差分イベントは一度しか発火しないため、
 * リトライキューが無いと取得失敗が恒久的な取り逃がしになる）。
 */
function fetchAndSaveJds(newTasks, state, events, warnings, isDryRun) {
  var pending = state.jdPending || [];
  var tasks = pending.concat(newTasks);
  var recovered = []; // {ats, company, title, jdUrl}
  if (tasks.length === 0) {
    state.jdPending = [];
    return recovered;
  }
  if (isDryRun) {
    tasks.forEach(function (t) {
      Logger.log('[dryRun] JD取得予定: [' + t.ats + '] ' + t.company + ': ' + t.title +
        ' (url=' + (t.url || 'なし') + ', 本文' + (t.descHtml ? '取得済み' : '未取得') + ')');
    });
    return recovered;
  }
  var stillPending = [];
  tasks.forEach(function (task) {
    var isRetry = pending.indexOf(task) >= 0;
    try {
      var jdUrl = saveJdPdf(task, warnings);
      if (isRetry) {
        recovered.push({ ats: task.ats, company: task.company, title: task.title, jdUrl: jdUrl });
      } else {
        attachJdUrl(events, task, jdUrl);
      }
    } catch (e) {
      task.attempts = (task.attempts || 0) + 1;
      if (task.attempts >= CONFIG.JD_MAX_ATTEMPTS) {
        warnings.push('[' + task.ats + '] ' + task.company + ': ' + task.title +
          ' のJD取得を' + task.attempts + '回失敗したため打ち切りました（手動で取得してください）: ' + e.message);
      } else {
        warnings.push('[' + task.ats + '] ' + task.company + ': ' + task.title +
          ' のJD取得に失敗（明日再試行 ' + task.attempts + '/' + CONFIG.JD_MAX_ATTEMPTS + '）: ' + e.message);
        stillPending.push(task);
      }
    }
  });
  state.jdPending = stillPending;
  return recovered;
}

/** JD本文を（必要なら詳細ページから取得して）PDF化し企業フォルダに保存、DriveのURLを返す */
function saveJdPdf(task, warnings) {
  var descHtml = task.descHtml;
  if (!descHtml && task.kind === 'zookeep') {
    if (!task.url) throw new Error('求人詳細ページのURLが不明です');
    var resp = UrlFetchApp.fetch(task.url, {
      muteHttpExceptions: true,
      headers: { 'User-Agent': 'Mozilla/5.0' }
    });
    if (resp.getResponseCode() !== 200) throw new Error('HTTP ' + resp.getResponseCode());
    descHtml = parseZookeepJobPosting(resp.getContentText());
  }
  if (!descHtml) throw new Error('JD本文を取得できませんでした');

  var dateStr = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyy-MM-dd');
  var html = buildJdHtml(task.company, task.ats, task.title, task.url, descHtml, dateStr);
  var baseName = sanitizeFileName(task.title);
  var pdf = Utilities.newBlob(html, 'text/html', baseName + '.html').getAs('application/pdf');
  var folder = getJdFolder(task.folder, warnings);
  var name = baseName + '.pdf';
  if (folder.getFilesByName(name).hasNext()) {
    // 同名JDが既にある場合は上書きせず取得日時つきで別ファイルにする
    name = baseName + '_' + Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyyMMdd_HHmmss') + '.pdf';
  }
  var file = folder.createFile(pdf.setName(name));
  return file.getUrl();
}

/** 共有ドライブルート直下の企業フォルダを取得。無ければ作成して警告に載せる */
function getJdFolder(folderName, warnings) {
  var root = DriveApp.getFolderById(CONFIG.JD_ROOT_FOLDER_ID);
  var it = root.getFoldersByName(folderName);
  if (it.hasNext()) return it.next();
  warnings.push('JDフォルダ「' + folderName + '」が見つからなかったため新規作成しました');
  return root.createFolder(folderName);
}

/** 保存したPDFのURLを、対応する新規イベントに書き込む */
function attachJdUrl(events, task, jdUrl) {
  for (var i = 0; i < events.length; i++) {
    var e = events[i];
    if (e.type === 'new' && e.ats === task.ats && e.company === task.company && e.position === task.title) {
      e.jdUrl = jdUrl;
      return;
    }
  }
}

/** JD PDFの中身になる完全なHTML文書を組み立てる（純関数・日本語のため charset 必須） */
function buildJdHtml(company, ats, title, sourceUrl, descHtml, dateStr) {
  return '<!DOCTYPE html><html><head><meta charset="utf-8"><style>' +
    'body{font-family:"Helvetica Neue",Arial,sans-serif;margin:24px;color:#222;font-size:11px;line-height:1.6;}' +
    'h1.jd-title{font-size:16px;border-bottom:2px solid #333;padding-bottom:6px;}' +
    'table.jd-meta{border-collapse:collapse;margin:8px 0 16px;}' +
    'table.jd-meta td{border:1px solid #ccc;padding:3px 8px;font-size:10px;}' +
    '</style></head><body>' +
    '<h1 class="jd-title">' + escapeHtml(title) + '</h1>' +
    '<table class="jd-meta">' +
    '<tr><td>企業</td><td>' + escapeHtml(company) + '</td></tr>' +
    '<tr><td>ATS</td><td>' + escapeHtml(ats) + '</td></tr>' +
    '<tr><td>取得日</td><td>' + escapeHtml(dateStr) + '（ATS求人ウォッチ自動取得）</td></tr>' +
    (sourceUrl ? '<tr><td>元URL</td><td>' + escapeHtml(sourceUrl) + '</td></tr>' : '') +
    '</table>' +
    descHtml +
    '</body></html>';
}

/** HTMLエスケープ（純関数） */
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Driveのファイル名に使えない・紛らわしい文字を置換する（純関数） */
function sanitizeFileName(title) {
  return String(title)
    .replace(/[\/\\:*?"<>|]/g, '-')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120);
}

/**
 * 手動実行用: 各ボードの先頭1求人でJD取得→PDF生成を試し、マイドライブ直下に保存してURLをログに出す。
 * デプロイ後のPDF品質確認用（企業フォルダは汚さない。確認後は手動で削除してよい）。
 */
function testJdPdf() {
  var dateStr = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyy-MM-dd');
  BOARDS.forEach(function (board) {
    try {
      var resp = UrlFetchApp.fetch(board.url, {
        muteHttpExceptions: true,
        headers: { 'User-Agent': 'Mozilla/5.0' }
      });
      var jobs = parseBoard(board.kind, resp.getContentText());
      if (jobs.length === 0) {
        Logger.log('[' + board.ats + '] 求人0件のためスキップ');
        return;
      }
      var job = jobs[0];
      var descHtml = job.descHtml;
      if (!descHtml && job.url) {
        var r2 = UrlFetchApp.fetch(job.url, {
          muteHttpExceptions: true,
          headers: { 'User-Agent': 'Mozilla/5.0' }
        });
        descHtml = parseZookeepJobPosting(r2.getContentText());
      }
      if (!descHtml) throw new Error('JD本文を取得できませんでした');
      var html = buildJdHtml(board.company, board.ats, job.title, job.url, descHtml, dateStr);
      var pdf = Utilities.newBlob(html, 'text/html', 'test.html').getAs('application/pdf')
        .setName('[test] ' + sanitizeFileName(job.title) + '.pdf');
      var file = DriveApp.getRootFolder().createFile(pdf);
      Logger.log('[' + board.ats + '] ' + job.title + ' → ' + file.getUrl());
    } catch (e) {
      Logger.log('[' + board.ats + '] 失敗: ' + e.message);
    }
  });
}

// ============================================================
// 通知メッセージ
// ============================================================

function buildMessage(events, firstRuns, state, warnings, recovered) {
  warnings = warnings || [];
  recovered = recovered || [];
  var newEvents = events.filter(function (e) { return e.type === 'new'; });
  var closedEvents = events.filter(function (e) { return e.type === 'closed'; });
  if (newEvents.length === 0 && closedEvents.length === 0 &&
      firstRuns.length === 0 && warnings.length === 0 && recovered.length === 0) return '';

  var today = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyy-MM-dd');
  var lines = ['📋 *ATS求人ウォッチ* (' + today + ')'];

  if (newEvents.length > 0) {
    lines.push('');
    lines.push('🆕 *新規求人 ' + newEvents.length + '件 → Recruitline へ登録*');
    newEvents.forEach(function (e) {
      var line = '• [' + e.ats + '] ' + e.company + ': ' + e.position;
      if (e.jdUrl) line += ' → <' + e.jdUrl + '|JD PDF>';
      if (e.ats === 'HERP') line += '（JDはHERPポータルから手動取得）';
      lines.push(line);
    });
  }
  if (recovered.length > 0) {
    lines.push('');
    lines.push('📎 *JD取得リトライ成功*（検知済み求人のPDFを保存しました）');
    recovered.forEach(function (r) {
      lines.push('• [' + r.ats + '] ' + r.company + ': ' + r.title + ' → <' + r.jdUrl + '|JD PDF>');
    });
  }
  if (closedEvents.length > 0) {
    lines.push('');
    lines.push('🔒 *クローズ ' + closedEvents.length + '件 → Recruitline で CLOSED 化*');
    closedEvents.forEach(function (e) {
      lines.push('• [' + e.ats + '] ' + e.company + ': ' + e.position);
    });
  }
  if (firstRuns.length > 0) {
    lines.push('');
    lines.push('📥 *初回スナップショット登録*（差分監視を開始しました）');
    firstRuns.forEach(function (f) {
      lines.push('• [' + f.ats + '] ' + f.company + ': ' + f.count + '求人');
      (f.titles || []).forEach(function (t) {
        lines.push('    ◦ ' + t);
      });
    });
  }
  if (warnings.length > 0) {
    lines.push('');
    lines.push('⚠️ *取得警告*');
    warnings.forEach(function (w) { lines.push('• ' + w); });
  }

  lines.push('');
  lines.push(summaryLine(state));
  return lines.join('\n');
}

function buildHeartbeat(state) {
  return '💓 ATS求人ウォッチ稼働中（今週の差分なし）\n' + summaryLine(state);
}

function summaryLine(state) {
  var herpCompanies = Object.keys(state.herp || {});
  var herpOpen = herpCompanies.reduce(function (sum, c) {
    return sum + state.herp[c].open.length;
  }, 0);
  var boardKeys = Object.keys(state.boards || {});
  var boardOpen = boardKeys.reduce(function (sum, k) {
    return sum + state.boards[k].open.length;
  }, 0);
  return '_監視中: HERP ' + herpCompanies.length + '社 ' + herpOpen + '求人（メール） / ' +
    'ボード ' + boardKeys.length + '社 ' + boardOpen + '求人（Workable・Ashby・Zookeep）_';
}

// ============================================================
// ユーティリティ
// ============================================================

/** 同一イベント（ats+company+type+position）の重複を除去する */
function dedupeEvents(events) {
  var seen = {};
  for (var i = events.length - 1; i >= 0; i--) {
    var key = [events[i].ats, events[i].company, events[i].type, events[i].position].join('|');
    if (seen[key]) {
      events.splice(i, 1);
    } else {
      seen[key] = true;
    }
  }
}

function isMonday() {
  var day = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'u'); // 1=月曜
  return day === '1';
}

function markProcessed(threads) {
  if (threads.length === 0) return;
  var label = GmailApp.getUserLabelByName(CONFIG.PROCESSED_LABEL) ||
    GmailApp.createLabel(CONFIG.PROCESSED_LABEL);
  // addToThreads は一度に100件まで
  for (var i = 0; i < threads.length; i += 100) {
    label.addToThreads(threads.slice(i, i + 100));
  }
}

function loadState() {
  var props = PropertiesService.getScriptProperties();
  var fileId = props.getProperty(CONFIG.PROP_STATE_FILE_ID);
  if (fileId) {
    try {
      var content = DriveApp.getFileById(fileId).getBlob().getDataAsString();
      return JSON.parse(content);
    } catch (e) {
      // ファイルが削除されていた場合は作り直す
    }
  }
  var file = DriveApp.createFile(CONFIG.STATE_FILE_NAME, '{}', 'application/json');
  props.setProperty(CONFIG.PROP_STATE_FILE_ID, file.getId());
  return {};
}

function saveState(state) {
  var fileId = PropertiesService.getScriptProperties().getProperty(CONFIG.PROP_STATE_FILE_ID);
  DriveApp.getFileById(fileId).setContent(JSON.stringify(state, null, 2));
}

function postSlack(text) {
  var webhook = PropertiesService.getScriptProperties().getProperty(CONFIG.PROP_WEBHOOK);
  if (!webhook) throw new Error('スクリプトプロパティ ' + CONFIG.PROP_WEBHOOK + ' が未設定です');
  UrlFetchApp.fetch(webhook, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ text: text })
  });
}
