"""Re-verify every quoted evidence passage against its open-access source.

For each evidence record (master graph edges + final-answer hidden connection) that
carries a ``quote``, the script fetches the source text and checks that the quote
appears in it (whitespace, ligatures, punctuation and '...' gaps are tolerated):

* full-text quotes -> the open-access PDF (arXiv / BMC), cached in ``.cache/`` (git-ignored);
* abstract quotes  -> the abstract in data/source_manifest.json.

PDFs are cached locally only for this check and are never committed or redistributed.

Usage:  python scripts/verify_evidence.py          (network needed for first run)
Exit code 1 if any quote cannot be found.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CACHE = ROOT / ".cache" / "fulltext"

PDF_SOURCES = {
    "PAPER_CHOI2011": "https://arxiv.org/pdf/1009.2722",
    "PAPER_BHAMIDI2010": "https://arxiv.org/pdf/math/0604367v2",
    "PAPER_NITATIKONDA2011": "https://arxiv.org/pdf/0809.0158",
}
# Full text via Europe PMC open-access XML (publisher PDF endpoints may serve bot checks)
EUROPEPMC_SOURCES = {"PAPER_MARGOLIN2006": "PMC1810318"}
WEB_SOURCES_SKIPPED = ("docs.nextstrain.org", "doi.org/10.1093/bioinformatics")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("‐", "-").replace("’", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[¨˝]", "", s)
    s = re.sub(r"-\s+", "", s)  # de-hyphenate line breaks
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def fetch_europepmc_text(pmcid: str) -> str | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{pmcid}.xml"
    if not f.exists():
        r = requests.get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML", timeout=60)
        if r.status_code != 200:
            return None
        f.write_bytes(r.content)
    return re.sub(r"<[^>]+>", " ", f.read_text(encoding="utf-8"))


def fetch_pdf_text(iid: str) -> str | None:
    import pymupdf

    if iid in EUROPEPMC_SOURCES:
        return fetch_europepmc_text(EUROPEPMC_SOURCES[iid])
    url = PDF_SOURCES.get(iid)
    if not url:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    pdf = CACHE / f"{iid}.pdf"
    if not pdf.exists():
        r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0 (evidence check)"})
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            return None
        pdf.write_bytes(r.content)
    with pymupdf.open(str(pdf)) as d:
        return "\n".join(p.get_text() for p in d)


def quote_found(quote: str, text: str) -> bool:
    hay = norm(text)
    parts = [p for p in re.split(r"\.\.\.|…", quote) if norm(p)]
    return all(norm(p) in hay for p in parts)


def main() -> int:
    from challenge import paths

    graph = paths.read_json(paths.MASTER_GRAPH)
    manifest = {p["internal_id"]: p for p in paths.read_json(paths.SOURCE_MANIFEST)["papers"]}
    fa = paths.read_json(paths.FINAL_ANSWER)
    records = [(e["id"], ev) for e in graph["edges"] for ev in e["evidence"]]
    records += [("hidden_connection", ev) for ev in fa["hidden_connection"]["evidence"]]
    texts: dict[str, str | None] = {}
    ok = bad = skipped = 0
    for rid, ev in records:
        q = ev.get("quote")
        if not q:
            continue
        src = ev["supporting_source"]
        if any(w in ev["doi_or_url"] for w in WEB_SOURCES_SKIPPED) or src.startswith("http"):
            skipped += 1
            continue
        basis = ev.get("basis", "")
        if "full text" in basis:
            if src not in texts:
                texts[src] = fetch_pdf_text(src)
            text = texts[src]
        else:
            text = manifest.get(src, {}).get("abstract")
        if text is None:
            print(f"SKIP  {rid}: no accessible text for {src}")
            skipped += 1
            continue
        if quote_found(q, text):
            ok += 1
        else:
            bad += 1
            print(f"MISS  {rid} [{src} {ev['location']}]: {q[:90]}")
    print(f"\nquotes verified: {ok}, not found: {bad}, skipped (web pages / inaccessible): {skipped}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
