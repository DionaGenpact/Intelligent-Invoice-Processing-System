# agents/anomaly_agent.py Agent G - Compliance & Risk Detection (Duplicate + Anomaly)
from __future__ import annotations

import json  
import os    
import difflib  
from typing import Any, Dict, List, Optional

import yaml  

from utils.audit_logger import log_step  


def run_anomaly_detection(bundle_path: str, run_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    log_step(run_path, "Anomaly Detection (G) started") 

    # REQ: uses extracted invoice artifact (deterministic)
    invoice = _load_json(os.path.join(run_path, "extracted_invoice.json")) or context.get("extracted_invoice") or {}
    header = invoice.get("header") or {}

    # REQ: optional supporting docs (history for duplicates, vendor master for bank change)
    history = _load_json(os.path.join(bundle_path, "history.json"))  # list of previous invoices (optional)
    vendor_master = _load_json(os.path.join(bundle_path, "vendor_master.json"))  # vendor snapshot (optional)
    approval_policy = _load_yaml("policies/approval_policy.yaml") or {}  # REQ: amount thresholds
    risk_policy = _load_yaml("policies/risk_policy.yaml") or {}  # REQ: weights / repeated behavior scoring

    findings: List[Dict[str, Any]] = []  # REQ: findings with severity + recs

     
    # REQ: Duplicate Invoice Detection (vendor + invoice_no + amount + date + similarity)
     
    dup = _find_duplicate(header, history)
    if dup:
        findings.append({
            "code": "DUPLICATE_INVOICE_SUSPECTED",
            "severity": "CRITICAL",
            "message": "Invoice appears to be a duplicate of a previously processed invoice.",
            "evidence": {"matched_record": dup},
            "recommendation": "BLOCK and investigate before posting.",
        })

     
    # REQ: Anomaly - Bank account change vs vendor master
     
    bank_change = _detect_bank_change(header, vendor_master)
    if bank_change:
        findings.append({
            "code": "BANK_ACCOUNT_CHANGE",
            "severity": "HIGH",
            "message": "Invoice bank account differs from vendor master snapshot.",
            "evidence": bank_change,
            "recommendation": "Route to finance for bank verification.",
        })

     
    # REQ: Anomaly - Repeated bank changes (needs history, best-effort)
     
    repeated = _repeated_bank_change(header, history)
    if repeated:
        findings.append({
            "code": "REPEATED_BANK_CHANGES",
            "severity": "HIGH",
            "message": "Vendor has multiple bank account changes across recent invoices.",
            "evidence": repeated,
            "recommendation": "Escalate to finance/compliance and verify bank details.",
        })

     
    # REQ: Anomaly - Amount just under approval threshold
     
    amt_flag = _just_under_threshold(header, approval_policy)
    if amt_flag:
        findings.append({
            "code": "AMOUNT_JUST_UNDER_APPROVAL_THRESHOLD",
            "severity": "MEDIUM",
            "message": "Invoice amount is just under an approval threshold.",
            "evidence": amt_flag,
            "recommendation": "Consider routing for review depending on policy.",
        })

    out = {
        "status": "completed",
        "findings": findings,  # REQ: severity + recommendations for orchestrator
        "notes": [],
        "policy_refs": {
            "approval_policy": "policies/approval_policy.yaml",
            "risk_policy": "policies/risk_policy.yaml",
        },
    }

    _write_json(run_path, "anomaly_findings.json", out)  # REQ: deterministic artifact
    log_step(run_path, f"Anomaly Detection (G) completed (findings={len(findings)})")  # REQ: audit
    return out


 
# Helpers
 

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


def _load_yaml(rel_path: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(os.getcwd(), rel_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def _to_str(x: Any) -> str:
    return str(x or "").strip()


def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(str(x).strip().replace(",", ""))
    except Exception:
        return None


def _similar(a: str, b: str) -> float:
    # REQ: similarity measure (simple + deterministic)
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _find_duplicate(header: Dict[str, Any], history: Any) -> Optional[Dict[str, Any]]:
    # REQ: use vendor + invoice_number + amount + date with similarity
    if not isinstance(history, list):
        return None

    vendor = _to_str(header.get("vendor_id") or header.get("vendor_name"))
    inv_no = _to_str(header.get("invoice_number"))
    inv_date = _to_str(header.get("invoice_date"))
    amt = _to_float(header.get("total_amount"))

    for rec in history:
        if not isinstance(rec, dict):
            continue

        rec_inv_no = _to_str(rec.get("invoice_number"))
        rec_vendor = _to_str(rec.get("vendor_id") or rec.get("vendor_name"))
        rec_date = _to_str(rec.get("invoice_date"))
        rec_amt = _to_float(rec.get("total_amount"))

        # Similarity on invoice_number and vendor (handles minor OCR variations)
        inv_match = (_similar(inv_no, rec_inv_no) >= 0.95) if inv_no and rec_inv_no else False
        vendor_match = (_similar(vendor, rec_vendor) >= 0.90) if vendor and rec_vendor else True

        # Date check (exact if present; you can loosen later if needed)
        date_match = (inv_date == rec_date) if inv_date and rec_date else True

        # Amount check (tight tolerance)
        amt_match = (amt is not None and rec_amt is not None and abs(amt - rec_amt) < 0.01)

        if inv_match and vendor_match and date_match and amt_match:
            return rec

    return None


def _detect_bank_change(header: Dict[str, Any], vendor_master: Any) -> Optional[Dict[str, Any]]:
    # REQ: bank change heuristic vs vendor master snapshot
    inv_bank = _to_str(header.get("bank_account"))
    if not inv_bank or not isinstance(vendor_master, dict):
        return None

    vendor_id = _to_str(header.get("vendor_id"))
    master_bank = None

    # Supports either vendors list or dict or flat snapshot (deterministic parsing)
    if vendor_id and isinstance(vendor_master.get("vendors"), list):
        for v in vendor_master["vendors"]:
            if _to_str(v.get("vendor_id")) == vendor_id:
                master_bank = _to_str(v.get("bank_account"))
                break
    elif vendor_id and isinstance(vendor_master.get("vendors"), dict):
        v = vendor_master["vendors"].get(vendor_id) or {}
        master_bank = _to_str(v.get("bank_account"))
    else:
        master_bank = _to_str(vendor_master.get("bank_account"))

    if master_bank and master_bank != inv_bank:
        return {"invoice_bank": inv_bank, "vendor_master_bank": master_bank}

    return None


def _repeated_bank_change(header: Dict[str, Any], history: Any) -> Optional[Dict[str, Any]]:
    # REQ: suspicious pattern like repeated bank changes (best-effort if history exists)
    if not isinstance(history, list):
        return None

    vendor = _to_str(header.get("vendor_id") or header.get("vendor_name"))
    if not vendor:
        return None

    banks = []
    for rec in history:
        if not isinstance(rec, dict):
            continue
        rec_vendor = _to_str(rec.get("vendor_id") or rec.get("vendor_name"))
        if rec_vendor and _similar(vendor, rec_vendor) >= 0.90:
            b = _to_str(rec.get("bank_account"))
            if b:
                banks.append(b)

    # If multiple distinct banks appear, flag it
    unique = sorted(set(banks))
    if len(unique) >= 2:
        return {"vendor": vendor, "distinct_banks_in_history": unique[:5], "count_distinct": len(unique)}

    return None


def _just_under_threshold(header: Dict[str, Any], approval_policy: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # REQ: anomaly "amount just under approval limit"
    amount = _to_float(header.get("total_amount"))
    if amount is None:
        return None

    thresholds = (approval_policy.get("approval_thresholds") or {})
    for role, t in thresholds.items():
        try:
            t_f = float(t)
        except Exception:
            continue
        if t_f > 0 and (t_f * 0.95) <= amount < t_f:
            return {"role": role, "threshold": t_f, "amount": amount}

    return None