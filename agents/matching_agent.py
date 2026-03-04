# agents/matching_agent.py
from __future__ import annotations  

import json  
import os    
import re    
from typing import Any, Dict, List, Optional, Tuple  

import yaml  

from utils.audit_logger import log_step  


def run_matching(bundle_path: str, run_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    log_step(run_path, "Matching (E) started")  # REQ: Audit log start

    # REQ: Use extracted invoice artifact from run directory (deterministic)
    invoice = _load_json(os.path.join(run_path, "extracted_invoice.json")) or context.get("extracted_invoice") or {}

    # REQ: Load PO + GRN from bundle (2-way needs PO, 3-way needs GRN)
    po = _load_json(os.path.join(bundle_path, "po.json"))
    grn = _load_json(os.path.join(bundle_path, "grn.json"))

    # REQ: Variance and tolerance checks must be policy-driven
    tolerances = _load_tolerances()

    # REQ: Structured matching output for auditors + downstream orchestrator
    result: Dict[str, Any] = {
        "status": "not_executed",         # REQ: deterministic status
        "mode": None,                    # REQ: 2-way or 3-way selection
        "tolerances": tolerances,        # REQ: show tolerances used (auditability)
        "matched_po": None,              # REQ: reference docs used in matching
        "matched_grn": None,
        "checks": [],                    # REQ: totals-level checks
        "line_item_checks": [],          # REQ: line-level checks
        "notes": [],                     # REQ: discrepancy evidence & missing doc notes
    }

    if po is None:
        # REQ: Discrepancy evidence (missing PO) + correct deterministic behavior
        result["notes"].append("po.json not provided; matching cannot run.")
        _write_json(run_path, "match_result.json", result)  # REQ: output artifact even on skip
        log_step(run_path, "Matching (E) skipped: missing po.json")  # REQ: audit trail
        return result

    # --- totals level (2-way) ---
    result["status"] = "completed"      # REQ: success status once matching runs
    result["mode"] = "2-way"            # REQ: 2-way matching executed
    result["matched_po"] = po.get("po_number")  # REQ: store PO reference for audit

    # REQ: totals comparison (Invoice total vs PO total)
    inv_total = _to_float(_get(invoice, "header.total_amount"))
    po_total = _to_float(po.get("total_amount"))

    # REQ: Variance and tolerance check (total variance)
    result["checks"].append(
        _variance_check(
            name="invoice_total_vs_po_total",           # REQ: documented check name
            left=inv_total,
            right=po_total,
            tolerance_pct=tolerances["total_variance_percent"],  # REQ: tolerance policy applied
        )
    )

    # --- line level (2-way) ---
    # REQ: line-level matching invoice lines to PO lines
    inv_lines = invoice.get("line_items") or []
    po_lines = po.get("line_items") or []
    result["line_item_checks"] = _match_lines(inv_lines, po_lines, tolerances)  # REQ: price/qty checks

    # --- 3-way (optional) ---
    if grn is not None:
        result["mode"] = "3-way"  # REQ: 3-way matching when GRN exists
        result["matched_grn"] = grn.get("grn_number")  # REQ: GRN reference for audit

        # REQ: total comparison (Invoice total vs GRN total) optional but useful evidence
        grn_total = _to_float(grn.get("total_amount"))
        result["checks"].append(
            _variance_check(
                name="invoice_total_vs_grn_total",
                left=inv_total,
                right=grn_total,
                tolerance_pct=tolerances["total_variance_percent"],
            )
        )

        # REQ: Handling complex delivery scenarios: split deliveries & partial receipts
        grn_lines = grn.get("line_items") or []
        result["line_item_checks"].extend(
            _three_way_qty_checks(inv_lines, po_lines, grn_lines, tolerances)
        )  # REQ: received qty variance checks across multiple GRNs

    _write_json(run_path, "match_result.json", result)  # REQ: deterministic output artifact
    log_step(run_path, f"Matching (E) completed (mode={result['mode']})")  # REQ: audit trail
    return result


def _load_json(path: str) -> Optional[Dict[str, Any]]:
    # REQ: deterministic file-based model for inputs
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None  # REQ: safe failure -> caller records missing/notes


def _write_json(run_path: str, filename: str, obj: Any) -> None:
    # REQ: write run artifacts for auditability
    with open(os.path.join(run_path, filename), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def _load_tolerances() -> Dict[str, float]:
    # REQ: policy-driven tolerances (YAML) + defaults for deterministic runs
    default = {
        "price_variance_percent": 5.0,
        "quantity_variance_percent": 5.0,
        "total_variance_percent": 2.0,
    }

    policies_path = os.path.join(os.getcwd(), "policies", "tolerance_policy.yaml")
    if not os.path.exists(policies_path):
        return default  # REQ: deterministic fallback when policy missing

    try:
        with open(policies_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        tol = (data.get("tolerances") or {})
        return {
            "price_variance_percent": float(tol.get("price_variance_percent", default["price_variance_percent"])),
            "quantity_variance_percent": float(tol.get("quantity_variance_percent", default["quantity_variance_percent"])),
            "total_variance_percent": float(tol.get("total_variance_percent", default["total_variance_percent"])),
        }
    except Exception:
        return default  # REQ: deterministic behavior even if YAML is malformed


def _to_float(val: Any) -> Optional[float]:
    # REQ: normalization for numeric comparisons
    try:
        if val is None:
            return None
        s = str(val).strip().replace(" ", "").replace(",", "")
        return float(s)
    except Exception:
        return None


def _get(obj: Dict[str, Any], dotted_path: str) -> Any:
    # REQ: access nested fields (header.total_amount) without crashes
    cur: Any = obj
    for part in dotted_path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _variance_check(name: str, left: Optional[float], right: Optional[float], tolerance_pct: float) -> Dict[str, Any]:
    # REQ: variance + tolerance check for totals/amounts
    if left is None or right is None:
        return {"check": name, "ok": False, "reason": "missing values"}  # REQ: discrepancy evidence

    diff = left - right
    pct = (abs(diff) / right * 100.0) if right != 0 else 0.0
    ok = pct <= tolerance_pct
    return {
        "check": name,                    # REQ: documented check id
        "ok": ok,                         # REQ: pass/fail for orchestrator
        "left": round(left, 2),
        "right": round(right, 2),
        "variance": round(diff, 2),
        "variance_pct": round(pct, 2),
        "tolerance_pct": float(tolerance_pct),
    }


def _norm_text(text: Any) -> str:
    # REQ: description-based matching support
    s = str(text or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _line_key(line: Dict[str, Any]) -> Tuple[str, str]:
    # REQ: match by stable keys (sku/item_id), else fallback to normalized description
    for k in ("item_id", "sku", "product_code"):
        if line.get(k):
            return (k, str(line.get(k)).strip().lower())
    return ("description", _norm_text(line.get("description")))


def _match_lines(inv_lines: List[Dict[str, Any]], po_lines: List[Dict[str, Any]], tol: Dict[str, float]) -> List[Dict[str, Any]]:
    # REQ: 2-way line matching with qty/price variance checks
    results: List[Dict[str, Any]] = []
    if not inv_lines or not po_lines:
        return [{
            "check": "line_items_present",
            "ok": False,
            "reason": "missing line_items in invoice or PO"  # REQ: missing documentation evidence
        }]

    # REQ: deterministic match index for PO lines
    po_index: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for pl in po_lines:
        key = _line_key(pl)
        po_index.setdefault(key, []).append(pl)

    for il in inv_lines:
        key = _line_key(il)
        candidates = po_index.get(key, [])
        if not candidates:
            # REQ: discrepancy documentation when invoice line has no PO line
            results.append({
                "line": il.get("line_number"),
                "key": {"type": key[0], "value": key[1]},
                "ok": False,
                "reason": "no matching PO line",
            })
            continue

        pl = candidates[0]  # REQ: deterministic choice
        qty_ok = _pct_ok(_to_float(il.get("quantity")), _to_float(pl.get("quantity")), tol["quantity_variance_percent"])
        price_ok = _pct_ok(_to_float(il.get("unit_price")), _to_float(pl.get("unit_price")), tol["price_variance_percent"])

        # REQ: line-level variance checks result
        results.append({
            "line": il.get("line_number"),
            "key": {"type": key[0], "value": key[1]},
            "ok": bool(qty_ok and price_ok),
            "qty_ok": qty_ok,
            "price_ok": price_ok,
        })

    return results


def _three_way_qty_checks(inv_lines: List[Dict[str, Any]], po_lines: List[Dict[str, Any]], grn_lines: List[Dict[str, Any]], tol: Dict[str, float]) -> List[Dict[str, Any]]:
    # REQ: 3-way matching focusing on received qty vs invoice qty (supports split deliveries)
    if not grn_lines:
        return [{"check": "grn_line_items_present", "ok": False, "reason": "missing GRN line_items"}]

    # REQ: index GRN lines to support multiple receipts (split deliveries)
    grn_index: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for gl in grn_lines:
        key = _line_key(gl)
        grn_index.setdefault(key, []).append(gl)

    out: List[Dict[str, Any]] = []
    for il in inv_lines:
        key = _line_key(il)
        gls = grn_index.get(key, [])
        if not gls:
            out.append({
                "check": "invoice_line_vs_grn_line",
                "line": il.get("line_number"),
                "key": {"type": key[0], "value": key[1]},
                "ok": False,
                "reason": "no matching GRN line",  # REQ: missing receipt evidence
            })
            continue

        # REQ: split delivery handling (sum receipts)
        rec_qty = sum((_to_float(x.get("quantity")) or 0.0) for x in gls)
        inv_qty = _to_float(il.get("quantity"))
        ok = _pct_ok(inv_qty, rec_qty, tol["quantity_variance_percent"])

        # REQ: receipt variance output
        out.append({
            "check": "invoice_qty_vs_received_qty",
            "line": il.get("line_number"),
            "key": {"type": key[0], "value": key[1]},
            "invoice_qty": inv_qty,
            "received_qty": rec_qty,
            "ok": ok,
        })
    return out


def _pct_ok(a: Optional[float], b: Optional[float], tolerance_pct: float) -> bool:
    # REQ: tolerance evaluation utility used for qty and price
    if a is None or b is None:
        return False
    if b == 0:
        return a == 0
    diff = abs(a - b)
    pct = diff / b * 100.0
    return pct <= tolerance_pct