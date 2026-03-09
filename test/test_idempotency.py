"""
Idempotency test - verifies that running the same bundle twice produces identical outputs.
This ensures deterministic behavior as required by the project specifications.
"""
import json
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.orchestrator import run_pipeline


def compare_json_files(file1, file2, filename):
    """Compare two JSON files and return True if identical."""
    with open(file1, 'r', encoding='utf-8') as f1, open(file2, 'r', encoding='utf-8') as f2:
        data1 = json.load(f1)
        data2 = json.load(f2)
        
        # Ignore run_id and timestamps which may differ
        if isinstance(data1, dict) and 'run_id' in data1:
            data1.pop('run_id', None)
            data2.pop('run_id', None)
        
        if data1 != data2:
            print(f"  [X] {filename} differs between runs")
            return False
        return True


def test_idempotency(bundle_path="bundles/bundle_01"):
    """Test that running the same bundle twice produces identical outputs."""
    # Change to project root directory
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    os.chdir(project_root)
    
    print(f"Testing idempotency for {bundle_path}...\n")
    
    if not os.path.exists(bundle_path):
        print(f"Error: Bundle {bundle_path} not found")
        return False
    
    # Run pipeline twice
    print("Run 1...", end=" ")
    run_path_1 = run_pipeline(bundle_path)
    print(f"[OK] Completed: {run_path_1}")
    
    print("Run 2...", end=" ")
    run_path_2 = run_pipeline(bundle_path)
    print(f"[OK] Completed: {run_path_2}")
    
    # Compare key output files
    print("\nComparing outputs:")
    
    files_to_compare = [
        "decision.json",
        "extracted_invoice.json",
        "match_result.json",
        "compliance_findings.json",
        "anomaly_findings.json",
        "approval_packet.json",
        "posting_payload.json",
        "vendor_resolution.json",
        "normalization.json"
    ]
    
    all_match = True
    
    for filename in files_to_compare:
        file1 = os.path.join(run_path_1, filename)
        file2 = os.path.join(run_path_2, filename)
        
        if not os.path.exists(file1) or not os.path.exists(file2):
            print(f"  [-] {filename} - skipped (not present in both runs)")
            continue
        
        if compare_json_files(file1, file2, filename):
            print(f"  [OK] {filename} - identical")
        else:
            all_match = False
    
    print(f"\n{'='*50}")
    if all_match:
        print("[PASSED] IDEMPOTENCY TEST PASSED")
        print("All outputs are deterministic and identical across runs")
    else:
        print("[FAILED] IDEMPOTENCY TEST FAILED")
        print("Some outputs differ between runs")
    print(f"{'='*50}")
    
    return all_match


if __name__ == "__main__":
    success = test_idempotency()
    sys.exit(0 if success else 1)