#!/usr/bin/env python3
"""Download the two retrieval models into models/huggingface at their pinned revisions.

models/ is not in git (no model artifacts in the repo), but docker/api.Dockerfile copies it into
the image so the API never downloads at runtime. CI runs this before building; on a dev PC the
folder usually exists already.

    python scripts/fetch_models.py            # download what's missing
    python scripts/fetch_models.py --dry-run  # print what would be fetched
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/retrieval_v3.yaml"
CACHE = ROOT / "models/huggingface/hub"


def pinned():
    text = CONFIG.read_text(encoding="utf-8")
    try:
        config = json.loads(text)
    except json.JSONDecodeError:
        import yaml

        config = yaml.safe_load(text)
    return [
        (config["embedding_model"], config["embedding_revision"]),
        (config["reranker_model"], config["reranker_revision"]),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    models = pinned()
    if args.dry_run:
        print(json.dumps({"state": "DRY_RUN", "cache": str(CACHE), "models": models}))
        return
    from huggingface_hub import snapshot_download

    CACHE.mkdir(parents=True, exist_ok=True)
    for repo, revision in models:
        path = snapshot_download(repo, revision=revision, cache_dir=CACHE)
        print(json.dumps({"model": repo, "revision": revision, "path": path}))


if __name__ == "__main__":
    main()
