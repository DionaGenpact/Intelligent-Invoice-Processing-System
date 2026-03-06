import os
import json
import re
from typing import Any, Optional
from utils.schema_validator import validate_json
from utils.audit_logger import log_step

REQUIRED_HEADER_FIELDS = [
    "invoice_number",
    "invoice_date",
    "vendor_id",
    "currency",
    "total_amount"
]
def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s:
        return None

    s = s.replace("€", "").replace("$", "").replace("£", "").replace(" ", "")

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        if "," in s and "." not in s:
            s = s.replace(",", ".")

    if not re.match(r"^[+-]?\d+(\.\d+)?$", s):
        return None

    try:
        return float(s)
    except Exception:
        return None


def _is_unusually_high_quantity(qty: float) -> bool:
    return qty > 1000

def run_invoice_validation(bundle_path: str, run_path: str, context: dict):
    log_step(run_path, "Agent D (Invoice Validation) started")

    extraction = context.get("extraction_result")

    if not extraction:
        raise ValueError("Extraction result missing from context")

    header = extraction.get("header", {})
    line_items = extraction.get("line_items", [])

    errors = []
    warnings  = []

    if not line_items:
        warnings.append("NO_LINE_ITEMS_FOUND")

    for field in REQUIRED_HEADER_FIELDS:
        val = header.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"Missing required header field: {field}")

    currency = header.get("currency")
    if currency is not None:
        header["currency"] = str(currency).strip().upper()

    expected_currency = (context.get("manifest", {}) or {}).get("expected_currency")
    if expected_currency:
        expected_currency = str(expected_currency).strip().upper()
        if header.get("currency") and header["currency"] != expected_currency:
            warnings.append(f"CURRENCY_MISMATCH: extracted={header['currency']} expected={expected_currency}")

    optional_fields = ["vendor_name", "bank_account", "vat_id"]
    for f in optional_fields:
        if not header.get(f):
            warnings.append(f"Missing optional header field: {f}")

    calculated_total = 0

    for item in line_items:

        qty_raw = item.get("quantity")
        price_raw = item.get("unit_price")
        line_total_raw = item.get("line_total")

        qty = _to_float(qty_raw)
        price = _to_float(price_raw)
        line_total = _to_float(line_total_raw)

        if qty is None or price is None or line_total is None:
            errors.append(
                f"Missing/invalid numeric values in line {item.get('line_number')}: "
                f"qty={qty_raw}, unit_price={price_raw}, line_total={line_total_raw}"
            )
            continue

        if qty <= 0:
            errors.append(f"Invalid quantity in line {item.get('line_number')}: {qty_raw}")
            continue

        if price < 0 or line_total < 0:
            errors.append(
                f"Invalid negative amount in line {item.get('line_number')}: "
                f"unit_price={price_raw}, line_total={line_total_raw}"
            )
            continue
        
        expected = round(qty * price, 2)

        if _is_unusually_high_quantity(qty):
            warnings.append(f"Unusually high quantity in line {item.get('line_number')}: {qty}")

        if round(line_total, 2) != expected:
            errors.append(
                f"Line {item.get('line_number')} calculation mismatch: {line_total} != {expected}"
            )
        calculated_total = round(calculated_total + expected, 2)

    declared_total_raw = header.get("total_amount")
    declared_total = _to_float(declared_total_raw)

    if declared_total is None and declared_total_raw is not None:
        errors.append(f"Invalid invoice total_amount: {declared_total_raw}")
    elif declared_total is not None:
        header["total_amount"] = declared_total

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
        "calculated_total": calculated_total,
        "declared_total": declared_total
    }

    schema_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "schemas", "invoice_validation.schema.json"))
    schema_errors = validate_json(result, schema_path)
    if schema_errors:
        log_step(run_path, f"Invoice validation schema failed: {schema_errors}")
        context.setdefault("risk_flags", []).append("INVOICE_VALIDATION_SCHEMA_INVALID")
        context["invoice_validation_schema_errors"] = schema_errors

        with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
            json.dump(context, f, indent=4)

        raise ValueError("Invoice validation schema validation failed")

    output_path = os.path.join(run_path, "invoice_validation.json")

    with open(output_path, 'w', encoding="utf-8") as f:
        json.dump(result,f,indent=2)

    context["invoice_validation_result"] = result

    with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, f"Agent D completed: valid={is_valid}")

    return is_valid, result