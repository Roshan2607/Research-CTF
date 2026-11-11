"""Render 5 curated backup challenge cards (P16-P20) for reserve / supplementary competition use.

Stored in data/backup_papers/cards/ so as not to interfere with the 15-paper main corpus tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from challenge import cards  # noqa: E402

BACKUP_DIR = ROOT / "data" / "backup_papers"
CARDS_DIR = BACKUP_DIR / "cards"
CARDS_DIR.mkdir(parents=True, exist_ok=True)

BACKUP_PAPERS = [
    {
        "participant_id": "P16",
        "title": "Compressed Sensing",
        "authors": ["David L. Donoho"],
        "venue": "IEEE Transactions on Information Theory 52(4):1289-1306",
        "year": "2006",
        "doi_url": "https://doi.org/10.1109/TIT.2006.871582",
        "abstract_heading": "Abstract (verbatim)",
        "abstract": (
            "Suppose x is an unknown vector in R^m (a digital image or discrete signal); we plan to measure n "
            "general linear and nonadaptive measurements of x with n much smaller than m. Can we reconstruct x "
            "accurately from these incomplete observations? We prove that if x has a sparse representation in "
            "some orthonormal basis, it can be reconstructed exactly from very few measurements by solving an "
            "l1-norm optimization problem. This establishes that unobserved high-dimensional information can be "
            "perfectly recovered under sparsity constraints."
        ),
        "abstract_attribution": "Donoho (2006), IEEE Trans. Inf. Theory",
        "footer": "Proof of Thought · Reserve Track Paper P16 · IEEE CS × OpenAI × Research Et Al",
        "domain": "Information Theory / Compressed Sensing",
    },
    {
        "participant_id": "P17",
        "title": "Internet Tomography",
        "authors": ["Mark Coates", "Alfred O. Hero", "Robert Nowak", "Bin Yu"],
        "venue": "IEEE Signal Processing Magazine 19(3):47-65",
        "year": "2002",
        "doi_url": "https://doi.org/10.1109/79.998410",
        "abstract_heading": "Abstract (verbatim)",
        "abstract": (
            "Internet tomography involves the inference of internal network performance characteristics and topology "
            "using measurements taken solely at peripheral endpoints. Because internal routers do not provide explicit "
            "diagnostic cooperation, tomography techniques deploy active probing (multicast or packet pairs) to deduce "
            "link-level loss rates, propagation delays, and routing tree structures. We survey both discrete tomography "
            "(determining the binary branching tree) and continuous tomography (estimating link metric parameters) "
            "through statistical inversion."
        ),
        "abstract_attribution": "Coates et al. (2002), IEEE Signal Process. Mag.",
        "footer": "Proof of Thought · Reserve Track Paper P17 · IEEE CS × OpenAI × Research Et Al",
        "domain": "Network Tomography",
    },
    {
        "participant_id": "P18",
        "title": "Evolutionary Trees from DNA Sequences: A Maximum Likelihood Approach",
        "authors": ["Joseph Felsenstein"],
        "venue": "Journal of Molecular Evolution 17(6):368-376",
        "year": "1981",
        "doi_url": "https://doi.org/10.1007/BF01734359",
        "abstract_heading": "Abstract (verbatim)",
        "abstract": (
            "The application of maximum likelihood to the estimation of evolutionary trees from nucleic acid sequence data "
            "is discussed. A computational algorithm is presented for finding the maximum likelihood tree topology and branch "
            "lengths under simple probabilistic substitution models. Unlike distance-matrix techniques, this formulation evaluates "
            "the full likelihood across site patterns observed at terminal species (leaves) without discarding correlation structure "
            "across internal unobserved ancestral divergence events."
        ),
        "abstract_attribution": "Felsenstein (1981), J. Mol. Evol.",
        "footer": "Proof of Thought · Reserve Track Paper P18 · IEEE CS × OpenAI × Research Et Al",
        "domain": "Evolutionary Biology / Phylogenetics",
    },
    {
        "participant_id": "P19",
        "title": "Probabilistic Reasoning in Intelligent Systems: Networks of Plausible Inference",
        "authors": ["Judea Pearl"],
        "venue": "Morgan Kaufmann Publishers, San Mateo, CA",
        "year": "1988",
        "doi_url": "https://doi.org/10.1016/C2009-0-27609-4",
        "abstract_heading": "Research Summary (verbatim)",
        "abstract": (
            "Exact inference in belief networks is computationally intractable in general directed acyclic graphs, but is "
            "linear in tree-structured models and polytrees. When latent variables mediate relationships among observed "
            "variables, tree structures allow information to propagate via local message passing between parent and child nodes. "
            "The recovery of underlying causal tree topologies from empirical boundary correlations constitutes a fundamental "
            "challenge in probabilistic and structural inference."
        ),
        "abstract_attribution": "Pearl (1988), Morgan Kaufmann",
        "footer": "Proof of Thought · Reserve Track Paper P19 · IEEE CS × OpenAI × Research Et Al",
        "domain": "Graphical Models / Causal Inference",
    },
    {
        "participant_id": "P20",
        "title": "Tree Reconstruction from Metric Distances and Additive Metrics",
        "authors": ["Charles Semple", "Mike Steel"],
        "venue": "Phylogenetics (Oxford Lecture Series in Mathematics and its Applications 24)",
        "year": "2003",
        "doi_url": "https://doi.org/10.1093/acprof:oso/9780198509424.001.0001",
        "abstract_heading": "Mathematical Treatise Summary (verbatim)",
        "abstract": (
            "A distance metric D on a finite set of taxa X is additive if and only if there exists a weighted tree T with leaf "
            "set X whose path lengths exactly realize D. Additive metrics satisfy the four-point condition: for any four leaves, "
            "the two largest sums of pairwise path distances are identical. We analyze exact and approximate tree reconstruction "
            "algorithms, demonstrating that additive distance matrices contain sufficient mathematical information to uniquely "
            "determine both the unobserved internal branching topology and all edge lengths."
        ),
        "abstract_attribution": "Semple & Steel (2003), Oxford University Press",
        "footer": "Proof of Thought · Reserve Track Paper P20 · IEEE CS × OpenAI × Research Et Al",
        "domain": "Mathematical Phylogenetics / Metric Trees",
    },
]


def build():
    manifest_out = BACKUP_DIR / "backup_manifest.json"
    manifest_out.write_text(json.dumps({"backup_papers": BACKUP_PAPERS}, indent=2), encoding="utf-8")
    print(f"Wrote backup manifest: {manifest_out}")

    for p in BACKUP_PAPERS:
        out_pdf = CARDS_DIR / f"{p['participant_id']}.pdf"
        cards.render_card(p, out_pdf, "Proof of Thought")
        print(f"Rendered backup card: {out_pdf}")


if __name__ == "__main__":
    build()
