"""
Idempotency test - verifies that running each bundle twice produces identical outputs.
This ensures deterministic behavior as required by the project specifications.
"""
import json
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.orchestrator import run_pipeline


def compare_json_files(file1, file2, filename):
    """Compare two JSON files and return True if identical."""
    with open(file1, "r", encoding="utf-8") as f1, open(file2, "r", encoding="utf-8") as f2:
        data1 = json.load(f1)
        data2 = json.load(f2)

    # Ignore fields that may change between runs
    if isinstance(data1, dict) and isinstance(data2, dict):
        for key in ["run_id", "timestamp", "created_at", "generated_at"]:
            data1.pop(key, None)
            data2.pop(key, None)

    return data1 == data2


def get_all_bundles():
    """Return all bundle paths inside the bundles directory."""
    bundles_dir = "bundles"

    if not os.path.exists(bundles_dir):
        print(f"Error: {bundles_dir} directory not found")
        return []

    bundles = [
        os.path.join(bundles_dir, b)
        for b in os.listdir(bundles_dir)
        if os.path.isdir(os.path.join(bundles_dir, b))
    ]

    return sorted(bundles)


def test_single_bundle_idempotency(bundle_path):
    """Run one bundle twice and compare outputs."""
    bundle_name = os.path.basename(bundle_path)
    print(f"\nTesting idempotency for {bundle_name}...\n")

    print("Run 1...", end=" ")
    run_path_1 = run_pipeline(bundle_path)
    print(f"[OK] Completed: {run_path_1}")

    print("Run 2...", end=" ")
    run_path_2 = run_pipeline(bundle_path)
    print(f"[OK] Completed: {run_path_2}")

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
        "normalization.json",
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
            print(f"  [X] {filename} - differs between runs")
            all_match = False

    return all_match


def test_idempotency_all_bundles():
    """Test idempotency for all bundles."""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(project_root)

    bundles = get_all_bundles()

    if not bundles:
        print("No bundles found to test")
        return False

    print(f"Testing idempotency for {len(bundles)} bundles...")

    passed = 0
    failed = 0

    for bundle_path in bundles:
        try:
            success = test_single_bundle_idempotency(bundle_path)
            if success:
                print("\n[PASSED] Bundle is idempotent")
                passed += 1
            else:
                print("\n[FAILED] Bundle is NOT idempotent")
                failed += 1
        except Exception as e:
            print(f"\n[FAILED] {os.path.basename(bundle_path)}: {e}")
            failed += 1

        print(f"\n{'=' * 50}")

    print("\nFINAL RESULTS")
    print(f"{'=' * 50}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total : {len(bundles)}")
    print(f"{'=' * 50}")

    return failed == 0


if __name__ == "__main__":
    success = test_idempotency_all_bundles()
    sys.exit(0 if success else 1)