import os
import json
from utils.audit_logger import log_step

def run_extraction(bundle_path, run_path, context):
    log_step(run_path, "Extraction started")

    manifest = context.get("manifest", {})
    invoice_file = manifest.get("invoice_file")

    # Placeholder extraction (until OCR is added)
    extracted_data = {
        "header": {
            "invoice_number": "INV-001",
            "vendor_id": manifest.get("vendor_id"),
            "currency": manifest.get("expected_currency"),
            "total_amount": 100.00
        },
        "line_items": [
            {
                "line_number": 1,
                "description": "Sample Item",
                "quantity": 2,
                "unit_price": 50.00,
                "line_total": 100.00
            }
        ],
        "confidence": {
            "invoice_number": 0.95,
            "vendor_id": 1.0,
            "currency": 1.0,
            "total_amount": 0.80
        }
    }

    output_path = os.path.join(run_path, "extracted_invoice.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(extracted_data, f, indent=2)

    log_step(run_path, "Extraction completed")

    return extracted_data