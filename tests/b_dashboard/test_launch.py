"""Exercise real Streamlit sessions: health alone never executes the page script."""

import asyncio
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from tornado.websocket import websocket_connect

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src/bugzilla_serving/dashboard/app.py"
PAGES = {
    "Overview",
    "Answer eval",
    "Retrieval eval",
    "Cost & latency",
    "Error analysis",
    "Experiment Lab",
    "Compare runs",
    "Presets",
    "Production",
}


async def load_pages(port):
    connection = await websocket_connect(
        f"ws://127.0.0.1:{port}/_stcore/stream", subprotocols=["streamlit"]
    )
    try:

        async def run(page_hash=""):
            request = BackMsg()
            request.rerun_script.page_script_hash = page_hash
            await connection.write_message(request.SerializeToString(), binary=True)
            pages, headings = {}, []
            while True:
                raw = await asyncio.wait_for(connection.read_message(), timeout=5)
                assert raw is not None, "Streamlit closed the session before finishing"
                response = ForwardMsg.FromString(raw)
                kind = response.WhichOneof("type")
                if kind == "navigation":
                    pages = {p.page_name: p.page_script_hash for p in response.navigation.app_pages}
                elif kind == "delta" and response.delta.HasField("new_element"):
                    element = response.delta.new_element
                    assert not element.HasField("exception"), str(element.exception)
                    if element.HasField("heading"):
                        headings.append(element.heading.body)
                elif kind == "script_finished":
                    assert response.script_finished == ForwardMsg.FINISHED_SUCCESSFULLY
                    return pages, headings

        pages, headings = await run()
        assert set(pages) == PAGES, pages
        assert "Overview" in headings
        for title, page_hash in pages.items():
            _, headings = await run(page_hash)
            assert title in headings, (title, headings)
        return len(pages)
    finally:
        connection.close()


@pytest.mark.ui
@pytest.mark.parametrize("from_root", [True, False], ids=["repo-root", "foreign-cwd"])
def test_real_streamlit_launch(tmp_path, from_root):
    foreign = tmp_path / "partner's workspace"
    foreign.mkdir()
    cwd = ROOT if from_root else foreign
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(word in k for word in ("KEY", "PASSWORD", "TOKEN", "SECRET"))
    }
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        MLFLOW_TRACKING_URI=(tmp_path / "mlflow").as_uri(),
        MLFLOW_REGISTRY_URI=(tmp_path / "mlflow").as_uri(),
        LANGSMITH_SOURCE="fixture",
        DASHBOARD_LAB_ENABLED="true",
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    # A relative CLI path is essential: an absolute AppTest path masks the bug.
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        os.path.relpath(APP, cwd),
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--server.fileWatcherType",
        "none",
        "--browser.gatherUsageStats",
        "false",
    ]
    with (tmp_path / "streamlit.log").open("w+") as log:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 10
            while True:
                assert process.poll() is None, "Streamlit exited before becoming healthy"
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/_stcore/health", timeout=1
                    ) as response:
                        assert response.read() == b"ok"
                    break
                except (urllib.error.URLError, ConnectionError):
                    assert time.monotonic() < deadline, "Streamlit health check timed out"
                    time.sleep(0.05)
            assert asyncio.run(asyncio.wait_for(load_pages(port), timeout=12)) == 9
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            log.seek(0)
            output = log.read()
        assert "Uncaught app execution" not in output, output
        assert "StreamlitAPIException" not in output, output
