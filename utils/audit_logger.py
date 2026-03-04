import os
from datetime import datetime, timezone


def log_step(run_path: str, message: str) -> None:

    os.makedirs(run_path, exist_ok=True)
    log_file = os.path.join(run_path, "audit_log.md")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")