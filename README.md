# Bugzilla: Firefox project-history QA

Course project: **Memorize, Retrieve, or Query? LLMs Answering Questions about a Software Project's History**. We compare M0 closed-book, M1 BM25 RAG, M2 hybrid retrieval, and M3 parameterized SQL; M4 small-graph retrieval is optional. The scientific plan is [research_roadmap.tex](docs/reference/research_roadmap.tex).

Data normalization and the 50-bug history pilot are verified. Phase 5 has **169 benchmark candidates and 6 supplemental paraphrase challenges**, awaiting completed human source review and validation. The 180-question target has an 11-question F2 shortfall; historical as-of coverage is zero. The benchmark is **not frozen** and method evaluation has not started.

## Set up a fresh clone

Use Git and **Python 3.10 or newer** (Python 3.11 recommended):

```bash
git clone https://github.com/ahmadfaisal9900/Bugzilla.git
cd Bugzilla
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell. If you already have a clone, work in that repository and pull your partner's latest changes before reviewing. Access to the GitHub repository is required. No paid service or API key is needed.

The review server itself uses only Python's standard library, so reviewers can skip the virtual environment and package installation if they only need the browser interface. `requirements.txt` pins DuckDB for the data and benchmark tools. A fresh clone includes the small review bundle; downloading datasets or rebuilding Phases 2–4 is not required to open it.

## Phase 5 — Human Benchmark Review

From the repository root, navigate to the review folder and start the local server:

```bash
cd "outputs/benchmark/phase05/agent_review/signoff/run-65c5be3381f66811"
python3 review_server.py
```

Open **[http://127.0.0.1:8765/](http://127.0.0.1:8765/)** in your browser. Enter **your own name** and review the questions one at a time. Check the proposed answer against the linked evidence, then choose:

| Interface action | Saved decision | What to do |
| --- | --- | --- |
| Looks correct | `APPROVE` | Check the source confirmation after inspecting the evidence. |
| Needs a fix | `CORRECT` | Supply an evidence-supported correction; F5 explanations also require rationale confirmation. |
| Reject | `REJECT` | Explain briefly why the question should be excluded. |
| Skip for now | `PENDING` for an unanswered item | Return when you have the evidence needed to decide. |

Decisions are automatically saved to `signoff_queue.csv`, with the reviewer name and UTC timestamp. No manual CSV editing is needed. Existing decisions are preserved; the default view shows remaining reviews. The interface tracks **64 required reviews**: all 30 F5 candidates, 22 seeded F1–F4 factual spot-checks, 6 F6 controls, and all 6 challenges (including one F5 challenge). Challenges do not increase the 169-candidate benchmark denominator.

For F5, check that **every causal claim is actually stated in the cited comment**. A log, path, unrelated “because” fragment, or proposed fix alone may not establish the explanation. All selected F5 comments come from FIXED-selected bugs; findings do not generalize to unresolved bugs. Codex recommendations are advisory and do not count as human source checks. Leave unavailable or ambiguous evidence pending rather than confirming it.

Expand **Full original question and technical audit details** to inspect the exact question, saved evidence fields, source hashes, and local packet reference. Judge the declared saved corpus, not today's live Bugzilla status. CSV snapshot time is UNKNOWN. Public links help inspect comments/history, but live pages alone cannot establish frozen aggregate counts or the precise archived state. The full hashed packets, population manifests and canonical DuckDB are not included in Git; request the matching local evidence from the project owner when needed, especially for F2/F3. Do not mark `source_checked` until you have sufficient evidence.

When finished, stop the server with **Ctrl+C**, then run from the same review folder:

```bash
python3 review_server.py --check
```

This reports outstanding reviews and checks immutable columns against `signoff_queue.before_review.csv`. It is a local consistency check, not a benchmark freeze or independent verification of the answers.

## Share reviews with your partner

Coordinate who reviews which questions, and avoid editing the same shared CSV simultaneously. Pull before starting a review session. After stopping the server and running `--check`, return to the repository root:

```bash
cd ../../../../../..
git diff -- outputs/benchmark/phase05/agent_review/signoff/run-65c5be3381f66811/signoff_queue.csv
git add outputs/benchmark/phase05/agent_review/signoff/run-65c5be3381f66811/signoff_queue.csv
git diff --cached --name-only
git commit -m "phase 5: record human benchmark reviews"
git push origin main
```

If Git reports a queue conflict, preserve both versions and reconcile by qid with your partner; do not overwrite their reviews. Do not invent a second reviewer or sign on another person's behalf.

Only the small, explicitly allowed review files are tracked under `outputs/`. The original queue backup and `REVIEW_BUNDLE.json` preserve the packaged provenance; the manifest's packaged queue checksum describes that version and is expected to differ after later reviews. Large datasets, raw API responses, full comment packets, databases, Parquet, logs and other generated outputs remain ignored. Keep reviewer artifacts and test gold out of method prompts, retrieval indexes and evaluation logs.

## Finalization belongs to the project owner

Completed UI decisions first need an audited transfer into the original generation run's `review_queue.csv`, preserving its immutable fields and a backup. The global `review_signoff.json` also requires actual owner signoff. Every retained F5 needs human review under the current protocol; an unchecked F5 remains unverified. Reduced F5 coverage requires an explicit documented protocol decision.

With matching local source artifacts, the owner runs from the repository root:

```bash
bash scripts/run_phase05_validate_freeze.sh --help
bash scripts/run_phase05_validate_freeze.sh --dry-run --run outputs/benchmark/phase05/run-65c5be3381f66811 --seed 317
# Only after genuine required reviews and global signoff have been transferred:
bash scripts/run_phase05_validate_freeze.sh --run outputs/benchmark/phase05/run-65c5be3381f66811 --seed 317 --resume
```

Dry-run prints preconditions only. The full validator recomputes gold and hashes the large local database; run it in your own terminal. Phase 5 becomes VERIFIED/FROZEN only after its real acceptance gates and results have been checked.

## Project documentation

- [RESEARCH_STATUS](docs/RESEARCH_STATUS.md): completed work, current state, evidence gaps and next gate.
- [PHASE_LOG](docs/PHASE_LOG.md), [DECISIONS](docs/DECISIONS.md), and [EXPERIMENT_REGISTRY](docs/EXPERIMENT_REGISTRY.md): implementation history and study decisions.
- [RUNBOOK](docs/RUNBOOK.md): terminal workflows and local artifacts.
- [Assisted review protocol](docs/PHASE05_ASSISTED_REVIEW_PROTOCOL.md) and [benchmark protocol](docs/PHASE05_BENCHMARK.md): review fields, rubric and freeze gates.
- [DATA_DICTIONARY](docs/DATA_DICTIONARY.md) and [TEMPORAL_VALIDITY](docs/TEMPORAL_VALIDITY.md): source fields and valid time claims.
- **[Project Report.pdf](<docs/Project Report.pdf>)**: planned project report; the owner will add this PDF to `docs/` soon. The link will work once it is committed.

Original downloads remain read-only under ignored `Dataset/`, including the upstream authors' clone. The existing repository remote is `https://github.com/ahmadfaisal9900/Bugzilla.git`.
