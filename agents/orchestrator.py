from utils.run_manager import create_run_directory
from utils.audit_logger import log_step
from utils.schema_validator import validate_json
from agents.intake_agent import run_intake
from agents.validation_agent import run_validation
import os
import json


def run_pipeline(bundle_path):
    run_id, run_path = create_run_directory()
    log_step(run_path, f"START RUN: {run_id}")

    # Step 1: Intake
    context = run_intake(bundle_path, run_path)

    schema_errors = validate_json(context, "schemas/context.schema.json")
    if schema_errors:
        for e in schema_errors:
            log_step(run_path, f"Context schema error: {e}")
        log_step(run_path, "Pipeline stopped due to context schema validation failure")
        return

    log_step(run_path, "Intake + context schema validation passed")

    # Step 2: Validation
    is_valid, validation = run_validation(bundle_path, run_path, context)

    validation_schema_errors = validate_json(validation, "schemas/validation.schema.json")
    if validation_schema_errors:
        for e in validation_schema_errors:
            log_step(run_path, f"Validation schema error: {e}")
        log_step(run_path, "Pipeline stopped due to validation schema failure")
        return

    # Persist validation into context (shared state)
    context["validation_result"] = validation

    # Rewrite context.json with latest state
    with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, f"Validation completed: {is_valid}")

    if not is_valid:
        log_step(run_path, "Pipeline stopped due to validation failure")
        return

    log_step(run_path, "Pipeline finished successfully")