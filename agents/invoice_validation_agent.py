import os
import json
from utils.audit_logger import log_step

REQUIRED_HEADER_FIELDS = [
    "invoice_number",
    "invoice_date",
    "vendor_id",
    "currency",
    "total_amount"
]

def run_invoice_validation(bundle_path, run_path, context):
    log_step(run_path, "Agent D (Invoice Validation) started")

    extraction = context.get("extraction_result")

    if not extraction:
        raise ValueError("Extraction result missing from context")

    header = extraction.get("header", {})
    line_items = extraction.get("line_items", [])

    errors = []
    warnings  = []

    for field in REQUIRED_HEADER_FIELDS:
        if not header.get(field):
            errors.append(f"Missing required header field: {field}")

    currency = header.get("currency")
    if currency:
        header["currency"] = currency.upper()

    calculated_total = 0

    for item in line_items:

        qty = item.get("quantity")
        price = item.get("unit_price")
        line_total = item.get("line_total")

        if qty is None or price is None or line_total is None:
            errors.append(f"Missing values in line {item.get('line_number')}")
            continue
        
        expected = round(qty * price, 2)

        if round(line_total, 2) != expected:
            errors.append(
                f"Line {item.get('line_number')} calculation mismatch"
                f"{line_total} != {expected}"
            )
        calculated_total += expected

    declared_total = header.get("total_amount")

    if declared_total is not None:
        if round(calculated_total, 2) != round(declared_total, 2):
            errors.append(
                f"Invoice total mismatch {declared_total} != {calculated_total}"
            )

    is_valid = len(errors) == 0

    result = {
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "calculated_total": calculated_total
    }

    output_path = os.path.join(run_path, "invoice_validation.json")

    with open(output_path, 'w', encoding="utf-8") as f:
        json.dump(result,f,indent=2)

    context["invoice_validation"] = result

    with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, f"Agent D completed: valid={is_valid}")

    return is_valid, result