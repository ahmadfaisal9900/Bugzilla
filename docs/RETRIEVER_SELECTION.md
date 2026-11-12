# Retriever selection preregistration

Registered 2026-11-12 before any Task 2 retrieval results. Only development
results determine S2. Locked test results never enter selection.

S2 is the (retriever, corpus) pair with the highest unweighted macro-average
known-citation Recall@10 over eligible **(dataset, family)** cells of v3 dev and
natural-rewrite dev. A cell is eligible only with at least 10 development
questions having nonempty passage qrels. Smaller cells are descriptive only.
Every candidate must complete the same eligible cells and question roster.
Phase 5 dev is reported but excluded from selection.

Pairs within 0.01 of the highest score tie; choose the lowest pooled question
p95 retrieval latency over eligible cells, then registry name and corpus name
for a deterministic final tie. R7a/R7b are eligible only if their macro score
exceeds R5 on the same corpus by **more than 0.02**. Their latency includes
the original measured query-transform latency even when a cached transform
is reused. Report transform-cache hits and measured reuse latency separately.

Qrels are incomplete known citations. Recall is over distinct source record IDs,
not the number of overlapping chunks. nDCG uses binary relevance; an unlabeled
chunk and a repeated occurrence of an already retrieved record score zero.
Do not remove unindexed known citations from recall denominators. Report them.
F3/F6/F6H are N/A for passage retrieval. Absent families are "not in dataset".
All cells report question n and applicable-qrel n. v3 has no F2/F5 and no test F3;
v3 MH dev has n=8 and is excluded from selection by the n>=10 rule.

Paired inference compares each method to R1 on the same corpus/question roster,
clustered by parent bug identity (shared paraphrases remain together). Use
10,000 cluster bootstrap resamples, seed 317, question-weighted differences,
percentile 95% intervals and centered two-sided bootstrap p values. Apply Holm
adjustment across all reported cell/method/metric comparisons within a run.
Intervals are descriptive with small cluster counts; fewer than two clusters
has no inferential interval. This is a retrieval selection study, not evidence
of final answer quality or exhaustive relevance.

An explicit `--confirm-locked-test` is required for test. Each test invocation
records access and refuses an existing run directory, including with --resume.
Changing any method after inspecting test creates an exploratory result.

`python -m bugzilla_qa.retrieval_v3.cli select --summaries ...` applies this rule
and writes `configs/selected_retriever.yaml` with input summary hashes. Existing
selection files require an explicit new output path; never silently replace one.
