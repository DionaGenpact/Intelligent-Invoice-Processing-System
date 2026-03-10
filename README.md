# Intelligent Invoice Processing System (IIPS)

Intelligent Invoice Processing System (IIPS) is a deterministic, file-based capstone prototype for automated accounts payable invoice handling. It processes an invoice bundle, runs a multi-agent pipeline, and writes traceable run artifacts for review, approval routing, and ERP-style posting.

## What is implemented

The current project includes an end-to-end pipeline with these agents:

- **Agent A – Intake & Context**: loads `manifest.yaml`, builds `context.json`, indexes evidence, and records ignored files and risk flags.
- **Agent B – OCR & Extraction**: extracts invoice header fields and normalized line items from PDF/image inputs, writes `extracted_invoice.json` and `line_items.csv`.
- **Agent C – Vendor Resolution**: resolves vendors against `vendor_master.json`, flags new vendors, bank changes, VAT mismatches, and high-risk vendors.
- **Agent D – Invoice Validation**: validates extracted invoice content and totals.
- **Agent E – Matching**: performs 2-way and 3-way matching against `po.json` and optional `grn.json`, including tolerance checks and currency checks.
- **Agent F – Compliance & Risk**: applies VAT/required-field checks and computes policy-driven risk.
- **Agent G – Anomaly Detection**: checks duplicate invoices, bank changes, repeated bank changes, and approval-threshold anomalies.
- **Agent H – Exception Triage**: consolidates issues, creates `exceptions.md`, and outputs `approval_packet.json`.
- **Agent I – Decisioning**: produces the final decision in `decision.json`.
- **Posting Payload Agent**: writes `posting_payload.json` in an ERP-style structure.

The pipeline also writes:

- `audit_log.md`
- `metrics.json`
- `policy_result.json`
- `normalization.json`
- `invoice_validation.json`
- `vendor_resolution.json`
- `match_result.json`
- `compliance_findings.json`
- `anomaly_findings.json`

## Current scenario coverage

The repository currently contains **12 deterministic test bundles**:

1. `bundle_01` – clean 2-way match → **APPROVE**
2. `bundle_02_total_mismatch` – invoice header total does not equal line-item sum → **REJECT**
3. `bundle_03_no_po` – missing `po.json` → **REVIEW**
4. `bundle_04_vendor_risk` – high-risk vendor from master data → **REVIEW**
5. `bundle_05_currency_error` – invoice currency differs from PO currency → **REVIEW**
6. `bundle_06_three_way_match` – successful PO + GRN match → **APPROVE**
7. `bundle_07_quantity_variance` – quantity variance beyond tolerance → **REVIEW**
8. `bundle_08_price_variance` – price variance beyond tolerance → **REVIEW**
9. `bundle_09_duplicate` – duplicate invoice detected from history → **REJECT**
10. `bundle_10_split_delivery` – split-delivery GRN totals reconcile correctly → **APPROVE**
11. `bundle_11_new_vendor` – new vendor not found in master data → **REVIEW**
12. `bundle_12` – image invoice input with successful extraction/match → **APPROVE**

## Project structure

```text
agents/      Pipeline agents
bundles/     Reference invoice bundles used for testing/demo
policies/    YAML policies for tolerances, approvals, risk, and tax rules
schemas/     JSON schemas for key artifacts
runs/        Deterministic output folders: runs/run_<bundle_name>/
utils/       Shared helpers (audit logging, OCR config, schema validation, uploads)
main.py      CLI entry point
demo.py  Demo UI
```

## Requirements

Install Python dependencies:

```bash
pip install -r requirements.txt
```

### OCR requirement for Windows

For image OCR (`.png`, `.jpg`, `.jpeg`, `.webp`) and scanned PDFs, the external **Tesseract OCR** program must also be installed.

1. Install Tesseract OCR on Windows.
2. Add the Tesseract installation folder to `PATH`, or set:

```powershell
$env:TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
```

The project uses `utils/ocr_config.py` to resolve the executable from `TESSERACT_CMD` or `PATH`.

## How to run

### Run a bundle from the command line

```bash
python main.py --bundle bundles/bundle_01
```

Artifacts are written to:

```text
runs/run_bundle_01/
```

### Run the Streamlit demo

```bash
streamlit run demo.py
```

The demo accepts a single uploaded invoice (PDF/image), creates a temporary deterministic bundle under `.demo_uploads/`, runs the full pipeline, and shows the generated artifacts.

## Output artifacts

A successful run produces these core artifacts:

- `context.json`
- `validation.json`
- `extracted_invoice.json`
- `line_items.csv`
- `normalization.json`
- `invoice_validation.json`
- `vendor_resolution.json`
- `match_result.json`
- `compliance_findings.json`
- `anomaly_findings.json`
- `exceptions.md`
- `approval_packet.json`
- `decision.json`
- `posting_payload.json`
- `policy_result.json`
- `audit_log.md`
- `metrics.json`

## Testing

### Run all scenario bundles

```bash
python test/test_all_bundles.py
```

This now verifies both:

- that key artifacts are generated for every bundle
- that each bundle returns the expected final decision

### Run idempotency checks

```bash
python test/test_idempotency.py
```

This reruns each bundle twice and verifies deterministic outputs for the main JSON artifacts.

## Notes on current scope

This repository meets the core prototype requirements for deterministic bundle processing, artifact generation, matching, exception routing, and auditability.

