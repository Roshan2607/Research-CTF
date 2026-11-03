# Organiser guide (ORGANISER ONLY)

> Contains the answer. Keep it off projected screens and out of participant channels.

## 1. One-time setup (about 15 minutes)

```bash
git clone https://github.com/naren-kanchi/Unchartered-Literature.git && cd Unchartered-Literature
python -m venv .venv && .venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                                   # macOS/Linux: cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"  # paste as FLAG_HMAC_SECRET in .env
#   also set ORGANISER_PASSWORD in .env
python scripts/build_challenge.py                        # validates and builds everything
python -m pytest                                         # all tests should pass
python scripts/demo_walkthrough.py                       # optional: rehearse the whole flow
```

`build_challenge.py` must print `[6] HMAC flag registry written`. If it prints a warning instead, `FLAG_HMAC_SECRET` is
missing. **Rotate the secret for each workshop run, then rebuild.** The registry is bound to the secret, and the
console's *Build & validate* tab shows whether both are present.

Set the final deadline in `config/challenge_config.json` (`final_submission.deadline`, ISO-8601 with timezone) or as
`FINAL_DEADLINE` in `.env`. Graph submissions also close at that deadline.

## 2. Running the apps

| App | Command | Who |
|---|---|---|
| Participant | `streamlit run app.py --server.port 8501 --server.address 0.0.0.0` | participants open `http://<your-LAN-IP>:8501` |
| Organiser | `streamlit run organiser_app.py --server.port 8502 --server.address 127.0.0.1` | you only (localhost + password) |

The participant app process reads the answer key **server-side only**, to score and validate flags. Nothing protected
is sent to browsers. Streamlit does not serve repository files over HTTP; this was checked, since requests for
`data/answer_key/...` and `.env` return only the app shell. Do **not** enable `server.enableStaticServing`.

If you use Kaggle for Submission 1, follow [KAGGLE_SETUP.md](KAGGLE_SETUP.md). The participant app is still used for the
corpus, hints and the final flag, and it is your fallback scorer.

## 3. Before the workshop (checklist)

- [ ] Read `docs/DATA_PROVENANCE.md`, `data/answer_key/*.json` and this guide end to end.
- [ ] **Review the flagged items** (section 8). Especially confirm the Ratnasamy & McCanne grouping procedure in the full
      text, and the Demers abstract repair.
- [ ] `python scripts/verify_evidence.py`: every quoted passage should be found (needs internet; caches PDFs locally).
- [ ] Create one team per pair in the console's **Teams** tab. Codes are shown once, so write them on cards.
- [ ] Print or share the challenge cards (`data/participant/cards/P01..P14.pdf`) or let teams download them in the app.
- [ ] Pilot the scoring weights with a colleague, and adjust `config/challenge_config.json` if needed. They are
      provisional.
- [ ] Prepare the live demo (minute 30–75) on a **different** example (section 5). Never demonstrate on this corpus.

## 4. Runbook (3 hours)

| Min | Activity | Console actions |
|---|---|---|
| 00–30 | Research fundamentals: problem, method, assumptions, limitations; why AI claims need verification | — |
| 30–75 | Live demo of finding a hidden interdisciplinary connection with ChatGPT plus evidence (section 5) | — |
| 75–85 | Teams, briefing, hand out team codes, open the app; read the *Start here* tab together | Teams tab |
| 85–105 | Reading and first graph | — |
| 105–115 | First graph submission (app or Kaggle) | Leaderboard tab |
| ~115 | Release **Hint 1** | Hints tab |
| 115–135 | Correction, alternative routes, evidence checking | Review queue (accept or reject evidence-backed new edges) |
| ~125 | Release **Hint 2** | Hints tab |
| ~135 | Release **Hint 3**; graph-submission deadline if on Kaggle | Hints tab |
| 135–150 | Hidden connection and applications | — |
| ~145 | Release **Hint 4** if teams are stuck | Hints tab |
| 150–165 | Final one-shot submission | Final flags tab (watch arrivals, don't reveal) |
| 165–180 | Solution walkthrough (section 6) and reflection | Canonical & alternatives, Decoys, Injections, AI-injection demo tabs |

Tip: during the solution walkthrough, project the **AI-injection demo** tab. It shows that a team with 20 correct edges
drops sharply when it adopts the naive assistant's injected edges.

## 5. Live demo suggestion (minute 30–75)

Use a different, well-known pair so you don't spoil the corpus. Examples: GPS positioning ↔ earthquake epicentre
location (trilateration), or PageRank ↔ eigenvector centrality in sociology. Show the steps:

1. Ask ChatGPT for a connection. It will produce something fluent.
2. Open the actual papers and find the passages that support or refute each claim.
3. Classify each claim: citation fact, method transfer, shared principle, or analogy.
4. Find an operational product and its official documentation. Ask whether there is real historical lineage, or only a
   shared principle.
5. Show a document containing a hidden instruction (make your own toy PDF) and how an assistant follows it.

## 6. Solution walkthrough (the answer)

**Starting paper P05.** Ratnasamy & McCanne 1999: infer a multicast tree from what receivers observe.
**Hidden target P03.** Saitou & Nei 1987: neighbor-joining, which reconstructs a phylogenetic tree from distances
between species.
**Shared principle:** *hidden-tree reconstruction from leaf-only measurements*. Two leaves that share more of the
unobserved tree look more similar (correlated packet loss / smaller evolutionary distance). The hidden branching
structure, including internal nodes nobody observes (routers / common ancestors), can therefore be rebuilt from leaf
data alone.

**Canonical route:** `P05 → P12 → P08 → P03`

| Hop | Evidence |
|---|---|
| P05 → P12 | P12 cites P05 among multicast-probing approaches (p.3, ref [23]) and says the network problem "is similar to the phylogenetic inference problem in evolutionary biology" (p.5) |
| P12 → P08 | P08 cites P12 (CISS 2008 version, ref [21]) and notes both use distance-based phylogenetic techniques (p.5) |
| P08 → P03 | P08 cites P03 (ref [24]); "the multicast link loss problem is in essence a special case of the standard model of DNA evolution" (p.5) |

**Verified alternatives:** ALT-A `P05 → P12 → P03` (P12 runs NJ, Alg. 1 p.13); ALT-B `P05 → P14 → P06 → P03`
(review → latent-tree ML, CLNJ); ALT-C `P05 → P12 → P08 → P11 → P03` (sample complexity).

**Application:** **Nextstrain**. It reconstructs pathogen phylogenies from sampled genomes and infers unobserved
ancestors' sequences and dates (`augur ancestral`, TreeTime). Evidence: Hadfield et al. 2018 (doi:10.1093/bioinformatics/bty407)
and docs.nextstrain.org. **No historical lineage** from P05 to Nextstrain. Nextstrain defaults to IQ-TREE (maximum
likelihood), not NJ.

**Decoys:**

* **P04** Candès et al. Its title matches the theme ("reconstruction from incomplete information"), but it is sparse
  signal recovery with no hidden graph.
* **P07** Demers et al. Uses "epidemic" vocabulary for gossip-based database replication; nothing is inferred. It is a
  tempting false bridge to "pathogen" applications.
* **P10** ARACNE. A biological network reconstruction that genuinely extends Chow-Liu (P01), but every node is an
  observed gene, with no hidden internal nodes.

**Injections:**

* **INJ-1** (P09 card): an explicit "SYSTEM OVERRIDE" pushing `P04 EXTENDS P05`.
* **INJ-2** (P01 card): a contextual claim that `P10 USES_METHOD P11` is "established".

Both are white-on-white in the card's annotation block. They are hosted on cards that are neither decoys nor on the
path, and the card layout is identical across all 14 cards.

Teaching points for the reflection:

1. A citation is a fact, a method transfer is a claim, and an analogy is an interpretation. Each needs different
   evidence.
2. Keyword overlap (P04) and shared metaphor (P07) are not shared methods.
3. A paper can be genuinely connected to part of the corpus (P10 → P01) and still not be on the path.
4. Documents are data, not instructions. The INJ edges carry the heaviest penalty for that reason.
5. Product ≠ lineage. Nextstrain operationalises the principle; it did not come from P05.

## 7. Scoring and review

* Weighted typed-edge F1 over 473 candidate edges. Classes: 41 reference, 89 neutral, 2 injection-induced,
  174 decoy-induced, 167 ordinary. Weights live in `config/challenge_config.json`.
* **Neutral** edges are neither rewarded nor penalised: `REQUIRES_REVIEW` edges, defensible cluster links, and every
  base–target link. The base–target masking stops the scorer being used as an oracle for the target.
* **Review queue:** any false-positive edge submitted with an `evidence_reference` appears in the console. Check the
  team's evidence against the paper. If it holds, accept it with your name; it becomes a reference edge for everyone
  and the local scores update immediately. For Kaggle, rebuild and re-upload the solution (KAGGLE_SETUP §5).
* **Final flags:** `CORRECT` is automatic only for target P03 plus a Nextstrain alias. Other applications arrive as
  `MANUAL_REVIEW`. Accept them if the team shows credible primary evidence that the product routinely rebuilds a
  hidden tree, including unobserved internal nodes, from leaf-only measurements. Record your decision in the Final
  flags tab. To accept an alternative application for everyone, add it to
  `final_answer.json → accepted_alternative_applications` and rebuild.
* The principle "advisory score" (0–4 keyword groups) only helps triage. Judge the explanation yourself.

## 8. Items flagged for scientific review before use with students

| Item | Status | What is needed |
|---|---|---|
| P05 grouping procedure is agglomerative pair-merging (like NJ) | abstract + Coates 2002 description only | Read Ratnasamy & McCanne §3 (IEEE, paywalled) |
| P07 abstract text | repaired from corrupted OCR | Compare with the ACM PDF |
| P06 EXTENDS P01, P06 EXTENDS P03, P08 USES_METHOD P11 | `REQUIRES_REVIEW` (neutral) | Expert decision: extension vs use |
| P12 card year 2011 / first public 2008 | documented | Make sure students understand that P08 cites the 2008 conference version |
| Abstracts reproduced on cards | attributed educational use | Check your institution's policy; replace with summaries if required |
| False-positive weights 1.0 / 0.5 / 3.0 | provisional | Pilot and tune |
| Nextstrain documentation quotes | fetched Nov 2026 | Re-check the pages before the workshop (docs change) |

## 9. After the workshop

Export from the console: graph submissions, leaderboard (public, private and all) and final flags (CSV). Archive
`data/submissions/` and then clear it for the next run. Rotate `FLAG_HMAC_SECRET` and rebuild.
