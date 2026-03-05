import os
from agents.invoice_validation_agent import run_invoice_validation

def main():

    bundle_path = "test_bundle"

    run_path = os.path.join("test_run", "test_d")
    os.makedirs(run_path, exist_ok=True)

    context = {
        "extraction_result": {
            "header": {
                "invoice_number": "INV-001",
                "invoice_date": "2025-01-01",
                "vendor_id": "VENDOR-123",
                "currency": "usd",
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
            ]
        }
    }

    result = run_invoice_validation(bundle_path, run_path, context)

    print("Validation result:")
    print(result)


if __name__ == "__main__":
    main()
