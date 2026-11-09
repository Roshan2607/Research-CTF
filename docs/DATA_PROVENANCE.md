# Data provenance (ORGANISER ONLY)

> This document names challenge roles (base, target, decoys). Do not hand it to participants.

## 1. Theme and selection criteria

**Theme:** *Reconstruction of Hidden Structures from Incomplete Information.*

Every paper in the corpus addresses some version of one question: *how can you work out something you cannot observe directly
from measurements that are partial, indirect or taken only at the edges of a system?* The corpus spans four discipline groups:

| Domain ID | Label | Papers |
|---|---|---|
| `DOM_BIO` | Biology & biomedical science | Saitou & Nei 1987; Margolin et al. 2006; Shepp & Logan 1974 (biomedical imaging) |
| `DOM_CS`  | Computer science, graph theory & ML | Chow & Liu 1968; Erdős et al. 1999; Choi et al. 2011 |
| `DOM_NET` | Networking & distributed systems | Demers et al. 1987; Ratnasamy & McCanne 1999; Duffield et al. 2002; Coates et al. 2002; Ni & Tatikonda 2011 |
| `DOM_SIG` | Signal processing, statistics & applied maths | Vardi 1996; Castro et al. 2004; Candès et al. 2006; Bhamidi et al. 2010 |

Selection rules applied:

1. **Primary research only, with one exception.** Castro et al. 2004 is a review. It is included on purpose: it is the
   paper in which network-tomography researchers themselves name the connection to phylogenetics and image reconstruction.
2. **Defensible inclusion.** Each paper has a reason to be here (table below), not keyword overlap alone.
3. **Mix of eras.** 1968 → 2011, with foundational and later work in each discipline.
4. **Open access preferred.** 8 of 15 have a free-to-read version. The rest are listed with DOI links only.
5. **No redistribution of full text.** Participant cards carry metadata, the attributed abstract and links. They never carry
   the paper body.

## 2. Corpus and inclusion rationale

Participant IDs are assigned in a shuffled order (see `data/corpus_seed.json`), so IDs say nothing about chronology,
domain or role.

| PID | Internal ID | Paper | Evidence level | Why it is included | Role (secret) |
|---|---|---|---|---|---|
| P01 | `PAPER_CHOWLIU1968` | Chow & Liu, *Approximating discrete probability distributions with dependence trees*, IEEE TIT 14(3), 1968 | abstract | Foundational tree-structure learning when **all** variables are observed. Two later corpus papers build on it. | supporting / hosts injection 2 |
| P02 | `PAPER_DUFFIELD2002` | Duffield, Horowitz, Lo Presti, Towsley, *Multicast topology inference from measured end-to-end loss*, IEEE TIT 48(1), 2002 | abstract | Formal estimators for the base paper's problem. | alternative-path node |
| P03 | `PAPER_SAITOUNEI1987` | Saitou & Nei, *The neighbor-joining method*, Mol. Biol. Evol. 4(4), 1987 | abstract (+ free PDF link) | Classic reconstruction of a hidden evolutionary tree from distances between observed species. | **TARGET** |
| P04 | `PAPER_CANDES2006` | Candès, Romberg, Tao, *Robust uncertainty principles: exact signal reconstruction from highly incomplete frequency information*, IEEE TIT 52(2), 2006 | abstract (+ arXiv) | Title matches the theme almost word for word, but its method (sparsity + ℓ1) has no hidden tree. | **DECOY** |
| P05 | `PAPER_RATNASAMY1999` | Ratnasamy & McCanne, *Inference of multicast routing trees and bottleneck bandwidths using end-to-end measurements*, INFOCOM 1999 | abstract | Infers the internal structure of a hidden tree from end-host observations only. | **BASE** (given to teams) |
| P06 | `PAPER_CHOI2011` | Choi, Tan, Anandkumar, Willsky, *Learning latent tree graphical models*, JMLR 12, 2011 | **full text** | Machine-learning generalisation of hidden-tree learning. Explicitly uses neighbor-joining and Chow-Liu. | alternative-path node |
| P07 | `PAPER_DEMERS1987` | Demers et al., *Epidemic algorithms for replicated database maintenance*, PODC 1987 | abstract | Uses biology vocabulary ("epidemic") for a distributed-systems problem; reconstructs nothing hidden. | **DECOY** |
| P08 | `PAPER_BHAMIDI2010` | Bhamidi, Rajagopal, Roch, *Network delay inference from additive metrics*, RSA 37(2), 2010 | **full text** | States that it uses phylogenetic techniques for network inference. | **INTERMEDIATE 2** |
| P09 | `PAPER_VARDI1996` | Vardi, *Network tomography: estimating source-destination traffic intensities from link data*, JASA 91(433), 1996 | abstract | Coined "network tomography": a linear inverse problem with **known** routing. | supporting / hosts injection 1 |
| P10 | `PAPER_MARGOLIN2006` | Margolin et al., *ARACNE*, BMC Bioinformatics 7(S1), 2006 | **full text** | Biological network reconstruction that sounds related but has no hidden nodes. | **DECOY** |
| P11 | `PAPER_ERDOS1999` | Erdős, Steel, Székely, Warnow, *A few logs suffice to build (almost) all trees (I)*, RSA 14(2), 1999 | abstract | Theory of how much data hidden-tree reconstruction needs. | alternative-path node |
| P12 | `PAPER_NITATIKONDA2011` | Ni & Tatikonda, *Network tomography based on additive metrics*, IEEE TIT 57(12), 2011 (arXiv 2008) | **full text (preprint)** | Says that network inference "is similar to the phylogenetic inference problem" and uses neighbor-joining. | **INTERMEDIATE 1** |
| P13 | `PAPER_COATES2002` | Coates et al., *Maximum likelihood network topology identification from edge-based unicast measurements*, SIGMETRICS 2002 | abstract | Topology inference with a global likelihood instead of pair-merging. | alternative-path node |
| P14 | `PAPER_CASTRO2004` | Castro, Coates, Liang, Nowak, Yu, *Network tomography: recent developments*, Stat. Sci. 19(3), 2004 | abstract | Review that names the phylogenetics connection. | alternative-path hub |
| P15 | `PAPER_SHEPPLOGAN1974` | Shepp & Logan, *The Fourier reconstruction of a head section*, IEEE Trans. Nucl. Sci. 21(3), 1974 | abstract | Added Nov 2026 as an easy decoy. It is classic CT image reconstruction from projections: the same vocabulary (reconstruction, tomography) as network tomography, but no hidden tree. Verified via OpenAlex and Crossref. | **DECOY (easy, L1)** |

"Evidence level" says how far the organiser read: **full text** means passages were located with page numbers (PyMuPDF on the
open-access PDF); **abstract** means only claims visible in the abstract or in OpenAlex reference lists are used as evidence.
Any edge resting on more than that is marked `REQUIRES_REVIEW` (see §4).

## 3. Sources and retrieval

* **OpenAlex** (`api.openalex.org`): titles, authors, years, venues, abstracts, `referenced_works`, OA status.
* **Crossref** (`api.crossref.org`): volume, issue, pages.
* **arXiv** (`export.arxiv.org`): abstract and full text for P06, P08, P12 and the P04 preprint.
* **Publisher OA PDFs**: BMC (P10).
* **Application evidence**: Nextstrain official documentation (`docs.nextstrain.org`) and Hadfield et al. 2018,
  *Bioinformatics* 34(23):4121–4123, doi:10.1093/bioinformatics/bty407.

Regenerate the manifest with `python scripts/fetch_metadata.py`. Re-check every quoted passage against the OA PDFs with
`python scripts/verify_evidence.py`.

### Documented overrides

* **P06**: OpenAlex indexes the arXiv record (2010). The JMLR publication year (2011) and venue are used instead. OpenAlex has
  no reference list for it, so citations were taken from the full text.
* **P07**: the OpenAlex abstract is corrupted OCR. A character-level repair is used. *Reviewer: confirm against the ACM PDF.*
* **P12**: there is no IEEE abstract in OpenAlex. The author's arXiv abstract is used. `first_public_year = 2008` because the
  CISS 2008 conference version is what Bhamidi et al. 2010 cite.

## 4. Verification policy

| Status | Meaning | Scored? |
|---|---|---|
| `VERIFIED` | The organiser found the supporting passage (or reference-list entry) and recorded it on the edge | Reference edge (counts as TP) |
| `REQUIRES_REVIEW` | Plausible and probably true, but needs full-text access or expert judgement | **Neutral**: neither rewarded nor penalised |
| `AI_PROPOSED` | Produced by a tool or an LLM. Never trusted until a human verifies it | Not in the reference set |
| `REJECTED` | Checked and found unsupported (decoy and injection edges) | False positive with organiser weight |

No AI-proposed relation is ever promoted automatically. Promotion happens only through the organiser review queue.

## 5. Known limitations

* Seven papers are abstract-only for the organiser. Their methodological edges are therefore limited to what the abstract
  states; deeper claims are `REQUIRES_REVIEW`.
* Year-based direction checks use `first_public_year`, which suits preprints but is an approximation.
* Abstract redistribution: abstracts are reproduced with attribution for non-commercial teaching. If an organiser's
  institution requires it, replace them with organiser-written summaries (field `abstract` in
  `data/participant/participant_papers.json`).
