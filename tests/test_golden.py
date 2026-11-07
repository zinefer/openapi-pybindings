"""The generated source for the fixture specs, byte for byte.

Regenerate after an intended change with `UPDATE_GOLDEN=1 uv run pytest
tests/test_golden.py`, then review the diff.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import GOLDEN, SPECS, Project, ProjectFactory


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


LONG_NAMES = """\
openapi: 3.0.3
info: {title: long, version: "1"}
paths:
  /v1/an/unreasonably/long/path/{the_identifier_of_the_thing}/with/many/segments:
    post:
      operationId: listEveryThingByOwnerAndYearIncludingTheArchivedOnesToo
      parameters:
        - name: the_identifier_of_the_thing
          in: path
          required: true
          schema: {type: string}
        - {name: aVeryLongQueryParameterName, in: query, schema: {type: string}}
        - name: anotherQuiteLongListOfIdentifiersParameter
          in: query
          explode: false
          schema: {type: array, items: {type: string, format: uuid}}
        - name: aRepeatedListOfExtremelyLongNamesParameter
          in: query
          required: true
          schema: {type: array, items: {type: integer}}
        - name: aDeepObjectFilterWithAnUnreasonablyLongName
          in: query
          style: deepObject
          schema: {$ref: "#/components/schemas/AThingWithAnExtremelyLongName"}
        - name: X-A-Header-Parameter-With-An-Unreasonably-Long-Name
          in: header
          schema: {type: array, items: {type: string}}
      requestBody:
        content:
          application/json:
            schema:
              type: array
              items: {$ref: "#/components/schemas/AThingWithAnExtremelyLongName"}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                type: object
                additionalProperties:
                  type: array
                  items: {$ref: "#/components/schemas/AThingWithAnExtremelyLongName"}
  /v1/short:
    get:
      operationId: getTheDownloadableExportOfEverythingThatHasEverExisted
      responses:
        "200":
          description: csv
          content:
            text/csv:
              schema: {type: string}
components:
  schemas:
    AThingWithAnExtremelyLongName:
      type: object
      properties: {a: {type: string}}
"""


@pytest.mark.parametrize("specs", ["fixtures", "long names"])
def test_generated_code_is_ruff_clean(make_project: ProjectFactory, specs: str) -> None:
    """Sorted imports and a stable `ruff format`, so the client can live in a
    project that checks both."""
    project = make_project(SPECS if specs == "fixtures" else {"long.yaml": LONG_NAMES})
    assert project.generate() == []
    ruff = str(Path(sys.executable).parent / "ruff")
    for target in ("py312", "py314"):
        common = ["--isolated", "--target-version", target]
        for args in (
            ["check", *common, "--select", "E,F,I,UP,W", "--ignore", "E501"],
            ["format", *common, "--check", "--diff"],
        ):
            result = subprocess.run(
                [ruff, *args, str(project.client_dir)],
                cwd=project.root,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr
