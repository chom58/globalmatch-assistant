"""CV 本文の安全チェック（posting_guard の CV 向け設定）

CV は外部から届く文書なので、AI 選考向けの隠し指示や不可視文字が仕込まれうる。
不可視文字を除いた本文を返し、AI 向けの指示らしき行を findings に残す（警告のみで止めない）。
jev_poc/match.py と 匿名化/batch_anonymize.py から使う。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import posting_guard  # noqa: E402

# エンジニアの CV では普通に出てくる語（SSH・curl・.env 等）の検出パターンは CV では使わない
_CV_NOISY_PATTERNS = {r"\b(curl|wget|ssh|scp)\b", r"\.env\b", r"settings\.json"}
_CV_PATTERNS = [p for p in posting_guard.INSTRUCTION_PATTERNS if p.pattern not in _CV_NOISY_PATTERNS]


def guard_cv(text: str) -> tuple[str, dict]:
    cleaned, findings = posting_guard.guard(text, "text")
    findings["instruction_like"] = [
        line for line in findings["instruction_like"] if any(p.search(line) for p in _CV_PATTERNS)
    ]
    findings["verdict"] = posting_guard.verdict(findings)
    return cleaned, findings


def report_lines(findings: dict) -> list[str]:
    """画面表示用の行（判定＋指示らしき行）"""
    return [f"CV 安全チェック: {findings['verdict']}"] + [
        f"  ⚠ 指示らしき行: {line}" for line in findings["instruction_like"]
    ]
