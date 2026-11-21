"""Aggregate-only adapters for saved dev research results. No inference or API calls."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import subprocess
import tempfile
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

import yaml

from bugzilla_serving.contracts.names import FAMILIES, RETRIEVAL_METRICS, validate_mlflow_run
from bugzilla_serving.contracts.run_config import FIXED_RETRIEVERS, ROOT, RunConfig
from bugzilla_serving.tracking.client import config_artifact, params_for


def read(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git_sha(root):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def csv_text(rows, fields):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def projected_config(system, config, root=ROOT, selected=None):
    """Translate saved research settings, preserving historical limits, never clipping."""
    root = Path(root)
    if selected is None:
        selection = read(root / config.get("selection", "configs/selected_retriever.yaml"))
        selected = selection["selected"]
    llm = config.get("effective_llm") or read(root / config["llm_config"])
    # Provider configurations may store model settings under roles.
    role = llm.get("roles", {}).get(
        "generator", llm.get("models", {}).get("generator", llm.get("generator", {}))
    )
    if isinstance(role, str):
        role = {"model": role}
    model = role.get(
        "model", role.get("id", role.get("model_id", llm.get("model", "openai/gpt-oss-20b")))
    )
    retriever = FIXED_RETRIEVERS.get(system, selected["retriever"])
    if system == "S3":
        retriever = config["query_transform"]
    tau = config.get("corrective_tau")
    calibration = root / config.get("corrective_calibration", "missing")
    if tau is None and calibration.is_file():
        tau = read(calibration).get("tau")
    values = dict(
        system_id=system,
        retriever=retriever,
        corpus=selected["corpus"],
        provider=llm.get("provider", "groq"),
        model=model,
        top_k=config.get("retrieval_k", 10),
        temperature=float(role.get("temperature", llm.get("temperature", 0))),
        context_budget_tokens=config.get("context_tokens", 3000),
        prompt_version=config.get("prompt_version", "answer-v1"),
    )
    if system in ("S5", "S8"):
        values["s5_dossier_budget"] = config.get("dossier_tokens", 12000)
    if system in ("S7", "S8"):
        values["s7_max_tool_steps"] = config.get("tool_steps", 4)
    if system == "S4":
        values["s4_tau"] = tau
    if system == "S3":
        values["query_transform"] = retriever
    if retriever not in ("R1", "R2"):
        rc = read(root / config.get("retrieval_config", "configs/retrieval_v3.yaml"))
        values["rrf_k"] = rc.get("rrf_k", 60)
    return RunConfig(**values).validate_against(mode="record")


class _Payload(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active, self.parts = False, []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "data":
            self.active = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)


def review_rows(source, include_all=False):
    source = Path(source)
    rows = list(csv.DictReader((source / "REVIEW.csv").open(encoding="utf-8-sig")))
    lookup = {}
    html = source / "START_HERE.html"
    if html.exists():
        parser = _Payload()
        parser.feed(html.read_text(encoding="utf-8"))
        if parser.parts:
            payload = json.loads("".join(parser.parts))
            lookup = {r["review_id"]: r for r in payload["rows"]}
    if include_all:
        supplied = {r["review_id"]: r for r in rows}
        if len(supplied) != len(rows):
            raise ValueError("Duplicate review_id")
        rows = [{**r, **supplied.get(r["review_id"], {})} for r in lookup.values()] or rows
    seen = set()
    identities = set()
    result = []
    for row in rows:
        if row["review_id"] in seen:
            raise ValueError("Duplicate review_id")
        seen.add(row["review_id"])
        meta = lookup.get(row["review_id"], {})
        if row.get("split", meta.get("split", "dev")) != "dev":
            raise ValueError("Test split source refused; use aggregate-only results separately")
        merged = {**meta, **row}
        merged["system_id"] = row.get("system_id") or meta.get("method")
        merged["family"] = row.get("family") or meta.get("family")
        merged["qid"] = row.get("qid") or meta.get("question_id")
        if merged["system_id"] not in [f"S{i}" for i in range(9)]:
            raise ValueError("Missing/unknown system: need HTML review_id metadata")
        if merged["family"] not in FAMILIES:
            raise ValueError("Missing/unknown family: need HTML review_id metadata")
        if merged.get("dataset") not in ("v3", "phase05", "natural", "sample"):
            raise ValueError("Unknown dataset")
        # Reject edited immutable fields when joining CSV decisions to saved evidence.
        for key in ("question", "model_answer", "reference_answer", "dataset"):
            if key in meta and row.get(key, meta[key]) != meta[key]:
                raise ValueError(f"Review evidence mismatch: {key}")
        verdict = merged.get("answer_verdict", "").strip().upper()
        if verdict not in ("", "CORRECT", "INCORRECT"):
            raise ValueError("Invalid human answer verdict")
        if verdict and (
            not merged.get("reviewer", "").strip() or not merged.get("note", "").strip()
        ):
            raise ValueError("Human verdict requires reviewer and source-check note")
        identity = (merged["dataset"], merged["system_id"], merged["qid"])
        if identity in identities:
            raise ValueError("Duplicate system/question review")
        identities.add(identity)
        result.append(merged)
    return result


def review_verdict(row):
    if row.get("answer_verdict", "").strip():
        return row["answer_verdict"].strip().upper(), "human-review"
    if row["family"] == "F5":
        return "NEEDS_HUMAN", "pending-human-review"
    result = row.get("current_result", "").strip()
    if result == "Correct (automatic)":
        return "CORRECT", "saved-automatic"
    if result == "Wrong (automatic)":
        return "INCORRECT", "saved-automatic"
    return "NEEDS_HUMAN", "pending-human-review"


def aggregate(scores):
    metrics, families = {}, []
    for family in sorted({s["family"] for s in scores}):
        members = [s for s in scores if s["family"] == family]
        scored = [s for s in members if s["verdict"] in ("CORRECT", "INCORRECT")]
        row = dict(
            family=family,
            source_n=len(members),
            scored_n=len(scored),
            pending_n=len(members) - len(scored),
            human_n=sum(s["scorer"] == "human-review" for s in scored),
            score="",
        )
        if scored:
            row["score"] = sum(s["verdict"] == "CORRECT" for s in scored) / len(scored)
            metrics[f"answer.{family}.score"] = row["score"]
            metrics[f"answer.{family}.n"] = len(scored)
        families.append(row)
    if any(f["scored_n"] for f in families):
        metrics["answer.macro"] = sum(f["score"] for f in families if f["scored_n"]) / sum(
            bool(f["scored_n"]) for f in families
        )
    return metrics, families


def discover_ledgers(source, root):
    """Only exact references are eligible; never guess from nearby smoke runs.

    Modern exports retain latest.json -> eval directories -> manifest input_sha256
    pointing to prediction manifests. A portable provenance.json may explicitly
    provide prediction_dirs by dataset (paths relative to project root).
    """
    source, root = Path(source), Path(root)
    explicit = source / "provenance.json"
    if explicit.exists():
        return read(explicit).get("prediction_dirs", {})
    latest = source / "latest.json"
    if not latest.exists():
        return {}
    result = {}
    for dataset, record in read(latest).get("evaluations", {}).items():
        if not record.get("output"):
            continue
        folder = Path(record["output"])
        folder = folder if folder.is_absolute() else root / folder
        manifest = read(folder / "manifest.json")
        candidates = [
            p
            for p in manifest.get("input_sha256", {})
            if "predictions/" in p and p.endswith("/manifest.json")
        ]
        if len(candidates) != 1:
            return {}
        result[dataset] = str(Path(candidates[0]).parent)
    return result


def load_dev_items(root, config, dataset):
    """Reuse the scorer, staging only dev natural rows before JSON/gold parsing.

    The mixed natural export is hash-checked as bytes. Non-dev lines are skipped
    before JSON decoding; locked test question/gold objects are never loaded.
    """
    from bugzilla_qa.evaluation import systems as scorer

    if dataset != "natural":
        return scorer.load_items(root, config, dataset, split="dev")
    path = root / config["natural_questions"]
    manifest_path = root / config["natural_manifest"]
    manifest = read(manifest_path)
    original_hash = sha(path)
    if original_hash != manifest["sha256"]:
        raise ValueError("Natural question checksum mismatch")
    with tempfile.TemporaryDirectory(prefix="bugzilla-dev-only-") as tmp:
        folder = Path(tmp)
        dev = folder / "dev.jsonl"
        with path.open("rb") as stream, dev.open("wb") as output:
            for line in stream:
                if re.search(rb'"split"\s*:\s*"dev"', line):
                    # Verify the top-level identity before staging any object.
                    if json.loads(line).get("split") != "dev":
                        raise ValueError("Natural split marker mismatch")
                    output.write(line)
        staged_manifest = folder / "manifest.json"
        staged_manifest.write_text(json.dumps({**manifest, "sha256": sha(dev)}))
        items, _ = scorer.load_items(
            root,
            {**config, "natural_questions": str(dev), "natural_manifest": str(staged_manifest)},
            "natural",
            split="dev",
        )
        for item in items:
            item["freeze_id"] = original_hash
    return items, {str(path): original_hash, str(manifest_path): sha(manifest_path)}


def _ledger_scores(reviews, directories, root, source):
    from bugzilla_qa.evaluation import systems as scorer

    rc = read(root / "configs/retrieval_v3.yaml")
    all_scores, configs, events, pins = defaultdict(list), {}, defaultdict(list), {}
    for dataset in sorted({r["dataset"] for r in reviews}):
        directory = Path(directories[dataset])
        directory = directory if directory.is_absolute() else root / directory
        items, item_pins = load_dev_items(root, rc, dataset)
        pins.update(item_pins)
        systems = sorted({r["system_id"] for r in reviews if r["dataset"] == dataset})
        selected, attempts, prediction_pins = scorer.select_predictions(directory, items, systems)
        pins.update(prediction_pins)
        pins[str(directory / "config_snapshot.json")] = sha(directory / "config_snapshot.json")
        snapshot = read(directory / "config_snapshot.json")
        identity_path = directory / "identity.json"
        selection = None
        if identity_path.exists():
            identity = read(identity_path)
            manifest = read(directory / "manifest.json")
            if scorer.digest(identity) != manifest["config_hash"]:
                raise ValueError("Prediction identity hash mismatch")
            if any(snapshot.get(k) != v for k, v in identity["config"].items()):
                raise ValueError("Snapshot and identity config disagree")
            snapshot = {**identity["config"], "effective_llm": identity["llm"]}
            selection = identity["selected"]
            pins[str(identity_path)] = sha(identity_path)
        item_map = {i["qid"]: i for i in items}
        for system in systems:
            cfg = projected_config(system, snapshot, root, selected=selection)
            if system in configs and configs[system] != cfg:
                raise ValueError("Mixed historical system configs across pilot datasets")
            configs[system] = cfg
            wanted = [r for r in reviews if r["dataset"] == dataset and r["system_id"] == system]
            ids = {r["qid"] for r in wanted}
            events[system].extend(e for e in attempts[system] if e["qid"] in ids)
            for review in wanted:
                item = item_map[review["qid"]]
                pred = selected[system].get(item["qid"])
                if pred and pred["status"] == "ok":
                    rid = scorer.digest(
                        [
                            scorer.VERSION,
                            item,
                            system,
                            pred["config_hash"],
                            pred["answer"],
                            pred.get("context_chunk_ids"),
                        ]
                    )[:24]
                    if rid != review["review_id"]:
                        raise ValueError("Human review is not bound to this prediction/source hash")
                result = scorer.grade(item, pred)
                human = review.get("answer_verdict", "").strip().upper()
                if human:
                    result.update(verdict=human, reason="human_review")
                all_scores[system].append(
                    dict(
                        family=item["family"],
                        verdict=result["verdict"],
                        reason=result["reason"],
                        scorer="human-review" if human else scorer.VERSION,
                        expected_unanswerable=item["kind"]
                        in ("unknown", "unanswerable", "abstain"),
                        abstained=bool(pred and pred.get("answer", {}).get("abstain")),
                    )
                )
    return all_scores, configs, events, pins


def answer_intervals(source, root, system):
    """Retain previously computed dev CIs as aggregates, never fabricate new CIs."""
    latest = Path(source) / "latest.json"
    intervals = []
    if not latest.exists():
        return intervals
    for dataset, record in read(latest).get("evaluations", {}).items():
        if not record.get("output"):
            continue
        folder = root / record["output"]
        summary_path = folder / "summary.json"
        if not summary_path.exists():
            continue
        summary = read(summary_path)
        if summary.get("split") != "dev":
            raise ValueError("Test source summary refused")
        for row in summary.get("table", []):
            ci = row.get("cluster_bootstrap_95")
            if row.get("system_id") == system and ci is not None:
                if (
                    not isinstance(ci, list)
                    or len(ci) != 2
                    or not all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in ci)
                ):
                    raise ValueError("Invalid saved confidence interval")
                intervals.append(
                    dict(
                        dataset=dataset,
                        family=row["family"],
                        n=row["n"],
                        ci_low=ci[0],
                        ci_high=ci[1],
                    )
                )
    return intervals


def answer_runs(source, mode="auto", root=ROOT):
    source, root = Path(source), Path(root)
    reviews = review_rows(source)
    if not reviews:
        raise ValueError("Empty review source")
    directories = discover_ledgers(source, root)
    datasets = sorted({r["dataset"] for r in reviews})
    available = all(
        d in directories and (root / directories[d] / "manifest.json").is_file() for d in datasets
    )
    selected_mode = ("ledgers" if available else "review-only") if mode == "auto" else mode
    if selected_mode == "ledgers" and not available:
        raise ValueError("Exact referenced prediction ledgers unavailable; use --mode review-only")
    reason = (
        "Exact referenced prediction runs available"
        if available
        else "Exact prediction references/manifests missing; no substitute smoke runs used"
    )
    pins = {str(source / "REVIEW.csv"): sha(source / "REVIEW.csv")}
    if (source / "START_HERE.html").exists():
        pins[str(source / "START_HERE.html")] = sha(source / "START_HERE.html")
    if selected_mode == "ledgers":
        reviews = review_rows(source, include_all=True)
        scores, configs, events, ledger_pins = _ledger_scores(reviews, directories, root, source)
        pins.update(ledger_pins)
    else:
        scores, configs, events = defaultdict(list), {}, {}
        cfg = read(root / "configs/answering.yaml")
        for row in reviews:
            system = row["system_id"]
            verdict, by = review_verdict(row)
            scores[system].append(dict(family=row["family"], verdict=verdict, scorer=by))
            configs[system] = projected_config(system, cfg, root)
    plans = []
    for system, values in sorted(scores.items()):
        metrics, families = aggregate(values)
        if selected_mode == "ledgers":
            attempts = events[system]
            if all(isinstance(e.get("call_count"), int) for e in attempts):
                metrics["cost.llm_calls"] = sum(e["call_count"] for e in attempts)
            for key, metric in [
                ("input_tokens", "cost.tokens_in"),
                ("output_tokens", "cost.tokens_out"),
            ]:
                if attempts and all(
                    isinstance(e.get("tokens", {}).get(key), (int, float)) for e in attempts
                ):
                    metrics[metric] = sum(e["tokens"][key] for e in attempts)
            latency = sorted(
                e["latency_ms"]
                for e in attempts
                if not e.get("llm_cache_hit") and isinstance(e.get("latency_ms"), (int, float))
            )
            if latency:
                metrics.update(
                    {
                        "latency.p50_ms": latency[len(latency) // 2],
                        "latency.p95_ms": latency[min(len(latency) - 1, int(0.95 * len(latency)))],
                    }
                )
            if values:
                metrics["fail.rate"] = sum(
                    v.get("reason") in ("execution_failure", "missing_prediction") for v in values
                ) / len(values)
            known = [v for v in values if v.get("expected_unanswerable")]
            if known:
                metrics["abstain.correct_rate"] = sum(
                    v.get("abstained", False) for v in known
                ) / len(known)
            answerable = [v for v in values if not v.get("expected_unanswerable")]
            if answerable:
                metrics["abstain.false_rate"] = sum(
                    v.get("abstained", False) for v in answerable
                ) / len(answerable)
        cfg = configs[system]
        tags = dict(
            source="backfill",
            eval_set=source.name,
            datasets=",".join(datasets),
            split="dev",
            scorer="bugzilla_qa.evaluation.systems" if selected_mode == "ledgers" else "review-csv",
            git_sha=git_sha(root),
            provenance=selected_mode,
            config_origin="historical" if selected_mode == "ledgers" else "reconstructed",
            pilot="true",
            system_id=system,
            pending_n=str(sum(f["pending_n"] for f in families)),
        )
        for f in families:
            if f["human_n"]:
                tags[f"scorer.{f['family']}"] = "human-review"
        artifacts = {
            "config.yaml": config_artifact(cfg),
            "per_family.csv": csv_text(families, list(families[0])),
            "intervals.json": json.dumps(
                answer_intervals(source, root, system) if selected_mode == "ledgers" else []
            ),
            "provenance.json": json.dumps(
                dict(
                    mode=selected_mode,
                    reason=reason,
                    input_sha256=pins,
                    datasets=datasets,
                    source_rows=len(values),
                    pending_n=sum(f["pending_n"] for f in families),
                    omitted_metrics="Unavailable metrics omitted, never zero-filled",
                ),
                indent=2,
            ),
        }
        params = params_for(cfg)
        validate_mlflow_run(params, tags, metrics)
        plans.append(
            dict(
                experiment="research-answer-eval",
                params=params,
                tags=tags,
                metrics=metrics,
                artifacts=artifacts,
            )
        )
    return plans, dict(mode=selected_mode, reason=reason, rows=len(reviews), datasets=datasets)


def retrieval_runs(directories, root=ROOT):
    root = Path(root)
    groups, hashes, intervals = defaultdict(dict), defaultdict(dict), []
    for directory in sorted(map(Path, directories)):
        path = directory / "summary.json"
        summary = read(path)
        if summary.get("split") != "dev" or summary.get("locked_test_used"):
            raise ValueError("Test retrieval input refused: aggregate-only ingestion is separate")
        if summary.get("state") != "COMPLETE" or summary.get("limited"):
            raise ValueError("Only complete, unlimited retrieval summaries can be backfilled")
        for row in summary.get("bootstrap", []):
            if isinstance(row, dict):
                intervals.append(
                    {
                        k: v
                        for k, v in row.items()
                        if isinstance(v, (int, float))
                        or k in ("dataset", "family", "retriever", "corpus", "metric")
                    }
                )
        for cell in summary["cells"]:
            pair = (cell["retriever"], cell["corpus"])
            key = (cell["dataset"], cell["family"])
            old = groups[pair].get(key)
            # Overlapping baseline reruns: retain first complete source, record all input hashes.
            if old is None:
                groups[pair][key] = cell
            else:

                def factual(c):
                    return {
                        k: v
                        for k, v in c.items()
                        if "latency" not in k and k != "r4_r3_jaccard_top10"
                    }

                if factual(old) != factual(cell):
                    raise ValueError(f"Conflicting retrieval cells for {pair}/{key}")
            hashes[pair][
                str(path.relative_to(root) if path.is_relative_to(root) else path.name)
            ] = sha(path)
    plans = []
    base = read(root / "configs/answering.yaml")
    selected = read(root / "configs/selected_retriever.yaml")["selected"]
    for (retriever, corpus), cells in sorted(groups.items()):
        cfg = projected_config("S2", base, root).model_copy(
            update=dict(
                retriever=retriever, corpus=corpus, rrf_k=None if retriever in ("R1", "R2") else 60
            )
        )
        metrics, na, per_family = {}, [], []
        for (dataset, family), cell in sorted(cells.items()):
            n = cell.get("n", cell.get("dataset_n", 0))
            if n:
                metrics[f"retr.{dataset}.{family}.n"] = n
            for metric in RETRIEVAL_METRICS:
                if metric == "n":
                    continue
                value = cell.get(metric)
                denom = n
                if isinstance(value, dict):
                    denom, value = value.get("n", n), value.get("value")
                if value is not None and denom and cell.get("state") != "not in dataset":
                    metrics[f"retr.{dataset}.{family}.{metric}"] = value
                else:
                    na.append(
                        dict(
                            dataset=dataset,
                            family=family,
                            metric=metric,
                            state=cell.get("state", "N/A"),
                            n=denom,
                        )
                    )
            per_family.append(dict(dataset=dataset, family=family, n=n, state=cell.get("state")))
        tags = dict(
            source="backfill",
            eval_set="retrieval-v3-dev",
            datasets=",".join(sorted({k[0] for k in cells})),
            split="dev",
            scorer="retrieval_v3",
            git_sha=git_sha(root),
            config_origin="historical",
            selected=str(
                (retriever, corpus) == (selected.get("retriever"), selected.get("corpus"))
            ).lower(),
        )
        artifacts = {
            "config.yaml": config_artifact(cfg),
            "per_family.csv": csv_text(per_family, ["dataset", "family", "n", "state"]),
            "na_cells.csv": csv_text(na, ["dataset", "family", "metric", "state", "n"]),
            "source_manifest.json": json.dumps(hashes[(retriever, corpus)], indent=2),
            "intervals.json": json.dumps(intervals, indent=2),
        }
        params = params_for(cfg)
        validate_mlflow_run(params, tags, metrics)
        plans.append(
            dict(
                experiment="research-retrieval-eval",
                params=params,
                tags=tags,
                metrics=metrics,
                artifacts=artifacts,
            )
        )
    return plans
