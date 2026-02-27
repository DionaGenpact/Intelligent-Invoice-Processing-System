from utils.run_manager import create_run_directory
from utils.audit_logger import log_step
from agents.intake_agent import run_intake
from agents.validation_agent import run_validation

def run_pipeline(bundle_path):
    run_id, run_path = create_run_directory()

    log_step(run_path, f"START RUN: {run_id}") 

    # Step 1: Intake
    context = run_intake(bundle_path, run_path)
    log_step(run_path, "Intake completed")

    # Step 2: Validation
    is_valid, validation = run_validation(bundle_path, run_path, context)
    log_step(run_path, f"Validation completed: {is_valid}")

    if not is_valid:
        log_step(run_path, "Pipeline stopped due to validation failure")
        return
        
    log_step(run_path, "Pipeline finished successfully")