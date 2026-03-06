from typing import Dict, Any, List


def run_decision(context: Dict[str, Any]) -> Dict[str, Any]:
    validation = context.get("validation_result", {})
    invoice_validation = context.get("invoice_validation_result", {})
    vendor_resolution = context.get("vendor_resolution_result", {})
    match_result = context.get("match_result", {})
    compliance_risk = context.get("compliance_risk_result", {})
    anomaly_result = context.get("anomaly_result", {})
    approval_packet = context.get("approval_packet", {})
    risk_flags = context.get("risk_flags", [])
    ignored_files = context.get("ignored_files", [])

    reasons: List[str] = []

    # Hard reject conditions
    if not validation.get("is_valid", False):
        return {
            "status": "REJECT",
            "reasons": ["VALIDATION_FAILED"],
            "risk_flags": risk_flags,
            "ignored_files_count": len(ignored_files)
        }

    if not invoice_validation.get("is_valid", True):
        return {
            "status": "REJECT",
            "reasons": ["INVOICE_VALIDATION_FAILED"],
            "risk_flags": risk_flags,
            "ignored_files_count": len(ignored_files)
        }

    # Approval packet can force decision
    packet_decision = str(approval_packet.get("decision", "")).upper()
    if packet_decision == "BLOCK":
        return {
            "status": "REJECT",
            "reasons": ["APPROVAL_PACKET_BLOCK"],
            "risk_flags": risk_flags,
            "ignored_files_count": len(ignored_files)
        }

    # Review conditions
    if risk_flags:
        reasons.append("RISK_FLAGS_PRESENT")

    if vendor_resolution.get("is_high_risk", False):
        reasons.append("HIGH_RISK_VENDOR")

    # Matching checks
    checks = match_result.get("checks", []) or []
    line_checks = match_result.get("line_item_checks", []) or []

    if any(isinstance(c, dict) and c.get("ok") is False for c in checks):
        reasons.append("MATCHING_CHECKS_FAILED")

    if any(isinstance(c, dict) and c.get("ok") is False for c in line_checks):
        reasons.append("LINE_ITEM_MATCH_FAILED")

    # Compliance findings
    compliance_findings = compliance_risk.get("findings", []) or []
    if any(str(f.get("severity", "")).upper() in ("HIGH", "CRITICAL") for f in compliance_findings):
        reasons.append("HIGH_COMPLIANCE_RISK")

    # Anomaly findings
    anomaly_findings = anomaly_result.get("findings", []) or []
    if any(str(f.get("severity", "")).upper() in ("HIGH", "CRITICAL") for f in anomaly_findings):
        reasons.append("HIGH_ANOMALY_RISK")

    # Approval packet route
    if packet_decision == "ROUTE":
        reasons.append("APPROVAL_REVIEW_REQUIRED")

    # Extraction confidence
    extraction = context.get("extraction_result", {})
    confidence_fields = extraction.get("confidence", {}).get("fields", {})
    total_conf = confidence_fields.get("total_amount", 1.0)
    invoice_conf = confidence_fields.get("invoice_number", 1.0)

    if total_conf < 0.8 or invoice_conf < 0.8:
        reasons.append("LOW_EXTRACTION_CONFIDENCE")

    # Normalization errors
    policy_result = context.get("policy_result", {})
    if policy_result.get("errors"):
        reasons.append("NORMALIZATION_ERRORS_PRESENT")

    if reasons:
        return {
            "status": "REVIEW",
            "reasons": reasons,
            "risk_flags": risk_flags,
            "ignored_files_count": len(ignored_files)
        }

    return {
        "status": "APPROVE",
        "reasons": ["ALL_CHECKS_PASSED"],
        "risk_flags": [],
        "ignored_files_count": len(ignored_files)
    }