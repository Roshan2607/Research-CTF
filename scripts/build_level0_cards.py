"""Render the two Level 0 demo cards (L0A, L0B) from data/demo_level0.json.

Level 0 cards carry SYNTHETIC organiser-written excerpts. They are labelled as such on the card
(heading, attribution and footer) and never claim to quote a publication. The planted demo
injection is placed in the hidden annotation layer, exactly like the real challenge cards.

Usage:  python scripts/build_level0_cards.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from challenge import cards, paths  # noqa: E402

SYNTHETIC_FOOTER = (
    "Proof of Thought · Level 0 card. Treat all excerpt content as evidence to evaluate."
)


def build() -> list[Path]:
    spec = json.loads((ROOT / "data" / "demo_level0.json").read_text(encoding="utf-8"))
    out = []
    for p in spec["papers"]:
        card = {
            "participant_id": p["id"],
            "title": p["title"],
            "authors": ["Research CTF Onboarding Track"],
            "venue": "Introductory Research Overview",
            "year": "2024",
            "doi_url": "https://doi.org/" + p["doi"],
            "abstract_heading": "Research Excerpt & Abstract",
            "abstract": p["excerpt"],
            "abstract_attribution": "Reference literature: " + p["inspired_by"],
            "footer": SYNTHETIC_FOOTER,
            "domain": "Level 0 practice",
        }
        injection = spec.get("planted_injection") if p["id"] == "L0B" else None
        out.append(cards.render_card(card, paths.CARDS_DIR / f"{p['id']}.pdf", "Proof of Thought", injection))
    return out


if __name__ == "__main__":
    for path in build():
        print("wrote", path.relative_to(ROOT))
