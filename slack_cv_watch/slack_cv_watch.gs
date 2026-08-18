/**
 * Slack CVウォッチ — Slackチャンネル（#all-vc-tai-recruit）に投稿されたCV（PDF/Word）を検知し、
 * 共有ドライブへ自動保存する Google Apps Script。
 *
 * 仕組み:
 *  - files.list API（Userトークン＝自分自身の権限）で対象チャンネルの新着ファイルを取得
 *    （conversations.history ではなく files.list を使うことで、スレッド内への投稿も拾える）。
 *    Userトークン方式のためBot招待が不要で、対象チャンネルには一切何も表示されない（完全無音）。
 *  - 拡張子 pdf/doc/docx のみ対象。JD・請求書などはファイル名の除外パターンでスキップ。
 *  - 保存先はGmail版「レジュメ自動保存」と同じ共有ドライブ・同じ命名規則（YYYYMMDD_元ファイル名）。
 *    サイズ→MD5の二段階比較で重複判定するため、同じCVがGmailとSlackの両方で届いても1回だけ保存される。
 *  - 保存結果は内部のバッチ通知チャンネル（Incoming Webhook）へ通知
 *    （Recruitlineへの手動アップロード導線。取り込みAPI提供後は saveCvToDrive の後段に自動化を足す）。
 *
 * 状態: Google Drive 上の slack_cv_watch_state.json に保存。
 * 設定: スクリプトプロパティ SLACK_USER_TOKEN / SLACK_CHANNEL_ID が必須、
 *       SLACK_WEBHOOK_URL（保存通知＋エラー通知用）は推奨。セットアップ手順は README.md 参照。
 */

var CONFIG = {
  STATE_FILE_NAME: 'slack_cv_watch_state.json',
  PROP_STATE_FILE_ID: 'SLACK_CV_WATCH_STATE_FILE_ID',
  PROP_TOKEN: 'SLACK_USER_TOKEN',
  PROP_CHANNEL_ID: 'SLACK_CHANNEL_ID',
  PROP_WEBHOOK: 'SLACK_WEBHOOK_URL',
  CV_FOLDER_ID: '0AADK2UzmdjokUk9PVA', // 共有ドライブ「ドライブ」ルート（Gmail版レジュメ自動保存と同じ保存先）
  TIMEZONE: 'Asia/Tokyo',
  BACKFILL_DAYS: 14, // 初回実行時にさかのぼる日数
  OVERLAP_SEC: 300, // 取りこぼし防止のため前回実行時刻より少し手前から取得（重複は処理済みIDで弾く）
  PROCESSED_KEEP: 500 // stateに保持する処理済みファイルIDの上限
};

/** CVとして扱う拡張子 */
var CV_EXTENSIONS = /\.(pdf|docx?)$/i;

/** ファイル名がこれらにマッチしたらCVではないと判断してスキップ（Gmail版と同じ方針） */
var EXCLUDE_PATTERNS = [
  /(^|[^a-z])JD([^a-z]|$)/i, // \b だと AIRoA_JD_Backend.pdf のような _ 区切りを検知できない
  /求人票/,
  /求人情報/,
  /契約書/,
  /取引先/,
  /登録票/,
  /invoice/i,
  /請求書/,
  /candidates\s+for/i,
  /memo\s+to/i,
  /HERP/i
];

// ============================================================
// エントリポイント
// ============================================================

/** 1時間おきのトリガーで実行するメイン関数 */
function checkSlackCvs() {
  runWatch(false);
}

/** 手動実行用: 保存・スレッド返信なしで検知結果をログに出す */
function dryRun() {
  runWatch(true);
}

/** 1時間おきのトリガーを設置する（既存の同名トリガーは削除してから作る） */
function setupTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'checkSlackCvs') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('checkSlackCvs').timeBased().everyHours(1).create();
  Logger.log('トリガーを設置しました: checkSlackCvs（1時間おき）');
}

// ============================================================
// メイン処理
// ============================================================

function runWatch(isDryRun) {
  try {
    var state = loadState();
    if (!state.processed) state.processed = {};
    var now = Math.floor(Date.now() / 1000);
    var tsFrom = state.lastTs
      ? state.lastTs - CONFIG.OVERLAP_SEC
      : now - CONFIG.BACKFILL_DAYS * 86400;

    var files = fetchSlackFiles(tsFrom);
    Logger.log('取得ファイル数: ' + files.length + '（ts_from=' + tsFrom + '）');

    var folder = DriveApp.getFolderById(CONFIG.CV_FOLDER_ID);
    var sizeIndex = null; // 必要になった時点で構築（Driveの全ファイル走査は1回だけ）
    var saved = []; // 今回保存したファイル（内部通知用）

    files.forEach(function (f) {
      var name = f.name || f.title || '';
      if (state.processed[f.id]) return;
      if (!CV_EXTENSIONS.test(name)) {
        Logger.log('スキップ（対象外拡張子）: ' + name);
        state.processed[f.id] = 'skip:ext';
        return;
      }
      var excluded = EXCLUDE_PATTERNS.some(function (re) { return re.test(name); });
      if (excluded) {
        Logger.log('スキップ（除外パターン）: ' + name);
        state.processed[f.id] = 'skip:pattern';
        return;
      }
      if (isDryRun) {
        Logger.log('[dryRun] 保存対象: ' + name + '（投稿: ' +
          Utilities.formatDate(new Date(f.created * 1000), CONFIG.TIMEZONE, 'yyyy-MM-dd HH:mm') + '）');
        return; // dryRunではstateも更新しない
      }

      var blob = downloadSlackFile(f);
      if (sizeIndex === null) sizeIndex = buildSizeIndex(folder);
      var existing = findDuplicate(sizeIndex, blob);
      if (existing) {
        Logger.log('重複スキップ（Drive保存済み）: ' + name + ' → ' + existing.getName());
        state.processed[f.id] = 'dup:' + existing.getId();
      } else {
        var savedFile = saveCvToDrive(folder, blob, f, name);
        addToSizeIndex(sizeIndex, savedFile);
        Logger.log('保存しました: ' + savedFile.getName());
        state.processed[f.id] = savedFile.getId();
        saved.push({ name: savedFile.getName(), url: savedFile.getUrl() });
      }
    });

    if (!isDryRun) {
      state.lastTs = now;
      pruneProcessed(state);
      saveState(state);
      notifySaved(saved);
    }
  } catch (e) {
    notifyError(e);
    throw e;
  }
}

/** CVを共有ドライブへ保存する（Recruitline取り込みAPIが提供されたらこの後段に自動アップロードを足す） */
function saveCvToDrive(folder, blob, slackFile, name) {
  var dateStr = Utilities.formatDate(new Date(slackFile.created * 1000), CONFIG.TIMEZONE, 'yyyyMMdd');
  return folder.createFile(blob.setName(dateStr + '_' + sanitizeFileName(name)));
}

// ============================================================
// Slack API
// ============================================================

/** files.list をページネーションしながら全件取得する */
function fetchSlackFiles(tsFrom) {
  var channelId = getRequiredProp(CONFIG.PROP_CHANNEL_ID);
  var all = [];
  var page = 1;
  while (true) {
    var resp = slackApi('files.list', {
      channel: channelId,
      ts_from: String(tsFrom),
      count: '100',
      page: String(page)
    });
    all = all.concat(resp.files || []);
    var paging = resp.paging || {};
    if (!paging.pages || page >= paging.pages) break;
    page++;
    if (page > 20) break; // 念のための暴走防止
  }
  return all;
}

/** url_private_download からファイル本体を取得する */
function downloadSlackFile(f) {
  var token = getRequiredProp(CONFIG.PROP_TOKEN);
  var resp = UrlFetchApp.fetch(f.url_private_download || f.url_private, {
    headers: { Authorization: 'Bearer ' + token },
    muteHttpExceptions: true
  });
  if (resp.getResponseCode() !== 200) {
    throw new Error('Slackファイルのダウンロードに失敗: ' + f.name + ' (HTTP ' + resp.getResponseCode() + ')');
  }
  var blob = resp.getBlob();
  // 認証切れ・権限不足だとHTMLログインページが返るため中身で検知する
  var head = blob.getBytes().slice(0, 15);
  var headStr = '';
  for (var i = 0; i < head.length; i++) headStr += String.fromCharCode(head[i] & 0xff);
  if (/<!doctype|<html/i.test(headStr)) {
    throw new Error('Slackファイルの中身がHTMLでした（トークンの権限不足の可能性）: ' + f.name);
  }
  return blob;
}

/**
 * 保存結果を内部のバッチ通知チャンネル（Incoming Webhook）へ通知する。
 * 対象チャンネルには何も投稿しない（完全無音方式）。Webhook未設定ならログのみ。
 */
function notifySaved(saved) {
  if (saved.length === 0) return;
  var webhook = PropertiesService.getScriptProperties().getProperty(CONFIG.PROP_WEBHOOK);
  if (!webhook) {
    Logger.log('SLACK_WEBHOOK_URL 未設定のため保存通知をスキップ（' + saved.length + '件保存済み）');
    return;
  }
  var lines = saved.map(function (s) {
    return '・<' + s.url + '|' + s.name + '>';
  });
  var text = '📄 Slack CVウォッチ: CVを' + saved.length + '件Driveに保存しました\n' +
    lines.join('\n') + '\n（Recruitlineへは手動アップロードをお願いします）';
  try {
    UrlFetchApp.fetch(webhook, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({ text: text })
    });
  } catch (e) {
    // 通知失敗で保存処理全体を落とさない（保存自体は成功している）
    Logger.log('保存通知に失敗: ' + e.message);
  }
}

/** Slack Web API 呼び出し（application/x-www-form-urlencoded・ok:false は例外にする） */
function slackApi(method, params) {
  var token = getRequiredProp(CONFIG.PROP_TOKEN);
  var resp = UrlFetchApp.fetch('https://slack.com/api/' + method, {
    method: 'post',
    headers: { Authorization: 'Bearer ' + token },
    payload: params,
    muteHttpExceptions: true
  });
  var json = JSON.parse(resp.getContentText());
  if (!json.ok) throw new Error('Slack API ' + method + ' が失敗: ' + json.error);
  return json;
}

// ============================================================
// 重複判定（Gmail版レジュメ自動保存と同じ「サイズ→MD5」二段階方式）
// ============================================================

/** 保存先フォルダの既存ファイルを サイズ→ファイルリスト で索引化する */
function buildSizeIndex(folder) {
  var index = {};
  var it = folder.getFiles();
  while (it.hasNext()) {
    var file = it.next();
    var size = file.getSize();
    if (!index[size]) index[size] = [];
    index[size].push(file);
  }
  return index;
}

function addToSizeIndex(index, file) {
  var size = file.getSize();
  if (!index[size]) index[size] = [];
  index[size].push(file);
}

/** 同一サイズのファイルが存在する場合のみMD5を比較し、同内容ならそのDriveファイルを返す */
function findDuplicate(index, blob) {
  var bytes = blob.getBytes();
  var candidates = index[bytes.length];
  if (!candidates || candidates.length === 0) return null;
  var hash = md5Hex(bytes);
  for (var i = 0; i < candidates.length; i++) {
    if (md5Hex(candidates[i].getBlob().getBytes()) === hash) return candidates[i];
  }
  return null;
}

function md5Hex(bytes) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, bytes)
    .map(function (b) { return ('0' + (b & 0xff).toString(16)).slice(-2); })
    .join('');
}

// ============================================================
// state・ユーティリティ
// ============================================================

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

/** 処理済みIDが増えすぎないよう古い順に間引く（Slackのfile idに時系列性は無いため単純に先頭から削る） */
function pruneProcessed(state) {
  var ids = Object.keys(state.processed);
  if (ids.length <= CONFIG.PROCESSED_KEEP) return;
  ids.slice(0, ids.length - CONFIG.PROCESSED_KEEP).forEach(function (id) {
    delete state.processed[id];
  });
}

/** Driveのファイル名に使えない・紛らわしい文字を置換する（純関数） */
function sanitizeFileName(title) {
  return String(title)
    .replace(/[\/\\:*?"<>|]/g, '-')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120);
}

function getRequiredProp(key) {
  var value = PropertiesService.getScriptProperties().getProperty(key);
  if (!value) throw new Error('スクリプトプロパティ ' + key + ' が未設定です');
  return value;
}

/** エラーをSlack Webhookへ通知する（Webhook未設定ならログのみ） */
function notifyError(e) {
  try {
    var webhook = PropertiesService.getScriptProperties().getProperty(CONFIG.PROP_WEBHOOK);
    if (!webhook) return;
    UrlFetchApp.fetch(webhook, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({ text: '⚠️ Slack CVウォッチでエラー: ' + e.message })
    });
  } catch (ignored) {
    // 通知自体の失敗は握りつぶす（元のエラーを優先）
  }
}
