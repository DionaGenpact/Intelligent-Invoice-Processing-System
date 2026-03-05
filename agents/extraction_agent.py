import os
import json
import csv
from typing import Dict, Any, List
from utils.audit_logger import log_step

LOW_CONFIDENCE_THRESHOLD = 0.75


def run_extraction(bundle_path: str, run_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    log_step(run_path, "Extraction (Agent B) started")

    manifest = context.get("manifest", {})
    invoice_file = manifest.get("invoice_file")

    if not invoice_file:
        raise ValueError("invoice_file missing in manifest")

    invoice_path = os.path.join(bundle_path, invoice_file)
    if not os.path.exists(invoice_path):
        raise FileNotFoundError(f"Invoice file not found: {invoice_file}")

    pages_data = _simulate_page_parsing(manifest)
    aggregated = _aggregate_pages(pages_data)

    confidence_block = _compute_confidence(aggregated)

    low_conf_fields = _detect_low_confidence(confidence_block)
    if low_conf_fields:
        context.setdefault("risk_flags", []).append("LOW_CONFIDENCE_FIELDS")
        log_step(run_path, f"Low confidence fields detected: {low_conf_fields}")

    extracted_data = {
        "header": aggregated["header"],
        "line_items": aggregated["line_items"],
        "confidence": confidence_block,
        "evidence": aggregated["evidence"],
        "aggregation": aggregated["aggregation"]
    }

    with open(os.path.join(run_path, "extracted_invoice.json"), "w", encoding="utf-8") as f:
        json.dump(extracted_data, f, indent=2)

    _export_csv(run_path, aggregated["line_items"])

    context["extraction_result"] = extracted_data
    with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, "Extraction (Agent B) completed")
    return extracted_data


def _simulate_page_parsing(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "page_number": 1,
            "header": {
                "invoice_number": "INV-001",
                "invoice_date": "2025-01-01",
                "vendor_id": manifest.get("vendor_id"),
                "currency": manifest.get("expected_currency"),
                "total_amount": 100.00
            },
            "line_items": [
                {
                    "line_number": 1,
                    "description": "Sample Item",
                    "quantity": 2,
                    "unit_price": 50.00,
                    "line_total": 100.00,
                    "page": 1
                }
            ],
            "evidence": {
                "invoice_number": {"page": 1, "bbox": [100, 120, 250, 150]},
                "total_amount": {"page": 1, "bbox": [400, 700, 520, 730]}
            }
        }
    ]


def _aggregate_pages(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    header = pages[0]["header"]
    line_items = []
    evidence = {}
    pages_processed = len(pages)

    for page in pages:
        line_items.extend(page["line_items"])
        evidence.update(page.get("evidence", {}))

    return {
        "header": header,
        "line_items": line_items,
        "evidence": evidence,
        "aggregation": {
            "pages_processed": pages_processed,
            "multi_page_detected": pages_processed > 1
        }
    }


def _compute_confidence(data: Dict[str, Any]) -> Dict[str, Any]:
    field_scores = {
        "invoice_number": 0.95,
        "invoice_date": 0.90,
        "vendor_id": 1.0,
        "currency": 1.0,
        "total_amount": 0.88
    }

    line_conf = [
        {"line_number": item["line_number"], "confidence": 0.87}
        for item in data["line_items"]
    ]

    return {
        "fields": field_scores,
        "line_items": line_conf
    }

def _detect_low_confidence(conf_block: Dict[str, Any]) -> List[str]:
    return [
        field
        for field, score in conf_block["fields"].items()
        if score < LOW_CONFIDENCE_THRESHOLD
    ]

def _export_csv(run_path: str, line_items: List[Dict[str, Any]]) -> None:
    csv_path = os.path.join(run_path, "line_items.csv")

    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=["line_number", "description", "quantity", "unit_price", "line_total", "page"]
        )
        writer.writeheader()
        for item in line_items:
            writer.writerow(item)