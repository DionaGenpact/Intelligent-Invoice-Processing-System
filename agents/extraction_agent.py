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
from PIL import Image, ImageOps, ImageFilter
import io

from utils.ocr_config import configure_tesseract

LOW_CONFIDENCE_THRESHOLD = 0.75


def run_extraction(bundle_path: str, run_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    configure_tesseract()
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
        existing_flags = context.setdefault("risk_flags", [])
        if "LOW_CONFIDENCE_FIELDS" not in existing_flags:
            existing_flags.append("LOW_CONFIDENCE_FIELDS")
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
        existing_flags = context.setdefault("risk_flags", [])
        if "EXTRACTION_SCHEMA_INVALID" not in existing_flags:
            existing_flags.append("EXTRACTION_SCHEMA_INVALID")
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

    invoice_patterns = [
        r"\bINV[- ]?\d+\b",
        r"\bIMG[- ]?\d+\b",
        r"\b[A-Z]{2,6}[- ]?\d{2,}\b",
        r"\bINVOICE\s*(NO|NUMBER|#)?\s*[:\-]?\s*[A-Z0-9-]+\b",
    ]
    inv = None
    for pattern in invoice_patterns:
        inv = _find_in_window(tokens, pattern, window_size=8) or _find_by_regex(tokens, pattern)
        if inv:
            break

    date_patterns = [
        r"\b\d{4}[-/]\d{2}[-/]\d{2}\b",
        r"\b\d{2}[-/]\d{2}[-/]\d{4}\b",
        r"\b\d{2}\.\d{2}\.\d{4}\b",
    ]
    date = None
    for pattern in date_patterns:
        date = _find_in_window(tokens, pattern, window_size=8) or _find_by_regex(tokens, pattern)
        if date:
            break
    

    vendor_id = manifest.get("vendor_id") or "UNKNOWN_VENDOR_ID"

    manifest_vendor_name = manifest.get("vendor_name")
    if manifest_vendor_name and manifest_vendor_name != "Uploaded Vendor":
        vendor_name = manifest_vendor_name
    else:
        vendor_name = _find_vendor_name(tokens) or "UNKNOWN_VENDOR"

    vendor_vat = manifest.get("vendor_vat") or "UNKNOWN_VENDOR_VAT"
    currency = manifest.get("expected_currency") or _find_currency(tokens) or "UNK"


    line_items, line_conf = _extract_line_items(tokens, page_number)

    calculated_from_lines = sum(
        item.get("line_total", item.get("quantity", 0) * item.get("unit_price", 0))
        for item in line_items
    )

    chosen_total = 0.0
    total_confidence = 0.0
    total_evidence = {"page": page_number, "bbox": [0, 0, 0, 0], "source": page.get("source", "ocr")}

    if total:
        extracted_total = float(total["value"])

        if calculated_from_lines > 0 and extracted_total < calculated_from_lines:
            chosen_total = float(calculated_from_lines)
            total_confidence = 0.85
            total_evidence = {"page": page_number, "bbox": [0, 0, 0, 0], "source": page.get("source", "ocr")}
        else:
            chosen_total = extracted_total
            total_confidence = float(total["confidence"])
            total_evidence = total["evidence"]
    else:
        chosen_total = float(calculated_from_lines)
        total_confidence = 0.85 if calculated_from_lines > 0 else 0.0
        total_evidence = {"page": page_number, "bbox": [0, 0, 0, 0], "source": page.get("source", "ocr")}

    invoice_number_value = inv["value"] if inv else "UNKNOWN"
    if invoice_number_value.upper().startswith("INVOICE"):
        parts = re.split(r"[:\-]\s*", invoice_number_value, maxsplit=1)
        if len(parts) == 2:
            invoice_number_value = parts[1].strip()

    invoice_date_value = date["value"].replace("/", "-").replace(".", "-") if date else "UNKNOWN"

    header = {
        "invoice_number": invoice_number_value,
        "invoice_date": invoice_date_value,
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


def _preprocess_image_for_ocr(img: Image.Image) -> Image.Image:
    img = img.convert("L")
    width, height = img.size
    img = img.resize((max(width * 2, width), max(height * 2, height)))
    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.SHARPEN)
    img = img.point(lambda x: 0 if x < 180 else 255, mode="1")
    return img


def _ocr_pil_image(img: Image.Image, page_number: int) -> Dict[str, Any]:
    processed = _preprocess_image_for_ocr(img)

    data = pytesseract.image_to_data(
        processed,
        output_type=Output.DICT,
        config=r"--oem 3 --psm 6"
    )

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
        text = str(t.get("text", ""))
        if rx.search(text):
            conf = max(0.0, min(1.0, (float(t.get("conf", 0)) / 100.0)))
            return {
                "value": text,
                "confidence": conf,
                "evidence": {
                    "page": t["page"],
                    "bbox": t["bbox"],
                    "source": t["source"]
                }
            }
    return None


def _find_vendor_name(tokens: List[Dict[str, Any]]) -> Optional[str]:

    patterns = [
        r"\bvendor[:\s]+([A-Za-z0-9&.,\- ]{3,})",
        r"\bsupplier[:\s]+([A-Za-z0-9&.,\- ]{3,})",
        r"\bfrom[:\s]+([A-Za-z0-9&.,\- ]{3,})",
    ]

    joined_text = " ".join(str(t.get("text", "")) for t in tokens)

    for pattern in patterns:
        m = re.search(pattern, joined_text, re.IGNORECASE)
        if m:
            value = m.group(1).strip()
            value = re.split(r"\s{2,}", value)[0].strip()
            if value and len(value) >= 3:
                return value

    rows = _group_tokens_into_rows(tokens, y_tolerance=12)

    for row in rows[:6]:
        row_text = " ".join(str(t.get("text", "")).strip() for t in row).strip()
        row_lower = row_text.lower()

        if not row_text:
            continue

        blocked = [
            "invoice",
            "invoice number",
            "invoice no",
            "date",
            "total",
            "amount due",
            "grand total",
            "subtotal",
            "bill to",
            "ship to"
        ]

        if any(b in row_lower for b in blocked):
            continue

        numeric_count = sum(
            1 for t in row
            if _parse_amount(str(t.get("text", ""))) is not None
            or _try_float(str(t.get("text", ""))) is not None
        )

        if numeric_count > 1:
            continue

        if len(row_text) >= 4:
            return row_text

    return None


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
            joined = " ".join(str(t.get("text", "")) for t in label_window)

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
        amt = _parse_amount(str(t.get("text", "")))
        if amt is None:
            continue

        conf = max(0.0, min(1.0, (float(t.get("conf", 0)) / 100.0)))
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
        amt = _parse_amount(str(t.get("text", "")))
        if amt is None:
            continue

        conf = max(0.0, min(1.0, (float(t.get("conf", 0)) / 100.0)))
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

        joined = " ".join(str(t.get("text", "")) for t in window)
        m = rx.search(joined)
        if not m:
            continue

        x0 = min(t["bbox"][0] for t in window)
        y0 = min(t["bbox"][1] for t in window)
        x1 = max(t["bbox"][2] for t in window)
        y1 = max(t["bbox"][3] for t in window)

        confs = [max(0.0, float(t.get("conf", 0))) for t in window]
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
    s = str(text).strip()
    if not s:
        return None

    s = s.replace("€", "").replace("$", "").replace("£", "").replace("CHF", "")
    s = s.replace("EUR", "").replace("USD", "").replace("GBP", "")
    s = s.replace(" ", "")

    s = re.sub(r"[^0-9,.\-]", "", s)

    if not s or s in {"-", ".", ","}:
        return None

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) in (2, 3):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")

    try:
        return float(s)
    except Exception:
        return None


def _group_tokens_into_rows(tokens: List[Dict[str, Any]], y_tolerance: int = 12) -> List[List[Dict[str, Any]]]:
    valid_tokens = [
        t for t in tokens
        if isinstance(t.get("bbox"), list) and len(t["bbox"]) == 4 and str(t.get("text", "")).strip()
    ]

    valid_tokens.sort(key=lambda t: (t["bbox"][1], t["bbox"][0]))
    rows: List[List[Dict[str, Any]]] = []

    for token in valid_tokens:
        y_top = token["bbox"][1]
        placed = False

        for row in rows:
            row_y = sum(t["bbox"][1] for t in row) / len(row)
            if abs(y_top - row_y) <= y_tolerance:
                row.append(token)
                placed = True
                break

        if not placed:
            rows.append([token])

    for row in rows:
        row.sort(key=lambda t: t["bbox"][0])

    return rows


def _is_header_like_row(row_text: str) -> bool:
    text = row_text.lower()
    header_keywords = [
        "description", "qty", "quantity", "unit", "unit price", "price",
        "amount", "total", "item", "product", "code", "vat", "tax"
    ]
    hits = sum(1 for kw in header_keywords if kw in text)
    return hits >= 2


def _is_noise_row(row_tokens: List[Dict[str, Any]], row_text: str) -> bool:
    text = row_text.strip().lower()
    if not text:
        return True

    noise_patterns = [
        "invoice", "invoice number", "invoice no", "bill to", "ship to",
        "subtotal", "grand total", "total due", "amount due", "balance due",
        "bank", "iban", "swift", "tax id", "page"
    ]

    if any(p in text for p in noise_patterns):
        numeric_count = sum(
            1 for t in row_tokens
            if _parse_amount(str(t.get("text", ""))) is not None or _try_float(str(t.get("text", ""))) is not None
        )
        if numeric_count < 2:
            return True

    useful_tokens = [t for t in row_tokens if str(t.get("text", "")).strip()]
    if len(useful_tokens) < 2:
        return True

    return False


def _clean_description_tokens(tokens: List[Dict[str, Any]]) -> str:
    parts = []

    for idx, t in enumerate(tokens):
        txt = str(t.get("text", "")).strip()
        if not txt:
            continue

        if idx == 0 and txt.isdigit():
            continue

        if _parse_amount(txt) is not None:
            continue

        if _try_float(txt) is not None:
            continue

        if txt.lower() == "x":
            continue

        parts.append(txt)

    return " ".join(parts).strip()


def _extract_line_from_row(row_tokens: List[Dict[str, Any]], page_number: int, line_no: int) -> Optional[Dict[str, Any]]:
    row_text = " ".join(str(t.get("text", "")).strip() for t in row_tokens).strip()

    if not row_text:
        return None

    if _is_header_like_row(row_text):
        return None

    if _is_noise_row(row_tokens, row_text):
        return None

    normalized_row = re.sub(r"\s+", " ", row_text).strip()

    pattern_with_row_no = re.match(
        r"^\s*(\d+)\s+(.+?)\s+(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:[.,]\d+)?)\s*$",
        normalized_row
    )
    if pattern_with_row_no:
        _, description_text, qty_text, unit_text = pattern_with_row_no.groups()

        qty = _try_float(qty_text)
        unit_price = _parse_amount(unit_text)

        if qty is not None and unit_price is not None and qty > 0:
            line_total = float(qty) * float(unit_price)

            conf_vals = [float(t.get("conf", 0) or 0) for t in row_tokens]
            conf = sum(max(0.0, c) for c in conf_vals) / (len(conf_vals) * 100.0) if conf_vals else 0.0
            conf = max(0.0, min(1.0, conf))

            return {
                "item": {
                    "line_number": line_no,
                    "description": description_text.strip() or "Item",
                    "quantity": float(qty),
                    "unit_price": float(unit_price),
                    "line_total": float(line_total),
                    "page": page_number
                },
                "confidence": conf
            }

    pattern_no_row_no = re.match(
        r"^\s*(.+?)\s+(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:[.,]\d+)?)\s*$",
        normalized_row
    )
    if pattern_no_row_no:
        description_text, qty_text, unit_text = pattern_no_row_no.groups()

        qty = _try_float(qty_text)
        unit_price = _parse_amount(unit_text)

        if qty is not None and unit_price is not None and qty > 0:
            line_total = float(qty) * float(unit_price)

            conf_vals = [float(t.get("conf", 0) or 0) for t in row_tokens]
            conf = sum(max(0.0, c) for c in conf_vals) / (len(conf_vals) * 100.0) if conf_vals else 0.0
            conf = max(0.0, min(1.0, conf))

            return {
                "item": {
                    "line_number": line_no,
                    "description": description_text.strip() or "Item",
                    "quantity": float(qty),
                    "unit_price": float(unit_price),
                    "line_total": float(line_total),
                    "page": page_number
                },
                "confidence": conf
            }

    parsed_values = []
    for idx, token in enumerate(row_tokens):
        txt = str(token.get("text", "")).strip()
        amt = _parse_amount(txt)
        if amt is not None:
            parsed_values.append((idx, amt, token))
            continue

        flt = _try_float(txt)
        if flt is not None:
            parsed_values.append((idx, flt, token))

    if len(parsed_values) < 2:
        return None

    parsed_values_sorted = sorted(parsed_values, key=lambda x: x[0])

    last_idx, last_val, last_token = parsed_values_sorted[-1]
    second_idx, second_val, second_token = parsed_values_sorted[-2]

    if len(parsed_values_sorted) >= 3:
        third_idx, third_val, third_token = parsed_values_sorted[-3]

        possible_qty = third_val
        possible_unit = second_val
        possible_total = last_val

        if possible_qty > 0 and possible_unit >= 0 and possible_total >= 0:
            calc = possible_qty * possible_unit
            tolerance = max(0.05, possible_total * 0.15)

            if abs(calc - possible_total) <= tolerance:
                desc_tokens = row_tokens[:third_idx]
                description = _clean_description_tokens(desc_tokens) or row_text

                conf_vals = [third_token["conf"], second_token["conf"], last_token["conf"]]
                conf = sum(max(0.0, float(x)) for x in conf_vals) / (len(conf_vals) * 100.0)
                conf = max(0.0, min(1.0, conf))

                return {
                    "item": {
                        "line_number": line_no,
                        "description": description,
                        "quantity": float(possible_qty),
                        "unit_price": float(possible_unit),
                        "line_total": float(possible_total),
                        "page": page_number
                    },
                    "confidence": conf
                }

    possible_qty = second_val
    possible_total = last_val

    if possible_qty > 0 and possible_total >= 0:
        desc_tokens = row_tokens[:second_idx]
        description = _clean_description_tokens(desc_tokens) or row_text

        unit_price = float(possible_total / possible_qty) if possible_qty != 0 else float(possible_total)

        conf_vals = [second_token["conf"], last_token["conf"]]
        conf = sum(max(0.0, float(x)) for x in conf_vals) / (len(conf_vals) * 100.0)
        conf = max(0.0, min(1.0, conf))

        return {
            "item": {
                "line_number": line_no,
                "description": description,
                "quantity": float(possible_qty),
                "unit_price": unit_price,
                "line_total": float(possible_total),
                "page": page_number
            },
            "confidence": conf
        }

    return None


def _extract_line_items(tokens: List[Dict[str, Any]], page_number: int):
    line_items = []
    line_conf = []
    line_no = 1

    rows = _group_tokens_into_rows(tokens, y_tolerance=12)

    for row in rows:
        extracted = _extract_line_from_row(row, page_number, line_no)
        if not extracted:
            continue

        item = extracted["item"]
        conf = extracted["confidence"]

        description = str(item.get("description", "")).strip()
        quantity = float(item.get("quantity", 0) or 0)
        unit_price = float(item.get("unit_price", 0) or 0)
        line_total = float(item.get("line_total", 0) or 0)

        if not description:
            continue
        if quantity <= 0:
            continue
        if unit_price < 0 or line_total < 0:
            continue

        lowered = description.lower()
        blocked_words = [
            "subtotal", "grand total", "total due", "amount due", "balance due",
            "vat", "tax", "discount", "invoice", "date", "bank"
        ]
        if any(word in lowered for word in blocked_words):
            continue

        line_items.append(item)
        line_conf.append({
            "line_number": line_no,
            "confidence": conf
        })
        line_no += 1

    return line_items, line_conf


def _try_float(text: str) -> Optional[float]:
    try:
        s = str(text).strip().replace(",", "")
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