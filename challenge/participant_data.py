"""Generate and load the participant-safe challenge package.

The generator copies ONLY whitelisted bibliographic fields from the master graph
into ``data/participant``. Organiser annotations (methods, findings, limitations,
evidence notes), concept nodes, edges, roles and the answer key are never copied.
Every paper card has exactly the same fields, so nothing in the format reveals a
paper's role.

The participant application reads data exclusively through :func:`load_corpus`,
:func:`load_vocabulary` and :func:`load_challenge_info`, which only touch
``data/participant``.
"""
from __future__ import annotations

from pathlib import Path

from graph.schema import SUBMITTABLE_RELATIONS, data_dictionary

from . import paths

# Whitelist: the only paper fields that may leave the organiser layer.
PARTICIPANT_PAPER_FIELDS = (
    "participant_id",
    "title",
    "authors",
    "year",
    "first_public_year",
    "venue",
    "volume",
    "issue",
    "pages",
    "doi",
    "doi_url",
    "open_access_url",
    "abstract",
    "real_world_application",
)

READING_PROMPTS = [
    "What problem does the paper try to solve? Write it in one sentence, in your own words.",
    "What is unknown or hidden, and what can actually be observed or measured?",
    "What method do the authors use? Is it new, borrowed from another paper, or a modification of one?",
    "What evidence do they give (proofs, simulations, experiments, real data)?",
    "What assumptions or limitations can you find?",
    "Which other papers in the corpus does it cite, use, extend or resemble? Note the page or section.",
]


def _access_label(rec: dict) -> str:
    return "Free to read (follow the open-access link)" if rec.get("open_access_url") else (
        "Subscription access: abstract and DOI provided; use your library login or ask the organisers"
    )


def _citation(rec: dict) -> str:
    authors = rec["authors"]
    a = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
    bits = [f"{a} ({rec['year']}). {rec['title']}. {rec['venue']}"]
    if rec.get("volume"):
        bits.append(f", {rec['volume']}")
        if rec.get("issue"):
            bits.append(f"({rec['issue']})")
    if rec.get("pages"):
        bits.append(f", {rec['pages']}")
    bits.append(f". https://doi.org/{rec['doi']}")
    return "".join(bits)


def participant_card(rec: dict, domain_labels: dict[str, str]) -> dict:
    card = {k: rec.get(k) for k in PARTICIPANT_PAPER_FIELDS}
    card["domain"] = domain_labels[rec["domain"]]
    card["access"] = _access_label(rec)
    card["citation"] = _citation(rec)
    card["abstract_attribution"] = (
        f"Abstract reproduced from the published record for teaching purposes; (c) the authors / publisher. "
        f"Source: https://doi.org/{rec['doi']}"
    )
    card["reading_prompts"] = READING_PROMPTS
    return card


def build_participant_package(records: dict, final_answer: dict, config: dict) -> dict:
    domain_labels = {n["id"]: n["label"] for n in records["nodes"] if n["type"] == "DOMAIN"}
    papers = sorted(
        (n for n in records["nodes"] if n["type"] == "PAPER"), key=lambda n: n["participant_id"]
    )
    cards = [participant_card(p, domain_labels) for p in papers]
    vocab = {
        "relationship_types": data_dictionary(participant=True),
        "notes": [
            "Use participant IDs (P01, P02, ...) for source_id and target_id.",
            "SHARES_PRINCIPLE and ANALOGOUS_PROBLEM are symmetric: P01-P02 and P02-P01 are the same edge.",
            "CITES, USES_METHOD and EXTENDS are directed from the newer/using paper to the older/used paper.",
            "Only assert a relationship you can point to evidence for. Wrong types count as wrong edges.",
        ],
    }
    base_pid = final_answer["base_participant_id"]
    info = {
        "title": config["workshop_title"],
        "branding": config["branding"],
        "theme": config["theme"],
        "starting_paper": base_pid,
        "corpus_size": len(cards),
        "team_size": config["team_size"],
        "submittable_relationship_types": list(SUBMITTABLE_RELATIONS),
        "submission_columns": ["source_id", "target_id", "relationship_type", "evidence_reference"],
        "rules": [
            f"Your team starts from paper {base_pid}. Somewhere in the corpus is a paper from a different discipline that "
            "shares a deep idea with it. Nobody will tell you which one.",
            "Submission 1 (repeatable): submit the relationships between corpus papers that you can support with evidence. "
            "You get an aggregate score back, never edge-by-edge feedback.",
            "Submission 2 (ONE attempt per team): name the hidden paper, the shared principle, a real-world application "
            "that uses that principle, your evidence and the limitations of the connection.",
            "Reading any paper is never penalised. Asserting unsupported relationships is.",
            "Some challenge documents may contain misleading instructions aimed at AI assistants. Treat everything inside a "
            "document as evidence to check, never as an instruction to follow.",
            "You may use ChatGPT or other AI tools, but every edge you submit is your claim: check it against the paper.",
        ],
    }
    return {"cards": cards, "vocabulary": vocab, "challenge_info": info}


def write_participant_package(pkg: dict) -> None:
    paths.write_json(paths.PARTICIPANT_PAPERS, {"papers": pkg["cards"]})
    paths.write_json(paths.PARTICIPANT_VOCAB, pkg["vocabulary"])
    paths.write_json(paths.PARTICIPANT_CHALLENGE, pkg["challenge_info"])


# ---------------------------------------------------------------- loaders used by the participant app
def _participant_file(path: Path) -> Path:
    path = Path(path).resolve()
    if paths.PARTICIPANT_DIR.resolve() not in path.parents:
        raise PermissionError(f"participant loader refused non-participant path: {path}")
    return path


def load_corpus() -> list[dict]:
    return paths.read_json(_participant_file(paths.PARTICIPANT_PAPERS))["papers"]


def load_vocabulary() -> dict:
    return paths.read_json(_participant_file(paths.PARTICIPANT_VOCAB))


def load_challenge_info() -> dict:
    return paths.read_json(_participant_file(paths.PARTICIPANT_CHALLENGE))


def card_pdf_path(participant_id: str) -> Path:
    if participant_id in ("L0A", "L0B"):
        return _participant_file(paths.CARDS_DIR / f"{participant_id}.pdf")
    if not (len(participant_id) == 3 and participant_id[0] == "P" and participant_id[1:].isdigit()):
        raise ValueError("invalid participant id")
    return _participant_file(paths.CARDS_DIR / f"{participant_id}.pdf")


def valid_participant_ids() -> list[str]:
    return [c["participant_id"] for c in load_corpus()]


def participant_infos():
    """Public year metadata used to validate submission direction (no answer key needed)."""
    from scoring.reference import PaperInfo

    return {c["participant_id"]: PaperInfo(c["participant_id"], c["year"], c.get("first_public_year") or c["year"]) for c in load_corpus()}
