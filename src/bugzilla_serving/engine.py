"""Thin dev-only adapter over the existing research AnswerGraph and Backend."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Callable

from .contracts.records import AnswerRecord, StatusData, StatusEvent
from .contracts.run_config import ROOT, RunConfig, config_hash, load_spec


def redact(value):
    """Redact known credential values before callbacks, outputs or fixture logging."""
    secrets = [v for k, v in os.environ.items() if v and (
        k.endswith(("_API_KEY", "_PASSWORD")) or k in {"LANGSMITH_KEY", "LLM_API_KEY"}
    )]
    from bugzilla_qa.answering.contracts import clean

    def walk(item):
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "[redacted]")
            return item
        if isinstance(item, dict):
            return {k: walk(v) for k, v in item.items()}
        if isinstance(item, list):
            return [walk(v) for v in item]
        return item

    return walk(clean(value))


def _bundle(path: Path):
    manifest = json.loads((path / "manifest.json").read_text())
    if manifest.get("split") != "dev":
        raise ValueError("bundle: only dev evidence is permitted")
    for name, meta in manifest["files"].items():
        file = (path / name).resolve()
        if not file.is_relative_to(path.resolve()):
            raise ValueError("bundle: path traversal")
        if file.stat().st_size != meta["bytes"]:
            raise ValueError("bundle: size mismatch")
        with file.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != meta["sha256"]:
                raise ValueError("bundle: checksum mismatch")
    return manifest


def build_runner(cfg: RunConfig, provider=None) -> Runner:
    return Runner(cfg, provider)


class Runner:
    def __init__(self, cfg: RunConfig, provider=None):
        from bugzilla_qa.answering.backend import Backend
        from bugzilla_qa.llm.provider import create_provider
        from bugzilla_qa.retrieval_v3.common import read_config

        spec = load_spec()
        defaults = {k: v["default"] for k, v in spec["hyperparameters"].items()}
        self.cfg = cfg.validate_against(spec)
        self.root = Path(os.environ.get("BUNDLE_DIR", "serving_bundle")).resolve()
        metadata = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        if metadata.get("synthetic"):
            self.manifest = _bundle(self.root)
        else:
            from .bundle import load_bundle

            self.manifest = load_bundle(self.root).manifest
        runtime = self.manifest["runtime_config"]
        if runtime not in self.manifest["files"]:
            raise ValueError("bundle: runtime config must be manifest-listed")
        self.config = read_config(self.root / runtime)
        self.config.update(
            context_tokens=cfg.context_budget_tokens,
            dossier_tokens=cfg.s5_dossier_budget or defaults["s5_dossier_budget"],
            tool_steps=cfg.s7_max_tool_steps or defaults["s7_max_tool_steps"],
            corrective_tau=(cfg.s4_tau if cfg.s4_tau is not None else defaults["s4_tau"]),
            retrieval_k=cfg.top_k, prompt_version=cfg.prompt_version,
            query_transform=cfg.query_transform or (
                cfg.retriever if cfg.system_id == "S3" else "R7b"
            ),
            compact_prompts=cfg.prompt_version == "answer-v2-compact",
        )
        prompt = "answer_v2_compact.txt" if self.config["compact_prompts"] else "answer_v1.txt"
        self.prompt = (ROOT / "prompts" / prompt).read_text()
        if provider is None:
            if cfg.provider == "mock" or cfg.system_id == "R0":
                provider = _mock_provider()
            else:
                llm = read_config(ROOT / "configs/llm.yaml")
                model = next(m for m in load_spec()["models"].values()
                             if m["model_id"] == cfg.model)
                llm.update(provider=cfg.provider, temperature=cfg.temperature)
                # The research cache key omits temperature. Isolate runtime configs
                # while retaining the shared per-model request ledger/quota history.
                llm["cache"] = f"outputs/llm/serving/{config_hash(cfg)}/cache.sqlite"
                llm["models"]["generator"].update(
                    id=cfg.model, rpm=model["rpm"], rpd=model["rpd"],
                )
                provider = create_provider(
                    llm, "generator", enable_llm=True, max_requests=32,
                    root=ROOT, resolve_env=False,
                )
        self.provider = provider
        self.backend = Backend(self.config, self.root, provider)
        if not self.manifest.get("synthetic"):
            if cfg.corpus not in self.manifest.get("available_corpora", []):
                raise ValueError("corpus: not included in this bundle")
            self.backend._engine = self._serving_engine
        elif cfg.retriever == "R1":
            # Synthetic fixtures ship lexical indexes only, so R1 must not load dense models.
            self.backend._engine = self._serving_engine
        # Every override is applied before lazy model/index construction. Research caches
        # are bypassed: their keys do not include these runtime hyperparameters.
        self.backend.cache_manifests = {}
        self.backend.memory_cache = None
        self.backend.selected = cfg.retriever
        self.backend.corpus = cfg.corpus
        self.backend.directory = self.backend.index / cfg.corpus
        variant = read_config(self.backend.directory / "manifest.json")
        if variant.get("state") != "COMPLETE":
            raise ValueError("corpus: index is incomplete")
        for name, expected in variant["sha256"].items():
            if hashlib.sha256((self.backend.directory / name).read_bytes()).hexdigest() != expected:
                raise ValueError("corpus: checksum mismatch")
        from bugzilla_qa.answering.contracts import public_chunk
        from bugzilla_qa.retrieval_v3.common import read_jsonl

        self.backend.docs = [public_chunk(d) for d in read_jsonl(
            self.backend.directory / "corpus.jsonl"
        )]
        self.backend.by_id = {d["chunk_id"]: d for d in self.backend.docs}
        if cfg.rrf_k is not None:
            self.backend.rc["rrf_k"] = cfg.rrf_k
        self._temp = None
        self._source_override = None
        if self.manifest.get("synthetic"):
            # Synthetic fixtures ship deterministic SQL rather than a version-specific
            # DuckDB binary. They are materialized only in a temporary directory.
            import duckdb

            self._temp = tempfile.TemporaryDirectory(prefix="bugzilla-p0-")
            db_path = Path(self._temp.name) / "canonical.duckdb"
            db = duckdb.connect(str(db_path))
            try:
                db.execute((self.root / "canonical.sql").read_text())
            finally:
                db.close()
            self._source_override = str(db_path)
        # The accepted real bundle uses text-only examples; their dev scope is
        # declared by the checksum-verified manifest. Structured rows still
        # require an explicit dev split, including any future metadata format.
        self.examples = [
            {"question": q["text"], "split": "dev"} if set(q) == {"text"} else q
            for q in read_jsonl(self.root / self.manifest["dev_questions"])
        ]
        if any(q.get("split") != "dev" for q in self.examples):
            raise ValueError("bundle: non-dev question refused")
        if any(not isinstance(q.get("question"), str) or not q["question"].strip()
               for q in self.examples):
            raise ValueError("bundle: expected nonempty question or text-only example")

    def _serving_engine(self):
        from bugzilla_qa.retrieval_v3.registry import Engine
        from bugzilla_qa.retrieval_v3.transforms import QueryTransforms

        backend = self.backend
        if backend.engine is None:
            if self.cfg.retriever == "R1":
                edges = json.loads((backend.index / "graph.json").read_text())
                backend.engine = Engine(backend.docs, backend.directory / "lexical.sqlite",
                                        None, None, edges, backend.rc)
            else:
                from sentence_transformers import CrossEncoder, SentenceTransformer

                from bugzilla_qa.retrieval_v3.runner import load_engine

                cache = str(self.root / "models/huggingface/hub")
                rc = backend.rc
                embed = SentenceTransformer(rc["embedding_model"],
                                            revision=rc["embedding_revision"], device=rc["device"],
                                            cache_folder=cache, local_files_only=True)
                cross = CrossEncoder(rc["reranker_model"], revision=rc["reranker_revision"],
                                     device=rc["device"], cache_dir=cache, local_files_only=True)
                backend.engine = load_engine(backend.directory, rc, (embed, cross),
                                             QueryTransforms(self.provider))
        return backend.engine

    def run(self, question: str, on_event: Callable | None = None) -> AnswerRecord:
        from bugzilla_qa.answering.graph import AnswerGraph
        from bugzilla_qa.answering.tools import Tools
        from langsmith import tracing_context

        if not isinstance(question, str) or not question.strip() or len(question) > 6000:
            raise ValueError("question: expected 1..6000 characters")
        start = time.perf_counter()
        before = self.provider.calls
        event_start = len(getattr(self.provider, "events", []))

        def emit(stage, detail):
            if on_event:
                event = StatusEvent(data=StatusData(stage=stage, detail=detail))
                on_event(redact(event.model_dump(mode="json")))

        matching = next((q for q in self.examples if q["question"] == question), None)
        q = dict(qid="interactive", question=question, family="UNKNOWN", split="dev",
                 dataset="serving", freeze_id="serving-bundle", scope={})
        if matching:
            q.update({k: matching[k] for k in ("qid", "family", "scope") if k in matching})
        if self.cfg.system_id == "ORACLE":
            if not matching or not matching.get("evidence_record_ids"):
                raise ValueError("ORACLE: requires explicit references for a known dev question")
            q["oracle_refs"] = matching["evidence_record_ids"]
        emit("retrieving", "Searching public evidence")
        if self.cfg.system_id == "R0":
            # R7 is rejected for R0 by RunConfig, so this cannot request a transform.
            docs, cached = self.backend.retrieve(q, self.cfg.retriever, use_cache=False)
            emit("retrieved", f"Found {len(docs)} sources")
            emit("generating", "Retrieval only; answer generation skipped")
            state = dict(answer=_abstain(), route="R0", route_rule="retrieval_only",
                         retrieved=docs, usage=[], errors=[], cache_hit=cached)
        else:
            graph_type = AnswerGraph
            tools_type = Tools
            if self.cfg.system_id == "S8v2":
                from bugzilla_qa.answering_v2.graph import AnswerGraphV2
                from bugzilla_qa.answering_v2.tools import ToolsV2

                graph_type, tools_type = AnswerGraphV2, ToolsV2
            tools = tools_type(self.config, self.root, self.backend)
            if self._source_override:
                tools.source["canonical_db"] = self._source_override
            outer = self

            class ProgressGraph(graph_type):
                def retrieve(self, state):
                    result = super().retrieve(state)
                    emit("retrieved", f"Found {len(result['retrieved'])} sources")
                    emit("generating", "Preparing answer from supplied evidence")
                    return result

            try:
                from .tracing import active

                with tracing_context(enabled=active()):
                    graph = ProgressGraph(
                        outer.config, outer.provider, outer.backend, tools,
                        outer.prompt, lambda state: None,
                    )
                    state = graph.invoke(q, outer.cfg.system_id, config_hash(outer.cfg))
            finally:
                tools.close()
        usage = (self.provider.events[event_start:] if hasattr(self.provider, "events")
                 else state.get("usage", []))
        charged = [u for u in usage if u.get("state") != "CACHE_HIT"]
        evidence = {d["chunk_id"]: d for d in state.get("retrieved", [])}
        for chunk_id in state.get("context_ids", []):
            if chunk_id in self.backend.by_id:
                evidence.setdefault(chunk_id, self.backend.by_id[chunk_id])
        value = dict(
            answer=state["answer"], route=state["route"], route_rule=state["route_rule"],
            evidence=[dict(
                chunk_id=d["chunk_id"], bug_id=str(d["bug_id"]),
                snippet=d["text"][:600], score=float(d.get("score", 0)),
                url=d.get("url", f"https://bugzilla.mozilla.org/show_bug.cgi?id={d['bug_id']}"),
            ) for d in evidence.values()],
            tokens={"input": sum(u.get("input_tokens") or 0 for u in charged),
                    "output": sum(u.get("output_tokens") or 0 for u in charged),
                    "cached_input": sum(u.get("input_tokens") or 0 for u in usage
                                        if u.get("state") == "CACHE_HIT"),
                    "cached_output": sum(u.get("output_tokens") or 0 for u in usage
                                         if u.get("state") == "CACHE_HIT"),
                    "usage_missing": bool(state.get("errors")) or any(
                        u.get("input_tokens") is None for u in charged)},
            llm_calls=self.provider.calls - before,
            cache_hits=sum(u.get("state") == "CACHE_HIT" for u in usage)
                       + int(state.get("retrieval_cache_hit", False)),
            latency_ms=(time.perf_counter() - start) * 1000,
            degraded=self.cfg.system_id == "R0", errors=state.get("errors", []),
            config_hash=config_hash(self.cfg),
        )
        record = AnswerRecord.model_validate(redact(value))
        emit("done", "Finished")
        return record

    def close(self):
        if self._temp:
            self._temp.cleanup()
            self._temp = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _abstain():
    return dict(abstain=True, answer=None, answer_type="unknown", bug_ids=[], citations=[],
                rationale="No generated answer is available; inspect the supplied sources.")


def _mock_provider():
    from bugzilla_qa.llm.provider import MockProvider

    class SchemaMock(MockProvider):
        def generate_json(self, prompt, schema, **kwargs):
            properties = schema.get("properties", {})
            if "queries" in properties:
                self.value = {"queries": [prompt] * properties["queries"]["minItems"]}
            elif "route" in properties:
                self.value = {"route": "S2"}
            elif "calls" in properties:
                self.value = {"calls": [{
                    "name": "submit_answer", "arguments_json": json.dumps(_abstain()),
                }]}
            else:
                self.value = _abstain()
            return super().generate_json(prompt, schema, **kwargs)

    return SchemaMock(None)
