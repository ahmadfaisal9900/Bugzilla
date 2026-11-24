"""Community Cloud entrypoint; install only the adjacent requirements.txt."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# The public dashboard always stays read-only, including after reruns.
os.environ["DASHBOARD_LAB_ENABLED"] = "false"
os.environ["DASHBOARD_ADVANCED"] = "false"

from bugzilla_serving.dashboard.cloud import main  # noqa: E402

main()
