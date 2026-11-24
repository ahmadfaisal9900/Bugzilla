"""Validate and cache serving bundles, open their databases read only, and list examples."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

_CACHE = {}


def listed_path(root, manifest, name):
    name = str(name).replace("\\", "/")
    path = (root / name).resolve()
    if not path.is_relative_to(root) or name not in manifest["files"]:
        raise ValueError("bundle: path must be inside the bundle and manifest-listed")
    return path


class Bundle:
    def __init__(self, root):
        import duckdb

        from .engine import _bundle

        self.root = root
        self.manifest = _bundle(root)
        self._temp = None
        self.db = None
        if self.manifest.get("schema_version") != "phase0-v1":
            raise ValueError("bundle: unsupported schema version")
        if not self.manifest.get("synthetic") and any(
            "test" in name.lower() or "gold" in name.lower() for name in self.manifest["files"]
        ):
            raise ValueError("bundle: test or gold file refused")
        runtime_path = listed_path(root, self.manifest, self.manifest["runtime_config"])
        self.runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        for key in ("source_config", "retrieval_config", "selection", "history_checkpoint"):
            listed_path(root, self.manifest, self.runtime[key])
        source = json.loads((root / self.runtime["source_config"]).read_text(encoding="utf-8"))
        selection = json.loads((root / self.runtime["selection"]).read_text(encoding="utf-8"))
        if selection.get("test_used"):
            raise ValueError("bundle: test selection refused")
        index = selection["index_build"].replace("\\", "/")
        listed_path(root, self.manifest, index + "/manifest.json")
        for name in self.manifest["files"]:
            if name.startswith(index + "/") and name.endswith("manifest.json"):
                metadata = json.loads((root / name).read_text(encoding="utf-8"))
                for entry in metadata.get("sha256", {}):
                    listed_path(root, self.manifest, str(Path(name).parent / entry))
        examples_path = listed_path(root, self.manifest, self.manifest["dev_questions"])
        self._examples = []
        for line in examples_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if self.manifest.get("synthetic"):
                if row.get("split") != "dev":
                    raise ValueError("bundle: non-dev question refused")
                text = row["question"]
            else:
                if set(row) != {"text"}:
                    raise ValueError("bundle: examples must contain text only")
                text = row["text"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("bundle: empty example")
            self._examples.append(text)
        if self.manifest.get("synthetic"):
            sql = listed_path(root, self.manifest, "canonical.sql")
            self._temp = tempfile.TemporaryDirectory(prefix="bugzilla-bundle-")
            self.db_path = Path(self._temp.name) / "canonical.duckdb"
            with duckdb.connect(str(self.db_path)) as db:
                db.execute(sql.read_text(encoding="utf-8"))
        else:
            self.db_path = listed_path(root, self.manifest, source["canonical_db"])
            for key in ("canonical_db", "history_db"):
                if source.get(key):
                    listed_path(root, self.manifest, source[key])
        self.db = duckdb.connect(str(self.db_path), read_only=True)

    def examples(self):
        return list(self._examples)

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self._temp:
            self._temp.cleanup()
            self._temp = None
        _CACHE.pop(self.root, None)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def load_bundle(path):
    root = Path(path).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    paths = [root / "manifest.json"]
    paths.extend(listed_path(root, manifest, name) for name in manifest["files"])
    signature = tuple((p.stat().st_size, p.stat().st_mtime_ns) for p in paths)
    cached = _CACHE.get(root)
    if cached and cached[0] == signature and cached[1].db is not None:
        return cached[1]
    if cached:
        cached[1].close()
    bundle = Bundle(root)
    _CACHE[root] = (signature, bundle)
    return bundle
