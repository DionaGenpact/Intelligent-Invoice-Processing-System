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
from agents.vendor_resolution_agent import run_vendor_resolution
from agents.matching_agent import run_matching
from agents.compliance_risk_agent import run_compliance_risk
from agents.anomaly_agent import run_anomaly_detection
from agents.exception_triage_agent import run_exception_triage
from agents.decision_agent import run_decision


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def _write_context(run_path, context):
    _write_json(os.path.join(run_path, "context.json"), context)


def _log_schema_errors(run_path, label, errors):
    for e in errors:
        log_step(run_path, f"{label} schema error: {e}")


def run_pipeline(bundle_path):
    start_ts = time.time()
    run_id, run_path = create_run_directory()
    log_step(run_path, f"START RUN: {run_id}")

    # Step 1: Intake (Agent A)
    context = run_intake(bundle_path, run_path)

    context_schema_errors = validate_json(context, "schemas/context.schema.json")
    if context_schema_errors:
        _log_schema_errors(run_path, "Context", context_schema_errors)
        log_step(run_path, "Pipeline stopped due to context schema validation failure")
        return

    log_step(run_path, "Intake + context schema validation passed")

    # Step 2: Validation
    is_valid, validation_result = run_validation(bundle_path, run_path, context)

    validation_schema_errors = validate_json(validation_result, "schemas/validation.schema.json")
    if validation_schema_errors:
        _log_schema_errors(run_path, "Validation", validation_schema_errors)
        log_step(run_path, "Pipeline stopped due to validation schema failure")
        return

    context["validation_result"] = validation_result
    _write_context(run_path, context)

    if not is_valid:
        log_step(run_path, "Pipeline stopped due to validation failure")
        return

    # Step 3: Extraction (Agent B)
    extracted_data = run_extraction(bundle_path, run_path, context)
    context["extraction_result"] = extracted_data
    _write_context(run_path, context)

    # Step 4: Normalization
    is_normalized, normalization_result = run_normalization(run_path, extracted_data)

    normalization_schema_errors = validate_json(normalization_result, "schemas/normalization.schema.json")
    if normalization_schema_errors:
        _log_schema_errors(run_path, "Normalization", normalization_schema_errors)
        log_step(run_path, "Pipeline stopped due to normalization schema failure")
        return

    context["normalization_result"] = normalization_result
    _write_context(run_path, context)

    if not is_normalized:
        log_step(run_path, "Pipeline stopped due to normalization failure")
        return

    # Step 5: Invoice Validation (Agent D)
    is_invoice_valid, invoice_validation_result = run_invoice_validation(bundle_path, run_path, context)
    context["invoice_validation_result"] = invoice_validation_result
    _write_context(run_path, context)

    if not is_invoice_valid:
        log_step(run_path, "Pipeline stopped due to invoice validation failure")
        return

    # Step 6: Vendor Resolution (Agent C)
    vendor_resolution_result = run_vendor_resolution(bundle_path, run_path, context)
    context["vendor_resolution_result"] = vendor_resolution_result

    if vendor_resolution_result.get("is_high_risk", False):
        context.setdefault("risk_flags", []).append("HIGH_RISK_VENDOR")

    for flag in vendor_resolution_result.get("flags", []):
        context.setdefault("risk_flags", []).append(flag)

    _write_context(run_path, context)

    # Step 7: Matching (Agent E)
    match_result = run_matching(bundle_path, run_path, context)
    context["match_result"] = match_result
    _write_context(run_path, context)

    # Step 8: Compliance & Risk (Agent F)
    compliance_risk_result = run_compliance_risk(bundle_path, run_path, context)
    context["compliance_risk_result"] = compliance_risk_result
    _write_context(run_path, context)

    # Step 9: Anomaly Detection (Agent G)
    anomaly_result = run_anomaly_detection(bundle_path, run_path, context)
    context["anomaly_result"] = anomaly_result
    _write_context(run_path, context)

    # Step 10: Exception Triage (Agent H)
    approval_packet = run_exception_triage(bundle_path, run_path, context)
    context["approval_packet"] = approval_packet
    _write_context(run_path, context)

    # Step 11: Decision (Agent I)
    decision_result = run_decision(context)

    decision_schema_errors = validate_json(decision_result, "schemas/decision.schema.json")
    if decision_schema_errors:
        _log_schema_errors(run_path, "Decision", decision_schema_errors)
        log_step(run_path, "Pipeline stopped due to decision schema failure")
        return

    context["decision_result"] = decision_result
    _write_json(os.path.join(run_path, "decision.json"), decision_result)
    _write_context(run_path, context)

    log_step(run_path, f"Decision: {decision_result['status']} | reasons={decision_result['reasons']}")

    # Step 12: Metrics
    duration = round(time.time() - start_ts, 3)
    metrics = {
        "run_id": run_id,
        "bundle_path": bundle_path,
        "duration_seconds": duration,
        "validation_passed": context.get("validation_result", {}).get("is_valid", False),
        "invoice_validation_passed": context.get("invoice_validation_result", {}).get("is_valid", True),
        "risk_flags_count": len(context.get("risk_flags", [])),
        "vendor_high_risk": context.get("vendor_resolution_result", {}).get("is_high_risk", False),
        "decision": decision_result.get("status", "UNKNOWN")
    }

    _write_json(os.path.join(run_path, "metrics.json"), metrics)

    log_step(run_path, f"Metrics written: duration_seconds={duration}")
    log_step(run_path, "Pipeline finished successfully")