import os
from agents.vendor_resolution_agent import run_vendor_resolution

bundle_path = "test_bundle"
run_path = "test_run/agent_c"
os.makedirs(run_path, exist_ok=True)

context = {
    "extraction_result": {
        "header": {
            "vendor_id": "VEND002",
            "vendor_name": "Global Supply Ltd"  # Slight typo to trigger fuzzy match
        }
    }
}

result = run_vendor_resolution(run_path, context)
print("Vendor Resolution Result:", result)