"""inject_fault / restore_fault / list_faults over faultlib (raw SQL only)."""

import contract
import faultlib


def run_inject(params):
    """Create a named fault. UNVERIFIED until run on a real WEKO database."""
    from dbx import SessionDb

    kind = contract.require_str(params, "kind")
    inner = params.get("params")
    if inner is None:
        inner = {}
    if not isinstance(inner, dict):
        raise contract.HelperError("InvalidArgument", "params must be an object")
    return faultlib.inject(SessionDb(), kind, inner)


def run_restore(params):
    """Restore one kind, one fault_id, or everything (default). UNVERIFIED."""
    from dbx import SessionDb

    kind = contract.optional_str(params, "kind", "all")
    return faultlib.restore(SessionDb(), kind, contract.optional_str(params, "fault_id"))


def run_list(params):
    """List active faults (``[]`` means clean) or, with catalog=true, the recipes."""
    if contract.optional_bool(params, "catalog", False):
        return faultlib.catalog()
    from dbx import SessionDb

    return faultlib.list_faults(SessionDb())
