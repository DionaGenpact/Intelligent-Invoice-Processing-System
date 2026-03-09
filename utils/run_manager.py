import os
import shutil
from typing import Tuple

RUNS_DIR = "runs"


def _safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)
    cleaned = cleaned.strip("_") or "default_bundle"
    return cleaned.lower()


def create_run_directory(bundle_path: str) -> Tuple[str, str]:
    
    os.makedirs(RUNS_DIR, exist_ok=True)

    bundle_name = _safe_name(os.path.basename(os.path.normpath(bundle_path)))
    run_id = f"run_{bundle_name}"
    run_path = os.path.join(RUNS_DIR, run_id)

    if os.path.exists(run_path):
        shutil.rmtree(run_path)
    os.makedirs(run_path, exist_ok=True)

    return run_id, run_path
