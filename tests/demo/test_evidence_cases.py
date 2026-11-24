"""R0 evidence packing with tiny synthetic IDs; opt-in real bundle uses the same checks."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from test_router_cases import CASES

from bugzilla_qa.answering.contracts import pack
from bugzilla_serving.contracts.run_config import RunConfig
from bugzilla_serving.engine import build_runner
from bugzilla_serving.experiments.fixtures import build_synthetic_bundle
from bugzilla_serving.routing import ordered_dossier, pack_dossier


@pytest.fixture(scope="module")
def evidence_bundle(tmp_path_factory):
    supplied = os.environ.get("DEMO_REAL_BUNDLE")
    if supplied:
        return Path(supplied).resolve()
    bundle = build_synthetic_bundle(tmp_path_factory.mktemp("evidence"))
    mapping = {"100000": "1708248", "100001": "1809146", "100002": "1718774", "100003": "1771951"}
    for path in bundle.rglob("*"):
        if path.suffix not in (".json", ".jsonl", ".sql") or path.name == "manifest.json":
            continue
        text = path.read_text()
        for old, new in mapping.items():
            text = text.replace(old, new)
        path.write_text(text)
    for corpus in ("C0", "C1", "C2"):
        path = bundle / "indexes" / corpus / "manifest.json"
        value = json.loads(path.read_text())
        for name in value["sha256"]:
            value["sha256"][name] = hashlib.sha256((path.parent / name).read_bytes()).hexdigest()
        path.write_text(json.dumps(value))
    path = bundle / "indexes/manifest.json"
    value = json.loads(path.read_text())
    for name in value["sha256"]:
        value["sha256"][name] = hashlib.sha256((path.parent / name).read_bytes()).hexdigest()
    path.write_text(json.dumps(value))
    path = bundle / "manifest.json"
    value = json.loads(path.read_text())
    for name in value["files"]:
        file = bundle / name
        value["files"][name] = dict(
            bytes=file.stat().st_size, sha256=hashlib.sha256(file.read_bytes()).hexdigest()
        )
    path.write_text(json.dumps(value))
    return bundle


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.get("must_cite_bug")], ids=lambda c: c["id"]
)
def test_packed_bug_evidence(case, evidence_bundle, monkeypatch):
    monkeypatch.setenv("BUNDLE_DIR", str(evidence_bundle))
    cfg = RunConfig(
        system_id="R0", retriever="R1", provider="mock", serving_bug_scope=True, top_k=10
    )
    with build_runner(cfg) as runner:
        docs, _ = runner.backend.retrieve({"question": case["question"]}, "R1", use_cache=False)
        if case["expected_route"] == "S5":
            context, mapping = pack_dossier(ordered_dossier(docs, case["question"]), 4096)
        else:
            context, mapping = pack(docs, 3000)
        assert context and mapping
        packed = [runner.backend.by_id[c] for c in mapping.values()]
        assert {str(d["bug_id"]) for d in packed} == {case["must_cite_bug"]}
        assert runner.provider.calls == 0


def test_truncation_marks_and_cap():
    docs = [
        dict(
            chunk_id="m",
            record_id="m",
            bug_id="1",
            kind="metadata",
            text="metadata",
            visibility="public",
        ),
        dict(
            chunk_id="c",
            record_id="c",
            bug_id="1",
            kind="comment",
            text="x" * 8000,
            visibility="public",
        ),
    ]
    text, ids = pack_dossier(docs, 4096)
    assert len(text.encode()) <= 4096 and "truncated" in text
    assert list(ids.values()) == ["m", "c"]
