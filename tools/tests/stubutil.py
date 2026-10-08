"""Shared helpers for the sword-stub tests (not a test module)."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUB_DIR = ROOT / "tools" / "sword-stub"
for entry in (STUB_DIR, ROOT / "seeds"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import build_fixtures as bf  # noqa: E402
import errtable  # noqa: E402, F401
import stub_server  # noqa: E402

EXAMPLE_CONFIG = json.loads((STUB_DIR / "stub.example.json").read_text(encoding="utf-8"))
ADMIN = "STUBTOKEN-direct-admin"


class Running:
    """A stub serving on an ephemeral port in a background thread."""

    def __init__(self, config: dict, log_file: str | None = None) -> None:
        self.server = stub_server.make_server(config, log_file)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self.thread.start()
        self.url = self.server.url
        self.world = self.server.world

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def fixture_bytes(name: str) -> bytes:
    return next(f for f in bf.catalogue() if f.name == name).build()


def fixture_packaging(name: str) -> str:
    found = next((f for f in bf.catalogue() if f.name == name), None)
    return found.packaging if found else bf.PKG_SIMPLEZIP


def deposit_headers(
    name: str,
    data: bytes | None = None,
    packaging: str | None = None,
    token: str | None = ADMIN,
    filename: str | None = None,
) -> dict[str, str]:
    data = data if data is not None else fixture_bytes(name)
    headers = {
        "Content-Disposition": f"attachment; filename={filename or name}",
        "Packaging": packaging or fixture_packaging(name),
        "Digest": bf.digest_header(data),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
