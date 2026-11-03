"""Resolve the organiser's corpus seed against scholarly APIs and write the source manifest.

Stage 0 data sourcing. For every paper in ``data/corpus_seed.json`` this script

* fetches the OpenAlex work record (title, authors, year, venue, abstract,
  referenced works, open-access status);
* fetches the Crossref record for volume / issue / pages where available;
* applies documented organiser overrides (only for missing or corrupted fields);
* records retrieval provenance (API, record id, timestamp) for every paper.

The resulting ``data/source_manifest.json`` is the bibliographic source of truth
used by the graph builder. Citation (CITES) edges between corpus papers are
derived from OpenAlex ``referenced_works`` and listed in the manifest under
``citations_in_corpus`` so they can be audited.

Usage::

    python scripts/fetch_metadata.py            # refresh manifest from the APIs
    python scripts/fetch_metadata.py --check    # report differences, do not write

Network access is required. The unit tests never call this script.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "corpus_seed.json"
MANIFEST = ROOT / "data" / "source_manifest.json"
OPENALEX = "https://api.openalex.org/works/"
CROSSREF = "https://api.crossref.org/works/"
UA = {"User-Agent": "UnchartedLiterature-workshop/0.1 (research-literacy CTF; metadata only)"}


def _get(url: str) -> dict | None:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def _abstract(inv: dict | None) -> str | None:
    if not inv:
        return None
    pos: dict[int, str] = {}
    for word, places in inv.items():
        for p in places:
            pos[p] = word
    return " ".join(pos[i] for i in sorted(pos))


_IEEE_SPL = {
    "isin": "∈", "Omega": "Ω", "delta": "δ", "les": "≤", "ges": "≥", "lscr": "ℓ", "middot": "·",
    "sigma": "Σ", "tau": "τ", "infin": "∞", "alpha": "α", "beta": "β", "lambda": "λ",
}


def clean_abstract(text: str | None, fixes: list[list[str]] | None = None) -> str | None:
    """Remove indexing artefacts without changing the authors' wording.

    * leading "Abstract" / "Abstract—" labels and trailing copyright / index-term blocks;
    * IEEE Xplore markup (``/spl isin/``, ``/sub M/``, ``/sup N/``) rendered as symbols;
    * explicit, organiser-listed word-split repairs from the seed (``abstract_fixes``).
    """
    if not text:
        return text
    t = re.sub(r"^\s*Abstract\s*[—:\-–]?\s*", "", text)
    t = re.sub(r"\s*Index Terms\s*[—:\-–].*$", "", t, flags=re.S)
    t = re.sub(r"\s*©\s*\d{4}.*$", "", t, flags=re.S)
    t = re.sub(r"/spl ([A-Za-z]+)/", lambda m: _IEEE_SPL.get(m.group(1), m.group(1)), t)
    t = re.sub(r"/sub ?([^/]*)/", lambda m: "_" + m.group(1).strip(), t)
    t = re.sub(r"/sup ?([^/]*)/", lambda m: "^" + m.group(1).strip(), t)
    t = t.replace("‐", "-")
    for old, new in fixes or []:
        t = t.replace(old, new)
    return re.sub(r"\s+", " ", t).strip()


def resolve(entry: dict) -> dict:
    doi = entry["doi"]
    work = None
    if entry.get("openalex"):
        work = _get(OPENALEX + entry["openalex"])
    if work is None:
        work = _get(OPENALEX + "doi:" + urllib.parse.quote(doi, safe="/:"))
    if work is None:
        raise RuntimeError(f"OpenAlex could not resolve {entry['internal_id']} ({doi})")
    cr = _get(CROSSREF + urllib.parse.quote(doi, safe="/")) or {}
    crm = cr.get("message", {}) if cr else {}
    biblio = work.get("biblio") or {}
    source = ((work.get("primary_location") or {}).get("source") or {})
    abstract = entry.get("abstract_override") or clean_abstract(
        _abstract(work.get("abstract_inverted_index")), entry.get("abstract_fixes")
    )
    record = {
        "internal_id": entry["internal_id"],
        "title": (work.get("title") or crm.get("title", [""])[0]).rstrip("."),
        "authors": [a["author"]["display_name"] for a in work.get("authorships", [])],
        "year": entry.get("year_override") or work.get("publication_year"),
        "first_public_year": entry.get("first_public_year")
        or entry.get("year_override")
        or work.get("publication_year"),
        "venue": entry.get("venue_override") or source.get("display_name"),
        "volume": crm.get("volume") or biblio.get("volume"),
        "issue": crm.get("issue") or biblio.get("issue"),
        "pages": crm.get("page")
        or ("-".join(p for p in [biblio.get("first_page"), biblio.get("last_page")] if p) or None),
        "doi": doi,
        "doi_url": "https://doi.org/" + doi,
        "open_access_url": entry.get("open_access_url"),
        "published_version": entry.get("published_version"),
        "access_note": entry.get("access_note"),
        "domain": entry["domain"],
        "abstract": abstract,
        "abstract_source": "organiser override (see override_notes)"
        if entry.get("abstract_override")
        else "OpenAlex abstract_inverted_index (cleaned: see clean_abstract)",
        "override_notes": entry.get("override_notes"),
        "openalex_id": work["id"],
        "openalex_referenced_works": work.get("referenced_works", []),
        "openalex_open_access": work.get("open_access"),
        "provenance": {
            "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "apis": ["OpenAlex"] + (["Crossref"] if crm else []),
        },
    }
    if record["title"]:
        record["title"] = record["title"][0].upper() + record["title"][1:]
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="do not write, only report")
    args = ap.parse_args(argv)
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    papers = []
    for entry in seed["papers"]:
        print(f"resolving {entry['internal_id']} ...", file=sys.stderr)
        papers.append(resolve(entry))
        time.sleep(0.3)
    by_oa = {p["openalex_id"]: p["internal_id"] for p in papers}
    citations = []
    for p in papers:
        for ref in p["openalex_referenced_works"]:
            if ref in by_oa:
                citations.append(
                    {
                        "source": p["internal_id"],
                        "target": by_oa[ref],
                        "evidence": f"OpenAlex referenced_works of {p['openalex_id']} contains {ref}",
                    }
                )
    manifest = {
        "theme": seed["theme"],
        "generated_by": "scripts/fetch_metadata.py",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "domains": seed["domains"],
        "papers": papers,
        "citations_in_corpus": citations,
        "notes": [
            "Abstracts are reproduced for educational, non-commercial workshop use with full attribution; "
            "full texts are NOT redistributed - participants follow DOI / open-access links.",
            "citations_in_corpus lists only citations visible in OpenAlex. Additional citations verified "
            "manually from full-text reference lists are recorded as evidence on CITES edges in the master graph.",
        ],
    }
    if args.check:
        old = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"papers": []}
        old_ids = {p["internal_id"]: p for p in old["papers"]}
        for p in papers:
            o = old_ids.get(p["internal_id"])
            if not o:
                print("NEW", p["internal_id"])
                continue
            for k in ("title", "year", "doi", "abstract", "authors"):
                if o.get(k) != p.get(k):
                    print(f"DIFF {p['internal_id']}.{k}")
        return 0
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST} with {len(papers)} papers and {len(citations)} in-corpus citations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
