# Care Art - QA Architecture for Regulated Adult Day Care SaaS

Full QA infrastructure built from scratch for a HIPAA, 42 CFR Part 2, CMS, ISO 13485, ISO 14971, and FDA 21 CFR Part 820-regulated platform. Every document traces to the next: system architecture drives the data model, the data model drives requirements, requirements drive the test strategy, test strategy drives the test plan, test plan drives the test cases one-to-one per REQ_ID.

## Documents

- [Requirements Phase 1](https://docs.google.com/spreadsheets/d/1zMsnvdmbzKZpY19QxgiGqnPbk7Alo9Xa/edit?usp=sharing) — 58 requirements grouped by entity with regulatory references.
- [Test Strategy Phase 1](https://docs.google.com/document/d/1f2_kuuXYukhl6_umYJ6bKmmWVprW6Q6q/edit?usp=sharing) — risk-based strategy, fixture layer design, CI gate.
- [Test Cases Phase 1](https://docs.google.com/spreadsheets/d/18La5det9gJWmvp3iMes4tGWEKTDdHjo_/edit?usp=sharing) — 10 test cases for Participant entity, steps mapped to REQ_IDs.
- [architecture.md](architecture.md)
- [test_plan_phase1.md](test_plan_phase1.md)
- [test_cases/](test_cases/)
- [mock_backend/](mock_backend/)

## Stack

Python, FastAPI, SQLite, Playwright, pytest, MCP agents, Claude Code.

## Regulatory Scope

HIPAA, 42 CFR Part 2, CMS Medicaid/Medicare, ISO 13485, ISO 14971, FDA 21 CFR Part 820, State adult day care licensing.
