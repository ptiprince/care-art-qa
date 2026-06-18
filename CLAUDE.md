## CLAUDE.md — Care Art Phase 2
## Project context
Care Art is a regulated, multi-tenant SaaS platform for adult day care program operators. Stack: FastAPI, SQLite, pytest, Python 3.12. Regulatory scope: HIPAA, 42 CFR Part 2, CMS Medicaid/Medicare, ISO 13485, ISO 14971, FDA 21 CFR Part 820, State adult day care licensing.
Phase 1 complete: 131 passing tests across 10 entities (Participant, User, Attendance, Claim, MARRecord, Incident, AuditLog, RBACSweep, TenantIsolation, DBSchema). All Phase 1 tests pass in CI gate defined in .github/workflows/ci.yml.
Phase 2 scope: defined with Jane before any agent starts work. No Phase 2 task begins without explicit scope confirmation from Jane via policy-agent.
## Files never to modify without explicit instruction from Jane
mock_backend/main.py
mock_backend/models.py
mock_backend/database.py
requirements_phase1.xlsx
requirements_phase2.xlsx
architecture.md
test_strategy_phase1.md
test_plan_phase1.md
.github/workflows/ci.yml
tests/conftest.py
test_cases/test_cases_phase1.xlsx
All Phase 2 sheets in test_cases_phase1.xlsx.
Exception: mock_backend/main.py and mock_backend/models.py may be modified by backend-agent only when Jane gives an explicit instruction via policy-agent for a specific Phase 2 task. That explicit instruction overrides the protection for that task only.
## Coding conventions
Test atomicity: every test function maps to exactly one REQ_ID. One test that covers two requirements must be split before it is accepted into the suite. A failing test must point to exactly one requirement violation.
No hardcoded values of any kind: no hardcoded dates, IDs, tenant values, user IDs, or any environment-specific strings anywhere in test code. Dates use datetime.now(timezone.utc). IDs come from fixture responses. Tenant and user constants come from helpers.py only.
No time.sleep anywhere. Wait on condition or state, not on time. If a state must be polled, use a retry loop with timeout and explicit condition check, not a fixed sleep.
Layer separation: tests describe the flow. Fixtures manage setup, teardown, and shared dependencies. Helpers hold constants, payload builders, and reusable API calls. No raw constants or inline payload construction in test bodies. A change in one layer must not require edits in another layer.
Data setup: no direct SQL inserts for test data setup. All data created through API endpoints. No test creates data inline. No test depends on side effects of another test. Tests run in any order and produce the same result.
Fixture scopes: session scope for engine, client, tenant, base users, auth tokens. Created once per run, never mutated. Function scope for any record that will be submitted, mutated, or involved in a state transition. Created fresh per test, torn down after assertion. If teardown fails, CI run is marked incomplete.
Assertions: assert API response status and required body fields first. Then assert DB state via db_session SQL query confirming what was actually written. Both must match expected values. DB assertion is not optional. Record count, field values, is_deleted, version all asserted where applicable.
Naming: test function names must match TC ID from test plan exactly. Example: test_tc_1_1_positive_participant_creation_by_program_administrator. No deviation without updating the test plan first.
## Verification gate
The P1 gate defined in .github/workflows/ci.yml is the source of truth for Phase 1 coverage. All P1 gate tests must remain passing at all times. No task is closed, no file is committed, no phase is complete without Jane's explicit confirmation. No automated check replaces Jane's review.
No xfail without a documented bug ID in the test docstring.
## Orchestration
policy-agent is the single entry point for all tasks. Jane gives every task to policy-agent first. Policy-agent routes to the correct subagent based on task type. No subagent starts work without routing from policy-agent. Subagents report completion back to policy-agent. Policy-agent presents result to Jane and waits for confirmation before closing the task.
Subagent selection is based on task type: new test goes to test-writer, DB validation goes to db-validator, backend change goes to backend-agent, document change goes to doc-agent, Excel test cases go to excel-agent, knowledge graph update goes to obsidian-agent. Any task that does not fit a single agent is broken into subtasks by policy-agent and routed sequentially. Each subtask is confirmed by Jane before the next one starts.
## Agent routing
New test or test coverage: test-writer. After test-writer completes: db-validator confirms DB state for every new test.
Backend change: policy-agent gets Jane confirmation first, then backend-agent executes. No backend changes without this sequence.
Document change: policy-agent discusses scope and format with Jane first, then doc-agent executes using the unified Python formatting script. Test strategy for each new phase is agreed with Jane strictly before writing starts.
Excel test cases: excel-agent only, new sheet per entity group, structure identical to Phase 1 sheets. Policy-agent confirms sheet name and column structure with Jane before excel-agent starts.
Knowledge graph update: obsidian-agent only, triggered by policy-agent after any new document is confirmed by Jane.
Prompt creation and updates: Jane owns all prompts. Policy-agent assists Jane in drafting and refining prompts for any agent. No prompt is created or changed without Jane's explicit confirmation. No agent modifies its own or another agent's prompt directly.
Rule violation by any agent: policy-agent logs it, stops the session, escalates to Jane before continuing.
Ambiguous task: policy-agent asks Jane for clarification before routing.
## Knowledge graph
All project documents are indexed in the Obsidian vault at care_art/obsidian/. Agents retrieve relevant context from the vault before executing any task. Agents do not scan all documentation: they retrieve only what is relevant to the current task.
Documents currently in vault: architecture.md, test_strategy_phase1.md, test_plan_phase1.md, README.md.
Any new document added in Phase 2 is added to the vault by obsidian-agent after Jane confirms the document is final. Policy-agent notifies obsidian-agent when a new document is ready for indexing.
