---
name: weko-env-up
description: Bring a local WEKO3 (docker compose, install.sh demo data) to the starting state the SWORD suite assumes - hosts entry and TLS trust, helpers copied into the web container, baseline-check, bootstrap run writing .env.local, health checks and the first-run verification checklist of the in-container helpers. Use on the owner's local machine before the first test run, after a reinstall, or when a run reports environment defects. Not for running the tests (use sword-test-run).
---

# Bringing WEKO up for the SWORD suite

The suite starts from "`install.sh` just finished" and never resets WEKO between
scenarios (`docs/BASELINE.md`). Demo users have the password `uspass123`; item
types 30001/30002, workflows 1/2, no SwordClient, no tokens, no deletion flow.
Everything here is **UNVERIFIED against a real WEKO** until you tick the checklist
in step 8; record each result in `HANDOFF.md` or the run notes.

## Rules

- `install.sh` is destructive (`docker compose down -v`). Run it only when the
  owner asks for a fresh install. Never from tests or from `bootstrap`.
- Do not modify the `weko` checkout (read-only reference) or the hub checkout.
- `.env`, `.env.local`, evidence and cert files are never committed. Keep them in
  git-ignored places (`.env*`, `artifacts/`).

## Procedure

1. **Layout and tools.** Sibling checkouts: `agentic-test-hub/` (at the SHA in
   `hub.lock`), `weko-test-suite/`, `weko/` (pre-change build `779c2d70`).
   ```sh
   cd weko-test-suite
   scripts/bootstrap-hub.sh && uv sync
   uv run playwright install chromium      # only for UI cases
   ```
2. **Start WEKO** (skip if already running from `install.sh`):
   ```sh
   cd ../weko && ./install.sh               # compose file docker-compose2.yml (amd64)
   docker compose -f docker-compose2.yml ps --format '{{.Name}} {{.State}}'
   ```
   Wait until web, worker, postgresql, pgpool, redis, elasticsearch, rabbitmq, nginx
   are up. Note the real container names (the project prefix depends on the directory).
3. **hosts and TLS** (UI cases use https via nginx, `weko3.example.org`):
   ```sh
   echo '127.0.0.1 weko3.example.org' | sudo tee -a /etc/hosts
   docker cp <nginx-container>:/etc/nginx/server.crt artifacts/weko3-server.crt   # self-signed
   curl --cacert artifacts/weko3-server.crt https://weko3.example.org/sword/service-document -o /dev/null -w '%{http_code}\n'   # 401 expected
   ```
   Python/httpx honours `SSL_CERT_FILE=artifacts/weko3-server.crt`. **Chromium does
   not**; for the self-signed certificate export **`ATH_BROWSER_IGNORE_HTTPS_ERRORS=1`** (owner decision
   2026-10-09). The hub's Python Playwright driver reads it (hub `docs/ARCHITECTURE.md`, "Browser TLS":
   `1`/`true`/`yes`/`on` turn `ignore_https_errors` on for the browser context), so no generated test is
   edited and no certificate goes into an NSS db. It is in `.env.example`; keep it out of any run that
   targets a server with a real certificate.
   `SESSION_COOKIE_SECURE=True` means a login over plain `http://127.0.0.1:5001` may
   not keep its cookie (UNVERIFIED); UI cases use https. API cases use
   `WEKO_BASE_URL=http://127.0.0.1:5001` (and `NO_PROXY=127.0.0.1` behind a proxy).
4. **.env** from `.env.example`: set `WEKO_BASE_URL`, the container names
   (`WEKO_WEB_CONTAINER`, `WEKO_DB_CONTAINER`, `WEKO_REDIS_CONTAINER`,
   `WEKO_ES_CONTAINER`, `WEKO_WORKER_CONTAINER`) exactly as `docker ps --format '{{.Names}}'`
   shows, `SW_REDIS_DB` (value of `ACCOUNTS_SESSION_REDIS_DB_NO`, default 1; verify), `SW_USER_PASSWORD=uspass123`,
   and `ATH_BROWSER_IGNORE_HTTPS_ERRORS=1` for UI cases over the self-signed https.
5. **Copy the helpers** into the web container and sanity-check Python:
   ```sh
   set -a; . ./.env; set +a
   docker cp helpers/. "$WEKO_WEB_CONTAINER":/opt/ath-helpers
   docker exec "$WEKO_WEB_CONTAINER" python --version            # must be Python 3.6.x of WEKO's virtualenv
   docker exec -i "$WEKO_WEB_CONTAINER" python /opt/ath-helpers/run.py list
   echo '{}' | docker exec -i "$WEKO_WEB_CONTAINER" python /opt/ath-helpers/run.py ping
   ```
   If `python` is not the virtualenv, use its full path
   (`/home/invenio/.virtualenvs/invenio/bin/python`) and set it in `weko_suite_ext`/the call. If `ping` fails on the app
   context, set `ATH_HELPERS_APP_FACTORY=module:callable` (default `invenio_app.factory:create_app`, then `create_ui`).
6. **Baseline check, then bootstrap:**
   ```sh
   uv run python seeds/bootstrap.py baseline-check     # [ERROR] stops; [WARN] to read (confirmed_at, ...)
   uv run python seeds/bootstrap.py run --dry-run      # the helper calls, no docker
   uv run python seeds/bootstrap.py run                # writes .env.local (0600); prints variable names only
   set -a; . ./.env; . ./.env.local; set +a
   ```
   It is idempotent (tokens reused by name; token 3 is recreated and revoked each time, so its value changes).
   It creates the deletion flow `ath-sword-delete-flow` (Start+End only), workflow `ath-sword-workflow`
   (copy of workflow 2), SwordClients C-D/C-W/C-OBO, C-X (OAuth only), tokens, and records R1-R8
   (recid 900001-900008; R9 = 900009 must stay absent).
7. **Health checks.**
   ```sh
   curl -s -o /dev/null -w '%{http_code}\n' "$WEKO_BASE_URL/sword/service-document"                         # 401
   curl -s -H "Authorization: Bearer $SW_TOKEN_1" "$WEKO_BASE_URL/sword/service-document" | head -c 300      # 200 JSON
   curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $SW_TOKEN_1" "$WEKO_BASE_URL/sword/deposit/$SW_R1"   # 200
   curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $SW_TOKEN_1" "$WEKO_BASE_URL/sword/deposit/$SW_R9"   # 404
   ```
8. **First-run verification checklist** (helpers; run in this order, each is
   `echo '<json>' | docker exec -i "$WEKO_WEB_CONTAINER" python /opt/ath-helpers/run.py <cmd>`). Expected result in brackets; on a mismatch stop and triage as a *test defect* in the helper, do not work around it.
   1. `list` -> about 19 names including `inject_fault`. `python --version` is 3.6.
   2. `ping` -> `ok:true`, `db_ok:true`, `db_user`. Note `db_user`: superuser/BYPASSRLS disables the RLS recipes (M1/M8/M10).
   3. `baseline` -> 4 roles, 5 users, item types 30001/30002, mappings, flow 1, workflows 1/2, location `local`.
   4. `create_user` twice with a scratch email: first `created:true`; second `created:false`, `roles_added:[]`. Then log in as `user@example.org` / `uspass123` in the UI over https (`confirmed_at` empty -> login may fail; `create_user` fills it, with `previous`).
   5. `create_token` with `scopes:[]` and `["deposit:write"]`; `service-document` with the bearer returns 200. Check the `WEKO_TEST_TOKEN_` prefix is accepted (if 401, retry with `token_prefix:""`: JWT validation).
   6. `register_sword_client` create then update -> `previous` filled; `registration_type: 99` accepted.
   7. `create_record` with `recid >= 900100` (scratch) -> `created:true`; `snapshot {"tables":["records","items","pids"],"recid":900100}` shows one row each; EP3 returns 200 for it; check Elasticsearch/side effects (item visible in search? worker log). Then `delete_record` -> EP3 404 (else retry `method:"pid_only"`) and `restore:true`.
   8. `orphan_record` -> `snapshot` (`pids` stays, `records` 0) -> `{"restore": <backup>}` returns to the original.
   9. `create_flow` (second call `created:false`), `create_workflow`, then EP5 on a Workflow client with the deletion flow: Start+End only should return **204** (202 acceptable); UNVERIFIED.
   10. `inject_fault`/`restore_fault`: see skill `weko-fault-injection` step "verify". At the end `list_faults` must be `[]`.
   11. `snapshot` twice in a row -> empty diff; no token value or password hash in the output; every command's stdout is exactly one JSON line (no WEKO startup noise).
   12. Redis lock key (F-7): `docker exec <redis> redis-cli -n $SW_REDIS_DB --scan --pattern 'pid_*_will_be_edit'` after a PUT on a scratch record within 3 seconds; confirm the key name `pid_<recid>_will_be_edit` (used by S7).

## Pitfalls

- `create_record` advances `RecordIdentifier`: always `recid >= 900000`.
- `register_sword_client` with `delete_flow_id` on workflows 1/2 rewrites demo data. Use `ath-sword-workflow`.
- XML registration (S5-05) and the upload limit change admin/config state; Tier 2, restore afterwards.
- `docker cp` of `helpers/` also copies `tests/`; harmless.
- If `install.sh` was re-run, tokens and records are gone: repeat steps 5-7.
