# Intelligent Invoice Processing System (IIPS)

## Current Status – Scaffold Phase

The repository structure and agent architecture (A–I) have been initialized to enable parallel development across three interns.


## What Has Been Done

- Project structure finalized:
  - `agents/`, `schemas/`, `policies/`, `bundles/`, `scripts/`, `utils/`
- Agent files created (scaffold / placeholders)
- Initial Policy Pack (YAML configuration files) added
- Base schemas defined
- Branch structure aligned with workload split

Most agent files currently contain structural placeholders only.
Core business logic is not yet implemented.



##  Work Split Overview

### Intern 1 – Platform & Orchestration (Agents A & I)
Responsible for:
- Intake & context building (`intake_agent.py`)
- Orchestrator flow control (`orchestrator.py`)
- Run management & execution pipeline
- Schema validation integration
- Ensuring deterministic run structure

**Pending:**
- Final orchestration logic
- Full pipeline wiring between agents
- Execution flow validation

---

### Intern 2 – Extraction & Validation (Agents B, C, D)
Responsible for:
- OCR & structured extraction (`extraction_agent.py`)
- Normalization (`normalization_agent.py`)
- Vendor resolution (`vendor_resolution_agent.py`)
- Invoice validation checks (`validation_agent.py`)

**Pending:**
- Accurate header + line item extraction
- Vendor matching logic
- Totals reconciliation & validation rules
- Structured extraction confidence scoring

---

### Intern 3 – Matching, Compliance & Risk (Agents E, F, G, H)
Responsible for:
- Matching engine (2-way / 3-way) (`matching_agent.py`)
- Compliance & tax rules (`compliance_risk_agent.py`)
- Anomaly & duplicate detection (`anomaly_agent.py`)
- Exception triage & approval routing (`exception_triage_agent.py`)
- Policy configuration (YAML files)

**Pending:**
- Matching logic with tolerance handling
- Risk scoring implementation
- Compliance rule validation
- Exception categorization & approval packet generation
- Full integration of policy pack with decision logic

---

## 🔜 Next Phase

- Implement full agent logic across all interns
- Finalize and validate schemas
- Integrate policy framework into execution pipeline
- Produce deterministic artifacts in `runs/`
- Prepare test invoice bundles
- Ensure reproducible demo execution

---

Current stage: **Architecture & structural setup completed.  
Functional implementation phase in progress.**