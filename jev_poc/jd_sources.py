"""
ATS 求人ウォッチの状態と Drive の JD ライブラリを突き合わせる（match.py から使う）

- 募集状況: ATS ウォッチが監視している会社は、募集中一覧にない Drive の JD を「closed」にする。
  監視外の会社は「unknown」（判断材料がないので対象に残す）
- 補完: 公開求人ボード（Workable / Ashby）で募集中なのに Drive に JD がない求人は、
  公開 API から本文を取って JD に加える。HERP はログイン必須のため名前の一覧だけ返す

状態ファイル: マイドライブの ats_watch_state.json（ATS ウォッチの Apps Script が毎朝更新）
"""

import difflib
import html
import json
import os
import re
import time
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

def drive_path(relative: str) -> Path:
    """Google Drive for desktop のマウントから relative が存在するものを返す（複数アカウント対応）。
    アカウント名（メールアドレス）をコードに書かないため、CloudStorage 配下を探す。
    環境変数 JEV_DRIVE_ROOT でマウント先を固定できる"""
    if os.environ.get("JEV_DRIVE_ROOT"):
        return Path(os.environ["JEV_DRIVE_ROOT"]) / relative
    mounts = sorted((Path.home() / "Library/CloudStorage").glob("GoogleDrive-*"))
    for mount in mounts:
        if (mount / relative).exists():
            return mount / relative
    return (mounts[0] if mounts else Path.home() / "Library/CloudStorage/GoogleDrive") / relative


DEFAULT_STATE = drive_path("マイドライブ/ats_watch_state.json")

# 取引先ごとの設定（公開リポに取引先名を載せないため gitignore 済みのファイルに置く）。
# 形式は sources.example.json を参照。ファイルがなければ募集状況の判定と補完はしない
CONFIG_PATH = Path(__file__).with_name("sources.local.json")


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


_CONFIG = load_config()
# ATS ウォッチ／HRMOS 上の会社名 → Drive の JD フォルダ名（全角・半角違いなど複数可）
COMPANY_FOLDERS: dict[str, list[str]] = _CONFIG.get("company_folders", {})
# 公開 API から JD 本文を取れるボード: 会社名 → (ATS 種別 "Workable" | "Ashby", API の URL)
BOARD_APIS: dict[str, tuple[str, str]] = {k: tuple(v) for k, v in _CONFIG.get("board_apis", {}).items()}
# 求人名の末尾に付く社名など、照合前に取り除く語（小文字）
TITLE_SUFFIXES: list[str] = [s.lower() for s in _CONFIG.get("title_suffixes", [])]

# HRMOS の書き出し（hrmos_export.js がブラウザから保存する）を探す場所
HRMOS_EXPORT_DIRS = [Path.home() / "Downloads"]

MATCH_RATIO = 0.8
# HERP の一覧は通知メールが届いたときしか更新されない。これより古い一覧では締め切り判定をしない
STALE_DAYS = 21

_CODE = re.compile(r"\b([A-Z&]{2,5}-\d{2,4})\b")  # 「R&D-037」「COM-102」のような求人コード


def _norm(title: str) -> str:
    s = unicodedata.normalize("NFKC", html.unescape(title)).lower().replace("_", " ")  # Drive のファイル名は「_」区切りがある
    s = re.sub(r"\s+jobs by workable$", "", s)
    s = re.sub(r"^(product|bizdev|corporate|ai r&d|infra)\s*-\s*\d+\.\s*", "", s)  # HERP の職種番号（振り直される）
    s = re.sub(r"^[【\[]?[a-z&]{2,5}-\d{2,4}[】\]]?[\s-]*", "", s)                # 「R&D-037」「【R&D-012】」形式の求人コード
    s = re.sub(r"^[a-z]{2,5}-\d+-", "", s)                                          # 「DZD-03-」形式の求人コード
    s = re.sub(r"(?<=\S)\s+[-|@]?\s*株式会社.*$", "", s)                            # 「… - 株式会社X」「… 株式会社X」
    s = re.sub(r"\s*[-|@]\s*herp hire.*$", "", s)
    for suffix in TITLE_SUFFIXES:                                                   # 「… - 社名」「…   社名」（「_」区切り由来）
        s = re.sub(r"(\s*[-|@]\s*|\s{2,})" + re.escape(suffix) + r".*$", "", s)
    s = re.sub(r"\s+at\s+\w+$", "", s)
    return re.sub(r"[^\w]+", " ", s).strip()


def _lang_variant(title: str) -> str | None:
    """「… / English」「… / Japanese」のような言語別の求人を区別する"""
    s = unicodedata.normalize("NFKC", title).lower()
    en, ja = bool(re.search(r"english|英語", s)), bool(re.search(r"japanese|日本語", s))
    return "en" if en and not ja else "ja" if ja and not en else None


def same_job(a: str, b: str) -> bool:
    """求人コードが両方にあればコードで、なければ正規化した求人名の類似度で判定する。
    英語版と日本語版を別求人として出している会社があるため、言語表記が食い違えば別の求人とみなす"""
    ca, cb = _CODE.search(unicodedata.normalize("NFKC", a)), _CODE.search(unicodedata.normalize("NFKC", b))
    if ca and cb:
        return ca.group(1) == cb.group(1)
    la, lb = _lang_variant(a), _lang_variant(b)
    if la and lb and la != lb:
        return False
    na, nb = _norm(a), _norm(b)
    short, long_ = sorted((na, nb), key=len)
    # 「Service Robot System Engineer」と「… at Development Division」のように片方が他方を含む場合
    if len(short.split()) >= 3 and short in long_:
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= MATCH_RATIO


def _epoch(iso: str | None) -> float:
    if not iso:
        return 0.0
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def load_open_jobs(state_path: Path = DEFAULT_STATE, now: float | None = None) -> dict[str, dict]:
    """{ATS上の会社名: {"ats", "open": [求人名], "updated": epoch}}。STALE_DAYS より古い一覧は除く"""
    now = time.time() if now is None else now
    state = json.loads(Path(state_path).read_text())
    entries = [(c, "HERP", v) for c, v in state.get("herp", {}).items()]
    entries += [(k.split("|", 1)[1], k.split("|", 1)[0], v) for k, v in state.get("boards", {}).items()]
    out = {}
    for company, ats, v in entries:
        updated = _epoch(v.get("updatedAt"))
        if now - updated <= STALE_DAYS * 86400:
            out[company] = {"ats": ats, "open": v["open"], "updated": updated}
    return out


def load_hrmos_export(dirs: list[Path] | None = None, now: float | None = None) -> tuple[dict, dict]:
    """最新の hrmos_export_*.json から (open_jobs 形式, board_jobs 形式) を作る。なければ空。
    アーカイブ済み・締め切り日を過ぎた求人は募集中に含めない"""
    now = time.time() if now is None else now
    files = [f for d in (dirs or HRMOS_EXPORT_DIRS) if d.exists() for f in d.glob("hrmos_export_*.json")]
    if not files:
        return {}, {}
    latest = max(files, key=lambda f: f.stat().st_mtime)
    data = json.loads(latest.read_text())
    exported = _epoch(data.get("exportedAt"))
    if now - exported > STALE_DAYS * 86400:
        return {}, {}
    def is_live(job: dict) -> bool:
        return not job.get("archived") and (not job.get("closeAt") or _epoch(job["closeAt"]) > exported)

    open_jobs, board = {}, {}
    for corp in data.get("corporates", []):
        live = [j for j in corp["jobs"] if is_live(j)]
        open_jobs[corp["name"]] = {"ats": "HRMOS", "open": [j["title"] for j in live], "updated": exported}
        board[corp["name"]] = [{"title": j["title"], "url": f"hrmos:{j['jobId']}", "text": j.get("text", "")} for j in live]
    return open_jobs, board


def annotate_status(jds: list[dict], open_jobs: dict[str, dict]) -> None:
    """各 JD に status（open / closed / unknown）を付ける。
    監視外の会社、一覧が古い会社、一覧の更新より後に保存された JD は unknown（対象に残す）"""
    folder_to_company = {f: c for c, folders in COMPANY_FOLDERS.items() for f in folders}
    for jd in jds:
        info = open_jobs.get(folder_to_company.get(jd["company"], ""))
        if info is None or jd.get("mtime", 0) > info["updated"]:
            jd["status"] = "unknown"
        elif any(same_job(jd["title"], o) for o in info["open"]):
            jd["status"] = "open"
        else:
            jd["status"] = "closed"


def _html_to_text(s: str) -> str:
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6])>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(s)).strip()


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read())


def fetch_board_jobs(cache_dir: Path, max_age_hours: float = 20) -> dict[str, list[dict]]:
    """公開ボードの募集中求人（本文つき）。1日1回程度だけ取り直す"""
    cache = cache_dir / "board_jobs.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < max_age_hours * 3600:
        return json.loads(cache.read_text())
    out = {}
    for company, (ats, url) in BOARD_APIS.items():
        data = _fetch_json(url)
        if ats == "Workable":
            out[company] = [{"title": j["title"], "url": j.get("url", ""),
                             "text": _html_to_text(j.get("description") or "")} for j in data.get("jobs", [])]
        else:  # Ashby
            out[company] = [{"title": j["title"], "url": j.get("jobUrl", ""),
                             "text": j.get("descriptionPlain") or _html_to_text(j.get("descriptionHtml") or "")}
                            for j in data.get("jobs", []) if j.get("isListed", True)]
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False))
    return out


def missing_jobs(jds: list[dict], open_jobs: dict[str, dict], board_jobs: dict[str, list[dict]]):
    """募集中なのに Drive に JD がない求人。(補完できたJD, HERPなど本文を取れない求人名) を返す"""
    added, unavailable = [], []
    for company, info in open_jobs.items():
        folders = COMPANY_FOLDERS.get(company, [company])
        drive_titles = [jd["title"] for jd in jds if jd["company"] in folders]
        board = {j["title"]: j for j in board_jobs.get(company, [])}
        for title in info["open"]:
            if any(same_job(title, t) for t in drive_titles):
                continue
            job = board.get(title)
            if job and job["text"].strip():
                added.append({"path": f"[{info['ats']}] {job['url']}", "company": folders[0], "title": title,
                              "text": job["text"], "status": "open", "source": info["ats"]})
            else:
                unavailable.append(f"{folders[0]}｜{title}（{info['ats']}）")
    return added, unavailable
