#!/usr/bin/env python3
"""Bring a freshly installed WEKO3 to the starting state the suite assumes (S0).

WEKO only works after `install.sh` has injected its demo data, and the suite does
not reset the target between scenarios. So this script does not build an
environment: it checks that the demo baseline is there and adds the few things
the SWORD specification needs on top (deletion flow, SwordClients, tokens,
state records), then writes the identifiers and tokens to `.env.local`.

    python seeds/bootstrap.py baseline-check       # list what is missing, change nothing
    python seeds/bootstrap.py run --dry-run        # print every helper call, touch nothing
    python seeds/bootstrap.py run                  # do it, write .env.local

Everything goes through the in-container helpers (`weko_suite_ext.helper`, i.e.
`docker exec` into the web container); the host needs no database access.
The script is idempotent: a second run converges to the same state (the tokens
of `sw-*` clients are reused, the records and the deletion flow are found by
name/recid). Secrets are written only to `.env.local` (git-ignored, mode 0600)
and never printed; the output names variables, not values.

See docs/BASELINE.md for the assumed baseline and the hazards.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

Call = Callable[[str, dict[str, Any]], Any]
"""`call(cmd, params) -> result` of one helper command; raises `HelperFailure`."""

# ---------------------------------------------------------------------------
# What the install.sh demo data provides (scripts/populate-instance.sh and
# scripts/demo/*.sql in the WEKO repository).
# ---------------------------------------------------------------------------

DEMO_PASSWORD = "uspass123"
"""INVENIO_USER_PASS in the install.sh instructions; override with SW_USER_PASSWORD."""

ROLE_SYSTEM = "System Administrator"
ROLE_REPOSITORY = "Repository Administrator"
ROLE_CONTRIBUTOR = "Contributor"
ROLE_COMMUNITY = "Community Administrator"
DEMO_ROLES = (ROLE_SYSTEM, ROLE_REPOSITORY, ROLE_CONTRIBUTOR, ROLE_COMMUNITY)

ITEM_TYPE_SIMPLE = 30001
ITEM_TYPE_FULL = 30002
MAPPING_SIMPLE = 30001
MAPPING_FULL = 30002
REGISTRATION_FLOW_ID = 1
TEMPLATE_WORKFLOW_ID = 2
"""Demo workflow of item type 30001 (simple); the new C-W workflow is copied from it."""
DEMO_WORKFLOW_IDS = (1, 2)
DEMO_INDEX_ID = 1623632832836
DEMO_ADMIN_SETTING_IDS = tuple(range(1, 10))

DELETE_FLOW_NAME = "ath-sword-delete-flow"
WORKFLOW_NAME = "ath-sword-workflow"

SCOPE_WRITE = "deposit:write"
SCOPE_ACTIONS = "deposit:actions"
SCOPE_ITEM_CREATE = "item:create"
SCOPE_ITEM_UPDATE = "item:update"
SCOPE_ITEM_DELETE = "item:delete"
SCOPE_ACTIVITY = "user:activity"
SCOPES_FULL = (
    SCOPE_WRITE,
    SCOPE_ACTIONS,
    SCOPE_ITEM_CREATE,
    SCOPE_ITEM_UPDATE,
    SCOPE_ITEM_DELETE,
    SCOPE_ACTIVITY,
)
"""Token (1): every scope the SWORD endpoints ask for, activity scope included."""
SCOPES_NO_ACTIVITY = tuple(s for s in SCOPES_FULL if s != SCOPE_ACTIVITY)
"""Token (2): write, actions and item_* but not the activity scope."""


@dataclass(frozen=True)
class User:
    """A demo user and the spec role it stands for."""

    key: str
    spec_role: str
    email: str
    roles: tuple[str, ...]


SPEC_USERS: tuple[User, ...] = (
    User("SYSADMIN", "システム管理者", "wekosoftware@nii.ac.jp", (ROLE_SYSTEM,)),
    User("REPOADMIN", "リポジトリ管理者", "repoadmin@example.org", (ROLE_REPOSITORY,)),
    User("COMADMIN", "コミュニティ管理者", "comadmin@example.org", (ROLE_COMMUNITY,)),
    User("CONTRIBUTOR", "コントリビュータ", "contributor@example.org", (ROLE_CONTRIBUTOR,)),
    User("GENERAL", "一般ユーザ", "user@example.org", ()),
)
DEFAULT_OBO_OK = "contributor@example.org"
DEFAULT_OBO_NG = "wekosoftware@nii.ac.jp"
"""On-Behalf-Of targets. weko-items-ui refuses the roles in
WEKO_ITEMS_UI_SHARED_USER_EXCLUDED_ROLE_NAME_LIST (default: System Administrator)."""

# Environment values passed through from the process environment (or .env) to
# .env.local so that one file is enough to run the generated tests.
PASSTHROUGH = (
    "WEKO_BASE_URL",
    "WEKO_DB_URL",
    "WEKO_SEARCH_URL",
    "WEKO_WEB_CONTAINER",
    "WEKO_DB_CONTAINER",
    "WEKO_REDIS_CONTAINER",
    "WEKO_ES_CONTAINER",
    "WEKO_WORKER_CONTAINER",
    "SW_REDIS_DB",
)
SECRET_KEYS_PREFIX = ("SW_TOKEN_", "SW_USER_PASSWORD")


class BootstrapError(Exception):
    """A step failed or the baseline is not what the suite assumes."""


class HelperFailure(BootstrapError):
    """A helper command answered `ok: false` or could not be run."""

    def __init__(self, cmd: str, kind: str, message: str) -> None:
        super().__init__(f"helper {cmd} failed: {kind}: {message}")
        self.cmd = cmd
        self.kind = kind
        self.message = message


@dataclass
class Config:
    """Everything that varies between runs."""

    recid_base: int = 900000
    password: str = DEMO_PASSWORD
    obo_ok: str = DEFAULT_OBO_OK
    obo_ng: str = DEFAULT_OBO_NG
    item_type_id: int = ITEM_TYPE_SIMPLE
    mapping_id: int = MAPPING_SIMPLE
    env_values: dict[str, str] = field(default_factory=dict)

    def recid(self, number: int) -> str:
        """Recid of state record R<number> (R1-R9)."""
        return str(self.recid_base + number)

    @property
    def user_emails(self) -> list[str]:
        emails = [u.email for u in SPEC_USERS]
        for extra in (self.obo_ok, self.obo_ng):
            if extra not in emails:
                emails.append(extra)
        return emails


# ---------------------------------------------------------------------------
# Baseline evaluation (pure)
# ---------------------------------------------------------------------------


@dataclass
class Report:
    """Result of comparing helper `baseline` facts with what the suite assumes."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)
    missing_users: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def evaluate_baseline(facts: Mapping[str, Any], cfg: Config) -> Report:
    """List what is missing from the demo baseline. Errors block the bootstrap.

    Users that do not exist are not errors: the bootstrap creates them.
    """
    r = Report()
    roles = set(facts.get("roles") or [])
    for name in DEMO_ROLES:
        if name not in roles:
            r.errors.append(f"role missing: {name}")

    users = facts.get("users") or {}
    for user in SPEC_USERS:
        info = users.get(user.email)
        if info is None:
            r.missing_users.append(user.email)
            r.warnings.append(f"user missing, bootstrap will create it: {user.email}")
            continue
        if not info.get("active"):
            r.errors.append(f"user is not active: {user.email}")
        if not info.get("confirmed"):
            r.warnings.append(
                f"user has no confirmed_at (install.sh creates users with --active only): "
                f"{user.email}; check that the UI login works"
            )
        for role in user.roles:
            if role not in (info.get("roles") or []):
                r.errors.append(f"user {user.email} lacks role {role}")
    for email in (cfg.obo_ok, cfg.obo_ng):
        if users.get(email) is None and email not in r.missing_users:
            r.missing_users.append(email)
            r.warnings.append(f"On-Behalf-Of user missing, bootstrap will create it: {email}")

    excluded = (facts.get("config") or {}).get("WEKO_ITEMS_UI_SHARED_USER_EXCLUDED_ROLE_NAME_LIST")
    if excluded is None:
        r.warnings.append("shared-user excluded role list not reported; OBO NG/OK roles unchecked")
    else:
        ok_roles = set((users.get(cfg.obo_ok) or {}).get("roles") or [])
        ng_roles = set((users.get(cfg.obo_ng) or {}).get("roles") or [])
        if ok_roles & set(excluded):
            r.errors.append(f"OBO OK user {cfg.obo_ok} holds an excluded role: {sorted(excluded)}")
        if users.get(cfg.obo_ng) is not None and not (ng_roles & set(excluded)):
            r.errors.append(
                f"OBO NG user {cfg.obo_ng} holds none of the excluded roles {sorted(excluded)}"
            )
    obo_enabled = (facts.get("config") or {}).get("WEKO_SWORDSERVER_SERVICEDOCUMENT_ON_BEHALF_OF")
    if obo_enabled is False:
        r.warnings.append(
            "On-Behalf-Of is disabled on the server (the OBO-allowed cases need True)"
        )

    item_types = {t["id"]: t.get("name") for t in facts.get("item_types") or []}
    for type_id in (ITEM_TYPE_SIMPLE, ITEM_TYPE_FULL):
        if type_id not in item_types:
            r.errors.append(f"item type missing: {type_id}")
    mappings = {m["id"]: m for m in facts.get("jsonld_mappings") or []}
    for mapping_id, type_id in ((MAPPING_SIMPLE, ITEM_TYPE_SIMPLE), (MAPPING_FULL, ITEM_TYPE_FULL)):
        found = mappings.get(mapping_id)
        if found is None:
            r.errors.append(f"jsonld mapping missing: {mapping_id}")
        elif found.get("item_type_id") != type_id:
            r.errors.append(f"jsonld mapping {mapping_id} is not for item type {type_id}")

    flows = {f["id"]: f for f in facts.get("flows") or []}
    flow = flows.get(REGISTRATION_FLOW_ID)
    if flow is None:
        r.errors.append(f"registration flow missing: id {REGISTRATION_FLOW_ID}")
    elif flow.get("flow_type") != 1:
        r.errors.append(f"flow {REGISTRATION_FLOW_ID} is not a registration flow")
    if not any(f.get("flow_type") == 2 for f in flows.values()):
        r.infos.append("no deletion flow yet (expected on a fresh install; bootstrap creates one)")

    workflows = {w["id"]: w for w in facts.get("workflows") or []}
    for workflow_id in DEMO_WORKFLOW_IDS:
        if workflow_id not in workflows:
            r.errors.append(f"workflow missing: id {workflow_id}")
    template = workflows.get(TEMPLATE_WORKFLOW_ID)
    if template is not None and template.get("itemtype_id") != cfg.item_type_id:
        r.errors.append(
            f"workflow {TEMPLATE_WORKFLOW_ID} is for item type {template.get('itemtype_id')}, "
            f"not {cfg.item_type_id}"
        )

    if not facts.get("locations"):
        r.errors.append("no files location (install.sh creates `local`)")
    if DEMO_INDEX_ID not in (facts.get("indexes") or []):
        r.warnings.append(f"demo index missing: {DEMO_INDEX_ID}")
    setting_ids = {s["id"] for s in facts.get("admin_settings") or []}
    absent = [i for i in DEMO_ADMIN_SETTING_IDS if i not in setting_ids]
    if absent:
        r.warnings.append(f"admin_settings ids missing: {absent}")

    counts = facts.get("counts") or {}
    if counts.get("sword_clients"):
        r.infos.append(f"{counts['sword_clients']} SwordClient rows exist (a fresh install has 0)")
    if counts.get("communities"):
        r.infos.append(f"{counts['communities']} communities exist (a fresh install has 0)")

    for number in range(1, 10):
        status = (facts.get("recids") or {}).get(cfg.recid(number))
        if number == 9 and status is not None:
            r.errors.append(
                f"R9 ({cfg.recid(9)}) must not exist but a recid PID does (status {status})"
            )
        elif status is not None:
            r.infos.append(
                f"R{number} ({cfg.recid(number)}) exists already (status {status}); reused"
            )
    return r


# ---------------------------------------------------------------------------
# Token / client plan (pure data)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenSpec:
    """One personal token, its OAuth client, and how the client is registered."""

    name: str
    token_env: str
    user_key: str
    scopes: tuple[str, ...]
    sword: str | None = "Direct"  # "Direct", "Workflow" or None (no SwordClient)
    client_env: str | None = None
    revoke: bool = False
    note: str = ""


def token_specs(cfg: Config) -> list[TokenSpec]:
    """Tokens of S0-02 for the clients of S0-03 (client names are the token names)."""
    specs = [
        TokenSpec(
            "sw-cd-1",
            "SW_TOKEN_1",
            "SYSADMIN",
            SCOPES_FULL,
            "Direct",
            "SW_CLIENT_ID_1",
            note="(1) C-D, activity scope present",
        ),
        TokenSpec(
            "sw-cd-2",
            "SW_TOKEN_2",
            "SYSADMIN",
            SCOPES_NO_ACTIVITY,
            "Direct",
            note="(2) no activity scope",
        ),
        TokenSpec("sw-cd-5", "SW_TOKEN_5", "SYSADMIN", (), "Direct", note="(5) no scope at all"),
        TokenSpec(
            "sw-cd-rev",
            "SW_TOKEN_REV",
            "SYSADMIN",
            SCOPES_FULL,
            "Direct",
            note="T-REV, to be revoked by S1-02",
        ),
        TokenSpec(
            "sw-cd-revoked",
            "SW_TOKEN_REVOKED",
            "SYSADMIN",
            SCOPES_FULL,
            None,
            revoke=True,
            note="(3) minted, then revoked here",
        ),
        TokenSpec(
            "sw-cw",
            "SW_TOKEN_W",
            "SYSADMIN",
            SCOPES_FULL,
            "Workflow",
            "SW_CLIENT_ID_2",
            note="C-W with a deletion flow",
        ),
        TokenSpec(
            "sw-cw-2",
            "SW_TOKEN_W2",
            "SYSADMIN",
            SCOPES_NO_ACTIVITY,
            "Workflow",
            note="(2) for C-W: no activity scope (S3-03, S3-05)",
        ),
        TokenSpec(
            "sw-cobo",
            "SW_TOKEN_OBO",
            "SYSADMIN",
            SCOPES_FULL,
            "Direct",
            "SW_CLIENT_ID_3",
            note="C-OBO",
        ),
        TokenSpec(
            "sw-cx",
            "SW_TOKEN_X",
            "SYSADMIN",
            SCOPES_FULL,
            None,
            "SW_CLIENT_ID_X",
            note="C-X: OAuth client without SwordClient",
        ),
    ]
    for user in SPEC_USERS[1:]:
        specs.append(
            TokenSpec(
                f"sw-role-{user.key.lower()}",
                f"SW_TOKEN_ROLE_{user.key}",
                user.key,
                SCOPES_FULL,
                "Direct",
                note=f"(1) for the role {user.spec_role} (S2-01)",
            )
        )
    return specs


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

_MASK_KEYS = {"password", "access_token"}


def mask(params: Mapping[str, Any]) -> dict[str, Any]:
    """Params with secret values hidden (for printing)."""
    return {k: ("***" if k in _MASK_KEYS else v) for k, v in params.items()}


def dry_run_call(log: Callable[[str], None]) -> Call:
    """A `Call` that prints the helper call and answers with placeholders."""

    def call(cmd: str, params: dict[str, Any]) -> Any:
        log(f"  {cmd} {json.dumps(mask(params), ensure_ascii=False, sort_keys=True)}")
        if cmd == "create_token":
            return {
                "access_token": "<token>",
                "client_id": f"<client_id of {params.get('client_name') or params['name']}>",
            }
        if cmd == "create_flow":
            return {"id": "<delete flow id>"}
        if cmd == "create_workflow":
            return {"id": "<workflow id>"}
        return {}

    return call


def helper_call(cmd: str, params: dict[str, Any]) -> Any:
    """Run one helper command through `weko_suite_ext.helper` (docker exec)."""
    import weko_suite_ext

    result = weko_suite_ext.helper({"cmd": cmd, "params": json.dumps(params)}, None)
    if not result.ok:
        raise HelperFailure(cmd, "HelperUnavailable", str(result.failure))
    body = result.body
    if not isinstance(body, dict) or not body.get("ok"):
        error = (body or {}).get("error", {}) if isinstance(body, dict) else {}
        raise HelperFailure(cmd, str(error.get("type")), str(error.get("message")))
    return body.get("result")


def fetch_facts(call: Call, cfg: Config) -> dict[str, Any]:
    """The helper `baseline` facts for this configuration."""
    return call(
        "baseline",
        {"emails": cfg.user_emails, "recids": [cfg.recid(n) for n in range(1, 10)]},
    )


def check_baseline(call: Call, cfg: Config) -> Report:
    """`ping` then evaluate the baseline."""
    ping = call("ping", {})
    if not (isinstance(ping, dict) and ping.get("db_ok")):
        raise BootstrapError("helper ping did not report db_ok")
    return evaluate_baseline(fetch_facts(call, cfg), cfg)


def print_report(report: Report, log: Callable[[str], None]) -> None:
    for label, items in (
        ("ERROR", report.errors),
        ("WARN", report.warnings),
        ("INFO", report.infos),
    ):
        for item in items:
            log(f"[{label}] {item}")
    log("baseline: OK" if report.ok else f"baseline: {len(report.errors)} problem(s)")


def bootstrap(
    cfg: Config,
    call: Call,
    log: Callable[[str], None],
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, str]:
    """Run every step and return the variables for `.env.local`."""
    users = {u.key: u for u in SPEC_USERS}

    log("1. baseline")
    if dry_run:
        call("ping", {})
        call(
            "baseline", {"emails": cfg.user_emails, "recids": [cfg.recid(n) for n in range(1, 10)]}
        )
        missing = list(cfg.user_emails)
        log("  (dry run: every user is listed; a real run creates only the missing ones)")
    else:
        report = check_baseline(call, cfg)
        print_report(report, log)
        if not report.ok and not force:
            raise BootstrapError("baseline problems; fix them or rerun with --force")
        missing = report.missing_users

    log("2. users (only the missing ones)")
    for email in missing:
        roles = next((list(u.roles) for u in SPEC_USERS if u.email == email), [])
        if email in (cfg.obo_ok, cfg.obo_ng) and not roles:
            roles = [ROLE_CONTRIBUTOR] if email == cfg.obo_ok else [ROLE_SYSTEM]
        call("create_user", {"email": email, "password": cfg.password, "roles": roles})

    log("3. deletion flow and workflow for C-W")
    flow = call("create_flow", {"flow_name": DELETE_FLOW_NAME, "for_delete": True})
    workflow = call(
        "create_workflow",
        {
            "flows_name": WORKFLOW_NAME,
            "copy_from": TEMPLATE_WORKFLOW_ID,
            "delete_flow_name": DELETE_FLOW_NAME,
        },
    )

    log("4. tokens, OAuth clients and SwordClients")
    env: dict[str, str] = {}
    client_ids: dict[str, str] = {}
    for spec in token_specs(cfg):
        owner = users[spec.user_key]
        minted = call(
            "create_token",
            {"user_email": owner.email, "name": spec.name, "scopes": list(spec.scopes)},
        )
        token, client_id = minted["access_token"], minted["client_id"]
        client_ids[spec.name] = client_id
        if spec.sword:
            reg: dict[str, Any] = {
                "client_id": client_id,
                "registration_type": spec.sword,
                "mapping_id": cfg.mapping_id,
            }
            if spec.sword == "Workflow":
                reg["workflow_id"] = workflow["id"]
            call("register_sword_client", reg)
        if spec.revoke:
            call("revoke_token", {"access_token": token})
        env[spec.token_env] = token
        if spec.client_env:
            env[spec.client_env] = client_id
        log(f"  {spec.name}: {spec.token_env} ({spec.note})")
    env["SW_TOKEN_3"] = env["SW_TOKEN_REVOKED"]
    env["SW_TOKEN_4"] = ""  # (4) is "no token presented"
    env["SW_TOKEN_ROLE_SYSADMIN"] = env["SW_TOKEN_1"]

    log("5. state records R1-R9")
    owner_email = users["SYSADMIN"].email
    for number in range(1, 9):
        recid = cfg.recid(number)
        call(
            "create_record",
            {
                "title": f"ath state record R{number}",
                "owner_email": owner_email,
                "recid": recid,
                "item_type_id": cfg.item_type_id,
                "with_doi": number == 2,
            },
        )
        if number == 3:
            call("delete_record", {"recid": recid})
        env[f"SW_R{number}"] = recid
    env["SW_R9"] = cfg.recid(9)  # never created

    for user in SPEC_USERS:
        env[f"SW_USER_{user.key}"] = user.email
    env["SW_USER_OBO_OK"] = cfg.obo_ok
    env["SW_USER_OBO_NG"] = cfg.obo_ng
    env["SW_USER_PASSWORD"] = cfg.password
    env["SW_ITEM_TYPE_ID"] = str(cfg.item_type_id)
    env["SW_WORKFLOW_ID"] = str(workflow["id"])
    env["SW_DELETE_FLOW_ID"] = str(flow["id"])
    for key in PASSTHROUGH:
        if cfg.env_values.get(key):
            env[key] = cfg.env_values[key]
    return env


# ---------------------------------------------------------------------------
# .env handling
# ---------------------------------------------------------------------------


def parse_env(text: str) -> dict[str, str]:
    """Parse KEY=value lines (comments and blanks skipped; no quoting rules)."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def load_env_values(root: Path, environ: Mapping[str, str]) -> dict[str, str]:
    """`.env.example` defaults, overridden by `.env`, overridden by the environment."""
    values: dict[str, str] = {}
    for name in (".env.example", ".env"):
        path = root / name
        if path.is_file():
            values.update({k: v for k, v in parse_env(path.read_text("utf-8")).items() if v})
    values.update({k: v for k, v in environ.items() if k in PASSTHROUGH and v})
    return values


GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Target and containers", PASSTHROUGH),
    (
        "Users (S0-01). Passwords are the install.sh demo password.",
        tuple(f"SW_USER_{u.key}" for u in SPEC_USERS)
        + ("SW_USER_OBO_OK", "SW_USER_OBO_NG", "SW_USER_PASSWORD"),
    ),
    (
        "Tokens (S0-02): 1..5 are the spec's (1)-(5); 4 is intentionally empty (no token).",
        (
            "SW_TOKEN_1",
            "SW_TOKEN_2",
            "SW_TOKEN_3",
            "SW_TOKEN_4",
            "SW_TOKEN_5",
            "SW_TOKEN_REVOKED",
            "SW_TOKEN_REV",
            "SW_TOKEN_W",
            "SW_TOKEN_W2",
            "SW_TOKEN_OBO",
            "SW_TOKEN_X",
        )
        + tuple(f"SW_TOKEN_ROLE_{u.key}" for u in SPEC_USERS),
    ),
    (
        "OAuth clients (S0-03): 1=C-D, 2=C-W, 3=C-OBO, X=C-X",
        ("SW_CLIENT_ID_1", "SW_CLIENT_ID_2", "SW_CLIENT_ID_3", "SW_CLIENT_ID_X"),
    ),
    ("Workflow facts", ("SW_ITEM_TYPE_ID", "SW_WORKFLOW_ID", "SW_DELETE_FLOW_ID")),
    ("State records (S0-05)", tuple(f"SW_R{n}" for n in range(1, 10))),
)


def render_env(values: Mapping[str, str]) -> str:
    """The text of `.env.local` (stable order, every key of `values` appears)."""
    lines = [
        "# Generated by seeds/bootstrap.py. Contains secrets: never commit, never paste.",
        "# Load after .env:  set -a; . ./.env; . ./.env.local; set +a",
    ]
    seen: set[str] = set()
    for title, keys in GROUPS:
        present = [k for k in keys if k in values]
        if not present:
            continue
        lines += ["", f"# {title}"]
        for key in present:
            lines.append(f"{key}={values[key]}")
            seen.add(key)
    extra = sorted(set(values) - seen)
    if extra:
        lines += ["", "# Other"] + [f"{k}={values[k]}" for k in extra]
    return "\n".join(lines) + "\n"


def write_env(path: Path, values: Mapping[str, str]) -> None:
    """Write `.env.local` atomically with mode 0600."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(render_env(values))
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def secret_names(values: Mapping[str, str]) -> list[str]:
    """Names of the variables that hold secrets (what may be printed instead of values)."""
    return sorted(k for k in values if k.startswith(SECRET_KEYS_PREFIX))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("baseline-check", "list what is missing from the install.sh baseline; change nothing"),
        ("run", "create what the suite needs on top of the baseline and write .env.local"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--recid-base", type=int, default=900000, help="R<n> = base + n")
        p.add_argument("--obo-ok", default=os.environ.get("SW_USER_OBO_OK", DEFAULT_OBO_OK))
        p.add_argument("--obo-ng", default=os.environ.get("SW_USER_OBO_NG", DEFAULT_OBO_NG))
        if name == "run":
            p.add_argument("--dry-run", action="store_true", help="print the helper calls only")
            p.add_argument("--force", action="store_true", help="continue despite baseline errors")
            p.add_argument("--env-file", default=str(ROOT / ".env.local"))
    return parser


def main(argv: list[str] | None = None, call: Call | None = None, root: Path = ROOT) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config(
        recid_base=args.recid_base,
        password=os.environ.get("SW_USER_PASSWORD") or DEMO_PASSWORD,
        obo_ok=args.obo_ok,
        obo_ng=args.obo_ng,
        env_values=load_env_values(root, os.environ),
    )

    def log(line: str) -> None:
        print(line)

    try:
        if args.command == "baseline-check":
            report = check_baseline(call or helper_call, cfg)
            print_report(report, log)
            return 0 if report.ok else 1
        dry = args.dry_run
        env = bootstrap(
            cfg, dry_run_call(log) if dry else (call or helper_call), log, dry, args.force
        )
        if dry:
            log(f"dry run: would write {args.env_file} with: {', '.join(sorted(env))}")
            return 0
        write_env(Path(args.env_file), env)
        log(f"wrote {args.env_file} (mode 0600); secret variables: {', '.join(secret_names(env))}")
        return 0
    except BootstrapError as exc:
        print(f"bootstrap: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
