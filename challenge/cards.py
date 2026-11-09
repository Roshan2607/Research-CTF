"""Render participant challenge cards (PDF wrappers) with an organiser annotation layer.

Each card is a workshop wrapper, NOT the published paper. It contains:

* the neutral ID, bibliographic reference, access link and domain;
* the abstract quoted verbatim with attribution (unaltered; checked by tests);
* a fixed-height "annotation layer" block, present on EVERY card so the layout is
  identical. On the cards listed in ``injection_annotations.json`` this block holds
  a synthetic AI-directed instruction rendered white-on-white (invisible on paper
  and on screen, but present in the text layer that PDF parsers and LLMs read);
* the uniform reading prompts and a footer saying the card is organiser material.

The injections live only in these wrappers; original publications are never modified.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepInFrame, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from . import paths

FONT_DIR = paths.ROOT / "assets" / "fonts"
ANNOTATION_BLOCK_HEIGHT = 16 * mm


def _register_fonts() -> tuple[str, str]:
    try:
        if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVuSans", str(FONT_DIR / "DejaVuSans.ttf")))
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
        return "DejaVuSans", "DejaVuSans-Bold"
    except Exception:  # pragma: no cover - font missing
        return "Helvetica", "Helvetica-Bold"


def _styles():
    regular, bold = _register_fonts()
    return {
        "brand": ParagraphStyle("brand", fontName=regular, fontSize=8, textColor=colors.HexColor("#555555")),
        "pid": ParagraphStyle("pid", fontName=bold, fontSize=22, leading=26),
        "title": ParagraphStyle("title", fontName=bold, fontSize=13, leading=16, spaceAfter=4),
        "meta": ParagraphStyle("meta", fontName=regular, fontSize=9, leading=12),
        "h": ParagraphStyle("h", fontName=bold, fontSize=10, leading=13, spaceBefore=8, spaceAfter=3),
        "body": ParagraphStyle("body", fontName=regular, fontSize=9.5, leading=13, alignment=TA_LEFT),
        "small": ParagraphStyle("small", fontName=regular, fontSize=7.5, leading=10, textColor=colors.HexColor("#555555")),
        "hidden": ParagraphStyle("hidden", fontName=regular, fontSize=6.5, leading=8, textColor=colors.white),
        "visible_note": ParagraphStyle("visible_note", fontName=regular, fontSize=7.5, leading=10, textColor=colors.HexColor("#555555")),
    }


def _annotation_block(text: str | None, st) -> Table:
    """Fixed-height block: exactly the same size on every card; holds the hidden text when given."""
    flow = [Paragraph("Notes: record the page or section for every claim you make about this paper.", st["visible_note"])]
    if text:
        flow.append(Paragraph(escape(text), st["hidden"]))
    inner = KeepInFrame(170 * mm, ANNOTATION_BLOCK_HEIGHT, flow, mode="truncate")
    t = Table([[inner]], colWidths=[170 * mm], rowHeights=[ANNOTATION_BLOCK_HEIGHT])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def render_card(card: dict, out_path: Path, branding: str, injection_text: str | None = None) -> Path:
    st = _styles()
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Proof of Thought challenge card {card['participant_id']}", author="Proof of Thought Organisers",
        subject="Challenge card excerpt",
        invariant=1,  # reproducible output: no timestamps / random IDs, so rebuilds do not churn
    )
    access_url = card.get("open_access_url") or card.get("doi_url", "")
    meta_rows = [
        [Paragraph("<b>Authors</b>", st["meta"]), Paragraph(escape(", ".join(card["authors"])), st["meta"])],
        [Paragraph("<b>Published</b>", st["meta"]), Paragraph(escape(f"{card['venue']} ({card['year']})"), st["meta"])],
    ]
    if access_url:
        meta_rows.append([Paragraph("<b>Paper Link</b>", st["meta"]), Paragraph(escape(access_url), st["meta"])])
    if card.get("domain"):
        meta_rows.append([Paragraph("<b>Domain</b>", st["meta"]), Paragraph(escape(card["domain"]), st["meta"])])

    meta = Table(meta_rows, colWidths=[24 * mm, 146 * mm])
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))

    story = [
        Paragraph(escape("Proof of Thought · Research Challenge Card"), st["brand"]),
        Spacer(1, 3 * mm),
        Paragraph(card["participant_id"], st["pid"]),
        Paragraph(escape(card["title"]), st["title"]),
        meta,
        Spacer(1, 1 * mm),
        Paragraph("Abstract", st["h"]),
        Paragraph(escape(card["abstract"]), st["body"]),
        Spacer(1, 1.5 * mm),
        Paragraph(escape(card["abstract_attribution"]), st["small"]),
        Spacer(1, 2 * mm),
        _annotation_block(injection_text, st),
        Paragraph("Reading prompts", st["h"]),
    ]
    for i, q in enumerate(card["reading_prompts"], 1):
        story.append(Paragraph(escape(f"{i}. {q}"), st["body"]))
    story += [
        Spacer(1, 4 * mm),
        Paragraph(
            "Proof of Thought · Challenge Excerpt Card. Check evidence in the paper before asserting relationships.",
            st["small"],
        ),
    ]
    doc.build(story)
    return out_path


def render_all_cards(out_dir: Path | None = None) -> list[Path]:
    from .participant_data import load_challenge_info, load_corpus

    out_dir = Path(out_dir or paths.CARDS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    injections = {a["host_card_participant_id"]: a["text"] for a in paths.read_json(paths.INJECTIONS)["annotations"]}
    branding = load_challenge_info()["branding"]
    out = []
    for card in load_corpus():
        pid = card["participant_id"]
        out.append(render_card(card, out_dir / f"{pid}.pdf", branding, injections.get(pid)))
    return out
