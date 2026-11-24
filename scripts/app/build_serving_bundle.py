"""Preview or copy the existing public runtime into a checked, portable serving bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = "outputs/evaluation/phase11/official_runtime/answering.json"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def safe_name(name):
    name = str(name).replace("\\", "/")
    if "test" in name.lower() or "gold" in name.lower():
        raise ValueError("test or gold path refused: " + name)
    if Path(name).is_absolute() or ".." in name.split("/") or ":" in name:
        raise ValueError("unsafe bundle path: " + name)
    return name


def source_path(root, name):
    path = (root / safe_name(name)).resolve()
    if not path.is_relative_to(root):
        raise ValueError("source escapes input root")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def plan(root, runtime_name=RUNTIME):
    root = Path(root).resolve()
    runtime = read(source_path(root, runtime_name))
    retrieval = read(source_path(root, runtime["retrieval_config"]))
    selection = read(source_path(root, runtime["selection"]))
    source = read(source_path(root, runtime["source_config"]))
    if selection.get("test_used") or selection["state"] != "RECONSTRUCTED_DEV_RUNTIME":
        raise ValueError("expected the reconstructed development selection")
    copies, generated = {}, {}

    def copy(name, target):
        copies[safe_name(target)] = source_path(root, name)

    def write(name, value):
        generated[safe_name(name)] = (json.dumps(value, indent=2) + "\n").encode()

    new_source = {"sample_seed": source.get("sample_seed", 317)}
    for key in ("canonical_db", "history_db"):
        if source.get(key):
            target = "data/" + Path(source[key].replace("\\", "/")).name
            copy(source[key], target)
            new_source[key] = target
    write("source.json", new_source)
    copy(runtime["history_checkpoint"], "history.json")
    index_name = selection["index_build"].replace("\\", "/")
    index = root / index_name
    available = [c for c in ("C0", "C1", "C2") if (index / c / "manifest.json").is_file()]
    if not available or selection["selected"]["corpus"] not in available:
        raise ValueError("selected corpus is missing")
    for corpus in available:
        manifest_name = index_name + "/" + corpus + "/manifest.json"
        variant = read(source_path(root, manifest_name))
        if variant.get("state") != "COMPLETE":
            raise ValueError("incomplete corpus: " + corpus)
        hashes = {}
        for name, expected in variant["sha256"].items():
            name = safe_name(name)
            original = source_path(root, index_name + "/" + corpus + "/" + name)
            if digest(original) != expected:
                raise ValueError("index checksum mismatch: " + str(original))
            copy(index_name + "/" + corpus + "/" + name, "indexes/" + corpus + "/" + name)
            hashes[name] = expected
        write("indexes/" + corpus + "/manifest.json", dict(variant, sha256=hashes))
    copy(index_name + "/graph.json", "indexes/graph.json")
    index_hashes = {
        c + "/manifest.json": hashlib.sha256(
            generated["indexes/" + c + "/manifest.json"]
        ).hexdigest()
        for c in available
    }
    write("indexes/manifest.json", {"state": "COMPLETE", "sha256": index_hashes})
    new_selection = dict(selection, index_build="indexes", sources=[])
    write("selection.json", new_selection)
    keys = (
        "seed",
        "candidate_k",
        "rrf_k",
        "hierarchical_max_bugs",
        "graph_top_bugs",
        "graph_max_slots",
        "graph_insert_after",
        "device",
        "embedding_model",
        "embedding_revision",
        "reranker_model",
        "reranker_revision",
        "batch_size",
    )
    write("retrieval.json", {k: retrieval[k] for k in keys})
    for kind in ("embedding", "reranker"):
        model = retrieval[kind + "_model"].replace("/", "--")
        revision = retrieval[kind + "_revision"]
        folder = "models/huggingface/hub/models--" + model + "/snapshots/" + revision
        files = sorted((root / folder).rglob("*"))
        if not any(p.name in ("model.safetensors", "pytorch_model.bin") for p in files):
            raise FileNotFoundError("local model weights missing: " + folder)
        for path in files:
            if path.is_file():
                name = path.relative_to(root).as_posix()
                copy(name, name)
    examples = []
    for key in ("phase05_dir", "v3_dir"):
        questions = source_path(root, retrieval[key].replace("\\", "/") + "/dev.questions.jsonl")
        for line in questions.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("split", "dev") != "dev":
                raise ValueError("non-dev example refused")
            examples.append({"text": row["question"]})
    generated["dev_questions.jsonl"] = "".join(json.dumps(q) + "\n" for q in examples).encode()
    keys = (
        "duckdb_memory",
        "seed",
        "context_tokens",
        "tool_steps",
        "retrieval_k",
        "prompt_version",
        "query_transform",
        "tool_result_limit",
    )
    settings = {k: runtime[k] for k in keys if k in runtime}
    settings.update(
        source_config="source.json",
        history_checkpoint="history.json",
        retrieval_config="retrieval.json",
        selection="selection.json",
        retrieval_runs=[],
        runtime_manifest="runtime_origin.json",
        dossier_tokens=4096,
    )
    write(
        "runtime_origin.json",
        {
            "kind": "reconstructed shared-source runtime",
            "source_sha256": digest(source_path(root, runtime_name)),
        },
    )
    write("runtime.json", settings)
    return copies, generated, available, len(examples)


def build(root, output, *, apply=False, require_all=False, runtime_name=RUNTIME):
    copies, generated, corpora, examples = plan(root, runtime_name)
    missing = sorted(set(("C0", "C1", "C2")) - set(corpora))
    if require_all and missing:
        raise ValueError("missing corpora: " + ", ".join(missing))
    report = dict(
        state="DRY_RUN",
        corpora=corpora,
        missing_corpora=missing,
        examples=examples,
        output=str(output),
        files=[{"path": n, "bytes": p.stat().st_size} for n, p in sorted(copies.items())],
    )
    report["files"].extend(
        {"path": name, "bytes": len(data), "generated": True}
        for name, data in sorted(generated.items())
    )
    report["bytes"] = sum(p.stat().st_size for p in copies.values()) + sum(
        map(len, generated.values())
    )
    if not apply:
        return report
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("output already exists; choose a new --out folder")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".serving-build-", dir=output.parent) as temporary:
        folder = Path(temporary) / "bundle"
        folder.mkdir()
        for name, original in copies.items():
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            before = digest(original)
            shutil.copyfile(original, target)
            if digest(target) != before:
                raise ValueError("source changed while copying: " + name)
        for name, data in generated.items():
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        files = {
            p.relative_to(folder).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
            for p in sorted(folder.rglob("*"))
            if p.is_file()
        }
        manifest = dict(
            schema_version="phase0-v1",
            split="dev",
            synthetic=False,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            runtime_config="runtime.json",
            dev_questions="dev_questions.jsonl",
            available_corpora=corpora,
            missing_corpora=missing,
            files=files,
        )
        (folder / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        folder.rename(output)
    report.update(state="COMPLETE", file_count=len(files))
    report.pop("files")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("serving_bundle"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--runtime", default=RUNTIME)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                build(
                    args.root,
                    args.out,
                    apply=args.apply,
                    require_all=args.require_all,
                    runtime_name=args.runtime,
                ),
                indent=2,
            )
        )
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
