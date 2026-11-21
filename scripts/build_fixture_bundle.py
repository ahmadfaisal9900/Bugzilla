#!/usr/bin/env python3
"""Regenerate tiny synthetic Phase 0 inputs. No downloads, real data or APIs."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(v, sort_keys=True) + "\n" for v in values), encoding="utf-8")


def files_under(root):
    return {p.relative_to(root).as_posix(): {
        "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
    } for p in sorted(root.rglob("*")) if p.is_file() and p != root / "manifest.json"}


def config(system="S2"):
    return dict(system_id=system, retriever={"S0": "R1", "S1": "R1", "S4": "R5",
                "S6": "R6", "ORACLE": "R1"}.get(system, "R7b"), corpus="C1",
                provider="mock", model="openai/gpt-oss-20b", top_k=5, temperature=0.0,
                context_budget_tokens=3000, prompt_version="answer-v1", s4_tau=None,
                s5_dossier_budget=None, s7_max_tool_steps=None, rrf_k=None, query_transform=None)


def cfg_hash(cfg):
    payload = json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def build(output):
    """Output is generated only from literals below, never from research datasets."""
    from bugzilla_qa.eval_extension.retrieval import build_lexical

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    bugs, docs, edges = [], [], []
    for i in range(20):
        bug = str(100000 + i)
        status = "NEW" if i % 2 else "RESOLVED"
        bugs.append(dict(bug_id=bug, product="Firefox", component="Synthetic Tabs",
                         snapshot_status=status, snapshot_resolution="" if i % 2 else "FIXED"))
        for kind, text in [
            ("metadata", f"Synthetic bug {bug}. Product Firefox. Component Synthetic Tabs. "
             f"Status {status}. Resolution {'UNKNOWN' if i % 2 else 'FIXED'}."),
            ("comment", f"Synthetic bug {bug}: the artificial switch stays off because "
             "the imaginary widget must remain keyboard accessible."),
            ("link", f"Synthetic bug {bug} depends on {100000 + (i + 1) % 20}."),
        ]:
            docs.append(dict(chunk_id=f"{kind}-{bug}:0", record_id=f"{kind}-{bug}",
                             bug_id=bug, kind=kind, chunk_type=kind, text=text,
                             visibility="public", source_hash=f"synthetic-{bug}-{kind}",
                             url=f"https://example.invalid/bugs/{bug}"))
        edges.append({"source": bug, "target": str(100000 + (i + 1) % 20)})
    docs.append(dict(chunk_id="history-100000:0", record_id="history-100000", bug_id="100000",
                     kind="history", chunk_type="history", visibility="public",
                     source_hash="synthetic-history", url="https://example.invalid/bugs/100000",
                     text="Synthetic history: resolution changed from empty to FIXED at "
                          "2020-01-03T00:00:00Z."))
    jsonl(output / "bugs.jsonl", bugs)
    jsonl(output / "comments.jsonl", [d for d in docs if d["kind"] == "comment"])
    write(output / "graph.json", edges)
    source_config = json.loads((ROOT / "configs/retrieval_v3.yaml").read_text())
    rc = {k: source_config[k] for k in (
        "rrf_k", "candidate_k", "graph_top_bugs", "graph_max_slots", "graph_insert_after",
        "hierarchical_max_bugs", "device", "embedding_model", "embedding_revision",
        "reranker_model", "reranker_revision", "batch_size",
    )}
    for corpus in ("C0", "C1", "C2"):
        folder = output / "indexes" / corpus
        folder.mkdir(parents=True, exist_ok=True)
        rows = [dict(d) for d in docs]
        if corpus == "C2":
            for d in rows:
                d["text"] = f"Bug {d['bug_id']} | Synthetic Tabs | Fictional fixture | " + d["text"]
        jsonl(folder / "corpus.jsonl", rows)
        # Same no-download FTS5 builder as the existing retrieval fixture tests.
        build_lexical(folder / "lexical.sqlite", rows, "phase0-synthetic-v1")
        write(folder / "dense_fixture.json", {
            "kind": "synthetic-term-overlap-test-double", "record_ids": [d["chunk_id"] for d in rows],
        })
        write(folder / "manifest.json", {
            "state": "COMPLETE", "synthetic": True, "chunks": len(rows), "truncated_chunks": 0,
            "sha256": {n: hashlib.sha256((folder / n).read_bytes()).hexdigest()
                       for n in ("corpus.jsonl", "lexical.sqlite", "dense_fixture.json")},
        })
    write(output / "indexes/graph.json", edges)
    write(output / "indexes/manifest.json", {
        "state": "COMPLETE", "synthetic": True,
        "sha256": {f"{c}/manifest.json": hashlib.sha256(
            (output / "indexes" / c / "manifest.json").read_bytes()
        ).hexdigest() for c in ("C0", "C1", "C2")},
    })
    write(output / "selection.json", {
        "state": "SELECTED_DEV_ONLY", "synthetic": True, "test_used": False, "sources": [],
        "selected": {"retriever": "R7b", "corpus": "C1"}, "index_build": "indexes",
    })
    write(output / "retrieval.json", rc)
    write(output / "source.json", {"canonical_db": "canonical.duckdb"})
    write(output / "history.json", {"candidate_results": {"100000": {
        "source_consistency_differences": [], "history": {
            "state": "PARSED", "chronology_ok": True, "same_time_groups": [],
            "first_fixed_at_utc": "2020-01-03T00:00:00Z", "reopened_count": 0,
            "changes": [{"field_name": "resolution", "old_value": "", "new_value": "FIXED",
                         "when": "2020-01-03T00:00:00Z"}],
        },
    }}})
    runtime = dict(source_config="source.json", history_checkpoint="history.json",
                   retrieval_config="retrieval.json", selection="selection.json", retrieval_runs=[],
                   duckdb_memory="64MB", seed=317, context_tokens=3000, dossier_tokens=4096,
                   tool_steps=4, retrieval_k=5, prompt_version="answer-v1", query_transform="R7b")
    write(output / "runtime.json", runtime)
    ddl = [
        "CREATE TABLE bugs(bug_id VARCHAR, product VARCHAR, component VARCHAR, "
        "snapshot_status VARCHAR, snapshot_resolution VARCHAR, opened_at_utc TIMESTAMPTZ, "
        "snapshot_as_of_utc TIMESTAMPTZ, source_record_id VARCHAR);",
        "CREATE TABLE sample_membership(bug_id VARCHAR, seed INTEGER);",
        "CREATE TABLE source_records(source_record_id VARCHAR, disposition VARCHAR, "
        "normalized_fields JSON, bug_id VARCHAR, source_dataset VARCHAR);",
        "CREATE TABLE bug_links(bug_id VARCHAR, target_bug_id VARCHAR, "
        "link_key VARCHAR, relation VARCHAR);",
    ]
    for b in bugs:
        bug = b["bug_id"]
        ddl.append(f"INSERT INTO bugs VALUES ('{bug}', 'Firefox', 'Synthetic Tabs', "
                   f"'{b['snapshot_status']}', '{b['snapshot_resolution']}', "
                   f"'2020-01-01T00:00:00Z', NULL, 'metadata-{bug}');")
        ddl.append(f"INSERT INTO sample_membership VALUES ('{bug}', 317);")
    for e in edges:
        ddl.append(f"INSERT INTO bug_links VALUES ('{e['source']}', '{e['target']}', "
                   f"'link-{e['source']}', 'depends_on');")
    (output / "canonical.sql").write_text("\n".join(ddl) + "\n")
    examples = [
        ("F1", "What product is recorded for bug 100000?"),
        ("F2", "How long until the first FIXED transition for bug 100000?"),
        ("F3", "How many synthetic cohort bugs exist?"),
        ("F4", "Which bugs depend on bug 100000?"),
        ("F5", "What reason is given for bug 100000?"),
        ("F6", "How many engineer hours were spent on bug 100000?"),
        ("KI", "Which synthetic report describes an imaginary keyboard widget?"),
        ("MH", "Which component contains the dependency target of bug 100000?"),
        ("F6H", "What is the missing verified lifecycle for bug 100019?"),
        ("F1", "What status is recorded for bug 100001?"),
    ]
    jsonl(output / "dev_questions.jsonl", [
        dict(qid=f"synthetic-{i:02d}", question=q, family=f, split="dev", scope={},
             evidence_record_ids=["metadata-100000", "comment-100000"])
        for i, (f, q) in enumerate(examples)
    ])
    write(output / "manifest.json", {
        "schema_version": "phase0-v1", "synthetic": True, "split": "dev", "bugs": 20,
        "dev_questions": "dev_questions.jsonl", "runtime_config": "runtime.json",
        "files": files_under(output),
    })
    return output


def samples(fixtures):
    cfg = config()
    record = dict(answer=dict(abstain=False, answer="Firefox", answer_type="string",
                             bug_ids=[100000], citations=["metadata-100000:0"],
                             rationale="The synthetic metadata states the product."),
                  route="S2", route_rule="system_selected", evidence=[dict(
                      chunk_id="metadata-100000:0", bug_id="100000", score=1.0,
                      snippet="Synthetic product Firefox.", url="https://example.invalid/bugs/100000",
                  )], tokens={"input": 10, "output": 5}, llm_calls=1, cache_hits=0,
                  latency_ms=12.0, degraded=False, errors=[], config_hash=cfg_hash(cfg))
    write(fixtures / "sample_answer_record.json", record)
    events = [{"event": "status", "data": {"stage": s, "detail": d}}
              for s, d in [("retrieving", "Searching"), ("retrieved", "Found 1 sources"),
                           ("generating", "Writing"), ("done", "Finished")]]
    events += [{"event": "evidence", "data": {"items": record["evidence"]}},
               {"event": "answer", "data": record},
               {"event": "error", "data": {"code": "rate_limited", "message": "Synthetic stop",
                                            "retry_after": 1}},
               {"event": "done", "data": {"request_id": "synthetic-request",
                                           "langsmith_run_id": None}}]
    write(fixtures / "sample_sse_events.json", events)
    runs = [dict(id=f"synthetic-run-{i:02d}", project="ensf621-serving",
                 metadata=dict(config_hash=cfg_hash(cfg), preset_slug=("recommended", "fast", "deep")[i % 3],
                               system_id="S2", model=cfg["model"], retriever="R7b", corpus="C1",
                               route="S2", degraded=i % 5 == 0, request_id=f"r-{i}", session_id=f"s-{i}"),
                 latency_ms=float(100 + i), abstain=i % 7 == 0,
                 start_time=f"2020-01-01T00:{i:02d}:00Z",
                 feedback=[dict(key="user_rating", score=i % 2, comment="Synthetic feedback")])
            for i in range(30)]
    write(fixtures / "sample_langsmith_runs.json", runs)
    header = ["review_id", "dataset", "question_type", "review_needed", "current_result",
              "review_reason", "question", "model_answer", "model_explanation", "reference_answer",
              "reference_evidence", "model_evidence", "answer_verdict", "grounding_verdict",
              "reviewer", "note"]
    folder = fixtures / "sample_partner_eval"
    folder.mkdir(exist_ok=True)
    with (folder / "REVIEW.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerow(dict.fromkeys(header, "synthetic"))
    (folder / "START_HERE.html").write_text(
        "<!doctype html><title>Synthetic PILOT review subset</title>"
        "<h1>Synthetic PILOT subset, n=1</h1><p>Fixture review only; no measured scores.</p>\n"
    )
    # Same top-level/cell schema as the inspected dev retrieval summary; all values fake.
    measures = ("hit_at_1", "hit_at_5", "hit_at_10", "recall_at_5", "recall_at_10",
                "mrr_at_10", "ndcg_at_10", "bug_hit_at_5")
    cell = dict(dataset="v3", family="F1", retriever="R1", corpus="C1", dataset_n=10,
                n=10, n_qrels=10, state="KNOWN_CITATION_PROXY",
                latency_p50_ms=10.0, latency_p95_ms=20.0)
    cell.update({m: {"n": 10, "value": 0.5} for m in measures})
    cell.update({m: {"n": 0, "value": None} for m in
                 ("mh_full_evidence_at_10", "r4_r3_jaccard_top10")})
    write(fixtures / "sample_retrieval_summary.json", {
        "state": "COMPLETE", "split": "dev", "actual_api_calls": 0,
        "assumptions": "Synthetic incomplete known-citation labels", "blocker": None,
        "bootstrap": [], "cells": [cell], "compatibility": "synthetic",
        "completed_rows": 10, "corpora": ["C1"], "coverage": {"v3": {"F1": 10}},
        "datasets": ["v3"], "expected_rows": 10, "index_build": "synthetic-index",
        "input_sha256": {}, "limit_per_dataset": None, "limited": False,
        "locked_test_used": False, "max_http_attempts_this_invocation": 0,
        "methods": ["R1"], "output": "synthetic", "planned_transform_calls_upper_bound": 0,
        "questions": 10, "selection_observations": [], "selection_protocol_sha256": "synthetic",
        "selection_roster": {"v3:F1": [f"synthetic-{i:02d}" for i in range(10)]},
        "tracing": False,
    })
    write(fixtures / "config_hashes.json", {s: cfg_hash(config(s)) for s in ("S0", "S1", "S2")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tests/fixtures/serving_bundle")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        print(json.dumps({"state": "DRY_RUN", "bugs": 20, "questions": 10, "api_calls": 0}))
        return
    build(args.output)
    samples(args.output.parent)
    print(json.dumps({"state": "COMPLETE", "synthetic": True, "bugs": 20, "questions": 10}))


if __name__ == "__main__":
    main()
