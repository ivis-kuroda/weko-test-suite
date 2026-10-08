"""Pure SQL builders for backing up, deleting and restoring single rows."""

import json

import contract

# table -> column that links a row to the record's object uuid
ROW_TABLES = {
    "records_metadata": "id",
    "item_metadata": "id",
}


def check_tables(tables):
    """Validate a list of row tables against the allow-list."""
    if not tables:
        raise contract.HelperError("InvalidArgument", "tables must not be empty")
    for table in tables:
        if table not in ROW_TABLES:
            raise contract.HelperError(
                "InvalidArgument", "table must be one of: %s" % ", ".join(sorted(ROW_TABLES))
            )
    return list(tables)


def backup_sql(table):
    """SELECT returning the row as JSON text."""
    key = contract.quote_ident(ROW_TABLES[table])
    return "SELECT row_to_json(t)::text AS row FROM %s t WHERE t.%s = CAST(:u AS uuid)" % (
        contract.quote_ident(table),
        key,
    )


def delete_sql(table):
    """DELETE of the record's row."""
    return "DELETE FROM %s WHERE %s = CAST(:u AS uuid)" % (
        contract.quote_ident(table),
        contract.quote_ident(ROW_TABLES[table]),
    )


def restore_sql(table):
    """INSERT re-creating a row from its JSON text (bind ``:row``)."""
    name = contract.quote_ident(table)
    return (
        "INSERT INTO %s SELECT (json_populate_record(CAST(NULL AS %s), CAST(:row AS json))).*"
        % (
            name,
            name,
        )
    )


def pid_uuid_sql():
    """Resolve a recid to the record's object uuid."""
    return (
        "SELECT object_uuid::text AS u FROM pidstore_pid "
        "WHERE pid_type = 'recid' AND pid_value = :v LIMIT 1"
    )


def delete_rows(db, recid, tables):
    """Back up then delete rows; return ``{uuid, backup}`` (executor based)."""
    tables = check_tables(tables)
    found = db.query(pid_uuid_sql(), {"v": str(recid)})
    if not found:
        raise contract.HelperError("RecordNotFound", "no recid pid for %s" % recid)
    uuid_ = found[0]["u"]
    backup = []
    for table in tables:
        for row in db.query(backup_sql(table), {"u": uuid_}):
            backup.append({"table": table, "row": row["row"]})
        db.execute(delete_sql(table), {"u": uuid_})
    db.commit()
    return {"recid": str(recid), "uuid": uuid_, "backup": backup}


def restore_rows(db, backup):
    """Re-insert rows returned by :func:`delete_rows` (idempotent per row)."""
    restored = []
    for entry in backup:
        table = entry.get("table") if isinstance(entry, dict) else None
        row = entry.get("row") if isinstance(entry, dict) else None
        check_tables([table])
        if not isinstance(row, str):
            raise contract.HelperError("InvalidArgument", "backup row must be a JSON string")
        key = json.loads(row).get(ROW_TABLES[table])
        exists = db.query(
            "SELECT 1 AS x FROM %s WHERE %s = CAST(:u AS uuid)"
            % (contract.quote_ident(table), contract.quote_ident(ROW_TABLES[table])),
            {"u": key},
        )
        if not exists:
            db.execute(restore_sql(table), {"row": row})
            restored.append(table)
    db.commit()
    return {"restored_tables": restored}
