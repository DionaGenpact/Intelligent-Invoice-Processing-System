from utils.schema_validator import validate_json

context = {
    "bundle_path": "bundles/bundle_01",
    "manifest": {
        "invoice_file": "invoice.pdf",
        "vendor_id": "VENDOR_001",
        "po_number": "PO_12345",
        "expected_currency": "EUR"
    },
    "validation_result": {},
    "extraction_result": {},
    "policy_result": {},
    "decision_result": {}
}

errs = validate_json(context, "schemas/context.schema.json")
print("ERRORS:", errs)