import json
import os
import time
from typing import Any, Dict

from utils.audit_logger import log_step
from utils.run_manager import create_run_directory
from utils.schema_validator import validate_json

from agents.anomaly_agent import run_anomaly_detection
from agents.compliance_risk_agent import run_compliance_risk
from agents.decision_agent import run_decision
from agents.exception_triage_agent import run_exception_triage
from agents.extraction_agent import run_extraction
from agents.intake_agent import run_intake
from agents.invoice_validation_agent import run_invoice_validation
from agents.matching_agent import run_matching
from agents.normalization_agent import run_normalization
from agents.posting_payload_agent import run_posting_payload
from agents.validation_agent import run_validation
from agents.vendor_resolution_agent import run_vendor_resolution


def _write_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)



def _write_context(run_path: str, context: Dict[str, Any]) -> None:
    _write_json(os.path.join(run_path, "context.json"), context)



def _log_schema_errors(run_path: str, label: str, errors: list[str]) -> None:
    for error in errors:
        log_step(run_path, f"{label} schema error: {error}")



def run_pipeline(bundle_path: str) -> str:
    start_ts = time.time()
    run_id, run_path = create_run_directory(bundle_path)
    log_step(run_path, f"START RUN: {run_id}")

    context = run_intake(bundle_path, run_path)
    context_schema_errors = validate_json(context, "schemas/context.schema.json")
    if context_schema_errors:
        _log_schema_errors(run_path, "Context", context_schema_errors)
        log_step(run_path, "Pipeline stopped due to context schema validation failure")
        return run_path
    log_step(run_path, "Intake + context schema validation passed")

    is_valid, validation_result = run_validation(bundle_path, run_path, context)
    validation_schema_errors = validate_json(validation_result, "schemas/validation.schema.json")
    if validation_schema_errors:
        _log_schema_errors(run_path, "Validation", validation_schema_errors)
        log_step(run_path, "Pipeline stopped due to validation schema failure")
        return run_path
    context["validation_result"] = validation_result
    _write_context(run_path, context)
    if not is_valid:
        log_step(run_path, "Pipeline stopped due to validation failure")
        return run_path

    extracted_data = run_extraction(bundle_path, run_path, context)
    context["extraction_result"] = extracted_data
    _write_context(run_path, context)

    is_normalized, normalization_result = run_normalization(run_path, extracted_data)
    normalization_schema_errors = validate_json(normalization_result, "schemas/normalization.schema.json")
    if normalization_schema_errors:
        _log_schema_errors(run_path, "Normalization", normalization_schema_errors)
        log_step(run_path, "Pipeline stopped due to normalization schema failure")
        return run_path
    context["normalization_result"] = normalization_result
    _write_context(run_path, context)
    if not is_normalized:
        log_step(run_path, "Pipeline stopped due to normalization failure")
        return run_path

    is_invoice_valid, invoice_validation_result = run_invoice_validation(bundle_path, run_path, context)
    context["invoice_validation_result"] = invoice_validation_result
    _write_context(run_path, context)
    if not is_invoice_valid:
        log_step(run_path, "Pipeline stopped due to invoice validation failure")
        return run_path

    vendor_resolution_result = run_vendor_resolution(bundle_path, run_path, context)
    context["vendor_resolution_result"] = vendor_resolution_result
    if vendor_resolution_result.get("is_high_risk", False):
        context.setdefault("risk_flags", []).append("HIGH_RISK_VENDOR")
    for flag in vendor_resolution_result.get("flags", []):
        if flag not in context.setdefault("risk_flags", []):
            context["risk_flags"].append(flag)
    _write_context(run_path, context)

    match_result = run_matching(bundle_path, run_path, context)
    context["match_result"] = match_result
    _write_context(run_path, context)

    compliance_risk_result = run_compliance_risk(bundle_path, run_path, context)
    context["compliance_risk_result"] = compliance_risk_result
    _write_context(run_path, context)

    anomaly_result = run_anomaly_detection(bundle_path, run_path, context)
    context["anomaly_result"] = anomaly_result
    _write_context(run_path, context)

    approval_packet = run_exception_triage(bundle_path, run_path, context)
    context["approval_packet"] = approval_packet
    _write_context(run_path, context)

    decision_result = run_decision(context)
    decision_schema_errors = validate_json(decision_result, "schemas/decision.schema.json")
    if decision_schema_errors:
        _log_schema_errors(run_path, "Decision", decision_schema_errors)
        log_step(run_path, "Pipeline stopped due to decision schema failure")
        return run_path
    context["decision_result"] = decision_result
    _write_json(os.path.join(run_path, "decision.json"), decision_result)

    posting_payload = run_posting_payload(run_path, context)
    posting_schema_errors = validate_json(posting_payload, "schemas/posting_payload.schema.json")
    if posting_schema_errors:
        _log_schema_errors(run_path, "Posting payload", posting_schema_errors)
        log_step(run_path, "Pipeline stopped due to posting payload schema failure")
        return run_path
    context["posting_payload"] = posting_payload
    _write_context(run_path, context)

    log_step(run_path, f"Decision: {decision_result['status']} | reasons={decision_result['reasons']}")

    duration = round(time.time() - start_ts, 3)
    extraction_fields = context.get("extraction_result", {}).get("confidence", {}).get("fields", {}) or {}
    avg_extraction_confidence = round(sum(extraction_fields.values()) / len(extraction_fields), 4) if extraction_fields else 0.0
    invoice_count = 1
    exception_total = context.get("approval_packet", {}).get("summary", {}).get("total", 0)
    anomaly_findings = context.get("anomaly_result", {}).get("findings", []) or []
    compliance_findings = context.get("compliance_risk_result", {}).get("findings", []) or []

    metrics = {
        "run_id": run_id,
        "bundle_path": bundle_path,
        "throughput": {
            "invoice_count": invoice_count,
            "duration_seconds": duration,
            "invoices_per_second": round(invoice_count / duration, 4) if duration else 0.0,
        },
        "validation_passed": context.get("validation_result", {}).get("is_valid", False),
        "invoice_validation_passed": context.get("invoice_validation_result", {}).get("is_valid", True),
        "risk_flags_count": len(context.get("risk_flags", [])),
        "vendor_high_risk": context.get("vendor_resolution_result", {}).get("is_high_risk", False),
        "extraction_confidence": {
            "average_field_confidence": avg_extraction_confidence,
            "fields": extraction_fields,
        },
        "exceptions": {
            "count": exception_total,
            "rate": round(exception_total / invoice_count, 4),
            "compliance_findings": len(compliance_findings),
            "anomaly_findings": len(anomaly_findings),
        },
        "decision": decision_result.get("status", "UNKNOWN"),
    }
    _write_json(os.path.join(run_path, "metrics.json"), metrics)

    log_step(run_path, f"Metrics written: duration_seconds={duration}")
    log_step(run_path, "Pipeline finished successfully")
    return run_path
