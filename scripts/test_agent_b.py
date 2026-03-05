import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.extraction_agent import run_extraction
import os

bundle_path = "test_bundle"
run_path = "test_run"

os.makedirs(run_path, exist_ok=True)

context = {
    "manifest": {
        "invoice_file": "invoice.pdf",
        "vendor_id": "VENDOR-123",
        "expected_currency": "USD"
    }
}

result = run_extraction(bundle_path, run_path, context)

print("Extraction Output:")
print(result)