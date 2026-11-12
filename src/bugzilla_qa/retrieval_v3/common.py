"""Small shared IO helpers; configuration contains no credentials."""
import datetime
import fcntl
import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from bugzilla_qa.benchmark.v3_source import file_hash, read_jsonl, write_json, write_jsonl
from bugzilla_qa.llm.provider import digest, read_config

ROOT = Path(__file__).resolve().parents[3]


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def git_commit():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def code_hashes():
    paths = sorted(Path(__file__).parent.glob('*.py'))
    paths += [ROOT/'src/bugzilla_qa/eval_extension'/p for p in ('retrieval.py', 'dense.py', 'cli.py')]
    return {str(p.relative_to(ROOT)): file_hash(p) for p in paths}


def verify_artifacts(directory, manifest):
    for name, sha in manifest['sha256'].items():
        path = Path(directory)/name
        if not path.resolve().is_relative_to(Path(directory).resolve()):
            raise RuntimeError('Unsafe manifest path')
        if not path.is_file() or file_hash(path) != sha:
            raise RuntimeError('Artifact hash mismatch: '+str(path))


def receipt(directory, **fields):
    directory = Path(directory)
    files = sorted(p for p in directory.rglob('*') if p.is_file()
                   and p != directory/'manifest.json' and p.name != '.lock'
                   and not p.name.endswith(('.tmp', '-wal', '-shm')))
    result = dict(fields, created_at_utc=now(), git_commit=git_commit(),
                  sha256={str(p.relative_to(directory)): file_hash(p) for p in files})
    write_json(directory/'manifest.json', result)
    return result


@contextmanager
def locked(directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    with (directory/'.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another process is using this run') from None
        yield


def append(path, value):
    with Path(path).open('a', encoding='utf-8') as f:
        f.write(json.dumps(value, sort_keys=True)+'\n'); f.flush(); os.fsync(f.fileno())


def checkpoint(path):
    """Recover only an interrupted final append; never discard a committed row."""
    path = Path(path)
    if not path.exists(): return []
    data = path.read_bytes()
    if data and not data.endswith(b'\n'):
        prefix, _, tail = data.rpartition(b'\n')
        backup = path.with_name(path.name+'.interrupted-'+digest(data.hex())[:12])
        if not backup.exists(): backup.write_bytes(tail)
        path.write_bytes(prefix+b'\n' if prefix else b'')
    return list(read_jsonl(path))
