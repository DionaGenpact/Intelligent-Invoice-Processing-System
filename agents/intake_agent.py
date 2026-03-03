import os
import json
import yaml
from utils.audit_logger import log_step
from utils.schema_validator import validate_json


def run_intake(bundle_path, run_path):
    log_step(run_path, "Intake started")

    manifest_path = os.path.join(bundle_path, "manifest.yaml")

    if not os.path.exists(manifest_path):
        log_step(run_path, "Manifest file not found")
        raise FileNotFoundError("manifest.yaml not found in bundle")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    # Validate manifest against schema
    schema_errors = validate_json(manifest, "schemas/manifest.schema.json")
    if schema_errors:
        log_step(run_path, f"Manifest schema validation failed: {schema_errors}")
        raise ValueError("Manifest schema validation failed")

    log_step(run_path, "Manifest schema validation passed")

    # Create structured context with placeholders
    context = {
    "bundle_path": bundle_path,
    "manifest": manifest,
    "validation_result": {},
    "extraction_result": {},
    "policy_result": {},
    "decision_result": {},
    "evidence_index": {}
}

    context_path = os.path.join(run_path, "context.json")

    with open(context_path, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, "Context generated successfully")

    return context