import json
import os
from typing import Any, Dict, List

from utils.audit_logger import log_step


def run_posting_payload(run_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    log_step(run_path, "Posting Payload generation started")

    extraction = context.get("extraction_result", {}) or {}
    approval_packet = context.get("approval_packet", {}) or {}
    decision = context.get("decision_result", {}) or {}
    manifest = context.get("manifest", {}) or {}
    vendor_resolution = context.get("vendor_resolution_result", {}) or {}
    match_result = context.get("match_result", {}) or {}

    header = extraction.get("header", {}) or {}
    lines = extraction.get("line_items", []) or []

    payload = {
        "document_type": "AP_INVOICE",
        "invoice_number": header.get("invoice_number"),
        "invoice_date": header.get("invoice_date"),
        "vendor_id": header.get("vendor_id") or manifest.get("vendor_id"),
        "vendor_name": header.get("vendor_name") or manifest.get("vendor_name"),
        "currency": header.get("currency") or manifest.get("expected_currency"),
        "gross_amount": header.get("total_amount"),
        "po_number": manifest.get("po_number"),
        "match_mode": match_result.get("mode"),
        "route_to": approval_packet.get("route_to"),
        "posting_status": _map_status(decision.get("status")),
        "approval_decision": approval_packet.get("decision"),
        "line_items": [
            {
                "line_number": line.get("line_number"),
                "description": line.get("description"),
                "quantity": line.get("quantity"),
                "unit_price": line.get("unit_price"),
                "line_total": line.get("line_total"),
            }
            for line in lines
        ],
        "evidence_refs": {
            "source_invoice": manifest.get("invoice_file"),
            "match_result": "match_result.json",
            "approval_packet": "approval_packet.json",
            "audit_log": "audit_log.md",
        },
        "vendor_master_match": {
            "resolved": vendor_resolution.get("resolved"),
            "method": vendor_resolution.get("match_method"),
        },
    }

    with open(os.path.join(run_path, "posting_payload.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    log_step(run_path, "Posting Payload generation completed")
    return payload


def _map_status(status: Any) -> str:
    normalized = str(status or "").upper()
    if normalized == "APPROVE":
        return "READY_TO_POST"
    if normalized == "REVIEW":
        return "PENDING_REVIEW"
    return "BLOCKED"
