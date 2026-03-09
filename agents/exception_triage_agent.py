from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import yaml

from utils.audit_logger import log_step



def run_exception_triage(bundle_path: str, run_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    log_step(run_path, "Exception Triage (H) started")

    compliance = _load_json(os.path.join(run_path, "compliance_findings.json")) or context.get("compliance_risk_result") or {}
    anomaly = _load_json(os.path.join(run_path, "anomaly_findings.json")) or context.get("anomaly_result") or {}
    matching = _load_json(os.path.join(run_path, "match_result.json")) or context.get("match_result") or {}
    validation = _load_json(os.path.join(run_path, "validation.json")) or context.get("validation_result") or {}
    invoice_validation = _load_json(os.path.join(run_path, "invoice_validation.json")) or context.get("invoice_validation_result") or {}
    approval_policy = _load_yaml("policies/approval_policy.yaml") or {}

    routing_rules = approval_policy.get("routing_rules", {})
    auto_post = approval_policy.get("auto_post_conditions", {})

    exceptions: List[Dict[str, Any]] = []

    for item in compliance.get("findings", []) or []:
        if isinstance(item, dict):
            exceptions.append(_normalize_exception("COMPLIANCE", "compliance", item))

    for item in anomaly.get("findings", []) or []:
        if isinstance(item, dict):
            exceptions.append(_normalize_exception("ANOMALY", "anomaly", item))

    for check in matching.get("checks", []) or []:
        if isinstance(check, dict) and check.get("ok") is False:
            exceptions.append({
                "category": "MATCHING",
                "source": "matching",
                "code": check.get("check", "MATCH_CHECK_FAILED"),
                "severity": "MEDIUM",
                "message": check.get("reason") or "Matching totals check failed.",
                "recommendation": "Review PO/GRN references and tolerance rules.",
                "evidence": check,
            })

    for check in matching.get("line_item_checks", []) or []:
        if isinstance(check, dict) and check.get("ok") is False:
            exceptions.append({
                "category": "MATCHING",
                "source": "matching",
                "code": check.get("check") or f"LINE_{check.get('line', 'UNKNOWN')}_MISMATCH",
                "severity": "MEDIUM",
                "message": check.get("reason") or "Line item matching check failed.",
                "recommendation": "Review PO/GRN line alignment and tolerances.",
                "evidence": check,
            })

    for error in validation.get("errors", []) or []:
        exceptions.append({
            "category": "VALIDATION",
            "source": "validation",
            "code": "BUNDLE_VALIDATION_ERROR",
            "severity": "HIGH",
            "message": error,
            "recommendation": "Correct bundle structure before reprocessing.",
            "evidence": {"error": error},
        })

    for error in invoice_validation.get("errors", []) or []:
        exceptions.append({
            "category": "VALIDATION",
            "source": "invoice_validation",
            "code": "INVOICE_VALIDATION_ERROR",
            "severity": "HIGH",
            "message": error,
            "recommendation": "Fix invoice totals or mandatory invoice fields.",
            "evidence": {"error": error},
        })

    decision, route_to, follow_up = _decide(exceptions, compliance, routing_rules, auto_post)
    packet = {
        "decision": decision,
        "route_to": route_to,
        "follow_up": follow_up,
        "summary": _summary(exceptions),
        "exceptions": exceptions,
        "evidence_files": [
            "validation.json",
            "invoice_validation.json",
            "match_result.json",
            "compliance_findings.json",
            "anomaly_findings.json",
            "audit_log.md",
        ],
    }

    _write_json(run_path, "approval_packet.json", packet)
    _write_md(run_path, "exceptions.md", _format_md(packet))
    log_step(run_path, f"Exception Triage (H) completed (decision={decision}, route={route_to})")
    return packet


def _normalize_exception(category: str, source: str, item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "category": category,
        "source": source,
        "code": item.get("code", f"{category}_ISSUE"),
        "severity": str(item.get("severity", "MEDIUM")).upper(),
        "message": item.get("message", f"{category.title()} issue detected."),
        "recommendation": item.get("recommendation", "Review before posting."),
        "evidence": item.get("evidence", {}),
    }


def _decide(
    exceptions: List[Dict[str, Any]],
    compliance: Dict[str, Any],
    routing_rules: Dict[str, Any],
    auto_post: Dict[str, Any],
) -> Tuple[str, Optional[str], List[str]]:
    severities = [str(e.get("severity", "")).upper() for e in exceptions]
    has_critical = "CRITICAL" in severities
    has_high = "HIGH" in severities
    has_any = bool(exceptions)
    risk_level = str((compliance.get("risk") or {}).get("level", compliance.get("risk_level", "LOW"))).upper()

    follow_up: List[str] = []
    if has_critical:
        follow_up.extend([
            "Investigate duplicate or fraud signals before posting.",
            "Verify vendor identity and invoice references.",
        ])
        return "BLOCK", routing_rules.get("high_risk", "finance"), follow_up

    if has_high or risk_level == "HIGH":
        follow_up.extend([
            "Verify compliance issues and supporting documents.",
            "Confirm vendor/bank details with finance.",
        ])
        return "ROUTE", routing_rules.get("high_risk", "finance"), follow_up

    if not has_any and bool(auto_post.get("require_no_compliance_issues", True)):
        follow_up.append("All checks passed under policy; eligible for auto-post.")
        return "AUTO_POST", None, follow_up

    if has_any:
        follow_up.append("Resolve listed exceptions before posting.")
        return "ROUTE", routing_rules.get("default", "manager"), follow_up

    follow_up.append("All checks passed under policy; eligible for auto-post.")
    return "AUTO_POST", None, follow_up


def _summary(exceptions: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_severity: Dict[str, int] = {}
    by_category: Dict[str, int] = {}
    for exception in exceptions:
        sev = str(exception.get("severity", "UNKNOWN")).upper()
        cat = str(exception.get("category", "UNCATEGORIZED")).upper()
        by_severity[sev] = by_severity.get(sev, 0) + 1
        by_category[cat] = by_category.get(cat, 0) + 1
    return {"total": len(exceptions), "by_severity": by_severity, "by_category": by_category}


def _format_md(packet: Dict[str, Any]) -> str:
    lines = ["# Exceptions", "", f"**Decision:** {packet.get('decision')}", ""]
    if packet.get("route_to"):
        lines.extend([f"**Route to:** {packet.get('route_to')}", ""])
    lines.extend(["## Follow-up", ""])
    for item in packet.get("follow_up", []) or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Findings", ""])
    exceptions = packet.get("exceptions", []) or []
    if not exceptions:
        lines.append("No exceptions detected.")
    else:
        for exception in exceptions:
            lines.append(
                f"- [{exception.get('severity')}] {exception.get('category')}::{exception.get('code')}: {exception.get('message')}"
            )
            if exception.get("recommendation"):
                lines.append(f"  - Recommendation: {exception.get('recommendation')}")
    return "\n".join(lines) + "\n"


def _load_json(path: str) -> Optional[Any]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(run_path: str, filename: str, obj: Any) -> None:
    with open(os.path.join(run_path, filename), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def _write_md(run_path: str, filename: str, content: str) -> None:
    with open(os.path.join(run_path, filename), "w", encoding="utf-8") as f:
        f.write(content)


def _load_yaml(rel_path: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(os.getcwd(), rel_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None
