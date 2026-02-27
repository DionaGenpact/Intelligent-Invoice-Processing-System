import os
import json
import yaml

def run_intake(bundle_path, run_path):
    manifest_path = os.path.join(bundle_path, "manifest.yaml")

    with open(manifest_path, "r") as f:
        manifest = yaml.safe_load(f)

        context = {
            "bundle_path": bundle_path,
            "manifest": manifest
        }
        context_path = os.path.join(run_path, "context.json")

        with open(context_path, "w") as f:
            json.dump(context, f, indent=4)
            
        return context

