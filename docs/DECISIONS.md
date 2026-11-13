# Decisions

| ID | Decision | Rationale / status |
|---|---|---|
| D-001 | Use a `src/bugzilla_qa/` Python package with separate data, benchmark, retrieval, methods, evaluation, and app subpackages. | Matches the planned research components while keeping Phase 0 free of system implementation. |
| D-002 | Ignore the complete root-level `Dataset/` directory, including the nested `EASE_2025_Data_paper` clone. | Protects downloaded data and upstream source from accidental staging or commits. |
| D-003 | Keep generated results and logs in `outputs/` and `logs/`, and ignore their contents. | Keeps reproducible source/configuration in Git while excluding local artifacts. |
| D-004 | Add no runtime dependencies in Phase 0. | Dependencies will be selected only when needed for a bounded, reproducible phase. |
| D-005 | Treat `docs/reference/research_roadmap.tex` as the authoritative scientific plan. | It defines scope, methods, benchmark, and temporal protocol; no results are implied by it. |
| D-006 | The only project Git root is `/home/ict317/master's/ENSF 621/Project/`; keep the root-level `Dataset/` external to Git. | The existing repository and `origin` predate the study; never create a nested project repository. |
| D-007 | Use a zero API spend budget and free/local methods. | Course constraint; model and hardware feasibility remain unresolved. |
| D-008 | Treat 180 as a generated candidate-question target across F1–F6. | The roadmap's target is not a quota for manually authored questions. |
| D-009 | Preserve metadata-only source notes in `docs/DATA_INVENTORY.md`; do not hash, import, or alter large source files during setup. | The comments files are multi-gigabyte and may include duplicate/private/contributor data. |
| D-010 | Resolve local dataset paths from ignored `configs/data_paths.local.yaml`; keep a tracked example with repository-relative paths. | Machine-specific paths must not enter Git, while audit runs need an explicit source manifest. |
| D-011 | Use Python's standard-library CSV parser and an ignored SQLite index for streaming audit counts and duplicate/join checks. | Avoid bulk CSV loads and new package dependencies; resumability is at completed-file boundaries. |
| D-012 | Verify comment Parts 1/2 with full SHA-256 on an unlimited user-run audit and report overlapping record IDs. | Equal sizes/headers alone do not prove duplicate content; limited scans never claim checksum verification. |
| D-013 | Treat license/redistribution and private/contributor-field authorization as unresolved until human review. | The audit reports evidence and field presence, not legal permission or a privacy approval. |
| D-014 | Strip embedded NUL characters only in the audit's streamed parser input and record their counts; never rewrite the source CSVs. | Python's CSV reader rejects NUL characters; transparent, non-persistent sanitation allows schema/count auditing while preserving source bytes. |
| D-015 | Count comment Part 1/2 once because the full Phase 2 audit verified matching SHA-256 values and 408,401 shared record IDs. | Exact byte equality is stronger than a matching filename/header; Phase 3A reuses this result only while file size and modification-time signatures match. |
| D-016 | Do not merge `Bug_meta_data_230k_all.csv`, Part 3, or quality-selected exports until full hashes, ID overlap, and comment-key overlap are profiled. | A similar schema, filename, or bounded prefix overlap cannot establish whether an export is a subset, superset, or repeat. |
| D-017 | Interpret status and resolution separately; never use `last_change_time` as a substitute for ordered history. | A sampled row is RESOLVED/INCOMPLETE, and Phase 2 headers do not expose event-time transitions. F2/as-of questions require validated history evidence. |
| D-018 | Keep the Phase 3A full profile user-run; the agent session may run only fixture tests and a tiny bounded sample. | The largest source is 1.6 GB and the operating contract prohibits long corpus jobs in-session. |
| D-019 | Phase 3B candidates are metadata + one verified comment copy + filtered reports, subject to Phase 3A results and rights/privacy review. | Together they provide snapshot facts, dated comment evidence, and report fields with high Phase 2 ID join coverage; the shortlist is not a final corpus or snapshot choice. |

| D-020 | Accept the user-run full 3A QC and select metadata + comment Parts 1/3 for Phase 3B base. | Supersedes the conditional shortlist in D-016/D-019: Parts 1/3 add complementary records, all parents join; Part 2 duplicates Part 1. Metadata-all is a near-repeat with anomalies. See PHASE03A_QC. |
| D-021 | Keep filtered reports/steps optional in a separate QUALITY tier; sample broad metadata without requiring comments. | All selected comment rows are FIXED-selected; open/non-FIXED outcomes exist in metadata and must survive sampling. |
| D-022 | Dedup comments by parent, nullable comment ID, UTC event time, exact parser-visible text hash and privacy flag. | Retain distinct comments and content versions; first metadata row wins deterministically with duplicate/conflict variants retained in provenance. |
| D-023 | Store nullable event/snapshot times and explicit UNKNOWN history; compute first FIXED only from actual qualifying transitions. | No source transition history exists; elapsed days are not engineer-hours. Reopening does not reset first FIXED. |
| D-024 | Use verified QC time as conservative observed-at, new-run time as ingested-at, and leave source snapshot date unknown. | Neither file mtime nor creation time establishes when snapshot status was true. Dual event/observation cutoffs prevent backdating evidence. |
| D-025 | Add pinned free DuckDB 1.4.4 for transactional streaming import and native Parquet export. | No PyArrow, paid API, crawler or MongoDB required; versioned outputs and complete manifests remain ignored. |
| D-026 | Reserve each observed status/resolution outcome before seeded component/year/outcome stratification. | 3,000 Firefox-product bugs is a planning target, not guaranteed coverage; retain smaller populations and zero-comment negative cases. No T0/T1 chosen. |
| D-027 | Withhold private/unknown-privacy bodies; retain local minimal row lineage and quarantines. | Preserve joins/accounting without treating absent authorization as public visibility. Dataset redistribution rights remain unresolved. |
| D-028 | Mark Phase 3B VERIFIED after reviewing user run `run-20261022T023542Z-1182018`; advance to Phase 4. | Manifest COMPLETE with unlimited scans, source hashes/counts matching 3A, exact row accounting, zero quarantines/orphans, 196,633 canonical bugs, 419,458 comments, and seeded sample QC. See `docs/PHASE03B_NORMALIZATION.md`. |
| D-029 | Keep Phase 3B event, observation and ingestion clocks separate; leave source snapshot date NULL. | CSV event times parse, 3A QC observed at 01:56:55Z, Phase 3B ingestion starts 02:35:42Z, but export as-of date is unverified; no historical reconstruction from present status. |
| D-030 | Carry the 3,000 seed-317 Firefox sample forward as the Phase 3B sample, retaining every observed outcome stratum plus zero-comment and open/reopened examples. | DuckDB confirms 18/18 eligible Firefox status/resolution combinations, 757 open/reopened and 2,539 no-comment members. It is not a population-proportional sample or all Firefox engineering. |
| D-031 | Use frozen Phase 3B corpus versus a selectively API-enriched sidecar as the primary temporal experiment; do not claim source-time drift or a 2024 snapshot. | Phase 3A/3B observation and ingestion clocks are in 2026, while source `snapshot_as_of_utc` is NULL. No independently dated v0/v1 source exports are verified. See `docs/TEMPORAL_VALIDITY.md`. |
| D-032 | Fetch only public unauthenticated Bugzilla GET endpoints; history first, current metadata separately, and comments only when CSV comments are absent or contain missing/empty bodies. | History supplies explicit event fields; current values are a refresh, not historical transitions. Exact API/CSV comment matches are skipped, changed text is retained as a source conflict, and private/unknown-privacy comments are withheld. Requests are paced, capped and resumable. |
| D-033 | Plan a stratified 50-bug pilot before considering a 100–300 bug selective cohort. | The 3,000 seed-317 sample supports every observed outcome; preserve FIXED, reopened/open, duplicate/incomplete, linked, comment-present and zero-comment cases. API request estimates are reported before any user-run requests. |
| D-034 | Treat F2 as UNKNOWN unless a fully parsed explicit resolution-to-FIXED history transition passes creation/observation chronology checks. | Current resolution and `last_change_time` cannot supply a transition timestamp; no initial status is inferred. Reopens and duplicate/invalid resolutions remain distinct. |
| D-035 | Provide strict observed/ingested cutoff checks and a separately labeled RETROSPECTIVE REPLAY mode. | Event date at/before a cutoff alone is not proof the evidence was available then. Strict mode requires event, observed and ingested times to precede cutoff; current API fields never travel backward. |
| D-036 | Treat the paper's October 2024 date as reported collection coverage, not a verified per-field CSV snapshot; treat its 119,585 curated and 10,351 quality-selected reports as distinct from the 196,633-bug broad metadata base. Keep the current source selection and use selective `/history` for ordered lifecycle events. | Local headers contain scalar latest-change/activity values, upstream extraction commit `e0f44e656ab8fee2f93a0adbce881dca5bdc8c9e` contains no history extraction, and Phase 3B has 0 field changes with NULL snapshot date. Equal local subset counts do not establish identical membership. See `docs/PAPER_DATASET_RECONCILIATION.md`. |

Phase 3B full output is validated. Base F2 history remains absent; selective Phase 4 pilot evidence is now verified below. F4 historical relationship coverage remains unresolved. Phase 4 selected a controlled evidence-addition experiment, but no historical source-time T0/T1 or final benchmark question set is established.


| ID | Phase 5 decision | Evidence / consequence |
|---|---|---|
| D-037 | Accept the completed 50-bug Phase 4 pilot as benchmark input, retaining reduced coverage. | Six overlay hashes, 147 response hashes/identities, parsed histories, metrics and 884 DuckDB event hashes match. 13 first-FIXED cases exist; 9 precede further exclusions after source/same-time checks. The 200-bug study was not run. |
| D-038 | Partition all parent/target IDs deterministically; aggregate scopes use the same explicit eligible partition. Hold out wording forms and review a separate test challenge set. | No dev/test shared parent/target IDs; complete F4 sets crossing partitions are skipped. Inference exports contain only opaque qid, question and factual scope; no SQL/template/gold leakage to M3 or retrieval. |
| D-039 | Keep every F5 answer a candidate until source-checked human approval; freeze only after all mandatory reviews and global signed acknowledgement of actual coverage. | Keyword matching is not causal verification. Review every F5/challenge, 20% F1–F4 and up to six F6; allow rejection/reduced F5 targets. Immutable version/checksum safeguards prevent silently replacing the test. |
| D-040 | Preserve population labels and report missing canonical fields explicitly. | The corpus uses broad metadata, not the 119,585 curated population or 10,351 CTQRS group. CSV explanations are FIXED-selected. Priority/issue type are not retained canonically: skip priority lookup, label enhancement coverage UNKNOWN, and make no defect-only or unresolved-explanation claim. |
| D-041 | Share only an explicit five-file Phase 5 review bundle in Git for partner annotation. | The user requested a fresh-clone review workflow: track the standard-library server, HTML, mutable signoff CSV, immutable pre-review backup, and a small provenance manifest. Preserve recorded decisions and source hashes; keep datasets, raw API responses, full comment packets and other outputs ignored. Six recorded UI approvals at packaging are not a verified freeze or official-queue transfer. Missing frozen evidence stays pending; live current status cannot substitute for a saved snapshot. |
| D-042 | Transfer the sampled data as a private ignored archive; keep base and API databases separate. | The partner needs the exact 3,000 frozen Firefox bugs and the existing 50-bug history pilot. Filter canonical rows by parent membership, preserve link targets as references and original source hashes, copy the small verified overlay unchanged, and provide native DuckDB files plus setup instructions. Do not recollect data, publish it in Git, merge current API fields into archive metadata, or represent this smaller database as the original full pinned source. Full export is a user-terminal task with table checkpoints and output checksums. |
| D-043 | Retain human-confirmed F5 questions whose cited comments do not state the requested reason, with evidence-scoped `unanswerable` gold. | The original F5 question wording already permits insufficient evidence. The prior validator incorrectly forced a supported rationale and discarded useful abstention cases. Require complete source review, a real reviewer and `source_checked=YES`, record `rationale_present=NO`, preserve the original candidate/ID/split, and report these cases separately. F5 model abstentions require human response review. Do not infer absence from an unavailable or truncated comment. |

| D-044 | Keep the expanded factual bank and retrieval corpus separate from original Phase 5; gate expanded test access on the genuine original freeze and a separately hashed bank/corpus/model/config seal. | New factual questions are automatically source-checked drafts. Natural variants and optional F5 packets require human review; original UI signoffs were subsequently transferred as documented below. F3 and scoped F6 are not passage-retrieval misses. See EVAL_EXTENSION_STATUS and EVAL_EXTENSION_METRICS. |
| D-045 | Preserve v1, build v2 with nonconstant F1, explicit family/split quotas and a new deterministic bug split; exclude inspected v1 test parents from new single-bug test. | V1 was F1-dominated, had no F2 dev and only two F4 dev questions. Quota shortfalls remain visible and aggregate populations overlap. The original benchmark remains a separate human-review track. |

2026-11-11 update to D-044: 64 existing human decisions were copied to the original Phase 5 queue with a backup and audit; the independent global signature and full validator freeze remain outstanding. M3 parser repair results use a separately identified development output and do not replace previous predictions.

Task 1 update: the owner subsequently completed original freeze d8ef826fbeb90d13. D-046: v3 stays separate, with root splits, explicit original/natural exclusions, source-supported KI/MH/F6H and independently rechecked v2 imports. The KI target is 220 forms from up to 110 description calls. Human spot checks assess wording; deterministic gold checks do not establish semantic equivalence. Copied v2 aggregates retain their original population and are labeled shared-population tasks. No as-of date, event, absent canonical field or human verdict is invented.

D-047 (2026-11-12): use Groq by explicit user request after Gemini access/capacity failures. Default openai/gpt-oss-20b with strict JSON Schema (Groq structured-output docs), GROQ_API_KEY read from ignored .env, and 3 configured RPM / 1,000 RPD as conservative local limits. New provider/model/config creates a new versioned v3 run; failed Gemini drafts, original freeze and human review gates are preserved. Groq token/account limits still apply. No live request is made by the coding agent.

D-048 (2026-11-12): Task 2 uses current v2 C0 (14,443 chunks) and immutable v3
freeze e2207774a0f2cbad. Preserve accepted missing F2/F5/test-F3 coverage. Reuse
existing implementations/provider (Groq generator role); tokenizer-safe C1/C2
preserve source record IDs. R4 alone restricts explicit bug references; R1/R2
use global retrieval for a distinct hierarchy comparison. R6 reserves at most
three top-10 slots for explicit graph-neighbour metadata. Select S2 using only
n>=10 v3/natural dev passage-qrel cells, per preregistered RETRIEVER_SELECTION.
Frozen data, empty base history and private/unknown comment bodies are excluded
from writes/ingestion as already required. Real scores await terminal runs.

D-049 (2026-11-13): Task 3 uses the observed selected R7b/C1 and the existing Groq
generator provider for all answering arms. A shared LangGraph and answer prompt
produce predictions only; no answer evaluation is added. Native tool transport
reuses provider quotas/cache/ledger. S7 uses allowlisted parameterized read-only
queries and separate verified Phase 4 evidence, never base field_changes. Original
M3 stays unchanged/deprecated. S2/S3 retrieval equivalence is disclosed. S4 uses
R5 cross-score scale and one deterministic local multi-query retry so low-evidence
abstention needs no model call. Tau is a recorded dev-only quantile suggestion.
Context budgets use conservative UTF-8 byte bounds; full dossiers have the
predeclared larger budget. Gold is isolated from inference except diagnostic
ORACLE; optional LangSmith reference upload is dev-only and never runs evaluators.
Pilot sets stay fixed on resume; daily limits advance. No live answering result
or production readiness is claimed. See ANSWERING_SYSTEMS.md.

D-050 (2026-11-13): Citation labels already explicitly mapped in packed context
may be resolved deterministically from Cn or [Cn] to the exact chunk ID before
contract validation. Preserve raw model output and a citation_normalization
record. Keep the supplied-evidence whitelist; never infer a source from bug ID,
claim wording or unknown labels. This is formatting normalization, not factual
answer correction or scoring. Preserve previous partial runs; retry fixed pilots
in the new code-identified version before daily batches.
