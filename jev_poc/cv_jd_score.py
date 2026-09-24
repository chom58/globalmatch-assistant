"""
CV×JD 9次元採点の Jev（TypeSafe System One）PoC

Recruitline（AIR）と同じ9次元・1〜5点のルーブリックを、Jev の Score 質問で採点する。
1リクエストで9問をまとめて投げ、各次元の期待値スコア・確率分布・confidence を返す。
総合点の重みづけはコード側で持つ（Composite scoring パターン）。

使い方:
  # 1ペアを採点
  python jev_poc/cv_jd_score.py score --cv cv.txt --jd jd.txt

  # 正解データ（Recruitline の実測値）と比較
  python jev_poc/cv_jd_score.py eval --truth jev_poc/data/truth.json

環境変数:
  TYPESAFE_API_KEY  TypeSafe の API キー（必須）

CV は送信前に氏名・メール・電話・URL を伏せる。CV/JD本文・正解データ・結果は
jev_poc/data/ と jev_poc/results/ に置く（gitignore 済み。公開リポにコミットしない）。
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prompts import extract_name_from_cv  # noqa: E402

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"

# 1〜5点の水準。Score の criteria は低い順に並べる（answer.score は 0〜4 の期待値）
_FIT_LEVELS = [
    "1 - No fit: the CV shows no evidence for this dimension, or clearly contradicts what the job needs.",
    "2 - Weak fit: only indirect or minor evidence; most of what the job needs here is missing.",
    "3 - Partial fit: some direct evidence, but clear gaps remain against what the job needs.",
    "4 - Strong fit: direct evidence covers most of what the job needs, with minor gaps.",
    "5 - Excellent fit: direct evidence fully covers or exceeds what the job needs.",
]

_COMMON = (
    "Compare `candidate_cv` against `job_description`. "
    "Only count evidence actually written in the CV; do not assume skills that are not stated. "
)

# key は Recruitline の rubric キーに合わせる（other_languages は Recruitline 画面上の次元）
DIMENSIONS = [
    {
        "key": "required_skills",
        "label": "Required Skills",
        "instructions": _COMMON + "How well does the candidate meet the REQUIRED (must-have) skills and qualifications listed in the job description?",
    },
    {
        "key": "desired_skills",
        "label": "Desired Skills",
        "instructions": _COMMON + "How well does the candidate meet the DESIRED / preferred / nice-to-have skills listed in the job description? If none are listed, judge against skills that would clearly help in this role.",
    },
    {
        "key": "domain_knowledge",
        "label": "Domain Knowledge and Experience",
        "instructions": _COMMON + "How closely does the candidate's industry and domain experience match the job's business domain and the problems the role works on?",
    },
    {
        "key": "scale_complexity",
        "label": "Scale & Complexity Fit",
        "instructions": _COMMON + "How well does the scale and complexity of the candidate's past work (team size, user or client scale, system or project complexity, budget) match what this role will handle?",
    },
    {
        "key": "ownership_seniority",
        "label": "Ownership & Seniority Fit",
        "instructions": _COMMON + "How well does the candidate's level of ownership, leadership and seniority match the seniority and responsibility expected for this role?",
    },
    {
        "key": "rd_academic_depth",
        "label": "R&D / Academic Depth",
        "instructions": _COMMON + "How well does the candidate's research, academic or R&D depth (degrees, publications, research projects, deep technical study) match what the role expects? If the job expects none, judge how relevant the candidate's academic background is to the role.",
    },
    {
        "key": "language_japanese",
        "label": "Language proficiency - Japanese",
        "instructions": _COMMON + "How well does the candidate's Japanese proficiency (JLPT level, stated fluency, work done in Japanese) meet the Japanese level the job requires? A candidate at or above the required level is an excellent fit.",
    },
    {
        "key": "language_english",
        "label": "Language proficiency - English",
        "instructions": _COMMON + "How well does the candidate's English proficiency meet the English level the job requires? "
        "Evidence includes stated fluency, test scores, work or study done in English, and the CV itself: "
        "a CV written in clear, professional English is direct evidence of at least business-level English. "
        "A candidate at or above the required level is an excellent fit. "
        "If the job states no English requirement, a candidate with working English is an excellent fit.",
    },
    {
        "key": "other_languages",
        "label": "Other Languages",
        # 求人が日英以外の言語を求める場合だけ評価する（OTHER_LANG_GATE が「いいえ」なら対象外）
        "instructions": _COMMON + "Assume the job description requires or prefers a specific language other than Japanese and English "
        "(for example Korean, Chinese or German). How well does the candidate's proficiency in THAT language meet the job's requirement? "
        "Other languages the job does not ask for do not count.",
    },
]
DIM_KEYS = [d["key"] for d in DIMENSIONS]

# Other Languages を評価するかの判定（Noul）。確率がしきい値未満なら対象外として総合点から外す
OTHER_LANG_GATE = "jd_requires_other_language"
OTHER_LANG_GATE_THRESHOLD = 0.5
_OTHER_LANG_GATE_Q = {
    "type": "noul",
    "instructions": "Does `job_description` explicitly require or prefer proficiency in a language other than Japanese and English?",
    "criteria": {
        "true": "The job names a specific other language (e.g. Korean, Chinese, German) as required or preferred.",
        "false": "The job asks only for Japanese and/or English, or names no language beyond them. "
        "An international team or global company alone does not count.",
    },
}

# 日本語の足切り用の判定（Noul）。language_japanese の点数は候補者の日本語力そのものに近く、
# 日本語不要の求人でも低く出るため、足切りは「求人が日本語を必要とする」場合に限る（match.py で使用）
JA_REQ_GATE = "jd_requires_japanese"
_JA_REQ_GATE_Q = {
    "type": "noul",
    "instructions": "Does the role in `job_description` require working in Japanese?",
    "criteria": {
        "true": "The job states a Japanese level (e.g. JLPT N2, business Japanese, native), or the work clearly "
        "has to be done in Japanese (e.g. Japanese-speaking clients or team, or the posting is only in Japanese).",
        "false": "The job says English is enough, Japanese is only a plus or not mentioned, or the company only "
        "offers Japanese lessons as a benefit.",
    },
}

# 総合点の補正（calibrated = a × raw + b）。analyze.py の calibration 出力から設定する
# 2026-09-24: Recruitline 28ペア（run_rl28_v3）で推定。補正前 MAE 7.3pt → 1件抜き交差検証 6.6pt
CALIBRATION = (0.776, 19.98)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_URL = re.compile(r"(https?://\S+|www\.\S+|(linkedin|github)\.com/\S+)", re.I)
# 「2019 - 2023」のような年の範囲を消さないよう、数字10桁以上のものだけを電話番号とみなす
_PHONE = re.compile(r"\+?\(?\d[\d().-]*(?:\s?[\d().-]+){2,}")


def _is_phone(s: str) -> bool:
    return sum(c.isdigit() for c in s) >= 10


def redact_cv(text: str) -> str:
    """送信前に候補者の氏名・メール・URL・電話番号を伏せる"""
    name = extract_name_from_cv(text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _URL.sub("[URL]", text)
    text = _PHONE.sub(lambda m: "[PHONE]" if _is_phone(m.group()) else m.group(), text)
    for part in {name, *name.split()}:
        if len(part) >= 3:
            text = re.sub(re.escape(part), "[CANDIDATE]", text, flags=re.I)
    return text


# Recruitline の求人ページには、元の求人票にない AI 生成の9次元ルーブリックが続く。
# 「その他言語があれば加点」のような文言が入り、求人の要件と誤読されるため取り除く
_RL_RUBRIC_START = re.compile(
    r"^(.*評価ルーブリック.*|Required Skills|Desired Skills|Domain Knowledge|Scale & Complexity|"
    r"Ownership & Seniority|R&D / Academic Depth|Other Languages|English Language|Japanese Language|Language - .+)\s*$",
    re.M,
)


def strip_recruitline_rubric(jd_text: str) -> str:
    """「主要スキル」より後ろで最初に現れるルーブリックの行から後ろを落とす。該当しない JD はそのまま返す"""
    skills = jd_text.find("主要スキル")
    m = _RL_RUBRIC_START.search(jd_text, skills) if skills >= 0 else None
    return jd_text[: m.start()] if m else jd_text


def build_questions() -> dict:
    questions = {
        d["key"]: {"type": "score", "instructions": d["instructions"], "criteria": _FIT_LEVELS}
        for d in DIMENSIONS
    }
    questions[OTHER_LANG_GATE] = _OTHER_LANG_GATE_Q
    questions[JA_REQ_GATE] = _JA_REQ_GATE_Q
    return questions


def ask_jev(state: dict, questions: dict, model: str = DEFAULT_MODEL, retries: int = 4) -> dict:
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY が未設定です")
    body = json.dumps({"state": state, "model": model, "questions": questions}).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < retries:
                time.sleep(float(e.headers.get("retry-after") or 2 ** attempt))
                continue
            raise RuntimeError(f"Jev API {e.code}: {e.read().decode(errors='replace')[:500]}") from e
    raise RuntimeError("Jev API: リトライ上限")


def score_pair(cv_text: str, jd_text: str, model: str = DEFAULT_MODEL) -> dict:
    """1ペアを採点し、次元ごとの 1〜5 点・確率・confidence と使用量を返す"""
    state = {"job_description": strip_recruitline_rubric(jd_text), "candidate_cv": redact_cv(cv_text)}
    res = ask_jev(state, build_questions(), model)
    gate = res["answers"][OTHER_LANG_GATE]
    other_lang_p = gate.get("noul", gate.get("probability"))
    dims = {}
    for key in DIM_KEYS:
        a = res["answers"][key]
        dims[key] = {
            "score": round(1 + a["score"], 2),
            "confidence": round(a["confidence"], 2),
            "probabilities": {str(int(k) + 1): round(v, 3) for k, v in a["probabilities"].items()},
        }
    # 求人が日英以外の言語を求めないなら Other Languages は対象外（score=None）
    dims["other_languages"]["jd_requires_p"] = round(other_lang_p, 3)
    if other_lang_p < OTHER_LANG_GATE_THRESHOLD:
        dims["other_languages"]["score"] = None
    scores = {k: v["score"] for k, v in dims.items()}
    raw = total_pct(scores)
    ja_gate = res["answers"][JA_REQ_GATE]
    return {"model": res.get("model"), "usage": res.get("usage"), "dimensions": dims,
            "total_pct": raw, "calibrated_total_pct": calibrate(raw),
            "jd_requires_japanese_p": round(ja_gate.get("noul", ja_gate.get("probability")), 3)}


def total_pct(dim_scores: dict, weights: dict | None = None) -> float:
    """1〜5点の加重平均を 0〜100% にする。weights 省略時は均等。score=None（対象外）の次元は分母からも外す"""
    weights = weights or {k: 1.0 for k in DIM_KEYS}
    keys = [k for k in DIM_KEYS if dim_scores.get(k) is not None]
    w_sum = sum(weights[k] for k in keys)
    return round(100 * sum(dim_scores[k] * weights[k] for k in keys) / (5 * w_sum), 1)


def calibrate(raw_pct: float) -> float:
    a, b = CALIBRATION
    return round(min(100.0, max(0.0, a * raw_pct + b)), 1)


def _print_pair(result: dict) -> None:
    for d in DIMENSIONS:
        r = result["dimensions"][d["key"]]
        s = "  n/a" if r["score"] is None else f"{r['score']:>5.2f}"
        print(f"  {d['label']:<34} {s}  conf={r['confidence']:.2f}")
    print(f"  {'Total (equal weights)':<34} {result['total_pct']:>5.1f}%  "
          f"calibrated={result['calibrated_total_pct']:.1f}%  usage={result['usage']}")


def cmd_score(args) -> None:
    result = score_pair(Path(args.cv).read_text(), Path(args.jd).read_text(), args.model)
    _print_pair(result)
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_eval(args) -> None:
    """truth.json: [{"id", "cv", "jd", "expected_total_pct"?, "expected_dims"?: {key: 1-5}}]
    cv/jd は truth.json からの相対パス"""
    truth_path = Path(args.truth)
    cases = json.loads(truth_path.read_text())
    rows, dim_errors = [], {k: [] for k in DIM_KEYS}
    for case in cases:
        base = truth_path.parent
        result = score_pair((base / case["cv"]).read_text(), (base / case["jd"]).read_text(), args.model)
        scores = {k: v["score"] for k, v in result["dimensions"].items()}
        print(f"\n[{case['id']}]")
        _print_pair(result)
        for k, exp in (case.get("expected_dims") or {}).items():
            if scores[k] is None:
                print(f"    {k:<22} jev=n/a  recruitline={exp}")
                continue
            dim_errors[k].append(scores[k] - exp)
            print(f"    {k:<22} jev={scores[k]:.2f} recruitline={exp} diff={scores[k] - exp:+.2f}")
        rows.append({"id": case["id"], "jev_total_pct": result["total_pct"],
                     "jev_calibrated_pct": result["calibrated_total_pct"],
                     "expected_total_pct": case.get("expected_total_pct"), "result": result})

    print("\n== 総合点（均等重み）vs Recruitline ==")
    for r in rows:
        exp = r["expected_total_pct"]
        diff = f"{r['jev_total_pct'] - exp:+.1f}pt" if exp is not None else "-"
        print(f"  {r['id']:<28} jev={r['jev_total_pct']:>5.1f}%  recruitline={exp}%  {diff}")
    paired = [r for r in rows if r["expected_total_pct"] is not None]
    if len(paired) >= 2:
        order = lambda key: [r["id"] for r in sorted(paired, key=lambda r: -r[key])]  # noqa: E731
        print(f"  順位 jev:         {order('jev_total_pct')}")
        print(f"  順位 recruitline: {order('expected_total_pct')}")
    errs = {k: v for k, v in dim_errors.items() if v}
    if errs:
        print("\n== 次元別 平均絶対誤差 ==")
        for k, v in errs.items():
            print(f"  {k:<22} MAE={sum(abs(x) for x in v) / len(v):.2f} (n={len(v)})")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default=DEFAULT_MODEL)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="1ペアを採点")
    s.add_argument("--cv", required=True)
    s.add_argument("--jd", required=True)
    s.add_argument("--out")
    e = sub.add_parser("eval", help="正解データと比較")
    e.add_argument("--truth", required=True)
    e.add_argument("--out")
    args = p.parse_args()
    {"score": cmd_score, "eval": cmd_eval}[args.cmd](args)


if __name__ == "__main__":
    main()
