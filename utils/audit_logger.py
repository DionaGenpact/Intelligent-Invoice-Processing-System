import os 
from datetime import datetime

def log_step(run_path, message):
    log_file = os.path.join(run_path, "audit_log.md")
    timestamp = datetime.now().strftime("run_%Y%m%d_%H%M%S")

    with open(log_file, "a") as f:
        f.write(f"[{timestamp}] {message}\n")