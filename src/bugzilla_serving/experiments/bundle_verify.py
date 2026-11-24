"""Read-only, offline bundle verification with stat-validated hash caching."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.tracking.backfill import read


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_bundle(bundle, *, rehash=False, allow_synthetic=False, cache_dir=None):
    bundle = Path(bundle).resolve()
    result = dict(ok=False, errors=[], available_corpora=[], missing_corpora=[], cache_reused=False)
    try:
        manifest_path = bundle / "manifest.json"
        manifest_sha = sha(manifest_path)
        manifest = read(manifest_path)
        synthetic = manifest.get("synthetic") is True
        result.update(
            split=manifest.get("split"),
            synthetic=synthetic,
            manifest_sha256=manifest_sha,
            built_at=manifest.get("built_at", manifest.get("created_at", "Not recorded")),
        )
        if manifest.get("split") != "dev":
            result["errors"].append("Bundle split must be dev")
        if manifest.get("synthetic") is not False and not (allow_synthetic and synthetic):
            result["errors"].append("Live use requires synthetic=false")
        files = manifest.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError("Manifest files must be a nonempty mapping")
        stats = {}
        paths = {}
        for name, expected in files.items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe manifest path")
            path = (bundle / relative).resolve()
            if not path.is_relative_to(bundle):
                raise ValueError("Manifest symlink escapes bundle")
            stat = path.stat()
            if not path.is_file():
                raise ValueError("Manifest entry is not a file")
            stats[name] = dict(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
            paths[name] = path
            if stat.st_size != expected["bytes"]:
                result["errors"].append(f"Size mismatch: {name}")
        cache_dir = Path(cache_dir or ROOT / "outputs/bundle_verify")
        cache_path = cache_dir / (manifest_sha + ".json")
        cached = {}
        if cache_path.exists() and not rehash:
            try:
                cached = read(cache_path)
            except (ValueError, OSError):
                pass
        reused = (
            cached.get("bundle") == str(bundle)
            and cached.get("stats") == stats
            and cached.get("hashes_ok") is True
        )
        result["cache_reused"] = reused
        if not reused:
            for name, path in paths.items():
                if sha(path) != files[name]["sha256"]:
                    result["errors"].append(f"SHA256 mismatch: {name}")
        # Only cache successful file integrity. Metadata/pins are always checked again.
        if not result["errors"] and not reused:
            cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=cache_dir, delete=False) as stream:
                json.dump(dict(bundle=str(bundle), stats=stats, hashes_ok=True), stream)
            Path(stream.name).replace(cache_path)
        retrieval = read(bundle / "retrieval.json")
        serving = read(ROOT / "configs/serving.yaml")
        pins = serving.get("retrieval", read(ROOT / "configs/retrieval_v3.yaml"))
        result["pins_source"] = (
            "serving.yaml"
            if "retrieval" in serving
            else "retrieval_v3.yaml (serving.yaml has no model pins)"
        )
        for model, revision in [
            ("embedding_model", "embedding_revision"),
            ("reranker_model", "reranker_revision"),
        ]:
            result[model] = retrieval.get(model)
            if retrieval.get(model) != pins.get(model) or retrieval.get(revision) != pins.get(
                revision
            ):
                result["errors"].append(f"Pinned {model} / revision mismatch")
            snapshot = (
                bundle
                / "models/huggingface/hub"
                / ("models--" + str(retrieval.get(model)).replace("/", "--"))
                / "snapshots"
                / str(retrieval.get(revision))
            )
            if not (allow_synthetic and synthetic) and not snapshot.is_dir():
                result["errors"].append(f"Missing local snapshot: {model}")
        available = manifest.get("available_corpora")
        if available is None:
            available = [c for c in ("C0", "C1", "C2") if (bundle / "indexes" / c).is_dir()]
        result.update(
            available_corpora=available,
            missing_corpora=manifest.get(
                "missing_corpora", [c for c in ("C0", "C1", "C2") if c not in available]
            ),
            size_bytes=sum(s["size"] for s in stats.values()),
        )
        for corpus in available:
            if corpus not in ("C0", "C1", "C2") or not (bundle / "indexes" / corpus).is_dir():
                result["errors"].append(f"Missing corpus directory: {corpus}")
        result["ok"] = not result["errors"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["errors"].append(f"Bundle verification failed ({type(exc).__name__}): {exc}")
    return result


def prepare_bundle(cfg, bundle=None, *, allow_synthetic=False):
    bundle = Path(bundle or os.environ.get("BUNDLE_DIR", ROOT / "serving_bundle")).resolve()
    report = verify_bundle(bundle, allow_synthetic=allow_synthetic)
    if not report["ok"]:
        raise ValueError("; ".join(report["errors"]))
    if cfg.corpus not in report["available_corpora"]:
        raise ValueError(
            f"{cfg.corpus} isn't in this bundle; "
            f"available: {', '.join(report['available_corpora'])}"
        )
    os.environ.update(
        HF_HOME=str(bundle / "models/huggingface"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1"
    )
    return report
