"""docs/helpers.md must mention every command and fault recipe."""

import os

import faultlib
import registry

DOC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs",
    "helpers.md",
)


def test_docs_cover_commands_and_recipes():
    with open(DOC, encoding="utf-8") as f:
        text = f.read()
    for name in list(registry.COMMANDS) + list(faultlib.RECIPES):
        assert "`%s`" % name in text, name
