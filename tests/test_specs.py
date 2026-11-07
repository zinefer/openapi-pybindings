"""The spec loader, operation walker and $ref resolver on their own."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openapi_pybindings.generator import Resolver, UnsupportedShape, _identifier
from openapi_pybindings.specs import discover_specs, iter_operations, load_spec


def test_yaml_is_read_as_yaml_1_2(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text(
        "words: [on, off, yes, no, y, n, On, NO]\n"
        "bools: [true, false, True, FALSE]\n"
        "date: 2026-01-02\n"
        "stamp: 2026-01-02T03:04:05Z\n"
        "codes: {200: a, '201': b}\n"
        "number: 1.5\n"
    )
    assert load_spec(path) == {
        "words": ["on", "off", "yes", "no", "y", "n", "On", "NO"],
        "bools": [True, False, True, False],
        "date": "2026-01-02",
        "stamp": "2026-01-02T03:04:05Z",
        "codes": {200: "a", "201": "b"},
        "number": 1.5,
    }


def test_json_specs_load(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"openapi": "3.0.3", "paths": {}}))
    assert load_spec(path) == {"openapi": "3.0.3", "paths": {}}


def test_json_specs_are_parsed_as_json(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text("openapi: 3.0.3\n")  # YAML, but not JSON
    with pytest.raises(ValueError):
        load_spec(path)


def test_invalid_yaml_is_a_value_error(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text("paths: {/x: [unclosed\n")
    with pytest.raises(ValueError, match="is not valid YAML"):
        load_spec(path)


@pytest.mark.parametrize("text", ["", "just a string\n", "- a\n- b\n"])
def test_non_mapping_documents_are_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "s.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="is not an OpenAPI document"):
        load_spec(path)


def test_discover_specs(tmp_path: Path) -> None:
    for name in ("b.yaml", "a.json", "c.yml", "notes.md", "d.YAML.bak"):
        (tmp_path / name).write_text("{}")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "e.yaml").write_text("{}")
    (tmp_path / "dir.yaml").mkdir()
    assert [p.name for p in discover_specs(tmp_path)] == ["a.json", "b.yaml", "c.yml"]


def test_iter_operations() -> None:
    shared = [{"name": "id", "in": "path"}]
    spec = {
        "paths": {
            "/a": {
                "parameters": shared,
                "post": {"operationId": "p"},
                "summary": "not an operation",
                "get": {"operationId": "g"},
                "x-extension": {"operationId": "nope"},
            },
            "/b": {"delete": {"operationId": "d"}},
            "/c": None,
        }
    }
    ops = list(iter_operations(spec))
    assert [(o.method, o.path, o.operation["operationId"]) for o in ops] == [
        ("GET", "/a", "g"),
        ("POST", "/a", "p"),
        ("DELETE", "/b", "d"),
    ]
    assert ops[0].path_parameters == shared
    assert ops[2].path_parameters == []
    assert list(iter_operations({})) == []
    assert list(iter_operations({"paths": None})) == []


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_refs_resolve_relative_to_the_file_they_are_in(tmp_path: Path) -> None:
    write(tmp_path / "a.yaml", "start: {$ref: 'shared/b.yaml#/hop'}\n")
    write(tmp_path / "shared" / "b.yaml", "hop: {$ref: '../c.yaml#/end'}\n")
    write(
        tmp_path / "c.yaml", "end: {here: true, again: {$ref: '#/other'}}\nother: {}\n"
    )
    resolver = Resolver(tmp_path, "api")
    node, current = resolver.resolve(resolver.spec("a.yaml")["start"], "a.yaml")
    assert node["here"] is True
    assert current == "c.yaml"
    # A later local ref in the target is relative to the target's file.
    assert resolver.resolve(node["again"], current) == ({}, "c.yaml")


def test_json_pointer_escapes(tmp_path: Path) -> None:
    write(
        tmp_path / "a.yaml",
        "paths:\n"
        "  /v1/x~y:\n"
        "    get:\n"
        "      responses:\n"
        "        200: {description: found}\n"
        "spaced key: {ok: 1}\n"
        "list: [{first: 1}, {second: 2}]\n",
    )
    resolver = Resolver(tmp_path, "api")
    for ref, expected in [
        ("#/paths/~1v1~1x~0y/get/responses/200", {"description": "found"}),
        ("#/spaced%20key", {"ok": 1}),
        ("#/list/1", {"second": 2}),
    ]:
        assert resolver.resolve({"$ref": ref}, "a.yaml") == (expected, "a.yaml")


@pytest.mark.parametrize(
    ("ref", "message"),
    [
        ("#/missing", "unresolvable $ref #/missing"),
        ("#/list/5", "unresolvable $ref #/list/5"),
        ("#/scalar/deeper", "unresolvable $ref"),
        ("#/scalar", "does not point at an object"),
        ("nope.yaml#/x", "cannot load nope.yaml"),
        ("http://example.com/a.yaml#/x", "remote $ref"),
        ("#/self", "$ref cycle"),
    ],
)
def test_bad_refs(tmp_path: Path, ref: str, message: str) -> None:
    write(tmp_path / "a.yaml", "list: [1]\nscalar: 3\nself: {$ref: '#/self'}\n")
    with pytest.raises(UnsupportedShape, match=message.replace("$", r"\$")):
        Resolver(tmp_path, "api").resolve({"$ref": ref}, "a.yaml")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("getMovie", "get_movie"),
        ("getMovieByID", "get_movie_by_id"),
        ("list-movies", "list_movies"),
        ("movie_id", "movie_id"),
        ("pageSize", "page_size"),
        ("v2Thing", "v2_thing"),
        ("class", "class_"),
        ("import", "import_"),
        ("page[size]", "page_size_"),
        ("filter.name", "filter_name"),
        ("2fa", "_2fa"),
        # Kept from the original for output compatibility: acronyms are not split.
        ("HTTPServer", "httpserver"),
    ],
)
def test_identifier(name: str, expected: str) -> None:
    assert _identifier(name) == expected


def test_identifier_rejects_empty() -> None:
    with pytest.raises(UnsupportedShape):
        _identifier("")
