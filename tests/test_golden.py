"""The generated source for the fixture specs, byte for byte.

Regenerate after an intended change with `UPDATE_GOLDEN=1 uv run pytest
tests/test_golden.py`, then review the diff.
"""

import os

from conftest import GOLDEN, Project


def test_rendered_files_match_golden(project: Project) -> None:
    files, problems = project.render()
    assert problems == []
    if os.environ.get("UPDATE_GOLDEN"):
        for stale in GOLDEN.glob("*.py"):
            stale.unlink()
        for name, text in files.items():
            (GOLDEN / name).write_text(text)
    assert sorted(files) == sorted(p.name for p in GOLDEN.glob("*.py"))
    for name, text in files.items():
        assert text == (GOLDEN / name).read_text(), name


def test_spec_without_operations_gets_no_module(project: Project) -> None:
    files, _ = project.render()
    assert "common.py" not in files
