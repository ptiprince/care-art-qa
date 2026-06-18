# Care Art - QA Architecture for Regulated Adult Day Care SaaS

Full QA infrastructure built from scratch for a HIPAA, 42 CFR Part 2, CMS, ISO 13485, ISO 14971, and FDA 21 CFR Part 820-regulated platform. Every document traces to the next: system architecture drives the data model, the data model drives requirements, requirements drive the test strategy, test strategy drives the test plan, test plan drives the test cases one-to-one per REQ_ID.

## Documents

- [Requirements Phase 1](https://docs.google.com/spreadsheets/d/1zMsnvdmbzKZpY19QxgiGqnPbk7Alo9Xa/edit?usp=sharing) — 58 requirements grouped by entity with regulatory references.
- [Test Cases Phase 1](https://docs.google.com/spreadsheets/d/1G49Hcsai-qalpWjhoa_YSNg29cKS7dQ3/edit?usp=sharing&ouid=106805557209921495723&rtpof=true&sd=true) — test cases for Participant, User, Attendance, Claim, MARRecord, Incident, AuditLog, RBACSweep, TenantIsolation, and DBSchema groups.
- [Test Strategy Phase 1](https://docs.google.com/document/d/1x1enpU5eGxImGEuwRYhl2H-8Ashm8yA2/edit?usp=sharing&ouid=106805557209921495723&rtpof=true&sd=true) — risk-based strategy, fixture layer design, CI gate.
- [Test Plan Phase 1](https://docs.google.com/document/d/1Ew2FrqAenj8HR3cHa3kUzQHNFU1Y-DBl/edit?usp=sharing&ouid=106805557209921495723&rtpof=true&sd=true) — 123 atomic test functions mapped to REQ_IDs.
- [Architecture](https://docs.google.com/document/d/1xLf16Hk8Bwd3enuRXE5GZun2e23lkWw-/edit?usp=sharing&ouid=106805557209921495723&rtpof=true&sd=true) — full system architecture covering all phases, data model, regulatory controls, and API design.
- [Requirements](https://docs.google.com/spreadsheets/d/1jfkVVRP_DWBoozTD8e5ZuhFKacrwMWSU/edit?usp=sharing&ouid=106805557209921495723&rtpof=true&sd=true) — 110 requirements across Phase 1 and Phase 2 entities with regulatory references and acceptance criteria.
- [Test Strategy Phase 2](https://docs.google.com/document/d/1OI8cUZ3wVTIKaiH84pAJfTjPKFumpTbo/edit?usp=sharing&ouid=106805557209921495723&rtpof=true&sd=true) — risk-based strategy, fixture layer design, and CI gate for Phase 2 entities.
- [Test Plan Phase 2](https://docs.google.com/document/d/1bCRuC3euiSOp7M08T2RX_HJl9YQpWckE/edit?usp=sharing&ouid=106805557209921495723&rtpof=true&sd=true) — 98 atomic test functions mapped to REQ_IDs for CarePlan, Appointment, MedicationRefill, Reminder, and Consent.
- [architecture.md](architecture.md)
- [test_plan_phase1.md](test_plan_phase1.md)
- [test_cases/](test_cases/)
- [mock_backend/](mock_backend/)

## Tests

| File | Status | Count |
|---|---|---|
| tests/test_participant.py | passing | 12 |
| tests/test_user.py | passing | 15 |
| tests/test_attendance.py | passing | 12 |
| tests/test_claim.py | passing | 15 |
| tests/test_mar_record.py | passing | 21 |
| tests/test_incident.py | passing | 15 |
| tests/test_audit_log.py | passing | 10 |
| tests/test_rbac_sweep.py | passing | 12 |
| tests/test_tenant_isolation.py | passing | 7 |
| db/test_schema.py | passing | 8 |
| **Total written** | | **131** |

## Stack

Python, FastAPI, SQLite, Playwright, pytest, MCP agents, Claude Code.

## Regulatory Scope

HIPAA, 42 CFR Part 2, CMS Medicaid/Medicare, ISO 13485, ISO 14971, FDA 21 CFR Part 820, State adult day care licensing.
