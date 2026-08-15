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
  TIMEZONE: 'Asia/Tokyo'
};

/**
 * ポーリング対象の公開求人ボード。追加するときはここに1行足すだけ
 * （kind は 'workable' | 'ashby' | 'zookeep' のいずれか）。
 * 注意: 公開ボードに載らない非公開求人（エージェント限定案件）は検知できない。
 */
var BOARDS = [
  { ats: 'Workable', company: 'AI Robot Association', kind: 'workable',
    url: 'https://www.workable.com/api/accounts/ai-robot-association?details=false' },
  { ats: 'Ashby', company: 'ai&', kind: 'ashby',
    url: 'https://api.ashbyhq.com/posting-api/job-board/aiand' },
  { ats: 'Zookeep', company: 'Recursive', kind: 'zookeep',
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
    var events = [];    // {ats, company, type: 'new'|'closed', position}
    var firstRuns = []; // {ats, company, count}
    var warnings = [];  // ボード取得失敗など、人間に見せるべき異常

    var herpThreads = processHerp(state, events, firstRuns);
    var workableThreads = processWorkable(state, events, firstRuns);
    processBoards(state, events, firstRuns, warnings);
    dedupeEvents(events); // メールとボードの両方で検知された同一求人を1件にまとめる

    var message = buildMessage(events, firstRuns, state, warnings);

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
      firstRuns.push({ ats: 'HERP', company: company, count: latest.snapshot.length });
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
  var firstRunCount = 0;

  threads.forEach(function (thread) {
    thread.getMessages().forEach(function (msg) {
      var p = parseWorkableSubject(msg.getSubject());
      if (!p) return;
      var key = p.company + '|' + p.title;
      if (state.workableSeen[key]) return;
      state.workableSeen[key] = msg.getDate().toISOString();
      if (isFirstRun) {
        firstRunCount++;
      } else {
        events.push({ ats: 'Workable', company: p.company, type: 'new', position: p.title });
      }
    });
  });

  if (isFirstRun && firstRunCount > 0) {
    firstRuns.push({ ats: 'Workable', company: '(直近14日の打診メール)', count: firstRunCount });
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

function processBoards(state, events, firstRuns, warnings) {
  if (!state.boards) state.boards = {};
  BOARDS.forEach(function (board) {
    var titles;
    try {
      var resp = UrlFetchApp.fetch(board.url, {
        muteHttpExceptions: true,
        headers: { 'User-Agent': 'Mozilla/5.0' }
      });
      if (resp.getResponseCode() !== 200) throw new Error('HTTP ' + resp.getResponseCode());
      titles = parseBoard(board.kind, resp.getContentText());
    } catch (e) {
      warnings.push('[' + board.ats + '] ' + board.company + ' のボード取得に失敗: ' + e.message);
      return;
    }
    var key = board.ats + '|' + board.company;
    var entry = state.boards[key];
    if (titles.length === 0 && entry && entry.open.length > 0) {
      // ページ改修やAPI仕様変更で0件になった可能性が高い。全件クローズと誤検知しないよう保留して警告
      warnings.push('[' + board.ats + '] ' + board.company + ' のボードが突然0件になりました（要確認・差分判定はスキップ）');
      return;
    }
    if (!entry) {
      state.boards[key] = { open: titles, updatedAt: new Date().toISOString() };
      firstRuns.push({ ats: board.ats, company: board.company, count: titles.length });
      return;
    }
    var diff = computeDiff(entry.open, titles);
    diff.added.forEach(function (pos) {
      events.push({ ats: board.ats, company: board.company, type: 'new', position: pos });
    });
    diff.removed.forEach(function (pos) {
      events.push({ ats: board.ats, company: board.company, type: 'closed', position: pos });
    });
    entry.open = titles;
    entry.updatedAt = new Date().toISOString();
  });
}

/** ボードの生レスポンスから求人タイトル一覧を取り出す（純関数） */
function parseBoard(kind, content) {
  if (kind === 'workable') {
    return (JSON.parse(content).jobs || []).map(function (j) { return j.title; });
  }
  if (kind === 'ashby') {
    return (JSON.parse(content).jobs || [])
      .filter(function (j) { return j.isListed !== false; })
      .map(function (j) { return j.title; });
  }
  if (kind === 'zookeep') {
    return parseZookeepHtml(content);
  }
  throw new Error('未知のボード種別: ' + kind);
}

/** Zookeep公開採用ページに埋め込まれた schema.org ItemList (JSON-LD) から求人名を抽出（純関数） */
function parseZookeepHtml(html) {
  var out = [];
  var re = /<script type="application\/ld\+json">([\s\S]*?)<\/script>/g;
  var m;
  while ((m = re.exec(html)) !== null) {
    try {
      var data = JSON.parse(m[1]);
      if (data['@type'] === 'ItemList' && data.itemListElement) {
        data.itemListElement.forEach(function (item) {
          if (item.name) out.push(item.name);
        });
      }
    } catch (e) {
      // JSON-LDでないscriptブロックは無視
    }
  }
  return out;
}

// ============================================================
// 通知メッセージ
// ============================================================

function buildMessage(events, firstRuns, state, warnings) {
  warnings = warnings || [];
  var newEvents = events.filter(function (e) { return e.type === 'new'; });
  var closedEvents = events.filter(function (e) { return e.type === 'closed'; });
  if (newEvents.length === 0 && closedEvents.length === 0 &&
      firstRuns.length === 0 && warnings.length === 0) return '';

  var today = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyy-MM-dd');
  var lines = ['📋 *ATS求人ウォッチ* (' + today + ')'];

  if (newEvents.length > 0) {
    lines.push('');
    lines.push('🆕 *新規求人 ' + newEvents.length + '件 → Recruitline へ登録*');
    newEvents.forEach(function (e) {
      lines.push('• [' + e.ats + '] ' + e.company + ': ' + e.position);
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
