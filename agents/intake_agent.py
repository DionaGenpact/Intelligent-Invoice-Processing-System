import os
import json
import yaml

from utils.audit_logger import log_step
from utils.schema_validator import validate_json


def _file_meta(path: str) -> dict:
    return {
        "path": path,
        "exists": os.path.exists(path),
        "size_bytes": os.path.getsize(path) if os.path.exists(path) else 0
    }


def build_evidence_index(bundle_path: str, manifest: dict) -> dict:
    evidence = {}

    # Always include manifest
    manifest_path = os.path.join(bundle_path, "manifest.yaml")
    evidence["manifest"] = {
        "file_name": "manifest.yaml",
        **_file_meta(manifest_path)
    }

    # Invoice file from manifest
    invoice_file = manifest.get("invoice_file")
    if invoice_file:
        invoice_path = os.path.join(bundle_path, invoice_file)
        evidence["invoice"] = {
            "file_name": invoice_file,
            **_file_meta(invoice_path)
        }

    return evidence


def detect_risk_flags(manifest: dict, evidence_index: dict) -> list[str]:
    flags = []

    # missing invoice file
    invoice_meta = evidence_index.get("invoice", {})
    if invoice_meta and not invoice_meta.get("exists", False):
        flags.append("MISSING_INVOICE_FILE")

    # missing PO number
    if not manifest.get("po_number"):
        flags.append("MISSING_PO_NUMBER")

    # missing currency
    if not manifest.get("expected_currency"):
        flags.append("MISSING_CURRENCY")

    return flags


def detect_ignored_files(bundle_path: str, evidence_index: dict) -> list[str]:
    referenced = set()

    for meta in evidence_index.values():
        file_name = meta.get("file_name")
        if file_name:
            referenced.add(file_name)

    ignored = []
    for f in sorted(os.listdir(bundle_path)):
        full_path = os.path.join(bundle_path, f)
        if os.path.isfile(full_path) and f not in referenced:
            ignored.append(f)

    return ignored


def run_intake(bundle_path, run_path):
    log_step(run_path, "Intake started")

    manifest_path = os.path.join(bundle_path, "manifest.yaml")

    if not os.path.exists(manifest_path):
        log_step(run_path, "Manifest file not found")
        raise FileNotFoundError("manifest.yaml not found in bundle")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f) or {}

    # Validate manifest against schema
    schema_errors = validate_json(manifest, "schemas/manifest.schema.json")
    if schema_errors:
        log_step(run_path, f"Manifest schema validation failed: {schema_errors}")
        raise ValueError("Manifest schema validation failed")
    log_step(run_path, "Manifest schema validation passed")

    # Agent A core outputs
    evidence_index = build_evidence_index(bundle_path, manifest)
    risk_flags = detect_risk_flags(manifest, evidence_index)
    ignored_files = detect_ignored_files(bundle_path, evidence_index)

    if risk_flags:
        log_step(run_path, f"Risk flags detected: {risk_flags}")
    else:
        log_step(run_path, "No risk flags detected")

    # Create structured context with placeholders + Agent A enrichments
    context = {
        "bundle_path": bundle_path,
        "manifest": manifest,
        "validation_result": {},
        "extraction_result": {},
        "policy_result": {},
        "decision_result": {},
        "evidence_index": evidence_index,
        "risk_flags": risk_flags,
        "ignored_files": ignored_files
    }

    context_path = os.path.join(run_path, "context.json")
    with open(context_path, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, "Context generated successfully")
    return context