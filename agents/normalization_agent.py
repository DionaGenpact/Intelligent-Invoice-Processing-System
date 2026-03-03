import os
import json
from utils.audit_logger import log_step

def run_normalization(run_path, extracted_data):
    log_step(run_path, "Normalization started")

    errors = []

    header = extracted_data.get("header", {})
    line_items = extracted_data.get("line_items", [])

    calculated_total = sum(
        item["quantity"] * item["unit_price"]
        for item in line_items
    )

    declared_total = header.get("total_amount" , 0)

    if round(calculated_total, 2) != round(declared_total, 2):
        errors.append("Header total does not match sum of line items")

    normalized_output = {
        "normalized": True,
        "calculated_total": calculated_total,
        "errors": errors
    }

    output_path = os.path.join(run_path, "normalization.json")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(normalized_output,f , indent=2)

    log_step(run_path, "Normalization completed")

    return len(errors) == 0, normalized_output