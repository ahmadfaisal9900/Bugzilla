"""Opt-in wall timings; labels never include arguments or credentials."""

import functools
import json
import os
import sys
import threading
import time
from contextlib import contextmanager

_LOCK = threading.Lock()
_EVENTS = []
_REQUEST_LIMIT = None
_REQUESTS = 0


def active():
    return os.environ.get("DASHBOARD_PROFILE") == "1"


@contextmanager
def timing(label):
    start = time.perf_counter()
    try:
        yield
    finally:
        if active():
            row = {"call": label, "seconds": round(time.perf_counter() - start, 6)}
            with _LOCK:
                _EVENTS.append(row)
            print("DASHBOARD_PROFILE " + json.dumps(row), file=sys.stderr, flush=True)


def measured(label):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            with timing(label):
                return fn(*args, **kwargs)

        return wrapped

    return decorate


def events():
    with _LOCK:
        return list(_EVENTS)


def page(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        offset = len(events())
        with timing("page." + fn.__name__):
            result = fn(*args, **kwargs)
        if active():
            import streamlit as st

            with st.sidebar.expander("Render timings", expanded=True):
                st.dataframe(events()[offset:], hide_index=True)
        return result

    return wrapped


class TimedClient:
    """Time SDK calls, consuming paginated iterators inside the timing scope."""

    def __init__(self, client, source):
        self.client, self.source = client, source

    def __getattr__(self, key):
        value = getattr(self.client, key)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            global _REQUESTS
            with _LOCK:
                if _REQUEST_LIMIT is not None and _REQUESTS >= _REQUEST_LIMIT:
                    raise RuntimeError(
                        "Dashboard request cap reached; rerun to resume artifact checkpoints"
                    )
                _REQUESTS += 1
            with timing(self.source + "." + key):
                result = value(*args, **kwargs)
                if key in ("list_runs", "list_feedback"):
                    return list(result)
                return result

        return call


def request_budget(limit=None):
    global _REQUEST_LIMIT, _REQUESTS
    if limit is not None and limit < 1:
        raise ValueError("max-requests must be positive")
    _REQUEST_LIMIT, _REQUESTS = limit, 0
