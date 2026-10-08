"""Command table: name -> (module, function, needs_app).

Modules are imported lazily so that ``list`` and unit tests never pull in WEKO.
"""

COMMANDS = {
    "ping": ("cmd_ping", "run", True),
    "create_user": ("cmd_create_user", "run", True),
    "create_token": ("cmd_create_token", "run", True),
    "revoke_token": ("cmd_create_token", "run_revoke", True),
    "register_sword_client": ("cmd_register_sword_client", "run", True),
    "set_client_field": ("cmd_register_sword_client", "run_set_field", True),
    "create_record": ("cmd_create_record", "run", True),
    "insert_doi_pid": ("cmd_create_record", "run_insert_doi_pid", True),
    "delete_record_row": ("cmd_create_record", "run_delete_record_row", True),
    "orphan_record": ("cmd_create_record", "run_orphan_record", True),
    "baseline": ("cmd_baseline", "run", True),
    "create_flow": ("cmd_workflow", "run_create_flow", True),
    "create_workflow": ("cmd_workflow", "run_create_workflow", True),
    "delete_record": ("cmd_workflow", "run_delete_record", True),
    "snapshot": ("cmd_snapshot", "run", True),
    "inject_fault": ("cmd_inject_fault", "run_inject", True),
    "restore_fault": ("cmd_inject_fault", "run_restore", True),
    "list_faults": ("cmd_inject_fault", "run_list", True),
}


def resolve(name):
    """Return the handler callable for a command name, or ``None``."""
    import importlib

    entry = COMMANDS.get(name)
    if entry is None:
        return None
    module = importlib.import_module(entry[0])
    return getattr(module, entry[1])


def needs_app(name):
    """Whether the command must run inside a Flask application context."""
    return COMMANDS[name][2]
