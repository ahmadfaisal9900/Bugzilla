# Retrieval extension status

**PARTIALLY IMPLEMENTED; NOT READY FOR THE REQUESTED END-TO-END RUN.**

- Implemented: bounded source corpus exporter, SQLite FTS5 index, explicit bug-ID filtering, deterministic RRF primitive, known-citation metric primitive, safe-stage CLI and synthetic unit tests.
- A one-bug export was smoke-tested locally. This is not a corpus or benchmark validation.
- Outstanding: expanded and natural question banks, human review workflow for those banks, complete source/chunk provenance and corpus audit, dense/FAISS, hybrid system, reranker, hierarchical retrieval, qrels, all-method evaluation, generator adapters and full resumable orchestration.
- Original Phase 5 freeze was not present at inspection; signed UI records are separate from the original pending queue. Never copy them without preserving and auditing genuine signoffs.
- Approximate time and resource requirements for the missing components have not been measured. Do not assume local models or a GPU are available.
