"""Schema for the heterogeneous, multi-relational scholarly knowledge graph.

This module is the *data dictionary*. Every node type, relationship type and
verification state used anywhere in the project is defined here, together with
the allowed (source type -> target type) signatures and the direction semantics.

Relationship kinds
------------------
Each relationship belongs to exactly one *claim kind*, so a bibliographic fact
(a citation) is never confused with a methodological or conceptual claim:

* ``bibliographic``  - a fact checkable in a reference list.
* ``methodological`` - a claim that a method is used or built upon.
* ``conceptual``     - a claim that two works rest on the same principle.
* ``interpretive``   - a claim that two problems are structurally analogous;
  an interpretation that needs explicit evidence.
* ``descriptive``    - organiser annotation linking a paper to concept nodes.
* ``application``    - a claim about a real-world product or technology.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NodeType(str, Enum):
    PAPER = "PAPER"
    PROBLEM = "PROBLEM"
    METHOD = "METHOD"
    PRINCIPLE = "PRINCIPLE"
    DOMAIN = "DOMAIN"
    APPLICATION = "APPLICATION"


class Status(str, Enum):
    VERIFIED = "VERIFIED"
    AI_PROPOSED = "AI_PROPOSED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    REJECTED = "REJECTED"


class ClaimKind(str, Enum):
    BIBLIOGRAPHIC = "bibliographic"
    METHODOLOGICAL = "methodological"
    CONCEPTUAL = "conceptual"
    INTERPRETIVE = "interpretive"
    DESCRIPTIVE = "descriptive"
    APPLICATION = "application"


@dataclass(frozen=True)
class RelationSpec:
    name: str
    claim_kind: ClaimKind
    symmetric: bool
    signatures: tuple[tuple[NodeType, NodeType], ...]
    meaning: str
    direction: str
    example: str
    temporal: bool = False  # source cannot pre-date target (checked on PAPER->PAPER)
    participant_submittable: bool = False  # usable in Submission 1 (paper-to-paper only)


P, PR, M, PI, D, A = (
    NodeType.PAPER,
    NodeType.PROBLEM,
    NodeType.METHOD,
    NodeType.PRINCIPLE,
    NodeType.DOMAIN,
    NodeType.APPLICATION,
)

RELATIONS: dict[str, RelationSpec] = {
    "CITES": RelationSpec(
        "CITES",
        ClaimKind.BIBLIOGRAPHIC,
        False,
        ((P, P),),
        "The source paper lists the target paper (or an earlier version of the same work) in its reference list.",
        "citing paper -> cited paper",
        "A 2015 paper whose reference list includes a 2009 paper CITES that 2009 paper.",
        temporal=True,
        participant_submittable=True,
    ),
    "USES_METHOD": RelationSpec(
        "USES_METHOD",
        ClaimKind.METHODOLOGICAL,
        False,
        ((P, M), (P, P)),
        "The source paper applies a method. PAPER->PAPER form: the source applies a method introduced in the target "
        "paper (as a component, baseline or tool), without necessarily changing it.",
        "user of the method -> method (or the paper that introduced it)",
        "A paper that runs k-means clustering as a pre-processing step USES_METHOD the paper that introduced k-means.",
        temporal=True,
        participant_submittable=True,
    ),
    "EXTENDS": RelationSpec(
        "EXTENDS",
        ClaimKind.METHODOLOGICAL,
        False,
        ((P, P), (M, M)),
        "The source proposes a new method by generalising, relaxing or modifying the target's method, and says so.",
        "newer, extended work -> work being extended",
        "A paper proposing 'weighted k-means' as a modification of k-means EXTENDS the k-means paper.",
        temporal=True,
        participant_submittable=True,
    ),
    "SHARES_PRINCIPLE": RelationSpec(
        "SHARES_PRINCIPLE",
        ClaimKind.CONCEPTUAL,
        True,
        ((P, P),),
        "Both papers' methods depend on the same underlying principle (named in the evidence), even if they use different "
        "vocabulary. A conceptual claim: you must name the principle and show it in both papers.",
        "symmetric (order does not matter; stored with the smaller ID first)",
        "A GPS-positioning paper and an earthquake-location paper both locate a source by intersecting distance estimates (trilateration), so they SHARE_PRINCIPLE.",
        participant_submittable=True,
    ),
    "ANALOGOUS_PROBLEM": RelationSpec(
        "ANALOGOUS_PROBLEM",
        ClaimKind.INTERPRETIVE,
        True,
        ((P, P), (PR, PR)),
        "The problems the two papers solve have the same abstract structure (what is hidden, what is observed, what must "
        "be inferred), possibly in different settings or disciplines. An interpretation: it needs evidence that an "
        "author draws the analogy, or a clear mapping between the problem statements.",
        "symmetric (order does not matter; stored with the smaller ID first)",
        "Locating a phone from cell-tower signal delays is ANALOGOUS_PROBLEM to locating an earthquake epicentre from seismograph arrival times; a paper that says so is evidence.",
        participant_submittable=True,
    ),
    "ADDRESSES": RelationSpec(
        "ADDRESSES",
        ClaimKind.DESCRIPTIVE,
        False,
        ((P, PR),),
        "The paper states this problem as (one of) its research problems.",
        "paper -> problem",
        "A paper on epicentre location ADDRESSES the problem 'locate a source from arrival times'.",
    ),
    "IN_DOMAIN": RelationSpec(
        "IN_DOMAIN",
        ClaimKind.DESCRIPTIVE,
        False,
        ((P, D),),
        "The paper's primary discipline (from venue and authors' framing).",
        "paper -> domain",
        "A Molecular Biology and Evolution paper is IN_DOMAIN biology.",
    ),
    "EMBODIES_PRINCIPLE": RelationSpec(
        "EMBODIES_PRINCIPLE",
        ClaimKind.CONCEPTUAL,
        False,
        ((M, PI), (P, PI)),
        "The method (or the paper's approach) is an instance of the principle.",
        "method/paper -> principle",
        "Trilateration EMBODIES_PRINCIPLE 'position from intersecting distance constraints'.",
    ),
    "OPERATIONALISES": RelationSpec(
        "OPERATIONALISES",
        ClaimKind.APPLICATION,
        False,
        ((A, PI), (A, M)),
        "A real-world product or technology puts the principle (or method) into routine practical use.",
        "application -> principle/method",
        "A satellite navigation receiver OPERATIONALISES trilateration.",
    ),
    "APPLICATION_OF": RelationSpec(
        "APPLICATION_OF",
        ClaimKind.APPLICATION,
        False,
        ((A, M), (A, P), (A, PR)),
        "The application is a use of this method / research problem. It does NOT claim historical lineage unless the "
        "evidence establishes it.",
        "application -> method/paper/problem",
        "A ride-hailing app's location fix is an APPLICATION_OF GPS positioning methods.",
    ),
}

SUBMITTABLE_RELATIONS: tuple[str, ...] = tuple(r for r, s in RELATIONS.items() if s.participant_submittable)
SYMMETRIC_RELATIONS: frozenset[str] = frozenset(r for r, s in RELATIONS.items() if s.symmetric)
TEMPORAL_RELATIONS: frozenset[str] = frozenset(r for r, s in RELATIONS.items() if s.temporal)

# Labels that describe organiser roles. None of these may appear in participant-facing data.
ORGANISER_ROLE_LABELS: tuple[str, ...] = (
    "BASE_PAPER",
    "INTERMEDIATE",
    "TARGET",
    "DECOY",
    "CANONICAL",
    "INJECTION",
    "ANSWER",
    "HIDDEN_CONNECTION",
)

PAPER_REQUIRED_FIELDS: tuple[str, ...] = (
    "title",
    "authors",
    "year",
    "doi",
    "abstract",
    "domain",
    "key_problem",
    "methods",
    "findings",
    "limitations",
    "evidence_refs",
    "participant_id",
)

EVIDENCE_REQUIRED_FIELDS: tuple[str, ...] = ("supporting_source", "doi_or_url", "location", "basis")


@dataclass
class Evidence:
    supporting_source: str
    doi_or_url: str
    location: str
    basis: str  # e.g. "full text", "abstract", "reference list", "OpenAlex referenced_works", "official documentation"
    quote: str | None = None


@dataclass
class Edge:
    id: str
    source: str
    target: str
    type: str
    explanation: str
    evidence: list[Evidence]
    status: Status
    reviewer_notes: str = ""
    extra: dict = field(default_factory=dict)


def canonical_pair(source: str, target: str, rel: str) -> tuple[str, str]:
    """Return the canonical (source, target) order for a relationship.

    Symmetric relations are stored with the lexicographically smaller ID first so
    that ``A SHARES_PRINCIPLE B`` and ``B SHARES_PRINCIPLE A`` are the same edge.
    """
    if rel in SYMMETRIC_RELATIONS and target < source:
        return target, source
    return source, target


def edge_key(source: str, target: str, rel: str) -> tuple[str, str, str]:
    s, t = canonical_pair(source, target, rel)
    return s, t, rel


def data_dictionary(participant: bool = True) -> list[dict]:
    """Description of the relationship vocabulary.

    With ``participant=True`` (default) only the paper-to-paper relationships that
    can be used in a graph submission are returned. Examples are deliberately taken
    from outside the corpus, so the dictionary reveals nothing about the answer.
    """
    rows = []
    for spec in RELATIONS.values():
        if participant and not spec.participant_submittable:
            continue
        rows.append(
            {
                "relationship_type": spec.name,
                "claim_kind": spec.claim_kind.value,
                "symmetric": spec.symmetric,
                "direction": spec.direction,
                "meaning": spec.meaning,
                "example": spec.example,
                "allowed_signatures": [f"{a.value}->{b.value}" for a, b in spec.signatures],
                "usable_in_graph_submission": spec.participant_submittable,
            }
        )
    return rows
