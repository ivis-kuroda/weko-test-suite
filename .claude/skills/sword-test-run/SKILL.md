---
name: sword-test-run
description: Run the generated SWORD v3 error-code tests against a real local WEKO in the order and groups of spec v4.2 section 0.6 - 3-second spacing for same-recid EP4/EP5, ATH_EVIDENCE_DIR and collecting evidence, the pre-change baseline capture on build 779c2d70 (S0-06, settles U-21/U-01), triage with the hub triage-run-result skill, the log-judgement rule (positive handler-line checks; out-of-scope ERROR lines are remarks), not_runnable cases, destructive-group rules and recovery (S0-08), and what is and is not verified. Use after weko-env-up has passed, whenever the owner asks to execute or re-execute the suite or record results.
---

# Running the SWORD suite against WEKO

Prerequisite: `weko-env-up` finished (baseline-check clean, bootstrap run, `.env.local`
written, helper checklist ticked). The suite never resets WEKO between scenarios, so
every test creates uniquely named data (`ath-<run.id>-...`) and cleans up after itself.

## What is and is not verified (state this in every report)

- Verified only on the rig (`tools/sword-stub`, **not WEKO**): the plumbing - multipart,
  env tokens, `{{step.x}}`, `produces`, cleanup, JSON assertions, evidence masking, the log-judgement rule
  (a missing handler line fails; out-of-scope ERROR noise does not).
- NOT verified: any behaviour of real WEKO, every helper ORM path, tokens with the
  `WEKO_TEST_TOKEN_` prefix under JWT, RLS recipes, `create_record`/`delete_record` side effects, the
  Workflow deletion flow (Start+End -> 204), the Redis lock key, and the real log line format: the
  handler-line expectations assume `<LEVEL> ... [<code>] METHOD path: message` on ONE line with the level before
  the code (detailed design 2.2 step 3; the stub uses exactly that, real WEKO's logger prefix is unseen). A pass on real WEKO is the first real evidence; a failure is
  as likely to be a test/spec/environment defect as a target defect.
- Out of Tier 1 (not generated): S1-01/S1-02 (UI), toggle cases (duplicate check S5-07 1503, XML S5-05,
  OBO setting S4-01, upload limit S5-03/S6-03/S12-02 413), S11-02 (locale method U-11), S7 locks, S9 UI,
  S10, S14, S15, S16. See `docs/TIER1-STATUS.md`, `docs/spec-trace.md` (on `spec-draft/sword-error-codes`).

## Environment variables

`WEKO_BASE_URL`, container names `WEKO_*_CONTAINER`, `SW_USER_*`, `SW_TOKEN_*`, `SW_CLIENT_ID_*`,
`SW_R1..SW_R9`, `SW_WORKFLOW_ID`, `SW_DELETE_FLOW_ID`, `SW_REDIS_DB` (from `.env` / `.env.local`);
`ATH_EVIDENCE_DIR` (where evidence is saved; unset = nothing saved and nothing can be triaged);
`ATH_BROWSER_IGNORE_HTTPS_ERRORS=1` (UI cases over the self-signed https; the hub reads it, no code edit);
`NO_PROXY=127.0.0.1`. Never print values; never commit evidence (`artifacts/` is git-ignored).

## Procedure

1. **Load and sanity-check**
   ```sh
   cd weko-test-suite && set -a; . ./.env; . ./.env.local; set +a
   uv run python seeds/bootstrap.py baseline-check
   curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $SW_TOKEN_1" "$WEKO_BASE_URL/sword/deposit/$SW_R1"   # 200
   ```
   If a record consumed by an earlier run is missing (R4/R5 are consumed), re-run `bootstrap run`.
2. **Pre-change baseline capture (S0-06) first, on the pre-change build.** Needed to settle
   U-21 (invalid token 401 or 403), U-01 (which roles may use which EP) and the response-time baseline
   (S12-04). The pre-change build is `weko` commit `779c2d70`.
   - Install/start that build with `install.sh`, then `weko-env-up` steps 5-8, then run Tier 1 once:
     ```sh
     scripts/run-ordered.sh --out artifacts/baseline-779c2d70 --only 's(1_03|2_01|12_0[1-4])'
     ```
     Expected: many *failures* are normal here (the pre-change build has no SWORD codes). Do not triage them as
     defects; the goal is to record, from `during-network-http-*.json`: the 401-vs-403 status for absent and
     revoked tokens (U-21), allowed/denied per role x EP (U-01), the normal responses of EP1-EP5, the
     existing 400/404/413 bodies (status, `@type`, wording) and `durationMs` per call. Items that cannot be
     captured are written "not obtainable". Keep the files under `artifacts/` and put the numbers in the owner report.
   - Switch to the changed build (re-run `install.sh` or the owner's deployment) and redo `weko-env-up`.
   - Until this is done S1-03 (401/403), S2-01 and S12-01/S12-04 are inconclusive by design.
3. **Run Tier 1 in spec order, with spacing.** Order is S1 -> S16 by number (spec 0.6.2); S9 changes
   are restored before moving on; S14/S15 last. Direct EP4/EP5 lock the recid for 3 seconds, so consecutive
   calls on the same recid need >= 3 s (a surprise 409 `WEKO_SWORDSERVER_E_2201` means spacing, not a defect).
   ```sh
   scripts/run-ordered.sh --list                       # the order
   scripts/run-ordered.sh --out artifacts/run-1        # 3 s gap between files, evidence in artifacts/run-1/evidence
   ```
   Inside one scenario the test code cannot sleep: S3-03 (two DELETE), S5-08 (three PUT on R1) and S6-01 call the
   same recid twice or more. Owner decision 2026-10-09: same-recid back-to-back calls are acceptable when the test
   needs them; the only spacing required is the 3 s between files (`run-ordered.sh --gap`, default 3). They should
   fail before the lock anyway (2101/150x precede it); if a 2201 still appears, record it as a remark, do not edit
   generated code.
   Run serially (no xdist) and never two runs at once against the same WEKO.
4. **Collect.** `artifacts/<run>/evidence/<run-id>/index.json` plus per entity/location files
   (`during-network-http-*`, `before|after|diff-app-log-*`, `-db-log-`, `-db-records-`), and `junit/*.xml`.
   Pack with `tar czf run-1.tgz artifacts/run-1` for the owner; evidence is masked for known headers and
   `WEKO_TEST_TOKEN_*`, but check before sharing.
5. **Log judgement (owner decision 2026-10-09; `docs/LOG-JUDGEMENT.md`).** The application log is NOT a
   negative gate: WEKO emits ERROR lines and stack traces for harmless and critical conditions alike, also outside the
   changed scope. A case passes or fails on its own expectations; for every coded 4xx/5xx one of them is an
   `operation_result` over `OP-APP-LOG` (log since `{{run.startedAt}}`) that finds the expected handler line
   `<LEVEL> ... [<code>] METHOD path: message` (4xx WARNING, 500/501/503 ERROR, a 503 propagated by type with its
   stack trace). A *missing* handler line, a wrong level or a wrong code is a failure (triage it: target defect,
   or a format assumption of the spec). Everything else in the log stays in the saved `diff-app-log-*` file and
   goes into the result row's remark column; it never changes a verdict:
   ```sh
   uv run python tools/log_remarks.py artifacts/run-1/evidence --rows    # one remark per entity
   ```
   `A-5 candidate` in a remark means an ERROR line was logged together with a 4xx (spec 4.5 A-5; basic design 5.4: 4xx is
   WARNING only): record it as 実装不具合候補 A-5 for the implementation team, with the line. Never loosen the handler
   patterns to make a case pass; never add an ignore pattern other than `.*` (`tools/check_log_rule.py` refuses it).
6. **Triage** every non-pass with the hub skill `triage-run-result` (`agentic-test-hub/.claude/skills/triage-run-result`):
   classes test / target / spec / environment defect / inconclusive-by-design, using the evidence index; one result row
   per entity. Rules: confirm environment suspicion by rerunning on clean state; reproduce target defects once;
   never turn a fail into a pass by editing expectations - propose a spec diff for `spec-draft/sword-error-codes`
   (YAML-only commits there) and let the owner decide. Typical first-run suspects: helper ORM errors (test defect),
   the handler-line format assumption (spec defect; see step 5), 401 vs 403 (U-21), consumed R4/R5 (environment).
7. **Destructive groups last (S14/S15) - rules.**
   - Not generated yet. When generated, they run only as a final group, after everything else and after the
     baseline capture, never in parallel, never mixed with other files.
   - S14 (owner decision): docker stop/start of DB/Redis/Elasticsearch is automated; the stop is always paired with a
     start in scenario `cleanup`, and the group runner must restart all three in a `finally` even when pytest dies.
   - S15 mocks: only the recipes of `weko-fault-injection`; always `restore_fault all` and check `list_faults == []`.
   - **Recovery (S0-08)** after any destructive step, before the next one:
     ```sh
     docker start "$WEKO_DB_CONTAINER" "$WEKO_REDIS_CONTAINER" "$WEKO_ES_CONTAINER" 2>/dev/null
     echo '{}' | docker exec -i "$WEKO_WEB_CONTAINER" python /opt/ath-helpers/run.py list_faults        # []
     curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $SW_TOKEN_1" "$WEKO_BASE_URL/sword/deposit/$SW_R1"   # 200
     curl -s "http://127.0.0.1:29201/_cluster/health"                                     # not red
     ```
     With the DB down even valid tokens give 503 (token lookup), not 401 (Q-1).
8. **Report**: counts per verdict, the out-of-scope log remarks (A-5 candidates listed), per non-pass the triage row, the baseline numbers, what is still
   unverified, and the owner decisions you need (see `HANDOFF.md` open decisions). Do not mark any case `verified` in
   specs yourself; propose it.

## Not runnable cases

`automation.status: not_runnable` (hub) marks a case that cannot be reproduced without modifying WEKO's source (never done: reproducibility/idempotence). The hub refuses to
generate it; it is not a failure and is not run. Current ones (provable from code): `TC-SW-S15-07` (3107) and `TC-SW-S15-15` (1411, mock
M14); reasons, dates and check methods are in the YAML (`automation.reason/checkedAt/checkedBy`) and in
`docs/TIER1-STATUS.md`. Report them as 実施不可 with that text (spec 0.6.3). Never mark a case `not_runnable` when a DB,
data or configuration route exists (those are manual/Tier 2). Policy: WEKO source is never modified; a local spike decides
per mock (`weko-fault-injection`), and a failing spike means `not_runnable` via a YAML-only commit on `spec-draft/sword-error-codes`
(then regenerate/remove tests on the feature branch; `hub.lock` stays compatible).

## Tier 2 (not automated; document, do not run unattended)

Toggle-dependent cases need a configuration change and, for some, a restart; verify the location first, change, run, restore:
- Duplicate check (S5-07, 1503): SwordClient column `duplicate_check` (helper `set_client_field`); confirm it is the switch the code reads.
- XML enabled (S5-05): admin screen `sword_api_setting` (and Direct XML is refused by design, 1410); restore afterwards.
- On-Behalf-Of allow (S4-01): `WEKO_SWORDSERVER_SERVICEDOCUMENT_ON_BEHALF_OF` (default True; config in the rendered
  `invenio.cfg` from `scripts/instance.cfg`; restart web); role exclusion `WEKO_ITEMS_UI_SHARED_USER_EXCLUDED_ROLE_NAME_LIST` (U-08).
- Upload limit L (S5-03/S6-03/S12-02 413, S0-12): `WEKO_SWORDSERVER_SERVICEDOCUMENT_MAX_UPLOAD_SIZE` lowered to e.g. 1048576,
  web restart, run only S5-03, restore default and restart (forgetting makes every later upload 413); use port 5001 (nginx may answer 413 first).
- UI cases (S1-02 token revoke, S9, S8-04) by real Playwright over `https://weko3.example.org` (hosts entry and `ATH_BROWSER_IGNORE_HTTPS_ERRORS=1`: see `weko-env-up`).

## Pitfalls

- Generated tests are not to be hand-edited; fix spec/plugin and regenerate (`scripts/gen-test.sh`, `SPECS_DIR=<spec-draft worktree>/specs`).
- Spec YAML changes go to `spec-draft/sword-error-codes` only (`git fetch origin && git rebase origin/<branch>` before every push).
- Real WEKO does not send `Location` on 201 (F-6): recid comes from body `@id`.
- Fixtures `needs:real-metadata` (S3-04, S8-02, S12-01) need CSV/JSON-LD exported from the target; until then expect 400/1501 instead of success.
- `S8-02` fails on the rig by design; on real WEKO it leaves activities behind.
