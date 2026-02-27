import os
from datetime import datetime

RUNS_DIR = "runs"

def create_run_directory():
    if not os.path.exists(RUNS_DIR):
        os.makedirs(RUNS_DIR)
    
    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_path = os.path.join(RUNS_DIR, run_id)
    os.makedirs(run_path)

    return run_id, run_path
        