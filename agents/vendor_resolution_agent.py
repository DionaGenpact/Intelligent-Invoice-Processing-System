import os
import json
from typing import Dict, Any
from fuzzywuzzy import fuzz, process
from utils.audit_logger import log_step

FUZZY_THRESHOLD = 85

# Sample trusted vendor list (in practice, load from DB or JSON)
TRUSTED_VENDORS = [
    {"vendor_id": "VEND001", "vendor_name": "Acme Corporation"},
    {"vendor_id": "VEND002", "vendor_name": "Global Supplies Ltd"},
    {"vendor_id": "VEND003", "vendor_name": "Techtronics Inc"}
]

def run_vendor_resolution(run_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    log_step(run_path, "Agent C (Vendor Resolution) started")

    extraction = context.get("extraction_result", {})
    header = extraction.get("header", {})

    invoice_vendor_id = header.get("vendor_id")
    invoice_vendor_name = header.get("vendor_name", "")

    risk_flags = []

    matched_vendor = next((v for v in TRUSTED_VENDORS if v["vendor_id"] == invoice_vendor_id), None)

    if matched_vendor:
        name_similarity = fuzz.token_sort_ratio(invoice_vendor_name, matched_vendor["vendor_name"])
        if name_similarity < FUZZY_THRESHOLD:
            risk_flags.append(f"Vendor name mismatch: invoice='{invoice_vendor_name}' vs trusted='{matched_vendor['vendor_name']}'")
    else:
        best_match = process.extractOne(invoice_vendor_name, [v["vendor_name"] for v in TRUSTED_VENDORS])
        if best_match and best_match[1] >= FUZZY_THRESHOLD:
            risk_flags.append(f"Vendor ID not found; closest name match: {best_match[0]} ({best_match[1]}%)")
        else:
            risk_flags.append(f"Vendor unknown: {invoice_vendor_name} ({invoice_vendor_id})")

    context["vendor_resolution"] = {
        "invoice_vendor_id": invoice_vendor_id,
        "invoice_vendor_name": invoice_vendor_name,
        "risk_flags": risk_flags,
        "is_high_risk": len(risk_flags) > 0
    }

    context_path = os.path.join(run_path, "context.json")
    with open(context_path, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    if risk_flags:
        log_step(run_path, f"High-risk vendor flags: {risk_flags}")
    else:
        log_step(run_path, "Vendor resolution passed with no risk flags")

    log_step(run_path, "Agent C completed")
    return context["vendor_resolution"]
