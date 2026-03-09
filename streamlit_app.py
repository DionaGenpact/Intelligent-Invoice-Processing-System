from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from agents.orchestrator import run_pipeline
from utils.upload_bundle_builder import create_bundle_from_uploaded_invoice


st.set_page_config(page_title="IIPS Demo", layout="wide")
st.title("Intelligent Invoice Processing System (IIPS) Demo")
st.caption("Upload one invoice PDF/image, run the full pipeline, and inspect the artifacts.")

with st.sidebar:
    st.header("Upload settings")
    expected_currency = st.selectbox("Expected currency", ["EUR", "USD", "GBP"], index=0)
    vendor_id = st.text_input("Vendor ID", value="UPLOADED_VENDOR")
    vendor_name = st.text_input("Vendor name", value="Uploaded Vendor")
    vendor_vat = st.text_input("Vendor VAT", value="UNKNOWN_VENDOR_VAT")
    po_number = st.text_input("PO number", value="NON_PO")

uploaded = st.file_uploader(
    "Upload invoice (PDF or image)",
    type=["pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"],
)


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if uploaded is not None:
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("Uploaded file")
        st.write(f"**Name:** {uploaded.name}")
        st.write(f"**Size:** {uploaded.size} bytes")
    with col2:
        st.subheader("Run")
        if st.button("Run pipeline", type="primary"):
            try:
                bundle_path = create_bundle_from_uploaded_invoice(
                    uploaded.getvalue(),
                    uploaded.name,
                    expected_currency=expected_currency,
                    vendor_id=vendor_id,
                    vendor_name=vendor_name,
                    vendor_vat=vendor_vat,
                    po_number=po_number,
                )
                run_path = run_pipeline(bundle_path)
                st.session_state["last_run_path"] = run_path
                st.session_state["last_bundle_path"] = bundle_path
                st.success(f"Pipeline completed: {run_path}")
            except Exception as exc:
                st.exception(exc)

run_path = st.session_state.get("last_run_path")
if run_path and os.path.exists(run_path):
    st.divider()
    st.subheader("Run summary")
    st.write(f"**Bundle path:** `{st.session_state.get('last_bundle_path')}`")
    st.write(f"**Run path:** `{run_path}`")

    decision = _read_json(os.path.join(run_path, "decision.json")) if os.path.exists(os.path.join(run_path, "decision.json")) else {}
    metrics = _read_json(os.path.join(run_path, "metrics.json")) if os.path.exists(os.path.join(run_path, "metrics.json")) else {}
    posting_payload = _read_json(os.path.join(run_path, "posting_payload.json")) if os.path.exists(os.path.join(run_path, "posting_payload.json")) else {}
    approval_packet = _read_json(os.path.join(run_path, "approval_packet.json")) if os.path.exists(os.path.join(run_path, "approval_packet.json")) else {}

    a, b, c = st.columns(3)
    a.metric("Decision", decision.get("status", "N/A"))
    b.metric("Exceptions", metrics.get("exceptions", {}).get("count", 0))
    c.metric("Risk flags", metrics.get("risk_flags_count", 0))

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Decision",
        "Metrics",
        "Posting Payload",
        "Approval Packet",
        "Audit Log",
    ])

    with tab1:
        st.json(decision)
    with tab2:
        st.json(metrics)
    with tab3:
        st.json(posting_payload)
    with tab4:
        st.json(approval_packet)
    with tab5:
        audit_path = os.path.join(run_path, "audit_log.md")
        if os.path.exists(audit_path):
            st.code(Path(audit_path).read_text(encoding="utf-8"), language="markdown")

    artifact_map = {
        "Extracted invoice": "extracted_invoice.json",
        "Match result": "match_result.json",
        "Exceptions": "exceptions.md",
        "Line items CSV": "line_items.csv",
        "Compliance findings": "compliance_findings.json",
        "Anomaly findings": "anomaly_findings.json",
    }
    st.subheader("Additional artifacts")
    for label, filename in artifact_map.items():
        path = os.path.join(run_path, filename)
        if not os.path.exists(path):
            continue
        with st.expander(label):
            if filename.endswith(".json"):
                st.json(_read_json(path))
            else:
                st.code(Path(path).read_text(encoding="utf-8"), language="text")
else:
    st.info("Upload an invoice and run the pipeline to see artifacts here.")
