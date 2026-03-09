"""
Test runner for all invoice bundles.
Validates that each bundle can be processed without errors.
"""
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.orchestrator import run_pipeline


def test_all_bundles():
    """Run pipeline on all bundles and report results."""
    # Change to project root directory
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    os.chdir(project_root)
    
    bundles_dir = "bundles"
    
    if not os.path.exists(bundles_dir):
        print(f"Error: {bundles_dir} directory not found")
        return False
    
    bundles = [f"bundles/{b}" for b in os.listdir(bundles_dir) 
               if os.path.isdir(f"bundles/{b}")]
    
    if not bundles:
        print("No bundles found to test")
        return False
    
    print(f"Testing {len(bundles)} bundles...\n")
    
    passed = 0
    failed = 0
    
    for bundle in sorted(bundles):
        bundle_name = os.path.basename(bundle)
        print(f"Testing {bundle_name}...", end=" ")
        
        try:
            run_path = run_pipeline(bundle)
            
            # Verify key artifacts exist
            required_files = [
                "decision.json",
                "metrics.json",
                "audit_log.md",
                "extracted_invoice.json"
            ]
            
            for file in required_files:
                if not os.path.exists(os.path.join(run_path, file)):
                    raise FileNotFoundError(f"Missing {file}")
            
            print(f"[PASSED]")
            passed += 1
            
        except Exception as e:
            print(f"[FAILED]: {str(e)}")
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(bundles)} total")
    print(f"{'='*50}")
    
    return failed == 0


if __name__ == "__main__":
    success = test_all_bundles()
    sys.exit(0 if success else 1)
