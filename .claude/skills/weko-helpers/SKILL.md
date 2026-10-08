---
name: weko-helpers
description: Work on the in-container helper scripts in helpers/ (JSON-over-stdin commands run inside the WEKO web container under Python 3.6) - the contract, the 3.6 constraints, how to add or change a command, how to test it on the host and in the container, and how it is wired to plugin.yaml and weko_suite_ext. Use when adding a helper command, fixing a helper that failed in the container, or reviewing helper code.
---

# The in-container helpers

`helpers/` runs **inside** the `web` container with WEKO's own virtualenv (Python 3.6, Flask 1.0.4,
SQLAlchemy via invenio-db) so tests use the application's ORM. The host calls it through
`weko_suite_ext.helper` (the `OP-HELPER` operation in `plugin.yaml`): one `docker exec -i` per command.
Reference: `docs/helpers.md` (commands, recipes, first-run checklist).

## Contract (do not break it)

- Input: one JSON object on stdin (empty = `{}`). Output: exactly **one line** of JSON on stdout.
  `{"ok":true,"result":...}` or `{"ok":false,"error":{"type","message"[,"sqlstate"]}}`.
- Exit code 0 even for `ok:false`; non-zero only for a crash outside the contract.
- stdout is reserved: `run.py` redirects WEKO's import-time prints to stderr. Never `print()` in a command.
- Secrets: only `create_token` returns `access_token`. No password hashes, client secrets or token values anywhere else
  (`snapshot` selects columns explicitly; a test checks it).
- Idempotent: running a command again converges to the same state and returns the previous values so the host can restore.
- Expected failures raise `contract.HelperError(type, message, **extra)`. Anything else is converted by
  `contract.error_from_exception` (keeps `sqlstate` from `orig.pgcode`).

## Python 3.6 constraints

No walrus, no `f"{x=}"`, no `dataclasses`, no `from __future__ import annotations`, no `str | None`, no `match`,
no `list[str]` generics at runtime. f-strings are allowed (3.6) but this code base uses `%` formatting. `ruff`'s oldest target is py37, so
`helpers/tests/test_py36_syntax.py` parses every `helpers/*.py` with `ast.parse(feature_version=(3, 6))`: that test is the gate.
`contract.py` must stay pure: no WEKO or third-party import. WEKO imports go inside the command function (lazy), so `list`
and unit tests never need WEKO.

## Layout

`run.py` dispatch - `registry.py` table `name -> (module, function, needs_app)` - `contract.py` envelope/validation -
`appctx.py` Flask app context (`invenio_app.factory:create_app`, override `ATH_HELPERS_APP_FACTORY=module:callable`) -
`dbx.py` raw SQL executor (`SessionDb`) - `rowlib.py` row helpers - `faultlib.py` fault recipes (pure + injected executor) -
`cmd_*.py` the commands.

## Add a command

1. Write `helpers/cmd_<topic>.py` with `def run(params): ...` that validates with `contract.require_str/optional_*`, imports WEKO lazily,
   uses `invenio_db.db.session` or `dbx.SessionDb()`, commits itself, and returns a JSON-serialisable dict that includes the
   previous values it overwrote.
2. Register it in `helpers/registry.py` (`needs_app=True` if it touches the DB or Flask).
3. Prefer the application's own models/functions; use raw SQL only where the model path is unsafe or the table is not modelled (record it in `docs/helpers.md`
   with a confidence: pure / medium / low).
4. Pure logic -> unit tests with `helpers/tests/fakes.py`; add the command to `docs/helpers.md` (command table + checklist item).
   `helpers/tests/test_docs.py` fails when a registered command is missing from the docs.
5. If tests/plugin need it: add an `OP-HELPER` call in a spec step (`cmd`, `params` as a JSON string), or a rig implementation in
   `tools/sword-stub/fake_docker.py` so the rig keeps running the same plumbing (see `docs/stub.md`).
6. Add the first-run expectation to the `weko-env-up` checklist.

## Test

```sh
cd helpers && ruff check . && ruff format --check . && pytest      # host, Python 3.11 (pure logic and fakes)
cd .. && scripts/check.sh                                            # everything CI runs
# in the container (UNVERIFIED parts):
docker cp helpers/. "$WEKO_WEB_CONTAINER":/opt/ath-helpers
echo '{...}' | docker exec -i "$WEKO_WEB_CONTAINER" python /opt/ath-helpers/run.py <cmd> | python -m json.tool
```
Check the output is a single JSON line (`| wc -l` = 1) and that stderr carries the logs. A passing host test says nothing about the ORM path:
every ORM-touching change needs the container run, recorded in the PR/handoff.

## Pitfalls

- `create_record` advances `RecordIdentifier`: use recid >= 900000; it calls `WekoDeposit.commit` (Elasticsearch/side effects UNVERIFIED).
- `create_user` fills `confirmed_at` of an existing user; `register_sword_client` with `delete_flow_id` writes into `workflow_workflow` (never workflows 1/2).
- DDL through pgpool is UNVERIFIED; fault recipes DROP their state tables when the last fault is restored.
- A user-supplied identifier never goes into SQL unquoted: use `contract.IDENT_RE`, `quote_ident`, `quote_literal` and the table allow-list.
- Do not add commands that delete data without a `restore` path or a unique `ath-` name guard.
