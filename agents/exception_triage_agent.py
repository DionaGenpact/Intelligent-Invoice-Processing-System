from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import yaml

from utils.audit_logger import log_step


def run_exception_triage(bundle_path: str, run_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    log_step(run_path, "Exception Triage (H) started")

    validation = context.get("validation_result") or _load_json(os.path.join(run_path, "validation.json")) or {}
    match_result = context.get("match_result") or _load_json(os.path.join(run_path, "match_result.json")) or {}
    compliance = context.get("compliance_risk_result") or _load_json(os.path.join(run_path, "compliance_risk.json")) or {}
    anomaly = context.get("anomaly_result") or _load_json(os.path.join(run_path, "anomaly_result.json")) or {}

    approval_policy = _load_yaml("policies/approval_policy.yaml") or {}
    thresholds = approval_policy.get("approval_thresholds") or {}
    routing_rules = approval_policy.get("routing_rules") or {}
    auto_post = approval_policy.get("auto_post_conditions") or {}

    exceptions: List[Dict[str, Any]] = []
    evidence: Dict[str, Any] = {
        "validation": validation,
        "match_result": match_result,
        "compliance": compliance,
        "anomaly": anomaly,
    }

    # Compliance findings -> exceptions
    for f in (compliance.get("findings") or []):
        if not isinstance(f, dict):
            continue
        exceptions.append({
            "category": "COMPLIANCE",
            "source": "compliance",
            "code": f.get("code"),
            "severity": str(f.get("severity", "MEDIUM")).upper(),
            "message": f.get("message"),
            "field": f.get("field"),
            "recommendation": f.get("recommendation"),
            "evidence": f.get("evidence"),
        })

    # Anomaly findings -> exceptions
    for f in (anomaly.get("findings") or []):
        if not isinstance(f, dict):
            continue
        exceptions.append({
            "category": "RISK",
            "source": "anomaly",
            "code": f.get("code"),
            "severity": str(f.get("severity", "MEDIUM")).upper(),
            "message": f.get("message"),
            "recommendation": f.get("recommendation"),
            "evidence": f.get("evidence"),
        })

    # Matching failures -> exceptions
    for chk in (match_result.get("checks") or []):
        if isinstance(chk, dict) and chk.get("ok") is False:
            exceptions.append({
                "category": "MATCHING",
                "source": "matching",
                "code": chk.get("check"),
                "severity": "MEDIUM",
                "message": chk.get("reason") or "Matching check failed",
                "recommendation": "Review PO/GRN matching and tolerances.",
                "evidence": chk,
            })

    # Validation issues -> exceptions
    for v in (validation.get("issues") or []):
        if isinstance(v, dict):
            exceptions.append({
                "category": "VALIDATION",
                "source": "validation",
                "code": v.get("code", "VALIDATION_ISSUE"),
                "severity": str(v.get("severity", "MEDIUM")).upper(),
                "message": v.get("message", "Validation issue detected."),
                "recommendation": v.get("recommendation", "Fix validation issue or route for review."),
                "evidence": v,
            })

    decision, route_to, follow_up = _decide(
        exceptions=exceptions,
        evidence=evidence,
        thresholds=thresholds,
        routing_rules=routing_rules,
        auto_post=auto_post,
    )

    packet = {
        "decision": decision,
        "route_to": route_to,
        "follow_up": follow_up,
        "summary": _summary(exceptions),
        "exceptions": exceptions,
        "evidence_files": [
            "validation.json",
            "match_result.json",
            "compliance_risk.json",
            "anomaly_result.json",
        ],
    }

    _write_json(run_path, "approval_packet.json", packet)
    _write_md(run_path, "exceptions.md", _format_md(packet))

    log_step(run_path, f"Exception Triage (H) completed (decision={decision}, route={route_to})")
    return packet


def _decide(
    exceptions: List[Dict[str, Any]],
    evidence: Dict[str, Any],
    thresholds: Dict[str, Any],
    routing_rules: Dict[str, Any],
    auto_post: Dict[str, Any],
) -> Tuple[str, Optional[str], List[str]]:
    severities = [str(e.get("severity", "")).upper() for e in exceptions]
    has_critical = "CRITICAL" in severities
    has_high = "HIGH" in severities
    has_any = len(exceptions) > 0

    compliance = evidence.get("compliance") or {}
    risk_level = str(
        compliance.get("risk_level", compliance.get("risk", ""))
    ).upper()

    follow_up: List[str] = []

    if has_critical:
        follow_up.append("Investigate duplicate/fraud signals before posting.")
        follow_up.append("Verify vendor identity and invoice references.")
        return "BLOCK", "finance", follow_up

    if has_high or risk_level == "HIGH":
        follow_up.append("Verify compliance issues and supporting documents (PO/GRN/VAT).")
        follow_up.append("Confirm bank details with vendor master / finance process.")
        return "ROUTE", routing_rules.get("high_risk", "finance"), follow_up

    require_no_compliance = bool(auto_post.get("require_no_compliance_issues", True))

 
    if not has_any:
        follow_up.append("All checks passed under policy; eligible for auto-post.")
        return "AUTO_POST", None, follow_up

   
    if has_any and require_no_compliance:
        follow_up.append("Resolve listed exceptions before posting.")
        return "ROUTE", routing_rules.get("default", "manager"), follow_up

    follow_up.append("All checks passed under policy; eligible for auto-post.")
    return "AUTO_POST", None, follow_up


def _summary(exceptions: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_sev: Dict[str, int] = {}
    by_cat: Dict[str, int] = {}

    for e in exceptions:
        sev = str(e.get("severity", "UNKNOWN")).upper()
        cat = str(e.get("category", "UNCATEGORIZED")).upper()
        by_sev[sev] = by_sev.get(sev, 0) + 1
        by_cat[cat] = by_cat.get(cat, 0) + 1

    return {
        "total": len(exceptions),
        "by_severity": by_sev,
        "by_category": by_cat
    }


def _format_md(packet: Dict[str, Any]) -> str:
    decision = packet.get("decision")
    route_to = packet.get("route_to")
    follow_up = packet.get("follow_up") or []
    exceptions = packet.get("exceptions") or []

    lines = []
    lines.append("# Exceptions\n")
    lines.append(f"**Decision:** {decision}\n")

    if route_to:
        lines.append(f"**Route to:** {route_to}\n")

    if follow_up:
        lines.append("## Follow-up\n")
        for x in follow_up:
            lines.append(f"- {x}")
        lines.append("")

    lines.append("## Findings\n")
    if not exceptions:
        lines.append("No exceptions detected.\n")
        return "\n".join(lines)

    for e in exceptions:
        lines.append(f"- [{e.get('severity')}] {e.get('category')}::{e.get('code')}: {e.get('message')}")
        rec = e.get("recommendation")
        if rec:
            lines.append(f"  - Recommendation: {rec}")

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