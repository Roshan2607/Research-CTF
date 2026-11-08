# Uncharted Literature: participant guide

**OpenAI × IEEE CS × Research Et Al** · Knowledge Graph CTF · teams of two

> You don't need any background in graph theory, research methods or AI security. Everything you need is explained below.

## 1. The story

You get 14 research papers from four fields: biology, computer science, networking and signal processing. Their titles
make them look unrelated, and most of them are. But some papers in different fields are secretly working on the same
idea, using completely different words.

Your team starts from one paper, your **starting paper** (shown in the app). Your mission:

1. **Read** the papers.
2. **Map** how they relate to each other, with evidence. This map is a small *knowledge graph*.
3. **Discover** which paper, from a *different discipline*, shares a deep idea with your starting paper.
4. **Find** a real-world technology that relies on that idea every day.

## 2. Five ideas you need

| Idea | Plain-language meaning | Example (not from the corpus) |
|---|---|---|
| **Research problem** | The specific question a paper answers | "How can we locate an earthquake when we only have a few seismometers?" |
| **Methodology** | *How* the paper answers it: algorithm, model, experiment, proof | "Intersect the distance estimates from three or more stations" |
| **Conceptual relationship** | Two papers rely on the same underlying idea, even with different words | GPS and earthquake location both use *trilateration* |
| **Knowledge graph** | Things (papers) connected by labelled arrows (relationships) | `PX --CITES--> PY` |
| **Evidence** | Where in the paper you saw it | `PX p.4, Sec. 2: "we adopt the estimator of [12]"` |

### Relationship types you can submit

| Type | Meaning | Direction |
|---|---|---|
| `CITES` | The paper lists the other one in its references | newer → older |
| `USES_METHOD` | The paper applies a method introduced in the other paper | user → origin |
| `EXTENDS` | The paper proposes a modified or generalised version of the other paper's method, and says so | newer → older |
| `SHARES_PRINCIPLE` | Both rely on the same underlying principle (name it!) | either way (symmetric) |
| `ANALOGOUS_PROBLEM` | Both problems have the same structure: what's hidden, what's observed, what's inferred | either way (symmetric) |

A citation is a **fact** you can check in the reference list. A shared method is a **claim** about how the work was done.
A shared principle or an analogous problem is an **interpretation**, and interpretations need the strongest evidence.

## 3. How to read a paper in 10 minutes

1. **Abstract**: what problem, what method, what result? (Every card has the abstract.)
2. **Introduction, last paragraph**: usually lists the contributions.
3. **Related work**: this is where authors connect their work to other fields. Look for phrases like
   *"is similar to"*, *"inspired by"*, *"we adopt"*.
4. **Methods / algorithm boxes**: what actually happens.
5. **Reference list**: which corpus papers are cited? (Match titles and authors.)
6. **Limitations**: what do they assume? Where does it break?

Use the reading prompts on each card. For every claim, write down the page or section.

## 4. Using AI tools (allowed, but be careful)

You can use ChatGPT or any other assistant to summarise papers, explain terms or suggest connections. But:

* AI tools produce **confident, fluent text that can be wrong**, including relationships that don't exist.
* **Documents can contain hidden instructions aimed at AI tools.** Some challenge documents may do exactly that. If you
  paste or upload a document into an AI assistant, the assistant may obey text you can't even see.
* Treat everything an AI tells you as a **lead to check**, not an answer. If you can't find the supporting passage in the
  paper itself, don't submit the edge.

## 5. Submission 1: your knowledge graph (repeatable)

Build your graph in the app's **Graph builder** tab, or upload a CSV like this:

```csv
source_id,target_id,relationship_type,evidence_reference
PX,PY,CITES,PX reference [12]
PX,PY,USES_METHOD,PX Sec. 3 p.5: "we use the estimator of [12]"
PX,PZ,SHARES_PRINCIPLE,Both rely on <name the principle>: PX p.2; PZ Sec. 4
```

*(Replace PX / PY / PZ with real IDs such as P01. These rows only illustrate the format.)*

* One row per relationship. Leaving a relationship out simply means "not claimed".
* Directed types go from the newer / using paper to the older / used paper. The app rejects impossible directions.
* Some cards say an earlier version of the paper was public before its journal year. Use that date for citations.
* `evidence_reference` is optional, but if you include it the organisers can review relationships they hadn't thought of
  and credit you.

**Scoring.** You get one number back, a **weighted F1** (0 to 1), plus precision and recall:

* **Recall** goes up when you find more real, evidence-backed relationships.
* **Precision** goes down when you claim unsupported ones. Claims that come from blindly following hidden instructions
  cost the most.
* A wrong relationship *type* counts as wrong.
* You will never be told which individual edges were right. Reading any paper is never penalised.
* Limited submissions, with a short wait between them. The leaderboard shows the best score per team.

If the workshop uses Kaggle, download **"Kaggle submission"** from the Graph builder and upload that file to the Kaggle
competition page.

## 6. Submission 2: the discovery (ONE attempt)

In the **Final discovery** tab, give:

1. your starting paper and the **hidden connected paper**;
2. the **shared principle**, in 2–4 sentences of your own words;
3. a **real-world product, technology or application** that uses that principle;
4. **evidence**: paper IDs with pages/sections, and links to credible sources about the application (official
   documentation, technical papers, patents);
5. **limitations**: where does the connection break down? Is there a real historical link, or just a shared idea?

A product name on its own will not be accepted. After you submit, your answer is locked and you get **no feedback until
the deadline**. Other well-argued applications are reviewed by the organisers by hand.

## 7. Hints

Hints appear in the **Hints** tab as the organisers release them. They point you towards *kinds of ideas*, never to
specific papers.

## 8. Quick checklist before you submit

- [ ] Every edge has a page, section or reference number you could show an organiser.
- [ ] You checked AI-suggested edges against the paper itself.
- [ ] You can explain the shared principle without using either paper's jargon.
- [ ] Your application evidence comes from the product's own documentation or a technical publication.
- [ ] You stated at least one limitation.
