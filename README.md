# Intelligent Invoice Processing System (IIPS)

## Current review status

This repository now includes an end-to-end deterministic prototype for the capstone flow:

- Agent A: intake, context, evidence index, ignored-file detection
- Agent B: extraction to `extracted_invoice.json` and `line_items.csv`
- Agent C: vendor resolution
- Agent D: invoice validation
- Agent E: 2-way / 3-way matching with tolerance checks
- Agent F: compliance and tax/risk checks
- Agent G: duplicate/anomaly detection
- Agent H: exception triage and approval routing
- Agent I: final decisioning
- ERP-ready `posting_payload.json`
- `metrics.json` with throughput, extraction confidence, and exception-rate data
- Deterministic re-runs into `runs/run_<bundle_name>/`

## How to run

```bash
python main.py --bundle bundles/bundle_01
```

Artifacts are written to:

```text
runs/run_bundle_01/
```

## Main output artifacts

- `context.json`
- `extracted_invoice.json`
- `line_items.csv`
- `match_result.json`
- `compliance_findings.json`
- `anomaly_findings.json`
- `exceptions.md`
- `approval_packet.json`
- `posting_payload.json`
- `audit_log.md`
- `metrics.json`
- `decision.json`

## Notes

- The pipeline is file-based and deterministic for the same bundle input.
- Optional supporting files such as `po.json`, `grn.json`, `vendor_master.json`, and `history.json` are indexed automatically when present.
- Policies are YAML-driven from `policies/`.


## Streamlit demo

Run the app with:

```bash
streamlit run streamlit_app.py
```

The demo accepts a single uploaded invoice (PDF/image), automatically creates a temporary bundle with a generated `manifest.yaml`, runs the full pipeline, and displays:

- `decision.json`
- `metrics.json`
- `posting_payload.json`
- `approval_packet.json`
- `audit_log.md`
- additional JSON/CSV/Markdown artifacts

The upload helper stores repeated uploads of the same invoice into a stable hashed bundle folder under `.demo_uploads/`, which works well with deterministic run folders such as `runs/run_bundle_upload_<hash>/`.
