from __future__ import annotations

import hashlib
import os
from typing import Optional

import yaml

UPLOAD_BUNDLES_DIR = ".demo_uploads"
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def _safe_filename(name: str) -> str:
    base = os.path.basename(name or "invoice.pdf")
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in base)
    return safe or "invoice.pdf"


def create_bundle_from_uploaded_invoice(
    file_bytes: bytes,
    original_name: str,
    expected_currency: str = "EUR",
    vendor_id: str = "UPLOADED_VENDOR",
    vendor_name: str = "Uploaded Vendor",
    vendor_vat: str = "UNKNOWN_VENDOR_VAT",
    po_number: str = "NON_PO",
    root_dir: str = UPLOAD_BUNDLES_DIR,
) -> str:
    if not file_bytes:
        raise ValueError("Uploaded invoice is empty.")

    invoice_name = _safe_filename(original_name)
    ext = os.path.splitext(invoice_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported invoice file type: {ext or 'unknown'}")

    digest = hashlib.sha256(file_bytes).hexdigest()[:12]
    bundle_name = f"bundle_upload_{digest}"
    bundle_path = os.path.join(root_dir, bundle_name)
    os.makedirs(bundle_path, exist_ok=True)

    invoice_path = os.path.join(bundle_path, invoice_name)
    with open(invoice_path, "wb") as f:
        f.write(file_bytes)

    manifest = {
        "invoice_file": invoice_name,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "vendor_vat": vendor_vat,
        "po_number": po_number,
        "expected_currency": (expected_currency or "EUR").upper(),
    }
    with open(os.path.join(bundle_path, "manifest.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)

    vendor_master = {
        "vendors": [
            {
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "bank_account": None,
                "vat_id": vendor_vat,
                "is_high_risk": False,
            }
        ]
    }
    import json
    with open(os.path.join(bundle_path, "vendor_master.json"), "w", encoding="utf-8") as f:
        json.dump(vendor_master, f, indent=2)

    return bundle_path
