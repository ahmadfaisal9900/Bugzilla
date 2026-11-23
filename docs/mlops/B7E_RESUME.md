# B7e offline findings

## Parser coverage

| Family | Fully parsed | Total |
| --- | ---: | ---: |
| F2 | 8 | 8 |
| F3 | 12 | 12 |
| F4 | 19 | 19 |
| MH | 8 | 8 |

## Existing new rows scored offline with scorer v2

| Family | S8v2 new | S8 v1 same questions | S8 v1 full eligible family |
| --- | ---: | ---: | ---: |
| F2 | 2/4 | 3/4 | 7/8 |
| F3 | 3/6 | 0/6 | 6/12 |
| F4 | 2/2 | 2/2 | 17/19 |
| MH | 0/0 | 0/0 | 1/8 |

Budget (Pacific quota date 2026-11-22):

{
  "requests": 843,
  "tokens": 61161,
  "used_requests": 57,
  "reported_tokens": 90171,
  "unknown_usage_calls": 12,
  "unknown_token_reserve": 28668,
  "used_tokens": 118839,
  "reserve_policy": "reported historical mean +50%",
  "date": "2026-11-22",
  "timezone": "America/Los_Angeles",
  "limits": {
    "provider": "groq",
    "model_id": "openai/gpt-oss-20b",
    "label": "GPT OSS 20B",
    "rpm": 30,
    "rpd": 1000,
    "tpm": 8000,
    "tpd": 200000,
    "max_context_tokens": 4096
  }
}

Completed source rows: 34; non-F5 new rows: 12.
Rows labelled ok with repair errors are superseded too. Source files stay unchanged.

Resume run-set: {"F1": 21, "F2": 7, "F3": 9, "F4": 19, "F6": 7, "F6H": 11, "KI": 1, "MH": 8}
Preserved new answers: 10; carried S8 v1: 29
Fresh calls estimate/upper: 2/3
Tokens estimate/upper (50% margin): 4704/7056
No new answer quality is claimed; the new route has only fixture tests, not a live run.


## Implementation and limits

S7v2 and S8v2 tool routes use plain `generate_json`, never native function calling.
The strict plan schema has one branch per exact allowlisted tool and rejects
unknown names, extra args, invented bug IDs and contradictory explicit args. The
pre-parser reads question text only: IDs, link direction, dev population, filters,
hours/reopened and answer operation. It never reads gold or expected types.

A complete plan skips the model. Otherwise there is one JSON plan request and
one repair. Exhaustion uses a valid parser guess or deterministic BM25 text
retrieval, with at most one free-text answer request. No native-tool or legacy
answer-repair loop follows this path. Maximum for a partially parsed question is
three fresh calls; fully parsed count/lifecycle/links/fields need zero. S7v2 F5
uses get_comment plus one answer request; S8v2's six completed pinned answers are
preserved and not regenerated. Tool logs record plan_source, explicit facts,
arguments and results; rows record route, tool_route_version and llm_calls.

Numeric answers are scalars; link answers are ID lists. Structured MH answers are
JSON text because the immutable common answer wrapper does not admit object
values; the research scorer decodes that representation. Unknown metrics/target
state and private or unknown-visibility comments produce abstention, not invented
values. Count and lifecycle SQL/history implementations are inherited unchanged.

The first field of the source-score table counts final scored answers, not error
messages: the two F4 rows score correctly despite repair errors. Per request,
those rows are still superseded. Nine source qids have failed/repair-error records,
including the last uncommitted attempt. Their supersession entries are in
`outputs/analysis/b7e/superseded_rows.json`, then in the new run's manifest/sidecar.
The source ledger and attempts remain immutable. Ten error-free new answers are
preserved, including all six F5 answers. Their grading fingerprints are preserved
across the new run ID. No research S0–S8 source, prompt, tool schema or cache key
was changed.

## Corrected accounting

The old guard reserved 12 × 7,200 = 86,400 unknown tokens. The corrected reserve
uses reported history for the exact same call purpose, including provider-reported
usage on failed calls when available. Here all 12 errors lack usage:

| Purpose | Unknown calls | Reported-call mean +50% | Reserve |
| --- | ---: | ---: | ---: |
| structured-tools-v2 | 9 | 2,309 | 20,781 |
| tool-repair-v2 | 3 | 2,629 | 7,887 |
| Total | 12 | | **28,668** |

Reported usage is 90,171; accounted usage is 118,839; remaining safe budget is
61,161 for the Pacific quota day containing the run (2026-11-22). These include estimates for unknown usage, not a
claim that the provider billed exactly that total. Cache hits are not charged.
Missing purpose history falls back to measured system/route history, then model
history. A cold start uses an explicit output-based estimate, never a default
full-TPM reserve. The unchanged per-request estimated-input + max-output gate is
7,200, the daily ceiling is 180K, the invocation cap is 25, and retries/checkpoint
checks remain bounded. TPM pacing reconciles reported usage and uses measured
cost for failed/unknown calls too.

## Owner resume commands

Use the existing checkout and iqfm environment. Only the owner runs the enabled
command; all work performed by the agent was offline. No separate S7v2 or holdout
job, and no Groq F5 judge job, is scheduled.

```bash
conda activate iqfm
export PYTHONPATH="$PWD/src:$PWD${PYTHONPATH:+:$PYTHONPATH}"
B7E_SOURCE="outputs/predictions/v2/dev/run-cf2c6f2cf859a3c6/S8v2.jsonl"
python -m bugzilla_serving.experiments.b7e_report
scripts/run_phase07_v2.sh plan --system S8v2 --eval-set pilot122-v2 \
  --scope changed --resume-from "$B7E_SOURCE" --dry-run \
  | tee outputs/analysis/b7e/resume-plan.json
B7E_LEDGER="$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["ledger"])' \
  outputs/analysis/b7e/resume-plan.json)"
```

Expected: 83 rerun questions, 10 preserved new answers, 29 carried S8 v1 answers.
The new rule route includes explicit see_also/regressed_by lookups, so all 19 F4
questions now use the tool route. Of 83 reruns, 82 are fully parsed and require
no model calls. The one KI query requires JSON planning plus a text answer.

| Invocation | Question order | Fresh calls estimate / upper | Tokens estimate / upper |
| --- | --- | ---: | ---: |
| 1 | MH (8), F2/F3/F4 errors (9), other pending F2/F3/F4 (26), keep F5, remaining tool work, deferred F1/F6H (32) | 2 / 3 | **4,704 / 7,056** |

Those token estimates include 50%. The same system's tool-route reported history
now gives 2,352 tokens per call. Existing F5 costs are already in the provider
ledger; preserving them does not charge them again. Backfill labels new costs as
resume_incremental. Unchanged routes are carried, not credited as cache hits.

```bash
scripts/run_phase07_v2.sh run --system S8v2 --eval-set pilot122-v2 \
  --scope changed --resume-from "$B7E_SOURCE" --enable-llm --max-requests 25
python -c 'import json,sys; s=json.load(open(sys.argv[1])); assert s["completed"] == s["total"], s; print(s)' \
  "$(dirname -- "$B7E_LEDGER")/summary.json"
```

Expected: COMPLETE, 122 total = 83 newly executed + 10 preserved + 29 carried.
Zero model calls for a deterministic answer means actual local tool work was
performed, not that the question was skipped. A repeated completed invocation
makes no new calls. A budget/provider pause preserves checkpoints and must not be
bypassed. The new route's live quality is not yet validated.

## External F5 judging: export, judge, import, backfill

The packet already exists at `outputs/analysis/f5_packet/packet.md` and contains
all 60 candidates. Exporting again preserves random IDs for unchanged answers:

```bash
python scripts/export_f5_grading_packet.py --ledger "$B7E_SOURCE"
```

The default output directory contains packet.jsonl and packet.md (blind), a
separate packet_key.jsonl (mode 0600), and checksummed provenance. Send only the
blind packet to the external judge. System IDs appear only in the separate key.
The rubric requires the same substantive reason, permits faithful paraphrase,
and rejects contradictions, generic overlap and unsupported declining.

Save all 60 judge output JSON lines to a local file, then import once for every
system using the actual model name, not a fabricated value:

```bash
python scripts/import_f5_verdicts.py --verdicts "/path/to/external-verdicts.jsonl" \
  --judge "ACTUAL JUDGE MODEL NAME"
```

Import rejects missing/extra/duplicate candidates, invalid verdicts, bad reasons,
changed packet/key hashes and mixed judge provenance. It writes one complete
`outputs/analysis/f5_packet/verdicts.jsonl` with source fingerprints, model name,
timestamp and packet SHA256. Only after validation does it update the F5 catalog
text to name that judge. No judge was invented or run in this offline task.

Backfill reads the same 60-row file for all systems; it validates the whole packet
before selecting the 54 original or six S8v2 bindings. The dashboard compares one
judge and one grading batch at a time. Reload the dashboard after the catalog
update. Finish the resume before backfilling S8v2:

```bash
B7E_VERDICTS="outputs/analysis/f5_packet/verdicts.jsonl"
for version in 1 2; do
  python scripts/backfill_answer_eval.py --mode ledgers --f5-gold llm \
    --f5-verdicts "$B7E_VERDICTS" --scorer-version "$version" --apply --resume
done
scripts/run_phase07_v2.sh backfill --system S8v2 --eval-set pilot122-v2 \
  --ledger "$B7E_LEDGER" --f5-verdicts "$B7E_VERDICTS" --dry-run
scripts/run_phase07_v2.sh backfill --system S8v2 --eval-set pilot122-v2 \
  --ledger "$B7E_LEDGER" --f5-verdicts "$B7E_VERDICTS" --apply
LANGSMITH_SOURCE=fixture python scripts/build_dashboard_snapshot.py --max-requests 1000
```

MLflow/snapshot commands are owner-only network operations with zero model calls.
Expected tags include iteration=v2, diagnosed_on=pilot125,
evaluation=composite_changed_routes, tool_route_version=json-tools-v2,
f5_judge and f5_packet_sha256. Old prediction ledgers are never edited.

## Validation / open questions

419 offline tests passed across bounded module invocations; Ruff check and format
checks passed. The original byte-identity test passes. Tiny fixtures cover every
JSON-plan fallback, deterministic answer shapes, direction/cohort behavior,
private-comment refusal, reported/error usage accounting, immutable resume and
F5 fingerprint preservation, all-60 external import and judge/batch separation.
Only existing dependency warnings appeared; none came from our code.
No live calls, external messages, MLflow writes or pushes were performed.

Open: the owner must execute and review the new route, and supply the stronger
external judge's complete verdicts/model name. No new accuracy or F5 improvement
is claimed before those steps.

Files changed for B7e:

- New `src/bugzilla_qa/answering_v2/json_tools.py`; updated variant `graph.py` and `tools.py`.
- New `experiments/v2_resume.py`, `f5_packet.py`, `b7e_report.py`; updated `v2_jobs.py`, `preflight.py`, `token_budget.py`, `runner.py` under `src/bugzilla_serving/`.
- Updated `tracking/f5_gold.py`, `tracking/backfill.py` and `dashboard/views.py` under `src/bugzilla_serving/`.
- New `scripts/export_f5_grading_packet.py` and `scripts/import_f5_verdicts.py`; included both in the existing Ruff scope in `pyproject.toml` (no dependency/version changes).
- New `tests/b_experiments/test_b7e.py`; updated variant regression tests and dashboard judge-selector tests.
- Updated `docs/AGENT_NOTES.md`, `BACKFILL_MAPPING.md`, `STREAM_B_HANDOFF.md` and the superseded `B7_ONE_DAY_PLAN.md`; added this runbook.

Existing staged work and the unrelated PDFs are preserved. Generated analysis and
packet files are intentionally ignored, including the separate grading key.
