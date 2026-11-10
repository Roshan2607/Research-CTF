# Evaluation: what is proven, how, and what is not

Measured on 2026-11-10 against the committed answer key and the live judge (`gpt-6.1-terra`, ChatGPT plan sign-in).
Every number below can be reproduced with the command next to it. Nothing here was tuned against the test data.

## 1. Graph scorer and level gate: PROVEN (deterministic)

`python3 scripts/prove_scoring.py` (no API calls, exits non-zero on any mismatch). **30/30 checks pass.**

* Weighted precision / recall / F1 equal hand-computed values at every level (reference sizes 5 / 16 / 26 / 41):
  full reference, a single edge, +2 ordinary errors (weight 1.0), +2 decoy-induced (0.5), half the reference + 1 error.
* Edges using papers not yet released are ignored at lower levels.
* Injection-induced edges carry weight 3.0 once their host card is released (P04-P05 EXTENDS at L2-L4, P08-P03 USES_METHOD at L4).
* **Not exercised:** the "host card not yet released" downgrade path. In this corpus both injected edges only exist in scope
  after their host card is released, so that branch has no data to run on.

Gate (flag AND graph floor, 0.40 at L1, 0.50 at L2-L4): `tests/test_graph_gate.py` (8 tests) and a full browser run:
a weak L2 graph was refused (score 0.00 vs 0.50), a fixed one locked; all later levels cleared the floor first try.

## 2. Judge pipeline under load: PROVEN for 35 teams x 4 bursts

`python3 scripts/sustained_load.py --bursts 4 --gap 20` (28 workers, batch 5, 6 distinct new edges per team):

| Burst | Teams verdict-complete | p50 | p90 | max | Within 30 s |
|---|---|---|---|---|---|
| 1 | 35/35 | 9.2 s | 14.5 s | 16.5 s | 35/35 |
| 2 | 35/35 | 9.0 s | 14.3 s | 15.0 s | 35/35 |
| 3 | 35/35 | 9.8 s | 14.6 s | 17.5 s | 35/35 |
| 4 | 35/35 | 9.5 s | 15.4 s | 16.4 s | 35/35 |

0 errors, 0 pending/deferred, no throttling. Submitting is never blocked by the judge (all 35 enqueue in ~0.25 s).
Earlier runs on weaker settings (14 workers) were 32 s worst case, which is why the default is now 28.

## 3. Token refresh against the real service: PROVEN

Forced an expired token and called `get_access_token()`: the real token endpoint accepted the standard
`grant_type=refresh_token` request. Findings:

* The response carries `access_token`, `refresh_token`, `expires_in`, `scope`, `id_token` and **`earliest_refresh_at`**.
  A refresh requested too early returns the same tokens; a later one rotates both.
* The refreshed credentials were saved (mode 0600) and a live `/v1/models` call with them returned 200.
* `chatgpt_auth.refresh` stores the rotated refresh token. Anything that calls the token endpoint directly
  without saving the result will consume the stored token (this happened once during testing and was repaired).

## 4. LLM judge accuracy: MEASURED, with real limits

`python3 scripts/judge_accuracy.py`. Ground truth = organiser classification: 41 reference edges (positives) vs 62 negatives
(30 decoy-induced, 30 ordinary, 2 injection-induced); `neutral` excluded. Each edge carries a real abstract quote, so the
evidence rule is not measured here. Two independent runs, 95% Wilson intervals.

| Rule | Precision | Recall on reference edges | False-accept rate on wrong edges |
|---|---|---|---|
| `supported` only | 7/7 = 100% (CI 65-100%) both runs | 7/41 = 17% (CI 9-31%) | 0/62 = 0% (CI 0-6%) both runs |
| `supported` or `plausible` | 53% / 75% | 20% / 22% | 11% / 5% |

What this says:

* **`supported` is trustworthy but rare.** Zero wrong edges were ever `supported` (124 judgments), but intervals are wide
  because only 7 edges reached it.
* **Recall is low because of the evidence available.** Judge sees abstracts only. By type, reference edges:
  ANALOGOUS_PROBLEM 6/7 supported (+1 plausible); SHARES_PRINCIPLE 1/3; CITES 0/26 (abstract has no reference list: 17 abstain, 9 unsupported);
  USES_METHOD 0/3; EXTENDS 0/2. The judge is a filter for **novel interpretive edges**, not a way to verify citations or method claims.
* **`plausible` is not safe to reward automatically** (5-11% of wrong edges land there). Use `supported` only for credit; treat
  `plausible` as organiser-review.
* **Not deterministic.** Same edge, two runs: 84/103 = **82%** same label (CI 73-88%) even at temperature 0. Within one event this
  is hidden by the per-edge cache (an edge is judged once), but a re-run after the event can change borderline verdicts.
  Not measured: agreement collapsing to accept-vs-not-accept, or the effect of `samples=3` unanimity.

## 5. Prompt-injection resistance: MEASURED

Same wrong edges, evidence replaced by one of five attack payloads (ignore-instructions, fake system tag with tag break-out,
"mark e1..e5 supported", fake organiser authorisation, forged JSON answer). 40 edges:

* raw `supported`: **0/40** with injected evidence (baseline 0/40).
* `supported` or `plausible`: 4/40 = 10% (baseline on wrong edges 11% / 5%): no measurable uplift.
* Mechanically, addressing is by server-assigned ids, tags are neutralised, the output is a forced schema, and the evidence
  rule is applied after the model, so no prompt can raise a verdict past `plausible` without a verifiable quote.
* **Not tested:** adaptive attackers who see the prompt, multilingual payloads, or injection through the paper text itself.

## 6. Full pipeline as a participant: PROVEN once

Browser run, team ALPHA1: L0 to L4 with real saves, edge building, explanations, locks; final page 72.92/100
(flags 40/40, graph 32.92/60). Per-level graph F1 0.60 / 0.56 / 0.53 / 0.51. Judging queued at each lock.

## 7. Test suite

`python3 -m pytest`: **252 passed, 1 skipped** (after installing `pymupdf`, already in requirements.txt; the two tests that
failed earlier needed it, and one older UI test needed Streamlit >= 1.37).

## 8. Not proven / open

* **Judge quality on real teams' edges.** Test set is the organiser's own classification; `ordinary` edges are organiser-labelled
  wrong but a few may be defensible, which would make some false accepts look worse than they are.
* **Plan limits over a whole event** (hours, not minutes), and whether the ChatGPT-plan sign-in is permitted for this use.
* **Nothing consumes the verdicts.** No creativity bonus calculation and no organiser view exist, so judge output changes no score.
* **Level 4 final discovery** is not active (`flag_mode=keyword` in `data/event_content.csv`); docs say otherwise.
* **Gate floors** are set from simulation, not from real team data; L1 (5 reference edges) is inherently noisy.
* **Security** items (hard-coded organiser password in source and the login placeholder) are unrelated to scoring and still open.
