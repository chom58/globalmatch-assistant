/**
 * ATS求人ウォッチ — HERP / Workable の通知メールから求人のオープン/クローズを検知し、
 * Recruitline への反映漏れを毎朝 Slack に通知する Google Apps Script。
 *
 * 仕組み:
 *  - HERP: 「新規職種への推薦を依頼されました」「職種がクローズされました」メールに
 *    毎回「現在推薦を依頼されている職種」の全リストが載っているため、
 *    前回スナップショットとの差分で新規/クローズを確定する（メールを取りこぼしても自己修復する）。
 *  - Workable: 「invites you to submit candidates for the ... job」メールの件名から新規求人を検知。
 *    クローズ通知は存在しないため新規のみ。
 *  - Ashby / Zookeep は求人の増減を示すメールを送ってこないため対象外（README参照）。
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

    var herpThreads = processHerp(state, events, firstRuns);
    var workableThreads = processWorkable(state, events, firstRuns);

    var message = buildMessage(events, firstRuns, state);

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

  // 全メッセージをパースして日付昇順に処理（同一企業の複数通知を正しい順で反映する）
  var parsed = [];
  threads.forEach(function (thread) {
    thread.getMessages().forEach(function (msg) {
      var p = parseHerpEmail(msg.getSubject(), msg.getPlainBody());
      if (p) {
        p.date = msg.getDate();
        parsed.push(p);
      }
    });
  });
  parsed.sort(function (a, b) { return a.date - b.date; });

  parsed.forEach(function (p) {
    if (p.snapshot.length === 0) return; // スナップショット欠落時は判定不能なのでスキップ
    var entry = state.herp[p.company];
    if (!entry) {
      // 初回はスナップショット登録のみ（全件を「新規」として通知しない）
      state.herp[p.company] = { open: p.snapshot, updatedAt: p.date.toISOString() };
      firstRuns.push({ ats: 'HERP', company: p.company, count: p.snapshot.length });
      return;
    }
    var diff = computeDiff(entry.open, p.snapshot);
    diff.added.forEach(function (pos) {
      events.push({ ats: 'HERP', company: p.company, type: 'new', position: pos });
    });
    diff.removed.forEach(function (pos) {
      events.push({ ats: 'HERP', company: p.company, type: 'closed', position: pos });
    });
    entry.open = p.snapshot;
    entry.updatedAt = p.date.toISOString();
  });

  dedupeEvents(events);
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

/** 前回オープン一覧と最新スナップショットの差分（純関数） */
function computeDiff(prevOpen, snapshot) {
  var prevSet = {};
  var snapSet = {};
  prevOpen.forEach(function (p) { prevSet[p] = true; });
  snapshot.forEach(function (p) { snapSet[p] = true; });
  return {
    added: snapshot.filter(function (p) { return !prevSet[p]; }),
    removed: prevOpen.filter(function (p) { return !snapSet[p]; })
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
// 通知メッセージ
// ============================================================

function buildMessage(events, firstRuns, state) {
  var newEvents = events.filter(function (e) { return e.type === 'new'; });
  var closedEvents = events.filter(function (e) { return e.type === 'closed'; });
  if (newEvents.length === 0 && closedEvents.length === 0 && firstRuns.length === 0) return '';

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
  var workableCount = Object.keys(state.workableSeen || {}).length;
  return '_監視中: HERP ' + herpCompanies.length + '社 ' + herpOpen + '求人 / Workable 累計 ' +
    workableCount + '求人（Ashby・Zookeepはメール通知なしのため対象外）_';
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
