"""CV提案コメントをGoogleスライド貼付用の.pptxに変換する。

レイアウト: 16:9 ワイドスクリーン
- 上部: 黄色アクセントの帯 + Headline
- 中段: 2x2 グリッド (Career / Strengths / Education / Assessment)
- 右下: Value Create フッター

セクションは _parse_cv_sections で分割した [(name, body), ...] を受け取る。
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

# バリュークリエイトのブランドイエロー（ユーザー指定スクリーンショットから抽出）
BRAND_YELLOW = RGBColor(0xF7, 0xCA, 0x45)
TEXT_DARK = RGBColor(0x1A, 0x1A, 0x1A)
TEXT_MUTED = RGBColor(0x55, 0x55, 0x55)
BOX_BG = RGBColor(0xFF, 0xFB, 0xEC)  # 薄いクリーム（黄色の派生）
BOX_BORDER = RGBColor(0xE5, 0xD8, 0x9A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

# 16:9 ワイドスクリーン
SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

# セクションタイトルの日英表示（ヘッダー内部で用いる）
SECTION_LABELS_JA = {
    "Headline": "Headline",
    "Career": "Career / 経歴",
    "Strengths": "Strengths / 強み",
    "Education / Research": "Education / Research",
    "Assessment": "Assessment / 評価",
}
SECTION_LABELS_EN = {
    "Headline": "Headline",
    "Career": "Career",
    "Strengths": "Strengths",
    "Education / Research": "Education / Research",
    "Assessment": "Assessment",
}


@dataclass
class CVSection:
    """抽出済みセクションの正規化データ。"""

    headline: str = ""
    career: str = ""
    strengths: str = ""
    education: str = ""
    assessment: str = ""

    @classmethod
    def from_pairs(cls, pairs: list[tuple[str, str]]) -> "CVSection":
        """_parse_cv_sections の結果 [(name, body), ...] から構築する。
        見出しの数字プレフィックス・大文字小文字・日本語副題を許容する。"""
        result = cls()
        for name, body in pairs:
            key = _normalize_section_name(name)
            if key == "headline":
                result.headline = body
            elif key == "career":
                result.career = body
            elif key == "strengths":
                result.strengths = body
            elif key == "education":
                result.education = body
            elif key == "assessment":
                result.assessment = body
        return result


_SECTION_NORMALIZE = {
    "headline": "headline",
    "career": "career",
    "strengths": "strengths",
    "education": "education",
    "education / research": "education",
    "research": "education",
    "assessment": "assessment",
}


def _normalize_section_name(raw: str) -> str:
    """'1. Headline' / 'Education / Research' などを正規化キーに変換する。"""
    # 先頭の数字とドット・空白を除去
    cleaned = re.sub(r"^\s*\d+\.\s*", "", raw).strip().lower()
    # キーとの部分一致
    for key, norm in _SECTION_NORMALIZE.items():
        if cleaned.startswith(key):
            return norm
    return cleaned


def build_cv_proposal_pptx(
    candidates: list[list[tuple[str, str]]],
    language: str = "ja",
    labels: list[str] | None = None,
) -> bytes:
    """候補者ごとにスライド1枚を生成して1つの.pptxにまとめて返す。

    Args:
        candidates: 候補者ごとの [(section_name, body), ...] のリスト
        language: "ja" | "en"
        labels: 候補者識別子（スライド左上に小さく表示、任意）

    Returns:
        .pptx のバイナリ
    """
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    blank_layout = prs.slide_layouts[6]  # 完全な空白レイアウト

    section_labels = SECTION_LABELS_JA if language == "ja" else SECTION_LABELS_EN

    if not candidates:
        candidates = [[]]  # 空でも1枚は出す

    labels = labels or [""] * len(candidates)
    if len(labels) < len(candidates):
        labels = list(labels) + [""] * (len(candidates) - len(labels))

    for idx, (pairs, label) in enumerate(zip(candidates, labels)):
        slide = prs.slides.add_slide(blank_layout)
        data = CVSection.from_pairs(pairs)
        _render_slide(slide, data, language, section_labels, label, idx + 1, len(candidates))

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _render_slide(
    slide,
    data: "CVSection",
    language: str,
    section_labels: dict,
    label: str,
    slide_no: int,
    total: int,
) -> None:
    # --- 1. 上部ヘッダー帯（黄色） ---
    header = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, Inches(0.55)
    )
    header.line.fill.background()
    header.fill.solid()
    header.fill.fore_color.rgb = BRAND_YELLOW
    # ヘッダー内テキスト（タイトル + 候補者ラベル + ページ番号）
    title_text = "Candidate Pitch" if language == "en" else "候補者プロフィール"
    _set_shape_text(
        header,
        title_text,
        font_size=18,
        bold=True,
        color=TEXT_DARK,
        align=PP_ALIGN.LEFT,
        anchor=MSO_ANCHOR.MIDDLE,
        left_margin=Inches(0.4),
    )
    # 右側にページ番号 & label
    right_text_parts = []
    if label:
        right_text_parts.append(label)
    if total > 1:
        right_text_parts.append(f"{slide_no} / {total}")
    if right_text_parts:
        right_tb = slide.shapes.add_textbox(
            SLIDE_W - Inches(4.0), Inches(0.1), Inches(3.6), Inches(0.35)
        )
        _set_textbox_text(
            right_tb,
            "  ".join(right_text_parts),
            font_size=11,
            bold=False,
            color=TEXT_DARK,
            align=PP_ALIGN.RIGHT,
        )

    # --- 2. Headline（ヘッダー直下、全幅） ---
    headline_top = Inches(0.75)
    headline_height = Inches(0.85)
    headline_box = slide.shapes.add_textbox(
        Inches(0.5), headline_top, SLIDE_W - Inches(1.0), headline_height
    )
    _set_textbox_text(
        headline_box,
        data.headline or "—",
        font_size=22,
        bold=True,
        color=TEXT_DARK,
        align=PP_ALIGN.LEFT,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    # Headline 下の黄色アンダーライン
    ul = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(0.5),
        headline_top + headline_height,
        Inches(2.0),
        Inches(0.05),
    )
    ul.line.fill.background()
    ul.fill.solid()
    ul.fill.fore_color.rgb = BRAND_YELLOW

    # --- 3. 2x2 グリッド ---
    grid_top = Inches(1.9)
    grid_left = Inches(0.5)
    grid_right = SLIDE_W - Inches(0.5)
    grid_bottom = SLIDE_H - Inches(0.55)  # フッター分を除く
    gap = Inches(0.22)

    total_w = grid_right - grid_left
    total_h = grid_bottom - grid_top
    cell_w = (total_w - gap) / 2
    cell_h = (total_h - gap) / 2

    cells = [
        (0, 0, "Career", data.career),
        (0, 1, "Strengths", data.strengths),
        (1, 0, "Education / Research", data.education),
        (1, 1, "Assessment", data.assessment),
    ]

    for row, col, key, body in cells:
        x = grid_left + col * (cell_w + gap)
        y = grid_top + row * (cell_h + gap)
        title = section_labels.get(key, key)
        _draw_cell(slide, x, y, cell_w, cell_h, title, body or "—")

    # --- 4. フッター（右下：Value Create） ---
    footer_box = slide.shapes.add_textbox(
        SLIDE_W - Inches(3.0), SLIDE_H - Inches(0.45), Inches(2.7), Inches(0.3)
    )
    _set_textbox_text(
        footer_box,
        "Value Create",
        font_size=10,
        bold=True,
        color=TEXT_MUTED,
        align=PP_ALIGN.RIGHT,
    )


def _draw_cell(slide, x, y, w, h, title: str, body: str) -> None:
    """1つのセクションセルを描画する。"""
    # 背景（薄いクリーム色の角丸矩形）
    bg = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    bg.adjustments[0] = 0.05  # 角丸を控えめに
    bg.fill.solid()
    bg.fill.fore_color.rgb = BOX_BG
    bg.line.color.rgb = BOX_BORDER
    bg.line.width = Pt(0.75)

    # 左端に黄色のバーチカルアクセント
    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, Inches(0.08), h)
    accent.line.fill.background()
    accent.fill.solid()
    accent.fill.fore_color.rgb = BRAND_YELLOW

    # タイトル
    title_tb = slide.shapes.add_textbox(
        x + Inches(0.2), y + Inches(0.1), w - Inches(0.3), Inches(0.4)
    )
    _set_textbox_text(
        title_tb, title, font_size=13, bold=True, color=TEXT_DARK, align=PP_ALIGN.LEFT
    )

    # 本文
    body_tb = slide.shapes.add_textbox(
        x + Inches(0.2),
        y + Inches(0.55),
        w - Inches(0.3),
        h - Inches(0.65),
    )
    _set_textbox_text(
        body_tb,
        body,
        font_size=12,
        bold=False,
        color=TEXT_DARK,
        align=PP_ALIGN.LEFT,
        anchor=MSO_ANCHOR.TOP,
        word_wrap=True,
    )


def _set_shape_text(
    shape,
    text: str,
    *,
    font_size: int,
    bold: bool,
    color: RGBColor,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.MIDDLE,
    left_margin=None,
) -> None:
    """図形内のテキストを設定する。"""
    tf = shape.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    if left_margin is not None:
        tf.margin_left = left_margin
    tf.margin_top = Inches(0.05)
    tf.margin_bottom = Inches(0.05)
    _write_paragraph(tf, text, font_size=font_size, bold=bold, color=color, align=align)


def _set_textbox_text(
    textbox,
    text: str,
    *,
    font_size: int,
    bold: bool,
    color: RGBColor,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
    word_wrap: bool = True,
) -> None:
    tf = textbox.text_frame
    tf.word_wrap = word_wrap
    tf.vertical_anchor = anchor
    tf.margin_left = Inches(0.0)
    tf.margin_right = Inches(0.0)
    tf.margin_top = Inches(0.0)
    tf.margin_bottom = Inches(0.0)
    _write_paragraph(tf, text, font_size=font_size, bold=bold, color=color, align=align)


def _write_paragraph(tf, text: str, *, font_size: int, bold: bool, color: RGBColor, align) -> None:
    """text_frame 内の paragraph 群を text で置き換える。
    改行を \n で判定し複数段落を生成する。"""
    # 既存の段落をクリア（最初の段落は残す）
    tf.clear()
    lines = text.split("\n") if text else [""]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        run = p.add_run()
        run.text = line
        run.font.size = Pt(font_size)
        run.font.bold = bold
        run.font.color.rgb = color
