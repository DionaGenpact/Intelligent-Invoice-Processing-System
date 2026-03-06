import os
import json
import csv
import re
from typing import Dict, Any, List, Optional

from utils.schema_validator import validate_json
from utils.audit_logger import log_step

import pytesseract
from pytesseract import Output
import pdfplumber
import fitz
from PIL import Image
import io

pytesseract.pytesseract.tesseract_cmd = r"C:\Users\602000885\tesseract.exe"

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

    pages = _parse_invoice(invoice_path)
    page_results = [_extract_from_page(p, manifest) for p in pages]
    aggregated = _aggregate_pages(page_results)
    confidence_block = _compute_confidence(aggregated)

    low_conf_fields = _detect_low_confidence(confidence_block)
    if low_conf_fields:
        context.setdefault("risk_flags", []).append("LOW_CONFIDENCE_FIELDS")
        context["low_confidence_fields"] = low_conf_fields
        log_step(run_path, f"Low confidence fields detected: {low_conf_fields}")

    extracted_data = {
        "header": aggregated["header"],
        "line_items": aggregated["line_items"],
        "confidence": confidence_block,
        "evidence": aggregated["evidence"],
        "aggregation": aggregated["aggregation"]
    }

    schema_path = os.path.join(os.path.dirname(__file__), "..", "schemas", "extraction.schema.json")
    schema_path = os.path.abspath(schema_path)

    schema_errors = validate_json(extracted_data, schema_path)
    if schema_errors:
        log_step(run_path, f"Extraction schema validation failed: {schema_errors}")
        context.setdefault("risk_flags", []).append("EXTRACTION_SCHEMA_INVALID")
        context["extraction_schema_errors"] = schema_errors

        with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
            json.dump(context, f, indent=4)

        raise ValueError("Extraction schema validation failed")

    with open(os.path.join(run_path, "extracted_invoice.json"), "w", encoding="utf-8") as f:
        json.dump(extracted_data, f, indent=2)

    _export_csv(run_path, aggregated["line_items"])

    context["extraction_result"] = extracted_data
    with open(os.path.join(run_path, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    log_step(run_path, "Extraction (Agent B) completed")
    return extracted_data


def _is_pdf(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".pdf"


def _parse_invoice(invoice_path: str) -> List[Dict[str, Any]]:
    if _is_pdf(invoice_path):
        pages = _extract_pdf_text_words(invoice_path)
        if _text_sufficient(pages):
            return pages
        return _ocr_pdf_pages(invoice_path)
    return [_ocr_image(invoice_path, page_number=1)]


def _extract_from_page(page: Dict[str, Any], manifest: Dict[str, Any]) -> Dict[str, Any]:
    tokens = page.get("tokens", [])
    page_number = page.get("page_number", 1)

    total = _find_total_amount(tokens)
    inv = _find_in_window(tokens, r"\bINV[- ]?\d+\b") or _find_by_regex(tokens, r"\bINV[- ]?\d+\b")
    date = _find_in_window(tokens, r"\b\d{4}[-/]\d{2}[-/]\d{2}\b") or _find_by_regex(tokens, r"\b\d{4}[-/]\d{2}[-/]\d{2}\b")

    vendor_id = manifest.get("vendor_id") or "UNKNOWN_VENDOR_ID"
    vendor_name = manifest.get("vendor_name") or "UNKNOWN_VENDOR"
    vendor_vat = manifest.get("vendor_vat") or "UNKNOWN_VENDOR_VAT"
    currency = manifest.get("expected_currency") or _find_currency(tokens) or "UNK"

    line_items, line_conf = _extract_line_items(tokens, page_number)

    calculated_from_lines = sum(
        item.get("line_total", item.get("quantity", 0) * item.get("unit_price", 0))
        for item in line_items
    )

    chosen_total = 0.0
    total_confidence = 0.0
    total_evidence = {"page": page_number, "bbox": [0, 0, 0, 0], "source": "ocr"}

    if total:
        extracted_total = float(total["value"])

        if calculated_from_lines > 0 and extracted_total < calculated_from_lines:
            chosen_total = float(calculated_from_lines)
            total_confidence = 0.85
            total_evidence = {"page": page_number, "bbox": [0, 0, 0, 0], "source": "ocr"}
        else:
            chosen_total = extracted_total
            total_confidence = float(total["confidence"])
            total_evidence = total["evidence"]
    else:
        chosen_total = float(calculated_from_lines)
        total_confidence = 0.85 if calculated_from_lines > 0 else 0.0
        total_evidence = {"page": page_number, "bbox": [0, 0, 0, 0], "source": "ocr"}

    header = {
        "invoice_number": inv["value"] if inv else "UNKNOWN",
        "invoice_date": date["value"].replace("/", "-") if date else "UNKNOWN",
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "vendor_vat": vendor_vat,
        "currency": currency,
        "total_amount": chosen_total,
    }

    evidence: Dict[str, Any] = {}
    field_conf: Dict[str, float] = {}

    def _set(field: str, obj: Optional[Dict[str, Any]]) -> None:
        if not obj:
            field_conf[field] = 0.0
            return
        evidence[field] = obj["evidence"]
        field_conf[field] = float(obj["confidence"])

    _set("invoice_number", inv)
    _set("invoice_date", date)

    evidence["total_amount"] = total_evidence
    field_conf["total_amount"] = total_confidence

    for key in ("invoice_number", "invoice_date"):
        if header.get(key) == "UNKNOWN":
            field_conf[key] = 0.0

    field_conf["vendor_id"] = 1.0 if vendor_id != "UNKNOWN_VENDOR_ID" else 0.6
    field_conf["vendor_name"] = 1.0 if vendor_name != "UNKNOWN_VENDOR" else 0.6
    field_conf["vendor_vat"] = 1.0 if vendor_vat != "UNKNOWN_VENDOR_VAT" else 0.6
    field_conf["currency"] = 1.0 if currency not in ("UNK", "", None) else 0.6

    evidence["vendor_id"] = {"page": page_number, "bbox": [0, 0, 0, 0], "source": "manifest"}
    evidence["vendor_name"] = {"page": page_number, "bbox": [0, 0, 0, 0], "source": "manifest"}
    evidence["vendor_vat"] = {"page": page_number, "bbox": [0, 0, 0, 0], "source": "manifest"}
    evidence["currency"] = {"page": page_number, "bbox": [0, 0, 0, 0], "source": "manifest"}

    return {
        "page_number": page_number,
        "header": header,
        "line_items": line_items,
        "evidence": evidence,
        "confidence": {
            "fields": field_conf,
            "line_items": line_conf
        }
    }


def _extract_pdf_text_words(pdf_path: str) -> List[Dict[str, Any]]:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            words = page.extract_words() or []
            norm_words = []
            for w in words:
                norm_words.append({
                    "text": w.get("text", ""),
                    "bbox": [w.get("x0"), w.get("top"), w.get("x1"), w.get("bottom")],
                    "conf": 95,
                    "page": i,
                    "source": "pdf_text"
                })
            pages.append({
                "page_number": i,
                "tokens": norm_words,
                "source": "pdf_text"
            })
    return pages


def _text_sufficient(pages: List[Dict[str, Any]], min_words: int = 30) -> bool:
    total_words = sum(len(p.get("tokens", [])) for p in pages)
    return total_words >= min_words


def _ocr_pdf_pages(pdf_path: str, dpi: int = 200) -> List[Dict[str, Any]]:
    doc = fitz.open(pdf_path)
    pages = []
    for idx in range(len(doc)):
        page = doc[idx]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        pages.append(_ocr_pil_image(img, page_number=idx + 1))
    return pages


def _ocr_pil_image(img: Image.Image, page_number: int) -> Dict[str, Any]:
    data = pytesseract.image_to_data(img, output_type=Output.DICT)
    tokens = []

    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue

        try:
            conf = float(data["conf"][i])
        except Exception:
            conf = 0.0

        if conf < 0:
            continue

        left = int(data["left"][i])
        top = int(data["top"][i])
        width = int(data["width"][i])
        height = int(data["height"][i])

        tokens.append({
            "text": text,
            "bbox": [left, top, left + width, top + height],
            "conf": conf,
            "page": page_number,
            "source": "ocr"
        })

    return {
        "page_number": page_number,
        "tokens": tokens,
        "source": "ocr"
    }


def _ocr_image(image_path: str, page_number: int = 1) -> Dict[str, Any]:
    img = Image.open(image_path)
    return _ocr_pil_image(img, page_number=page_number)


def _aggregate_pages(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    best_header = {}
    best_conf = {}
    best_evidence = {}
    all_line_items = []

    for p in pages:
        hdr = p["header"]
        conf = p["confidence"]["fields"]
        ev = p["evidence"]

        for k, v in hdr.items():
            c = conf.get(k, 0.0)
            if (k not in best_conf) or (c > best_conf[k]):
                best_conf[k] = c
                best_header[k] = v
                if k in ev:
                    best_evidence[k] = ev[k]

        all_line_items.extend(p.get("line_items", []))

    for idx, li in enumerate(all_line_items, start=1):
        li["line_number"] = idx

    return {
        "header": best_header,
        "line_items": all_line_items,
        "evidence": best_evidence,
        "best_field_conf": best_conf,
        "aggregation": {
            "pages_processed": len(pages),
            "multi_page_detected": len(pages) > 1
        }
    }


def _find_by_regex(tokens: List[Dict[str, Any]], pattern: str) -> Optional[Dict[str, Any]]:
    rx = re.compile(pattern, re.IGNORECASE)
    for t in tokens:
        if rx.search(t["text"]):
            conf = max(0.0, min(1.0, (t["conf"] / 100.0)))
            return {
                "value": t["text"],
                "confidence": conf,
                "evidence": {
                    "page": t["page"],
                    "bbox": t["bbox"],
                    "source": t["source"]
                }
            }
    return None


def _find_currency(tokens: List[Dict[str, Any]]) -> Optional[str]:
    hit = _find_by_regex(tokens, r"\b(EUR|USD|GBP|CHF)\b")
    return hit["value"].upper() if hit else None


def _find_total_amount(tokens: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    priority_patterns = [
        r"\bgrand\s+total\b",
        r"\btotal\s+due\b",
        r"\bamount\s+due\b",
        r"\binvoice\s+total\b",
        r"\bbalance\s+due\b",
        r"\btotal\b"
    ]

    for pattern in priority_patterns:
        for i in range(len(tokens)):
            label_window = tokens[i:i + 6]
            joined = " ".join(t["text"] for t in label_window)

            if re.search(pattern, joined, re.IGNORECASE):
                amount_window = tokens[i:i + 12]
                amounts = _find_all_amounts_in_tokens(amount_window)
                if amounts:
                    return max(amounts, key=lambda x: x["value"])

    all_amounts = _find_all_amounts_in_tokens(tokens)
    if all_amounts:
        return max(all_amounts, key=lambda x: x["value"])

    return None


def _find_amount_in_tokens(tokens: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for t in tokens:
        amt = _parse_amount(t["text"])
        if amt is None:
            continue

        conf = max(0.0, min(1.0, (t["conf"] / 100.0)))
        return {
            "value": float(amt),
            "confidence": conf,
            "evidence": {
                "page": t["page"],
                "bbox": t["bbox"],
                "source": t["source"]
            }
        }
    return None


def _find_all_amounts_in_tokens(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    amounts = []
    for t in tokens:
        amt = _parse_amount(t["text"])
        if amt is None:
            continue

        conf = max(0.0, min(1.0, (t["conf"] / 100.0)))
        amounts.append({
            "value": float(amt),
            "confidence": conf,
            "evidence": {
                "page": t["page"],
                "bbox": t["bbox"],
                "source": t["source"]
            }
        })
    return amounts


def _find_in_window(tokens: List[Dict[str, Any]], pattern: str, window_size: int = 6) -> Optional[Dict[str, Any]]:
    rx = re.compile(pattern, re.IGNORECASE)

    for i in range(len(tokens)):
        window = tokens[i:i + window_size]
        window = [t for t in window if isinstance(t.get("bbox"), list) and len(t["bbox"]) == 4]
        if not window:
            continue

        joined = " ".join(t["text"] for t in window)
        m = rx.search(joined)
        if not m:
            continue

        x0 = min(t["bbox"][0] for t in window)
        y0 = min(t["bbox"][1] for t in window)
        x1 = max(t["bbox"][2] for t in window)
        y1 = max(t["bbox"][3] for t in window)

        confs = [max(0.0, float(t["conf"])) for t in window]
        conf = sum(confs) / (len(confs) * 100.0)
        conf = max(0.0, min(1.0, conf))

        return {
            "value": m.group(0),
            "confidence": conf,
            "evidence": {
                "page": window[0]["page"],
                "bbox": [x0, y0, x1, y1],
                "source": window[0]["source"]
            },
        }
    return None


def _parse_amount(text: str) -> Optional[float]:
    s = text.strip()
    s = s.replace("€", "").replace("$", "").replace("£", "").replace(" ", "")

    if not re.match(r"^\d{1,3}(,\d{3})*(\.\d{2})$|^\d+(\.\d{2})$", s):
        return None

    try:
        return float(s.replace(",", ""))
    except Exception:
        return None


def _extract_line_items(tokens: List[Dict[str, Any]], page_number: int):
    line_items = []
    line_conf = []
    line_no = 1

    i = 0
    while i < len(tokens) - 2:
        qty = _try_float(tokens[i]["text"])
        unit = _parse_amount(tokens[i + 1]["text"])
        total = _parse_amount(tokens[i + 2]["text"])

        if qty is not None and unit is not None and total is not None:
            desc_tokens = []
            j = i - 1

            while j >= 0 and len(desc_tokens) < 5:
                prev_text = tokens[j]["text"]
                if _try_float(prev_text) is not None or _parse_amount(prev_text) is not None:
                    break
                desc_tokens.insert(0, prev_text)
                j -= 1

            desc = " ".join(desc_tokens).strip() or "Item"

            line_items.append({
                "line_number": line_no,
                "description": desc,
                "quantity": float(qty),
                "unit_price": float(unit),
                "line_total": float(total),
                "page": page_number
            })

            confs = [tokens[i]["conf"], tokens[i + 1]["conf"], tokens[i + 2]["conf"]]
            c = sum(max(0.0, float(x)) for x in confs) / (len(confs) * 100.0)
            c = max(0.0, min(1.0, c))

            line_conf.append({
                "line_number": line_no,
                "confidence": c
            })

            line_no += 1
            i += 3
            continue

        i += 1

    return line_items, line_conf


def _try_float(text: str) -> Optional[float]:
    try:
        s = text.strip().replace(",", "")
        return float(s)
    except Exception:
        return None


def _compute_confidence(aggregated: Dict[str, Any]) -> Dict[str, Any]:
    fields = dict(aggregated.get("best_field_conf", {}))

    required = [
        "invoice_number",
        "invoice_date",
        "vendor_id",
        "vendor_name",
        "vendor_vat",
        "currency",
        "total_amount"
    ]

    for k in required:
        fields.setdefault(k, 0.0)

    line_items = aggregated.get("line_items", [])
    line_conf = [
        {"line_number": li.get("line_number", i + 1), "confidence": 0.80}
        for i, li in enumerate(line_items)
    ]

    return {
        "fields": fields,
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