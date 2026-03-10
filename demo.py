from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from agents.orchestrator import run_pipeline
from utils.upload_bundle_builder import create_bundle_from_uploaded_invoice


st.set_page_config(page_title="IIPS Demo", layout="wide")

st.title("Intelligent Invoice Processing System (IIPS)")
st.caption("Process invoices automatically using the multi-agent pipeline.")



# Hidden defaults (not visible in UI)


DEFAULT_EXPECTED_CURRENCY = "EUR"
DEFAULT_VENDOR_ID = "UPLOADED_VENDOR"
DEFAULT_VENDOR_NAME = "Uploaded Vendor"
DEFAULT_VENDOR_VAT = "UNKNOWN_VENDOR_VAT"
DEFAULT_PO_NUMBER = "NON_PO"

BUNDLES_DIR = Path("bundles")


# Helpers
def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_invoice(bundle):
    for name in ["invoice.pdf", "invoice.png", "invoice.jpg", "invoice.jpeg"]:
        p = bundle / name
        if p.exists():
            return p
    return None


def _list_sample_bundles():
    if not BUNDLES_DIR.exists():
        return []

    result = []
    for b in sorted(BUNDLES_DIR.iterdir()):
        if b.is_dir() and _find_invoice(b):
            result.append(b.name)

    return result


sample_bundles = _list_sample_bundles()


# Mode selection


st.subheader("Choose how to run the demo")

mode = st.radio(
    "Choose invoice source",
    ["Try demo invoice", "Upload your own invoice"],
    horizontal=True,
    label_visibility="collapsed",
)

st.divider()


# DEMO INVOICE MODE


if mode == "Try demo invoice":

    if not sample_bundles:
        st.warning("No demo invoices found in the bundles folder.")
    else:
        selected = st.selectbox(
            "Select a demo scenario",
            sample_bundles,
        )

        bundle_path = BUNDLES_DIR / selected

        st.write(f"**Scenario:** `{selected}`")

        if st.button("Run demo pipeline", type="primary"):

            try:
                run_path = run_pipeline(str(bundle_path))

                st.session_state["last_run_path"] = run_path
                st.session_state["last_bundle_path"] = str(bundle_path)

                st.success("Pipeline executed successfully!")

            except Exception as exc:
                st.exception(exc)



# UPLOAD MODE


else:

    uploaded = st.file_uploader(
        "Upload invoice (PDF or image)",
        type=["pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"],
    )

    if uploaded:

        col1, col2 = st.columns([1, 1])

        with col1:
            st.write(f"**File:** {uploaded.name}")
            st.write(f"**Size:** {uploaded.size} bytes")

        with col2:
            if st.button("Run pipeline", type="primary"):

                try:
                    bundle_path = create_bundle_from_uploaded_invoice(
                        uploaded.getvalue(),
                        uploaded.name,
                        expected_currency=DEFAULT_EXPECTED_CURRENCY,
                        vendor_id=DEFAULT_VENDOR_ID,
                        vendor_name=DEFAULT_VENDOR_NAME,
                        vendor_vat=DEFAULT_VENDOR_VAT,
                        po_number=DEFAULT_PO_NUMBER,
                    )

                    run_path = run_pipeline(bundle_path)

                    st.session_state["last_run_path"] = run_path
                    st.session_state["last_bundle_path"] = bundle_path

                    st.success("Pipeline executed successfully!")

                except Exception as exc:
                    st.exception(exc)



# RESULTS VIEW


run_path = st.session_state.get("last_run_path")

if run_path and os.path.exists(run_path):

    st.divider()

    st.subheader("Run Results")

    st.write(f"**Bundle:** `{st.session_state.get('last_bundle_path')}`")
    st.write(f"**Run folder:** `{run_path}`")

    decision = _read_json(os.path.join(run_path, "decision.json")) if os.path.exists(os.path.join(run_path, "decision.json")) else {}
    metrics = _read_json(os.path.join(run_path, "metrics.json")) if os.path.exists(os.path.join(run_path, "metrics.json")) else {}
    posting_payload = _read_json(os.path.join(run_path, "posting_payload.json")) if os.path.exists(os.path.join(run_path, "posting_payload.json")) else {}
    approval_packet = _read_json(os.path.join(run_path, "approval_packet.json")) if os.path.exists(os.path.join(run_path, "approval_packet.json")) else {}

    c1, c2, c3 = st.columns(3)

    c1.metric("Decision", decision.get("status", "N/A"))
    c2.metric("Exceptions", metrics.get("exceptions", {}).get("count", 0))
    c3.metric("Risk Flags", metrics.get("risk_flags_count", 0))

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
        audit = os.path.join(run_path, "audit_log.md")
        if os.path.exists(audit):
            st.code(Path(audit).read_text(), language="markdown")

    artifact_map = {
        "Extracted Invoice": "extracted_invoice.json",
        "Match Result": "match_result.json",
        "Exceptions": "exceptions.md",
        "Line Items": "line_items.csv",
        "Compliance Findings": "compliance_findings.json",
        "Anomaly Findings": "anomaly_findings.json",
    }

    st.subheader("Additional Artifacts")

    for label, filename in artifact_map.items():

        path = os.path.join(run_path, filename)

        if not os.path.exists(path):
            continue

        with st.expander(label):

            if filename.endswith(".json"):
                st.json(_read_json(path))

            else:
                st.code(Path(path).read_text())

else:

    st.info("Choose a demo invoice or upload your own to run the pipeline.")