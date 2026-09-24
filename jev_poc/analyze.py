"""
cv_jd_score.py eval の結果を Recruitline の正解と突き合わせて集計する（API は呼ばない）

使い方:
  python jev_poc/analyze.py --results jev_poc/results/run_rl28.json --truth jev_poc/data/truth_rl.json

出力: 総合点の誤差・相関、次元別の MAE・偏り・相関・平均 confidence、候補者内の順位相関、
      Recruitline の重みの逆算（非負最小二乗）
標準ライブラリのみで動く（numpy 不要）。ケース ID は「候補者:会社:求人」の形式を前提とする。
"""

import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cv_jd_score import DIM_KEYS  # noqa: E402


def corr(a, b):
    ma, mb = st.mean(a), st.mean(b)
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if not sa or not sb:
        return float("nan")
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)


def rank(a):
    order = sorted(range(len(a)), key=lambda i: a[i])
    r = [0.0] * len(a)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and a[order[j + 1]] == a[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a, b):
    return corr(rank(a), rank(b))


def report(rows, truth, label):
    jev = [[r["result"]["dimensions"][k]["score"] for k in DIM_KEYS] for r in rows]
    exp = [[truth[r["id"]]["expected_dims"][k] for k in DIM_KEYS] for r in rows]
    jt = [r["jev_total_pct"] for r in rows]
    tt = [r["expected_total_pct"] for r in rows]
    print(f"\n### {label} (n={len(rows)})")
    print("総合点 MAE=%.1fpt bias=%+.1fpt Pearson=%.2f Spearman=%.2f" % (
        st.mean(abs(a - b) for a, b in zip(jt, tt)), st.mean(a - b for a, b in zip(jt, tt)),
        corr(jt, tt), spearman(jt, tt)))
    print("  dim                   MAE   bias   corr  conf  n")
    for i, k in enumerate(DIM_KEYS):
        # score=None（対象外）のペアは除いて比べる
        pairs = [(x[i], y[i]) for x, y in zip(jev, exp) if x[i] is not None]
        conf = st.mean(r["result"]["dimensions"][k]["confidence"] for r in rows)
        if not pairs:
            print(f"  {k:<20} 全ペア対象外")
            continue
        a, b = [p[0] for p in pairs], [p[1] for p in pairs]
        c = corr(a, b) if len(pairs) >= 3 else float("nan")
        print(f"  {k:<20} {st.mean(abs(x - y) for x, y in pairs):.2f}  "
              f"{st.mean(x - y for x, y in pairs):+.2f}  {c:+.2f}  {conf:.2f}  {len(pairs)}")
    cands = sorted({r["id"].split(":")[0] for r in rows})
    within = {}
    for c in cands:
        sel = [r for r in rows if r["id"].startswith(c + ":")]
        within[c] = round(spearman([r["jev_total_pct"] for r in sel], [r["expected_total_pct"] for r in sel]), 2)
    print("  候補者内 Spearman:", within)
    return jev, exp, tt


def fit_weights(exp, tt, iters=200000, lr=1e-6):
    """総合点 ≈ Σ w_k × (次元点×20) を非負制約つきで解く（射影勾配法）"""
    x = [[v * 20 for v in row] for row in exp]
    w = [1 / len(DIM_KEYS)] * len(DIM_KEYS)
    for _ in range(iters):
        g = [0.0] * len(w)
        for xi, y in zip(x, tt):
            e = sum(a * b for a, b in zip(w, xi)) - y
            for i in range(len(w)):
                g[i] += e * xi[i]
        w = [max(0.0, wi - lr * gi) for wi, gi in zip(w, g)]
    fitted = [sum(a * b for a, b in zip(w, xi)) for xi in x]
    return w, st.mean(abs(a - b) for a, b in zip(fitted, tt))


def _linfit(x, y):
    mx, my = st.mean(x), st.mean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    a = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sxx
    return a, my - a * mx


def calibration(jt, tt):
    """総合点の補正 calibrated = a × raw + b を最小二乗で求め、1件抜き交差検証の誤差も出す"""
    a, b = _linfit(jt, tt)
    loo = []
    for i in range(len(jt)):
        ai, bi = _linfit(jt[:i] + jt[i + 1:], tt[:i] + tt[i + 1:])
        loo.append(abs(ai * jt[i] + bi - tt[i]))
    raw_mae = st.mean(abs(p - q) for p, q in zip(jt, tt))
    return a, b, raw_mae, st.mean(loo)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results", required=True)
    p.add_argument("--truth", required=True)
    p.add_argument("--exclude", action="append", default=[], help="除外する候補者ID接頭辞（例: y）")
    args = p.parse_args()
    rows = json.loads(Path(args.results).read_text())
    truth = {c["id"]: c for c in json.loads(Path(args.truth).read_text())}
    _, exp, tt = report(rows, truth, "全ペア")
    for ex in args.exclude:
        report([r for r in rows if not r["id"].startswith(ex + ":")], truth, f"{ex} を除く")
    gate = [r["result"]["dimensions"]["other_languages"].get("jd_requires_p") for r in rows]
    if any(p is not None for p in gate):
        applied = sum(1 for r in rows if r["result"]["dimensions"]["other_languages"]["score"] is not None)
        print(f"\nOther Languages を評価したペア: {applied}/{len(rows)}（求人が日英以外の言語を求めると判定）")
    a, b, raw_mae, loo_mae = calibration([r["jev_total_pct"] for r in rows], tt)
    print(f"\n総合点の補正: CALIBRATION = ({a:.3f}, {b:.2f})  "
          f"補正前 MAE={raw_mae:.1f}pt → 補正後 MAE（1件抜き交差検証）={loo_mae:.1f}pt")
    w, mae = fit_weights(exp, tt)
    print("\nRecruitline 重みの逆算（比率）:", {k: round(x / sum(w), 2) for k, x in zip(DIM_KEYS, w)})
    print("  この重みで Recruitline 総合点を再現した誤差: MAE=%.1fpt" % mae)


if __name__ == "__main__":
    main()
