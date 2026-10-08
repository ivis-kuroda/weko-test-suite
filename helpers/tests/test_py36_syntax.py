"""Every helper module must parse with Python 3.6 grammar."""

import ast
import glob
import os

import pytest

HELPERS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = sorted(glob.glob(os.path.join(HELPERS, "*.py")))


@pytest.mark.parametrize("path", FILES, ids=os.path.basename)
def test_parses_as_python_36(path):
    with open(path, encoding="utf-8") as f:
        ast.parse(f.read(), filename=path, feature_version=(3, 6))


def test_no_future_annotations_or_dataclasses():
    for path in FILES:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert "from __future__ import annotations" not in src, path
        assert "import dataclasses" not in src and "from dataclasses" not in src, path
