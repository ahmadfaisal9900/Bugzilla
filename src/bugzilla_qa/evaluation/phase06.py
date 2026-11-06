"""Phase 6: run development questions and score them afterwards.

M3/BM25 are model-free; M0/M1 and m3-llm call an explicitly configured local Ollama model.
The split is development only. Full jobs belong in the user's terminal.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from bugzilla_qa.benchmark import phase05 as p5
from bugzilla_qa.data.normalize import file_hash, write_json
from bugzilla_qa.evaluation import scoring, shared_dev
from bugzilla_qa.methods import generation, m3_intent, m3_sql
from bugzilla_qa.methods.local_model import OllamaClient
from bugzilla_qa.retrieval import bm25

SPLIT = "dev"
FROZEN = "FROZEN_DEV"
SMOKE = "UNFROZEN_DEV_SMOKE; not reportable"


def stamp():
    return datetime.now(timezone.utc).isoformat()


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def source_paths(root, sources):
    pins = p5.read(sources)
    base, overlay = root / pins["base_run"], root / pins["phase04_run"]
    return pins, base, overlay


def check_pins(pins, base, overlay):
    """Cheap identity checks. The 1.89-GB hash belongs to the freeze."""
    assert p5.read(base / "manifest.json")["identity_hash"] == pins["base_identity"], "Canonical run differs from its pin"
    assert file_hash(overlay / "summary.json") == pins["phase04_summary_sha256"], "Phase 4 overlay differs from its pin"


def load_benchmark(run, unfrozen):
    """Returns (state, inference questions, a loader for gold). Gold stays unread until scoring."""
    if unfrozen:
        items = [q for q in p5.read(run / "candidates.json") if q["split"] == SPLIT]
        return SMOKE, [{k: q[k] for k in ("qid", "question", "scope")} for q in items], lambda: items
    pointer = run / "FROZEN"
    if not pointer.is_file():
        raise SystemExit("Benchmark is not frozen. Finish review and freeze, or use --unfrozen-dev-smoke.")
    dest = run / pointer.read_text().strip()
    manifest = p5.read(dest / "manifest.json")
    assert manifest["state"] == "FROZEN_HUMAN_SIGNED", "Unexpected frozen state"
    for name in (SPLIT + ".questions.jsonl", SPLIT + ".gold.jsonl"):
        assert file_hash(dest / name) == manifest["sha256"][name], "Changed frozen file: " + name
    questions = _jsonl(dest / (SPLIT + ".questions.jsonl"))
    assert all(set(q) == {"qid", "question", "scope"} for q in questions), "Inference file has extra fields"
    return FROZEN, questions, lambda: _jsonl(dest / (SPLIT + ".gold.jsonl"))


def read_checkpoint(path):
    """A crash can leave one torn final line. Drop it and continue from the last whole record."""
    if not path.is_file():
        return {}
    done, lines = {}, path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines):
        try:
            row = json.loads(line)
        except ValueError:
            assert number == len(lines) - 1, "Corrupt checkpoint line before the end: " + str(path)
            path.write_text("".join(x + "\n" for x in lines[:-1]), encoding="utf-8")
            break
        done[row["qid"]] = row
    return done


def run_questions(questions, path, answer, limit):
    done = read_checkpoint(path)
    with path.open("a", encoding="utf-8") as handle:
        for q in questions:
            if q["qid"] in done:
                continue
            if limit is not None and len(done) >= limit:
                break
            row = answer(q)
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            handle.flush()
            done[q["qid"]] = row
    return done


def open_sql_store(base_db, overlay, seed, population=None):
    store = m3_sql.SqlStore(base_db, overlay / "api_enrichment.duckdb", seed)
    if population is not None and store.population_sha256 != population:
        store.close()
        raise SystemExit("Sample population differs from the development quiz")
    return store


def run_m3(questions, out, base_db, overlay, seed, limit, population=None):
    store = open_sql_store(base_db, overlay, seed, population)
    try:
        return run_questions(questions, out / "predictions.jsonl", lambda q: m3_sql.answer_question(store, q), limit)
    finally:
        store.close()


def run_bm25(questions, out, base, overlay, limit, top_k=10):
    db = duckdb.connect(str(base / "canonical.duckdb"), read_only=True)
    api = duckdb.connect(str(overlay / "api_enrichment.duckdb"), read_only=True)
    try:
        db.execute("SET TimeZone='UTC'")
        db.execute("SET memory_limit='512MB'")
        index = bm25.BM25Index(bm25.build_corpus(db, api))
    finally:
        db.close()
        api.close()

    def retrieve(q):
        hits = index.search(q["question"], top_k)
        return {"qid": q["qid"], "retrieved": [{k: d[k] for k in ("doc_id", "record_id", "rank", "score")} for d in hits]}
    return run_questions(questions, out / "retrievals.jsonl", retrieve, limit)


def run_generation(questions, out, base_db, overlay, args, population=None):
    client = OllamaClient(args.model, args.endpoint, args.timeout,
                          args.max_requests, args.max_output_tokens, args.seed)
    path = out / "predictions.jsonl"
    previous = read_checkpoint(path)
    remaining = [q for q in questions if q["qid"] not in previous][:args.max_requests]
    if args.method == "m3-llm":
        store = open_sql_store(base_db, overlay, args.seed, population)
        try:
            done = run_questions(remaining, path, lambda q: m3_intent.answer_question(store, q, client), args.limit)
        finally:
            store.close()
        return done, client.calls

    index = None
    if args.method == "m1":
        db = duckdb.connect(str(base_db), read_only=True)
        api = duckdb.connect(str(overlay / "api_enrichment.duckdb"), read_only=True)
        try:
            db.execute("SET TimeZone='UTC'")
            db.execute("SET memory_limit='512MB'")
            index = bm25.BM25Index(bm25.build_corpus(db, api))
        finally:
            db.close()
            api.close()
    done = run_questions(remaining, path, lambda q: generation.answer_question(
        q, client, args.method.upper(), index, args.top_k, args.evidence_chars), args.limit)
    return done, client.calls


def score_m3(done, gold, out):
    results = [scoring.score(item, done[item["qid"]]) for item in gold if item["qid"] in done]
    (out / "scores.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in results), encoding="utf-8")
    return {"table": scoring.summarize(results), "scored": len(results)}


def score_bm25(done, gold):
    cells = {}
    for item in gold:
        relevant = bm25.relevant_records(item)
        if item["qid"] not in done or not relevant:
            continue
        hits = done[item["qid"]]["retrieved"]
        cells.setdefault(item["family"], []).append((bm25.recall_at(hits, relevant, 5), bm25.recall_at(hits, relevant, 10),
                                                     bm25.precision_at(hits, relevant, 5)))
    return {"table": [{"family": family, "questions": len(rows), "recall_at_5": sum(r[0] for r in rows) / len(rows),
                       "recall_at_10": sum(r[1] for r in rows) / len(rows), "precision_at_5": sum(r[2] for r in rows) / len(rows)}
                      for family, rows in sorted(cells.items())]}


def missing_inputs(args, base, overlay):
    if args.review_bundle:
        needed = [args.review_bundle / name for name in shared_dev.REVIEW_FILES]
        if args.sample_bundle:
            needed.extend(args.sample_bundle / name for name in shared_dev.SAMPLE_FILES)
        return [str(p) for p in needed if not p.is_file()]
    needed = [] if args.method == "m0" else [base / "canonical.duckdb", base / "manifest.json",
                                            overlay / "api_enrichment.duckdb", overlay / "summary.json"]
    needed.append(args.run / ("candidates.json" if args.unfrozen_dev_smoke else "FROZEN"))
    return [str(p) for p in needed if not p.exists()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("method", choices=("m0", "m1", "m3", "m3-llm", "bm25"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--sources", type=Path, default=Path("configs/phase05_sources.json"))
    parser.add_argument("--run", type=Path, default=Path("outputs/benchmark/phase05/run-65c5be3381f66811"))
    parser.add_argument("--review-bundle", type=Path, help="Use the partner development review sheet for a separate smoke run")
    parser.add_argument("--sample-bundle", type=Path, help="Use the exported sample databases for m3 or m3-llm")
    parser.add_argument("--output", type=Path, default=Path("outputs/phase06"))
    parser.add_argument("--seed", type=int, default=317)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--unfrozen-dev-smoke", action="store_true", help="Read dev questions from the unreviewed candidates")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--model", help="Already installed local Ollama model; required for m0/m1/m3-llm")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--max-requests", type=int, default=5, help="Maximum local model calls per invocation")
    parser.add_argument("--max-output-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--evidence-chars", type=int, default=12000)
    args = parser.parse_args(argv)
    if args.sample_bundle:
        if args.method not in ("m3", "m3-llm"):
            parser.error("--sample-bundle is for m3 and m3-llm")
        args.review_bundle = args.review_bundle or Path(shared_dev.DEFAULT_REVIEW)
    if args.review_bundle and (args.unfrozen_dev_smoke or (args.method != "m0" and not args.sample_bundle)):
        parser.error("Use --review-bundle for m0 or with --sample-bundle for M3; omit --unfrozen-dev-smoke")
    generative = args.method in ("m0", "m1", "m3-llm")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.top_k <= 0 or args.evidence_chars < 2:
        parser.error("--top-k must be positive and --evidence-chars at least 2")
    model_settings = None
    if generative:
        # Configuration validation makes no network call, including during dry-run.
        try:
            OllamaClient(args.model, args.endpoint, args.timeout, args.max_requests, args.max_output_tokens, args.seed)
        except ValueError as error:
            parser.error(str(error))
        model_settings = {"model": args.model, "endpoint": args.endpoint, "temperature": 0,
                          "seed": args.seed, "max_output_tokens": args.max_output_tokens,
                          "top_k": args.top_k, "evidence_chars": args.evidence_chars,
                          "generation_sha256": file_hash(Path(generation.__file__)),
                          "adapter_sha256": file_hash(Path(sys.modules[OllamaClient.__module__].__file__))}
        if args.method == "m3-llm":
            model_settings["intent_sha256"] = file_hash(Path(m3_intent.__file__))
            model_settings["sql_sha256"] = file_hash(Path(m3_sql.__file__))
    root = args.root.resolve()
    args.run = root / args.run
    pins, base, overlay = source_paths(root, root / args.sources)
    base_db = base / "canonical.duckdb"
    if args.review_bundle:
        args.review_bundle = root / args.review_bundle
    if args.sample_bundle:
        args.sample_bundle = root / args.sample_bundle
        overlay = args.sample_bundle
        base_db = overlay / "sample.duckdb"
    report = {"method": args.method, "split": SPLIT, "limit": args.limit, "network_requests": 0, "model_calls": 0, "started_at_utc": stamp()}
    if generative:
        report.update(model_settings=model_settings, max_requests=args.max_requests,
                      provisional_answers=bool(args.unfrozen_dev_smoke or args.review_bundle))
    missing = missing_inputs(args, base, overlay)
    population = None
    if args.review_bundle and not missing:
        questions, gold, review_sources = shared_dev.load_review(args.review_bundle, pins, args.seed)
        population = review_sources["population_manifest_declared_sha256"]
        report.update(benchmark_state=shared_dev.STATE, questions=len(questions), provisional_answers=True,
                      review_sha256=p5.digest(gold))
        if args.sample_bundle:
            report["sample_sha256"] = shared_dev.verify_sample(args.sample_bundle, pins, review_sources)
            if args.dry_run:
                open_sql_store(base_db, overlay, args.seed, population).close()
    if missing or args.dry_run:
        report.update(state="BLOCKED" if missing else "DRY_RUN", missing_inputs=missing)
    else:
        if args.review_bundle:
            state, load_gold = shared_dev.STATE, lambda: gold
            fingerprint = p5.digest([questions, model_settings, report["review_sha256"], report.get("sample_sha256")])[:12]
            mode = "shared-smoke"
        else:
            if args.method != "m0":
                check_pins(pins, base, overlay)
            state, questions, load_gold = load_benchmark(args.run, args.unfrozen_dev_smoke)
            fingerprint_input = [questions, model_settings] if generative else questions
            fingerprint = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True).encode()).hexdigest()[:12]
            mode = "smoke" if args.unfrozen_dev_smoke else "frozen"
        out = root / args.output / f"{args.method}-{SPLIT}-{mode}-{fingerprint}"
        if out.exists() and not args.resume:
            raise SystemExit("Output exists; use --resume to continue it: " + str(out))
        out.mkdir(parents=True, exist_ok=True)
        if generative:
            done, report["model_calls"] = run_generation(questions, out, base_db, overlay, args, population)
            scored = score_m3(done, load_gold(), out)
        elif args.method == "m3":
            done = run_m3(questions, out, base_db, overlay, args.seed, args.limit, population)
            scored = score_m3(done, load_gold(), out)
        else:
            done = run_bm25(questions, out, base, overlay, args.limit)
            scored = score_bm25(done, load_gold())
        report.update(state="COMPLETE" if len(done) == len(questions) else "PARTIAL", benchmark_state=state, questions=len(questions),
                      answered=len(done), output=str(out), finished_at_utc=stamp(), **scored)
        write_json(out / "summary.json", report)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.summary, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["state"] == "BLOCKED" else 0


if __name__ == "__main__":
    sys.exit(main())
