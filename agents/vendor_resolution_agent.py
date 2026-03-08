import os
import json
import re
from typing import Dict, Any, List, Optional
from fuzzywuzzy import fuzz
from utils.audit_logger import log_step
from utils.schema_validator import validate_json

FUZZY_THRESHOLD = 85


def run_vendor_resolution(bundle_path: str, run_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    log_step(run_path, "Agent C (Vendor Resolution) started")

    vendor_master = _load_vendor_master(bundle_path)
    vendors: List[Dict[str, Any]] = vendor_master.get("vendors", [])

    if not isinstance(vendors, list):
        raise ValueError("vendor_master.json invalid: 'vendors' must be a list")

    extraction = context.get("extraction_result", {})
    header = extraction.get("header", {})

    invoice_vendor_id = str(header.get("vendor_id") or "").strip()
    invoice_vendor_name = str(header.get("vendor_name") or "").strip()
    invoice_bank = str(header.get("bank_account") or "").strip()
    invoice_vat = str(header.get("vat_id") or "").strip()

    flags: List[str] = []
    resolved = False
    match_method = "none"
    match_score: Optional[float] = None
    matched_vendor: Optional[Dict[str, Any]] = None

   
    if invoice_vendor_id:
        matched_vendor = _find_by_id(vendors, invoice_vendor_id)
        if matched_vendor:
            resolved = True
            match_method = "vendor_id"
            match_score = None

            master_name = str(matched_vendor.get("vendor_name") or "").strip()
            if invoice_vendor_name and master_name:
                score = fuzz.token_set_ratio(invoice_vendor_name, master_name)
                if score < FUZZY_THRESHOLD:
                    flags.append("VENDOR_NAME_MISMATCH")
            else:
                if not invoice_vendor_name:
                    flags.append("VENDOR_NAME_MISSING")

   
    if not matched_vendor:
        if invoice_vendor_name:
            matched_vendor = _find_by_name_fuzzy(vendors, invoice_vendor_name)

        if matched_vendor:
            resolved = True
            match_method = "vendor_name_fuzzy"
            match_score = float(matched_vendor.get("_match_score", 0))
        else:
            if not invoice_vendor_name:
                flags.append("VENDOR_NAME_MISSING")

            if not invoice_vendor_id:
                flags.append("NEW_VENDOR")


    if matched_vendor:
        master_bank = str(matched_vendor.get("bank_account") or "").strip()
        master_vat = str(matched_vendor.get("vat_id") or "").strip()

        if invoice_bank and master_bank and _norm_str(invoice_bank) != _norm_str(master_bank):
            flags.append("VENDOR_BANK_CHANGE")

        if invoice_vat and master_vat and _norm_str(invoice_vat) != _norm_str(master_vat):
            flags.append("VENDOR_VAT_MISMATCH")

    is_high_risk = bool(matched_vendor.get("is_high_risk", False)) if matched_vendor else False

    result: Dict[str, Any] = {
        "resolved": resolved,
        "match_method": match_method,
        "match_score": match_score,
        "vendor_master": None,
        "invoice_vendor": {
            "vendor_id": invoice_vendor_id,
            "vendor_name": invoice_vendor_name,
            "bank_account": invoice_bank or None,
            "vat_id": invoice_vat or None
        },
        "flags": flags,
        "is_high_risk": is_high_risk
    }

    if matched_vendor:
        result["vendor_master"] = {
            "vendor_id": str(matched_vendor.get("vendor_id") or ""),
            "vendor_name": str(matched_vendor.get("vendor_name") or ""),
            "bank_account": matched_vendor.get("bank_account"),
            "vat_id": matched_vendor.get("vat_id"),
            "is_high_risk": bool(matched_vendor.get("is_high_risk", False))
        }

    out_path = os.path.join(run_path, "vendor_resolution.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    schema_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "schemas", "vendor_resolution.schema.json")
    )
    errors = validate_json(result, schema_path)
    if errors:
        log_step(run_path, f"Vendor resolution schema validation failed: {errors}")
        context.setdefault("risk_flags", []).append("VENDOR_RESOLUTION_SCHEMA_INVALID")
        context["vendor_resolution_schema_errors"] = errors

        with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
            json.dump(context, f, indent=4)

        raise ValueError("Vendor resolution schema validation failed")

    context["vendor_resolution_result"] = {
        "resolved": resolved,
        "match_method": match_method,
        "flags": flags,
        "is_high_risk": is_high_risk,
        "matched_vendor_id": (result.get("vendor_master") or {}).get("vendor_id")
    }

    for fl in flags:
        context.setdefault("risk_flags", []).append(fl)

    if is_high_risk:
        context.setdefault("risk_flags", []).append("HIGH_RISK_VENDOR")

    with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, f"Vendor resolution completed: resolved={resolved}, method={match_method}, flags={flags}")

    return result


def _find_by_id(vendors: List[Dict[str, Any]], vendor_id: str) -> Optional[Dict[str, Any]]:
    vid = vendor_id.strip().lower()
    for v in vendors:
        if isinstance(v, dict) and str(v.get("vendor_id", "")).strip().lower() == vid:
            return v
    return None


def _find_by_name_fuzzy(vendors: List[Dict[str, Any]], name: str, threshold: int = 85) -> Optional[Dict[str, Any]]:
    name = (name or "").strip()
    if not name:
        return None

    best = None
    best_score = -1

    for v in vendors:
        if not isinstance(v, dict):
            continue

        vn = str(v.get("vendor_name", "")).strip()
        if not vn:
            continue

        score = fuzz.token_set_ratio(name, vn)
        if score > best_score:
            best_score = score
            best = v

    if best and best_score >= threshold:
        best = dict(best)
        best["_match_score"] = best_score
        return best

    return None


def _norm_str(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]", "", str(s)).lower()


def _load_vendor_master(bundle_path: str) -> Dict[str, Any]:
    path = os.path.join(bundle_path, "vendor_master.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"vendor_master.json not found in bundle: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)