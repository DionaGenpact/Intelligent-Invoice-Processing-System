import os
import json
from datetime import datetime, timezone
from utils.run_manager import create_run_directory
from utils.audit_logger import log_step
from utils.schema_validator import validate_json
from agents.intake_agent import run_intake
from agents.validation_agent import run_validation
from agents.extraction_agent import run_extraction
from agents.normalization_agent import run_normalization

# Intern 3 scope: Agents E/F/G/H
from agents.matching_agent import run_matching
from agents.compliance_risk_agent import run_compliance_risk
from agents.anomaly_agent import run_anomaly_detection
from agents.exception_triage_agent import run_exception_triage

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

    # Even if validation fails, continue best-effort to produce downstream artifacts
    # so the run is still auditable end-to-end.

    # Step 3: Extraction
    extracted_data = run_extraction(bundle_path, run_path, context)

    extraction_schema_errors = validate_json(extracted_data, "schemas/extraction.schema.json")
    if extraction_schema_errors:
        for e in extraction_schema_errors:
            log_step(run_path, f"Extraction schema error: {e}")

    context["extracted_invoice"] = extracted_data

    # Step 4: Normalization
    is_normalized, norm_result = run_normalization(run_path, extracted_data)
    context["normalization_result"] = norm_result
    if not is_normalized:
        log_step(run_path, "Normalization failed; continuing best-effort to triage exceptions")

    # Step 5: Matching (Agent E)
    match_result = run_matching(bundle_path, run_path, context)
    context["match_result"] = match_result

    # Step 6: Compliance & Risk (Agent F)
    compliance = run_compliance_risk(bundle_path, run_path, context)
    context["compliance_findings"] = compliance

    # Step 7: Duplicate/Anomaly (Agent G)
    anomaly = run_anomaly_detection(bundle_path, run_path, context)
    context["anomaly_findings"] = anomaly

    # Step 8: Exception triage + approval packet (Agent H)
    approval_packet = run_exception_triage(bundle_path, run_path, context)
    context["approval_packet"] = approval_packet

    # Write a unified findings list aligned to findings.schema.json
    findings_list = _build_findings_list(run_path, context)
    with open(os.path.join(run_path, "findings.json"), "w", encoding="utf-8") as f:
        json.dump(findings_list, f, indent=2)

    findings_schema_errors = validate_json(findings_list, "schemas/findings.schema.json")
    if findings_schema_errors:
        for e in findings_schema_errors:
            log_step(run_path, f"Findings schema error: {e}")

    # Write final decision aligned to decision.schema.json
    decision_obj = _build_decision(run_id, approval_packet, compliance)
    with open(os.path.join(run_path, "decision.json"), "w", encoding="utf-8") as f:
        json.dump(decision_obj, f, indent=2)

    decision_schema_errors = validate_json(decision_obj, "schemas/decision.schema.json")
    if decision_schema_errors:
        for e in decision_schema_errors:
            log_step(run_path, f"Decision schema error: {e}")

    # Validate policy_result.json written by Agent F
    try:
        with open(os.path.join(run_path, "policy_result.json"), "r", encoding="utf-8") as f:
            policy_result = json.load(f)
        policy_schema_errors = validate_json(policy_result, "schemas/policy_result.schema.json")
        if policy_schema_errors:
            for e in policy_schema_errors:
                log_step(run_path, f"Policy result schema error: {e}")
    except Exception as e:
        log_step(run_path, f"Policy result read/validation error: {e}")

    # Rewrite context.json with latest state
    with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, "Pipeline finished (end-to-end artifacts written)")


def _impact_from_severity(sev: str) -> str:
    s = (sev or "").upper()
    if s in ("CRITICAL", "HIGH"):
        return "high"
    if s == "MEDIUM":
        return "medium"
    return "low"


def _build_findings_list(run_path: str, context: dict) -> list[dict]:
    """Normalize findings from Agents E/F/G (+ validation) to findings.schema.json."""
    out: list[dict] = []

    # Validation errors/warnings
    validation = context.get("validation_result") or {}
    for i, msg in enumerate(validation.get("errors") or []):
        out.append({
            "id": f"VAL-ERR-{i+1}",
            "agent": "D/validation",
            "type": "validation_error",
            "impact": "high",
            "confidence": 1.0,
            "summary": str(msg),
            "recommendation": "Fix manifest/bundle issues and re-run.",
            "evidence": ["validation.json"],
            "assumptions": [],
        })
    for i, msg in enumerate(validation.get("warnings") or []):
        out.append({
            "id": f"VAL-WARN-{i+1}",
            "agent": "D/validation",
            "type": "validation_warning",
            "impact": "low",
            "confidence": 1.0,
            "summary": str(msg),
            "recommendation": "Review warning and confirm if action is needed.",
            "evidence": ["validation.json"],
            "assumptions": [],
        })

    # Matching failures
    match_result = context.get("match_result") or {}
    for i, chk in enumerate(match_result.get("checks") or []):
        if isinstance(chk, dict) and chk.get("ok") is False:
            out.append({
                "id": f"MATCH-{i+1}",
                "agent": "E/matching",
                "type": "matching_check_failed",
                "impact": "medium",
                "confidence": 0.9,
                "summary": chk.get("reason") or chk.get("check") or "Matching check failed",
                "recommendation": "Review PO/GRN matching inputs and tolerances.",
                "evidence": ["match_result.json"],
                "assumptions": [],
            })

    # Compliance findings
    compliance = context.get("compliance_findings") or {}
    for i, f in enumerate(compliance.get("findings") or []):
        out.append({
            "id": f"COMP-{i+1}",
            "agent": "F/compliance",
            "type": str(f.get("code") or "compliance"),
            "impact": _impact_from_severity(str(f.get("severity"))),
            "confidence": 0.85,
            "summary": str(f.get("message") or "Compliance finding"),
            "recommendation": str(f.get("recommendation") or "Route for manual review."),
            "evidence": ["compliance_findings.json"],
            "assumptions": [],
        })

    # Anomaly findings
    anomaly = context.get("anomaly_findings") or {}
    for i, f in enumerate(anomaly.get("findings") or []):
        out.append({
            "id": f"RISK-{i+1}",
            "agent": "G/anomaly",
            "type": str(f.get("code") or "anomaly"),
            "impact": _impact_from_severity(str(f.get("severity"))),
            "confidence": 0.75,
            "summary": str(f.get("message") or "Risk/anomaly finding"),
            "recommendation": str(f.get("recommendation") or "Route for investigation."),
            "evidence": ["anomaly_findings.json"],
            "assumptions": [],
        })

    return out


def _build_decision(run_id: str, approval_packet: dict, compliance: dict) -> dict:
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    risk_level = None
    try:
        risk_level = (compliance.get("risk") or {}).get("level")
    except Exception:
        risk_level = None

    decision = approval_packet.get("decision")
    route_to = approval_packet.get("route_to")
    follow_up = approval_packet.get("follow_up") or []
    summary = approval_packet.get("summary") or {}
    artifacts = [
        "context.json",
        "validation.json",
        "extracted_invoice.json",
        "normalization.json",
        "match_result.json",
        "compliance_findings.json",
        "policy_result.json",
        "anomaly_findings.json",
        "approval_packet.json",
        "exceptions.md",
        "findings.json",
        "decision.json",
        "audit_log.md",
    ]

    return {
        "run_id": run_id,
        "created_at": created_at,
        "decision": decision,
        "route_to": route_to,
        "risk_level": (str(risk_level).upper() if risk_level else None),
        "reasons": [str(x) for x in follow_up],
        "summary": {
            "total_exceptions": int(summary.get("total", 0)) if isinstance(summary, dict) else 0,
            "by_severity": (summary.get("by_severity") if isinstance(summary, dict) else {}),
            "by_category": (summary.get("by_category") if isinstance(summary, dict) else {}),
        },
        "artifacts": artifacts,
    }
