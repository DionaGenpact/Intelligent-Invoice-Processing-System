import os
import re
import json 
from utils.audit_logger import log_step

REQUIRED_KEYS = ["invoice_file", "vendor_id", "po_number", "expected_currency"]
RE_CURRENCY = re.compile(r"^[A-Z]{3}$")

def run_validation(bundle_path, run_path, context):
    log_step(run_path, "Validation started")

    manifest = context.get("manifest", {})
    errors = []
    warnings = []

    # Required fields
    for key in REQUIRED_KEYS:
        if not manifest.get(key):
            errors.append(f"Missing required field: {key}")

    # Check invoice file exists
    invoice_file = manifest.get("invoice_file")
    if invoice_file:
        invoice_path = os.path.join(bundle_path, invoice_file)
        if not os.path.exists(invoice_path):
            errors.append(f"Invoice file not found: {invoice_file}")

    # Currency format
    currency = manifest.get("expected_currency")
    if currency and not RE_CURRENCY.match(currency):
        errors.append(f"Invalid currency format: {currency}")

    is_valid = len(errors) == 0

    result = {
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings
    }
    
    output_path = os.path.join(run_path, "validation.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    log_step(run_path, f"Validation completed: is_valid={is_valid}")

    return is_valid, result












