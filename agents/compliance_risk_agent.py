# agents/compliance_risk_agent.py Agent F - Compliance and Risk Detection

from __future__ import annotations  

import json  
import os    
import re    
from dataclasses import dataclass  
from typing import Any, Dict, List, Optional

import yaml  

from utils.audit_logger import log_step  


# REQ: findings must include severity + recommendations for orchestrator processing
@dataclass
class Finding:
    code: str
    severity: str  # LOW, MEDIUM, HIGH. CRITICAL
    message: str
    field: Optional[str] = None
    recommendation: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None  # REQ: evidence pointers / values

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.field:
            out["field"] = self.field
        if self.recommendation:
            out["recommendation"] = self.recommendation
        if self.evidence:
            out["evidence"] = self.evidence
        return out


def run_compliance_risk(bundle_path: str, run_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    # REQ: audit trail
    log_step(run_path, "Compliance & Risk (F) started")

    # REQ: read extracted invoice from deterministic run artifact
    invoice = _load_json(os.path.join(run_path, "extracted_invoice.json")) or context.get("extracted_invoice") or {}
    header = (invoice.get("header") or {})  # REQ: invoice structure checks live in header
    confidence = (invoice.get("confidence") or {})  # REQ: low OCR confidence contributes to risk

    # REQ: rule-based validation via policy YAML files
    tax_rules = _load_yaml("policies/tax_rules.yaml") or {}
    risk_policy = _load_yaml("policies/risk_policy.yaml") or {}
    approval_policy = _load_yaml("policies/approval_policy.yaml") or {}

    findings: List[Finding] = []  # REQ: outputs must include compliance findings
    policy_result: Dict[str, Any] = {  # REQ: audit/debug snapshot of active rules
        "jurisdiction": tax_rules.get("jurisdiction"),
        "required_fields": tax_rules.get("required_fields", []),
        "vat_rules": tax_rules.get("vat_rules", {}),
        "risk_score": 0,
        "risk_level": "LOW",
    }

     
    # REQ: invoice structure checks (rule-based)
     

    # REQ: validate required fields from tax_rules.yaml
    required = list(tax_rules.get("required_fields") or [])
    for f in required:
        if header.get(f) in (None, "", []):
            findings.append(
                Finding(
                    code="MISSING_REQUIRED_FIELD",
                    severity="HIGH",
                    field=f,
                    message=f"Required field '{f}' is missing.",
                    recommendation="Request corrected invoice data or route for manual review.",
                    evidence={"source": "invoice.header", "field": f},
                )
            )

    # REQ: validate invoice_date basic format if present (structure sanity)
    inv_date = header.get("invoice_date")
    if inv_date and not _looks_like_date(str(inv_date)):
        findings.append(
            Finding(
                code="INVOICE_DATE_INVALID_FORMAT",
                severity="MEDIUM",
                field="invoice_date",
                message="Invoice date format looks invalid.",
                recommendation="Normalize invoice_date to ISO format (YYYY-MM-DD) or confirm date.",
                evidence={"invoice_date": inv_date},
            )
        )

     
    # REQ: Tax & VAT checks (rule-based)
     

    vat_rules = tax_rules.get("vat_rules") or {}
    standard_rate = vat_rules.get("standard_rate")  # REQ: compare against policy-defined standard
    allow_zero = bool(vat_rules.get("allow_zero_vat", False))  # REQ: enforce policy

    # REQ: VAT ID presence/format checks (VAT IDs requirement)
    vendor_vat = header.get("vendor_vat")
    if vendor_vat in (None, "", []):
        # If your policy/jurisdiction requires it, treat missing VAT as compliance issue.
        # (You can tighten this by jurisdiction later.)
        findings.append(
            Finding(
                code="VENDOR_VAT_MISSING",
                severity="MEDIUM",
                field="vendor_vat",
                message="Vendor VAT ID is missing.",
                recommendation="Request vendor VAT ID or route to compliance review.",
                evidence={"source": "invoice.header", "field": "vendor_vat"},
            )
        )
    else:
        if not _looks_like_vat_id(str(vendor_vat)):
            findings.append(
                Finding(
                    code="VENDOR_VAT_INVALID_FORMAT",
                    severity="MEDIUM",
                    field="vendor_vat",
                    message="Vendor VAT ID format looks invalid.",
                    recommendation="Verify VAT ID format and confirm vendor details.",
                    evidence={"vendor_vat": vendor_vat},
                )
            )

    # REQ: VAT rate vs policy (tax rate validation requirement)
    vat_rate = header.get("vat_rate")
    if vat_rate is not None and standard_rate is not None:
        try:
            vat_rate_f = float(vat_rate)
            std_f = float(standard_rate)

            if vat_rate_f == 0 and not allow_zero:
                findings.append(
                    Finding(
                        code="VAT_ZERO_NOT_ALLOWED",
                        severity="HIGH",
                        field="vat_rate",
                        message="VAT rate is 0 but policy does not allow zero VAT.",
                        recommendation="Confirm jurisdiction rules or correct VAT rate.",
                        evidence={"vat_rate": vat_rate_f, "standard_rate": std_f, "allow_zero_vat": allow_zero},
                    )
                )
            elif abs(vat_rate_f - std_f) > 0.01:
                findings.append(
                    Finding(
                        code="VAT_RATE_MISMATCH",
                        severity="MEDIUM",
                        field="vat_rate",
                        message=f"VAT rate {vat_rate_f} differs from standard rate {std_f}.",
                        recommendation="Confirm tax rate for the jurisdiction and invoice type.",
                        evidence={"vat_rate": vat_rate_f, "standard_rate": std_f},
                    )
                )
        except Exception:
            findings.append(
                Finding(
                    code="VAT_RATE_INVALID",
                    severity="MEDIUM",
                    field="vat_rate",
                    message="VAT rate is present but not numeric.",
                    recommendation="Normalize VAT rate to a numeric value.",
                    evidence={"vat_rate": vat_rate},
                )
            )

     
    # REQ: Risk classification + recommendations (policy-driven)
  

    risk_score = _score_risk(invoice, findings, confidence, risk_policy, approval_policy)  # REQ: risk scoring
    risk_level = _risk_level(risk_score, risk_policy)  # REQ: map score → LOW/MEDIUM/HIGH
    policy_result["risk_score"] = risk_score
    policy_result["risk_level"] = risk_level

    out = {
        "status": "completed",
        # REQ: severity ratings + recommended actions returned
        "findings": [f.to_dict() for f in findings],
        # REQ: risk classified output for orchestrator processing
        "risk": {"score": risk_score, "level": risk_level},
        # REQ: traceability to policy files
        "policy_refs": {
            "tax_rules": "policies/tax_rules.yaml",
            "risk_policy": "policies/risk_policy.yaml",
            "approval_policy": "policies/approval_policy.yaml",
        },
    }

    # REQ: write deterministic artifacts
    _write_json(run_path, "compliance_findings.json", out)
    _write_json(run_path, "policy_result.json", policy_result)

    # REQ: audit trail end
    log_step(run_path, f"Compliance & Risk (F) completed (risk={risk_level}, score={risk_score})")
    return out


 
# Helpers (deterministic + policy-driven)
 

def _load_json(path: str) -> Optional[Dict[str, Any]]:
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


def _load_yaml(rel_path: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(os.getcwd(), rel_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def _looks_like_date(s: str) -> bool:
    # Minimal check, avoids strict parsing to keep it simple/deterministic
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", s.strip()))


def _looks_like_vat_id(s: str) -> bool:
    # Minimal VAT ID sanity (country prefix + alphanum length). Not a full validation.
    # Example: DE123456789, FRXX999999999, etc.
    s = s.strip().replace(" ", "").upper()
    return bool(re.match(r"^[A-Z]{2}[A-Z0-9]{6,14}$", s))


def _score_risk(
    invoice: Dict[str, Any],
    compliance_findings: List[Finding],
    confidence: Dict[str, Any],
    risk_policy: Dict[str, Any],
    approval_policy: Dict[str, Any],
) -> int:
    # REQ: risk scoring with policy weights
    weights = risk_policy.get("risk_weights") or {}
    score = 0

    # REQ: low OCR confidence contributes to risk
    low_conf_fields = [k for k, v in confidence.items() if isinstance(v, (int, float)) and v < 0.6]
    if low_conf_fields:
        score += int(weights.get("low_confidence_ocr", 30))

    # REQ: compliance findings (HIGH/CRITICAL) increase risk
    if any(f.severity in ("HIGH", "CRITICAL") for f in compliance_findings):
        score += int(weights.get("compliance_high", 20)) if "compliance_high" in weights else 20

    # REQ: heuristic for "just under approval limit" risk
    header = invoice.get("header") or {}
    amount_f = _to_float(header.get("total_amount"))
    if amount_f is not None:
        thresholds = (approval_policy.get("approval_thresholds") or {})
        for _, t in thresholds.items():
            try:
                t = float(t)
            except Exception:
                continue
            if t > 0 and (t * 0.95) <= amount_f < t:
                score += int(weights.get("high_amount", 40))
                break

    return min(score, 100)  # REQ: bounded score


def _risk_level(score: int, risk_policy: Dict[str, Any]) -> str:
    # REQ: classification using policy ranges
    levels = risk_policy.get("risk_levels") or {}

    def _parse_range(val: Any):
        if isinstance(val, str) and "-" in val:
            a, b = val.split("-", 1)
            return int(a), int(b)
        if isinstance(val, dict) and "min" in val and "max" in val:
            return int(val["min"]), int(val["max"])
        return None

    for name in ("low", "medium", "high"):
        rng = _parse_range(levels.get(name))
        if rng and rng[0] <= score <= rng[1]:
            return name.upper()

    # Deterministic fallback
    if score <= 40:
        return "LOW"
    if score <= 70:
        return "MEDIUM"
    return "HIGH"


def _to_float(val: Any) -> Optional[float]:
    try:
        if val is None:
            return None
        return float(str(val).strip().replace(",", ""))
    except Exception:
        return None