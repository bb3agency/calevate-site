# Test pruning, 13 Oct 2026

The founder (13 Oct 2026): the suite has about 15,000 collected tests and takes about two hours
here, and many of them guard nothing. Tests were deleted or merged in five categories:

1. **Absence:** a removed thing stays removed (route 404s, column gone, name not in source).
2. **Wording pin:** exact prose of a comment, docstring, doc or UI copy.
3. **Gate re-run:** a test that runs a `scripts/check_*` gate over the real tree, which CI already
   runs.
4. **Duplicate:** the same path with trivially different inputs, or a unit restatement of an
   end-to-end test.
5. **Trivial:** a constant equal to itself, a field that exists, a frozen dataclass.

Kept, whatever the category:
- RLS and cross-tenant tests, security censuses, engine conformance and golden transcripts.
- Legal text hashes, compliance disclosure text, and money, rate and wire values.
- Client-facing copy rules (D-679, not clinic-centric) and security absence properties.
- Any test that may be the only one exercising a coverage-ratchet branch.

**286 test functions removed, about 4,600 lines.** No test was written. The edits were static (no pytest run), so the first full run is the check.

## Removed, by lane

| Lane | Tests removed | Whole files deleted |
|---|---|---|
| `tests/a*`–`c*` | 81 (about 96 cases) | `call_latency_column_test.py`, `calls_carrier_call_id_test.py` |
| `tests/d*`–`o*` | about 73 (about 100 cases) | `outbox_queue_deprecation_test.py`, `onboarding_known_gaps_test.py`, `eval_known_gaps_test.py` |
| `tests/p*`–`z*`, lead | 55 (57 cases) | `publish_known_gaps_test.py`, `reliability_known_gaps_test.py`, `tenant_birth_known_gaps_test.py` |
| p–z chunk 0 (`packages/shared/tests` … `recording_source_egress`) | 12 | none |
| p–z chunk 1 (`redaction_phone` … `statement_timeout`) | 14, plus 3 trimmed | none |
| p–z chunk 2 (`step_up_window_mirror` … `vobiz_callback_secret`) | 23, plus 2 assertions | none |
| p–z chunk 3 (`vobiz_client` … `zero_spend_cap`) | 26 | none |

`dpdp_known_gaps_test.py` was deleted and restored unchanged: SECURITY-COMPLIANCE,
PRODUCTION-READINESS, LAUNCH-CHECKLIST, DATA-MODEL and `check_erasure_coverage.py` cite it as the
record of the open DPDP gaps.

## Left on purpose (selection)

- `credit_stop_copy_test.py`: it stops the false promise that callers still get through on an
  empty wallet.
- `breach_notification` DPA and CERT-In deadline pins.
- `extraction_prompt_test.py` (37 prompt pins): with no keys in CI they are the only guard on the
  extraction prompt.
- `authn_enumeration::test_there_is_no_identifier_existence_endpoint` and the
  `vendor_error_message` checks: security properties.
- `variant_drift_coverage_test.py::test_an_experiment_arm_carries_no_knowledge_base_known_gap`:
  it runs guarded `agents/service.py` code.
- `transactional_campaign_classification_test.py::test_both_gates_ask_it_so_a_running_campaign_stops_too`:
  the only proof that the dispatch gate also refuses.
- `processor_erasure_test.py`: six absence assertions were proposed for removal. The edit was
  refused by the tool's permission check as security-test removal, and the file is unchanged.
  It needs the founder's decision.

## Stale references to fix when the pruning is integrated

- `tests/call_latency_column_test.py` is still named in:
  - `apps/api/admin/health.py:69`
  - `apps/api/crm/models.py:597`
  - `scripts/check_metadata_columns.py:60`
  - migrations `b7d3e91c4a05` and `f1a7c39d5be2`
- `tests/outbox_queue_deprecation_test.py` is still named in `apps/api/reliability/service.py:343` and migration `b7e4c1a90d38`.
- Removed test names still appear in:
  - `docs/ENGINEERING-PRACTICES.md:48`
  - `tests/rls_exempt_untenanted_write_test.py:26` (`test_live_schema_is_clean`)
  - `tests/call_optout_test.py:3` (`eval_known_gaps`)
- `docs/evidence/*` mentions are history and stay.
- Some files were rewritten from CRLF to LF by the editing tools. Check that `git diff` shows only
  real changes.
