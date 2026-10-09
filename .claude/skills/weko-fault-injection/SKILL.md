---
name: weko-fault-injection
description: Recreate the spec's mocks M1-M15 (S0-09, S15) on a real local WEKO by rewriting database, data or environment through the helpers inject_fault, restore_fault, list_faults, set_client_field and orphan_record, with the confidence of each recipe, restore and fault.none verification, spike order, and when to stop and ask the owner to approve a source modification. Use when preparing or running S14/S15, a spike of a mock, or when a fault will not restore. Not for stopping containers (that is S14, see sword-test-run).
---

# Fault injection by data, not by code

Owner decision (e): rewrite DB / data / environment first through the helpers; modify WEKO source
only as a last resort and **only with the owner's explicit approval**. The helpers never touch WEKO code.
Every recipe below is a hypothesis: nothing has run on a real WEKO. A spike per mock decides whether
it works; a mock that cannot be reproduced by data is reported to the owner, never patched silently.

## Mechanics

All objects are named `ath_fault_<n>_*`; state lives in `ath_fault_state` / `ath_fault_backup`, which are dropped
when the last fault is restored, so `list_faults == []` proves nothing is left.
```sh
H='docker exec -i '"$WEKO_WEB_CONTAINER"' python /opt/ath-helpers/run.py'
echo '{"catalog":true}' | $H list_faults                       # recipes and the mocks they target
echo '{"kind":"trigger_raise","params":{"table":"records","event":"delete","sqlstate":"23503"}}' | $H inject_fault   # -> fault_id
echo '{}' | $H list_faults                                       # the active faults
echo '{"kind":"all"}' | $H restore_fault                         # LIFO rollback + sweeps orphan ath_fault_* objects
echo '{}' | $H list_faults                                       # must be []
```
Logical table names: users, roles, tokens, clients, sword_clients, records, items, pids, activities, workflows,
flows, flow_actions, jsonld_mappings, item_type_mapping. A fault is created in one transaction (failure = nothing left).
`restore_fault` accepts `kind`, `fault_id` or `"all"` (default).

## Per-mock recipes

Confidence: H = likely works, M = plausible, L = doubtful. "Spike" = first thing to try.

| Mock | Needed condition (spec S0-09) | Recipe (helpers) | Conf. | Notes / spike |
|---|---|---|---|---|
| M1 | non-connection DB error (`ProgrammingError`/`IntegrityError`) on EP3 `get_record_permalink` read path | `rls_raise_on_row` on `pids` (or `records`) for the target recid, sqlstate 42xxx (`ProgrammingError`) | L | Needs a DB role without superuser/BYPASSRLS; else `RlsBypassed`. A SELECT cannot fire a trigger. If bypassed: owner decision |
| M2 | Direct failure with `Unexpected error: <type>` marker (non-SQLAlchemy exception inside `import_items_to_system`) | none dedicated; try `corrupt_mapping_json` (mode `drop_key`/`json_string`) so the import raises KeyError/TypeError | L | Spike after M7; the marker text must match. Else source change |
| M3 | EP2 `import_items_to_system` raises a non-connection `SQLAlchemyError` (`sqlalchemy error: <type>`) | `trigger_raise` insert on `records` (or `items`/`pids`) sqlstate 23505/23503, or `check_violation_new_rows` (23514) with `row_condition` on the new title | M | Pick a row condition so only the test's item fails. Check the wrapped marker in the response |
| M4 | same as M3 on EP4 (update) | `trigger_raise` event `update` on `records` with `row_condition` `{column:id|json..., ref:NEW}` for R1's uuid | M | |
| M5 | unknown exception during delete (EP5) | `trigger_raise` event `delete` or `update` on `pids`/`records` (sqlstate 23xxx/42xxx) | M | `soft_delete` updates the PID: update on `pids` for the recid |
| M6 | `WekoWorkflowException` during delete | `break_workflow_flow` (`mode: delete_flow_actions` on the C-W workflow; also `flow_status`, `mark_deleted`) | M/L | Whether the delete flow code raises that exception type is UNVERIFIED |
| M7 | exception in `check_jsonld_import_items` (e.g. mapping undefined) | `corrupt_mapping_json` (`mapping_id` 30001) modes `empty_object`/`null_json`/`drop_key` | M | |
| M8 | OBO target lookup: `OperationalError` only on the user query | `rls_raise_on_row` on `users`, `column:email`, sqlstate 08006, `command:"SELECT"` | L | Token validation also reads users (different row - condition on the OBO target's email only). RLS bypass -> owner |
| M9 | response serialization validation error | `corrupt_record_json` on the record (`mode: drop_key`, `key` of a required field, or `json_array`) | M | Make EP3 the probe first |
| M10 | OBO lookup: non-connection DB error (`ProgrammingError`) | as M8 with sqlstate 42P01 / 42703 | L | |
| M11 | Workflow update: activity cannot be created (before creation) | `break_workflow_flow` `mode: flow_status` (or `delete_flow_actions`) on the C-W workflow; or `trigger_raise` insert on `activities` | M/L | Must leave no activity/draft |
| M12 | invalid `registration_type` in DB (EP4 3103, EP5 3102) | `set_client_field {client_id, field:"registration_type_id", value:99}` (restore with the previous value it returns) | H | Not a fault-kind: restore by hand; the value is returned in `previous` |
| M13 | dependency-type exception during delete (DB `OperationalError`, Redis/ES `ConnectionError`) | DB: `trigger_raise` sqlstate `08006` on the delete path. Redis/ES: none | M (DB) / L | 08006 through pgpool/SQLAlchemy is UNVERIFIED. Redis/ES ConnectionError inside delete only: source change (container stop = S14, different path, token lookup first for DB) |
| M14 | `check_import_file_format` returns an unknown format | none (pure Python function, `views` module attribute) | L | Unreachable by data. Source modification/monkeypatch: **ask the owner** |
| M15 | delete-side `Resolver.resolve` returns `(pid, None)` while EP5's first existence check (2101) passes | `orphan_record {recid}` (record rows removed, PID kept; `{"restore": <backup>}` to undo) | M | The 2101 check uses another Resolver and may also fail (-> 2101 not 2102). Check; Q-10 |

## Verify, per mock (always in this order)

1. `list_faults` is `[]` and a `snapshot` (tables involved) is taken: this is the **fault.none** baseline.
2. `inject_fault` returns a `fault_id`; `list_faults` shows exactly it.
3. Run the probe request (EP and input from the S15 case) and read: HTTP status, `error` code, `@type`, and the app log
   (`docker logs --since <t> $WEKO_WEB_CONTAINER`): the SQLSTATE / exception type that WEKO saw. Compare with the spec's expected code.
4. `restore_fault` (`all`); `list_faults == []`; a second `snapshot` equals the first (the diff is empty).
5. Repeat the probe: the **normal response** returns (spec: every mock must be switchable off).
6. Record per mock: recipe, params, observed code, observed log line, "reproduced / not reproduced / different code".

Authoring the S14/S15 case for a mock: the log is judged *positively* (`docs/LOG-JUDGEMENT.md`, `tools/log_expect.py`):
an `operation_result` over `OP-APP-LOG` with `Variant(code, status)`; 500/501/503 are ERROR, and a 503 that propagates by type
(3108-3110 via `handle_dependency_error`, EP3/EP5 and the authentication stage) also needs `trace=True`
(the stack trace attached to the handler line, spec C-5xx-3). 3108-3110 reached through the fixed value in the EP2/EP4 import
stage get no trace requirement (F-08): record whether a trace is present, do not assert it. The ERROR lines and traces WEKO
writes on its own are never judged. If a spike fails and the owner declines the source change, mark the case `not_runnable`
with reason, checkedAt and checkedBy in the YAML (spec-draft) instead of leaving it manual.

If a step fails and a fault stays, `restore_fault {"kind":"all"}` sweeps `ath_fault_*` triggers, constraints, policies
and functions; if even that fails, inspect `pg_trigger`, `pg_policy`, `pg_proc` for `ath_fault_%` in the DB container and report.

## Spike order (cheapest and most informative first)

M12 -> M15 -> M3/M4 -> M5 -> M7 -> M9 -> M11/M6 -> M13 (DB part) -> M2 -> M1/M8/M10 (RLS; first
`ping` -> `db_user`, then check `rolsuper`/`rolbypassrls`) -> M14.

## Escalate to the owner (stop, do not patch) when

- the DB role bypasses RLS (M1/M8/M10) and no trigger can substitute;
- the mock needs a Python-level exception inside WEKO (M2, M13 Redis/ES, M14, sometimes M6);
- a recipe yields a different code than the spec (maybe a spec defect: report, do not adapt expectations);
- injection risks the shared state (e.g. affects other users' rows).
A source change proposal states: file and function, the exact minimal patch (as a diff in a scratch copy, never committed to
`weko`), how it is removed, and which M-id it serves. The owner approves it per mock.

## Pitfalls

- RLS recipes use FORCE; the helper records and restores the previous RLS state; never leave a table forced.
- Row conditions use structured `column/op/value/ref` (no raw SQL); `ref` NEW for insert/update, OLD for delete.
- Faults act on the whole table; scope with `row_condition` or other tests running concurrently will break.
- A destructive group must `restore_fault all` in a `finally` and verify `list_faults == []` before the next case.
- Do not use faults on the demo records R1.. unless the case says so; use scratch records (recid >= 900100).
