#!/usr/bin/env python3
"""Write a COPY of plugin.yaml with the rig-only operations appended.

    python make_rig_plugin.py <plugin.yaml> <rig-ops.yaml> <out.yaml>

plugin.yaml itself is never modified. The operations are inserted at the end of
the `operations:` section, which ends where the top-level `states:` begins.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(__doc__)
        return 2
    plugin, ops, out = (Path(a) for a in argv)
    text = plugin.read_text(encoding="utf-8")
    marker = "\nstates:"
    head, sep, tail = text.partition(marker)
    if not sep:
        sys.stderr.write("no top-level `states:` section found in the plugin\n")
        return 1
    addition = ops.read_text(encoding="utf-8").rstrip("\n") + "\n"
    out.write_text(head.rstrip("\n") + "\n\n" + addition + marker + tail, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
