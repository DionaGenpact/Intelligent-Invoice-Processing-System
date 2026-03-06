from typing import Dict, Any, List


def run_decision(context: Dict[str, Any]) -> Dict[str, Any]:
    validation = context.get("validation_result", {}) or {}
    invoice_validation = context.get("invoice_validation_result", {}) or {}
    vendor_resolution = context.get("vendor_resolution_result", {}) or {}
    match_result = context.get("match_result", {}) or {}
    compliance_risk = context.get("compliance_risk_result", {}) or {}
    anomaly_result = context.get("anomaly_result", {}) or {}
    approval_packet = context.get("approval_packet", {}) or {}
    extraction = context.get("extraction_result", {}) or {}
    normalization_result = context.get("normalization_result", {}) or {}

    risk_flags = context.get("risk_flags", []) or []
    ignored_files = context.get("ignored_files", []) or []

    reasons: List[str] = []

    def add_reason(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

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
        add_reason("RISK_FLAGS_PRESENT")

    if vendor_resolution.get("is_high_risk", False):
        add_reason("HIGH_RISK_VENDOR")

    # Matching checks
    checks = match_result.get("checks", []) or []
    line_checks = match_result.get("line_item_checks", []) or []

    if any(isinstance(c, dict) and c.get("ok") is False for c in checks):
        add_reason("MATCHING_CHECKS_FAILED")

    if any(isinstance(c, dict) and c.get("ok") is False for c in line_checks):
        add_reason("LINE_ITEM_MATCH_FAILED")

    # Compliance overall risk level
    compliance_level = str(
        compliance_risk.get("risk_level", compliance_risk.get("risk", ""))
    ).upper()
    if compliance_level in ("HIGH", "CRITICAL"):
        add_reason("HIGH_COMPLIANCE_RISK")

    # Anomaly findings
    anomaly_findings = anomaly_result.get("findings", []) or []
    if any(
        isinstance(f, dict) and str(f.get("severity", "")).upper() in ("HIGH", "CRITICAL")
        for f in anomaly_findings
    ):
        add_reason("HIGH_ANOMALY_RISK")

    # Approval packet route
    if packet_decision == "ROUTE":
        add_reason("APPROVAL_REVIEW_REQUIRED")

    # Extraction confidence
    confidence_fields = extraction.get("confidence", {}).get("fields", {}) or {}
    total_conf = float(confidence_fields.get("total_amount", 1.0) or 1.0)
    invoice_conf = float(confidence_fields.get("invoice_number", 1.0) or 1.0)

    if total_conf < 0.8 or invoice_conf < 0.8:
        add_reason("LOW_EXTRACTION_CONFIDENCE")

    # Normalization errors
    if normalization_result.get("errors"):
        add_reason("NORMALIZATION_ERRORS_PRESENT")

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