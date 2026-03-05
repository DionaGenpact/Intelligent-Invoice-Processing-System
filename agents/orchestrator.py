import os
import json
import time

from utils.run_manager import create_run_directory
from utils.audit_logger import log_step
from utils.schema_validator import validate_json
from agents.intake_agent import run_intake
from agents.validation_agent import run_validation
from agents.extraction_agent import run_extraction
from agents.normalization_agent import run_normalization
from agents.invoice_validation_agent import run_invoice_validation


def make_decision(context: dict) -> dict:
    validation = context.get("validation_result", {})
    risk_flags = context.get("risk_flags", [])
    ignored_files = context.get("ignored_files", [])

    if not validation.get("is_valid", False):
        return {
            "status": "REJECT",
            "reasons": ["VALIDATION_FAILED"],
            "risk_flags": risk_flags,
            "ignored_files_count": len(ignored_files)
        }

    if risk_flags:
        return {
            "status": "REVIEW",
            "reasons": ["RISK_FLAGS_PRESENT"],
            "risk_flags": risk_flags,
            "ignored_files_count": len(ignored_files)
        }

    return {
        "status": "APPROVE",
        "reasons": ["VALIDATION_PASSED_NO_RISKS"],
        "risk_flags": [],
        "ignored_files_count": len(ignored_files)
    }


def run_pipeline(bundle_path):
    start_ts = time.time()
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

    context["validation_result"] = validation

    with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, f"Validation completed: {is_valid}")

    if not is_valid:
        log_step(run_path, "Pipeline stopped due to validation failure")
        return

    # Step 3: Extraction
    log_step(run_path, "Extraction started")
    extracted_data = run_extraction(bundle_path, run_path, context)
    context["extraction_result"] = extracted_data

    with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, "Extraction completed")

    # Step 4: Normalization
    log_step(run_path, "Normalization started")
    is_normalized, norm_result = run_normalization(run_path, extracted_data)

    if not is_normalized:
        log_step(run_path, "Pipeline stopped due to normalization failure")
        return

    context["policy_result"] = norm_result
    with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, "Normalization completed")

    # Step 4b: Invoice Validation (Agent D)
    log_step(run_path, "Invoice Validation (Agent D) started")
    is_invoice_valid, invoice_validation_result = run_invoice_validation(run_path, context)

    context["invoice_validation_result"] = invoice_validation_result

    with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    if not is_invoice_valid:
        log_step(run_path, "Pipeline stopped due to invoice validation failure")
        return

    log_step(run_path, "Invoice Validation completed")

    # Step 5: Decision (Agent I)
    decision = make_decision(context)

    decision_schema_errors = validate_json(decision, "schemas/decision.schema.json")
    if decision_schema_errors:
        for e in decision_schema_errors:
            log_step(run_path, f"Decision schema error: {e}")
        log_step(run_path, "Pipeline stopped due to decision schema failure")
        return

    context["decision_result"] = decision

    with open(os.path.join(run_path, "decision.json"), "w", encoding="utf-8") as f:
        json.dump(decision, f, indent=4)

    with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, f"Decision: {decision['status']} | reasons={decision['reasons']}")

    # Metrics
    duration = round(time.time() - start_ts, 3)
    metrics = {
        "run_id": run_id,
        "bundle_path": bundle_path,
        "duration_seconds": duration,
        "validation_passed": context.get("validation_result", {}).get("is_valid", False),
        "risk_flags_count": len(context.get("risk_flags", [])),
        "decision": decision.get("status", "UNKNOWN")
    }

    with open(os.path.join(run_path, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=4)

    log_step(run_path, f"Metrics written: duration_seconds={duration}")
    log_step(run_path, "Pipeline finished successfully")