"""Every shape the generator cannot type precisely is reported, never guessed, at
the JSON pointer of the part of the spec at fault."""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from conftest import Project, ProjectFactory
from openapi_pybindings import render

COMPONENTS: dict[str, Any] = {
    "schemas": {
        "Thing": {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        },
        "Nested": {
            "type": "object",
            "properties": {"inner": {"$ref": "#/components/schemas/Thing"}},
        },
        "Color": {"type": "string", "enum": ["red", "blue"]},
    },
    "parameters": {
        "Loop": {"$ref": "#/components/parameters/Loop2"},
        "Loop2": {"$ref": "#/components/parameters/Loop"},
        "Session": {"name": "sid", "in": "cookie", "schema": {"type": "string"}},
    },
}


def spec(paths: dict[str, Any]) -> str:
    return yaml.safe_dump(
        {
            "openapi": "3.0.3",
            "info": {"title": "svc", "version": "1"},
            "paths": paths,
            "components": COMPONENTS,
        },
        sort_keys=False,
    )


@pytest.fixture
def svc(make_project: ProjectFactory) -> Project:
    """A project whose models come from COMPONENTS; tests replace the paths."""
    return make_project({"svc.yaml": spec({})})


def with_paths(project: Project, paths: dict[str, Any]) -> list[str]:
    (project.spec_dir / "svc.yaml").write_text(spec(paths))
    _, problems = project.render()
    return problems


def ok(schema: Any = None) -> dict[str, Any]:
    if schema is None:
        return {"200": {"description": "ok"}}
    return {
        "200": {
            "description": "ok",
            "content": {"application/json": {"schema": schema}},
        }
    }


THING = {"$ref": "#/components/schemas/Thing"}
GET_X = "svc.yaml#/paths/~1x/get"
POST_X = "svc.yaml#/paths/~1x/post"
SCHEMA_200 = f"{GET_X}/responses/200/content/application~1json/schema"
BODY_SCHEMA = f"{POST_X}/requestBody/content/application~1json/schema"


def op(**fields: Any) -> dict[str, Any]:
    return {"operationId": "doIt", "responses": ok(), **fields}


def param(name: str, location: str = "query", **schema: Any) -> dict[str, Any]:
    return {
        "name": name,
        "in": location,
        "required": location == "path",
        "schema": schema or {"type": "string"},
    }


def json_body(schema: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {
        "required": True,
        "content": {"application/json": {"schema": schema}},
        **fields,
    }


def get_x(**fields: Any) -> dict[str, Any]:
    return {"/x": {"get": op(**fields)}}


CASES: list[tuple[str, dict[str, Any], str]] = [
    (
        "cookie parameter",
        get_x(parameters=[param("sid", "cookie")]),
        f"{GET_X}/parameters/0: cookie parameter sid",
    ),
    (
        "cookie parameter by ref",
        get_x(parameters=[{"$ref": "#/components/parameters/Session"}]),
        f"svc.yaml#/components/parameters/Session: cookie parameter sid (from {GET_X})",
    ),
    (
        "inline object query parameter",
        get_x(parameters=[param("f", type="object")]),
        f"{GET_X}/parameters/0: parameter f is not a single value",
    ),
    (
        "array of arrays",
        get_x(
            parameters=[
                param("ids", type="array", items={"type": "array", "items": {}})
            ]
        ),
        f"{GET_X}/parameters/0: parameter ids items are not single values",
    ),
    (
        "array items that may be null",
        get_x(
            parameters=[param("ids", type="array", items={"type": ["string", "null"]})]
        ),
        f"{GET_X}/parameters/0/schema/items: parameter ids items may be null",
    ),
    (
        "label style path parameter",
        {
            "/x/{id}": {
                "get": op(parameters=[{**param("id", "path"), "style": "label"}])
            }
        },
        "svc.yaml#/paths/~1x~1{id}/get/parameters/0: "
        "label style without explode for path parameter id",
    ),
    (
        "object query parameter without explode",
        get_x(parameters=[{**param("f", **THING), "explode": False}]),
        f"{GET_X}/parameters/0: form style without explode for query parameter f",
    ),
    (
        "object path parameter",
        {"/x/{f}": {"get": op(parameters=[param("f", "path", **THING)])}},
        "svc.yaml#/paths/~1x~1{f}/get/parameters/0: "
        "simple style without explode for path parameter f",
    ),
    (
        "object query parameter with an object property",
        get_x(parameters=[param("f", **{"$ref": "#/components/schemas/Nested"})]),
        "svc.yaml#/components/schemas/Nested/properties/inner: "
        f"parameter f property inner is not a single value (from {GET_X})",
    ),
    (
        "enum of mixed types",
        get_x(parameters=[param("e", enum=["a", 1])]),
        f"{GET_X}/parameters/0/schema: enum values must be all strings or all integers",
    ),
    (
        "OpenAPI 3.1 type list",
        get_x(parameters=[param("q", type=["string", "integer"])]),
        f"{GET_X}/parameters/0: parameter q is not a single value",
    ),
    (
        "nullable path parameter",
        {
            "/x/{q}": {
                "get": op(parameters=[param("q", "path", type=["string", "null"])])
            }
        },
        "svc.yaml#/paths/~1x~1{q}/get/parameters/0: required parameter q is nullable",
    ),
    (
        "nullable required query parameter",
        get_x(
            parameters=[{**param("q", type="string", nullable=True), "required": True}]
        ),
        f"{GET_X}/parameters/0: required parameter q is nullable",
    ),
    (
        "parameter with content",
        get_x(
            parameters=[
                {
                    "name": "q",
                    "in": "query",
                    "content": {"application/json": {"schema": THING}},
                }
            ]
        ),
        f"{GET_X}/parameters/0: parameter q uses content",
    ),
    (
        "parameter without a name",
        get_x(parameters=[{"in": "query", "schema": {"type": "string"}}]),
        f"{GET_X}/parameters/0: parameter without a name or in",
    ),
    (
        "inline object response",
        get_x(
            responses=ok({"type": "object", "properties": {"a": {"type": "string"}}})
        ),
        f"{SCHEMA_200}: inline object schema; give it a components/schemas entry",
    ),
    (
        "bare object response",
        get_x(responses=ok({"type": "object"})),
        f"{SCHEMA_200}: inline object schema; give it a components/schemas entry",
    ),
    (
        "inline object inside an array",
        get_x(responses=ok({"type": "array", "items": {"type": "object"}})),
        f"{SCHEMA_200}/items: inline object schema; give it a components/schemas entry",
    ),
    (
        "inline object inside a union",
        get_x(responses=ok({"oneOf": [THING, {"type": "object"}]})),
        f"{SCHEMA_200}/oneOf/1: inline object schema; give it a components/schemas "
        "entry",
    ),
    (
        "allOf of two schemas",
        get_x(responses=ok({"allOf": [THING, THING]})),
        f"{SCHEMA_200}: allOf of 2 schemas; give the combination a "
        "components/schemas entry",
    ),
    (
        "anyOf alongside properties",
        get_x(responses=ok({"anyOf": [THING], "properties": {}})),
        f"{SCHEMA_200}: anyOf alongside properties",
    ),
    (
        "response content without schema",
        get_x(
            responses={
                "200": {"description": "ok", "content": {"application/json": {}}}
            }
        ),
        f"{SCHEMA_200}: body has no schema",
    ),
    (
        "inline request body",
        {
            "/x": {
                "post": op(
                    requestBody=json_body(
                        {"type": "object", "properties": {"a": {"type": "integer"}}}
                    )
                )
            }
        },
        f"{BODY_SCHEMA}: inline object schema; give it a components/schemas entry",
    ),
    (
        "form request body",
        {
            "/x": {
                "post": op(
                    requestBody={
                        "content": {
                            "application/x-www-form-urlencoded": {"schema": THING}
                        }
                    }
                )
            }
        },
        f"{POST_X}/requestBody: request body types "
        "['application/x-www-form-urlencoded']",
    ),
    (
        "optional request body that may be null",
        {
            "/x": {
                "post": op(
                    requestBody=json_body({**THING, "nullable": True}, required=False)
                )
            }
        },
        f"{POST_X}/requestBody: optional request body that may also be null",
    ),
    (
        "schema missing from the models",
        get_x(responses=ok({"$ref": "#/components/schemas/Missing"})),
        f"{SCHEMA_200}: api.svc has no class Missing for #/components/schemas/Missing",
    ),
    (
        "body ref that is not a schema",
        get_x(responses=ok({"$ref": "#/components/parameters/Session"})),
        f"{SCHEMA_200}: #/components/parameters/Session is not a components/schemas "
        "ref",
    ),
    (
        "remote ref",
        get_x(parameters=[{"$ref": "https://example.com/s.yaml#/components/x"}]),
        f"{GET_X}/parameters/0: remote $ref https://example.com/s.yaml#/components/x",
    ),
    (
        "unresolvable ref",
        get_x(parameters=[{"$ref": "#/components/parameters/Nope"}]),
        f"{GET_X}/parameters/0: unresolvable $ref #/components/parameters/Nope",
    ),
    (
        "ref into a missing file",
        get_x(parameters=[{"$ref": "other.yaml#/components/x"}]),
        f"{GET_X}/parameters/0: cannot load other.yaml",
    ),
    (
        "ref cycle",
        get_x(parameters=[{"$ref": "#/components/parameters/Loop"}]),
        "svc.yaml#/components/parameters/Loop2: $ref cycle at "
        f"#/components/parameters/Loop (from {GET_X})",
    ),
    (
        "missing operationId",
        {"/x": {"get": {"responses": ok()}}},
        f"{GET_X}: operation has no operationId",
    ),
    (
        "unusable operationId",
        get_x(operationId=""),
        f"{GET_X}: '' cannot be made a Python identifier",
    ),
    (
        "non-JSON response with a query",
        get_x(
            parameters=[param("q")],
            responses={
                "200": {
                    "description": "csv",
                    "content": {"text/csv": {"schema": {"type": "string"}}},
                }
            },
        ),
        f"{GET_X}: non-JSON response with a query, header or body",
    ),
    (
        "non-JSON response to anything but GET",
        {
            "/x": {
                "delete": op(
                    responses={
                        "200": {
                            "description": "text",
                            "content": {"text/plain": {"schema": {"type": "string"}}},
                        }
                    }
                )
            }
        },
        "svc.yaml#/paths/~1x/delete: non-JSON response to DELETE",
    ),
    (
        "JSON and non-JSON success responses",
        get_x(
            responses={
                **ok(THING),
                "203": {"description": "csv", "content": {"text/csv": {}}},
            }
        ),
        f"{GET_X}/responses: success responses ['203'] are not JSON but others are",
    ),
    (
        "undeclared path placeholder",
        {"/x/{id}": {"get": op()}},
        "svc.yaml#/paths/~1x~1{id}/get: path placeholder {id} is not a parameter",
    ),
    (
        "path parameter missing from the path",
        get_x(parameters=[param("id", "path")]),
        f"{GET_X}: path parameters ['id'] are not in the path",
    ),
    (
        "unbalanced braces",
        {"/x/{id": {"get": op()}},
        "svc.yaml#/paths/~1x~1{id/get: path has unbalanced braces",
    ),
    (
        "operation that is not a mapping",
        {"/x": {"get": None}},
        f"{GET_X}: operation is a NoneType, not a mapping",
    ),
    (
        "parameters that are not a list",
        get_x(parameters={"q": param("q")}),
        f"{GET_X}/parameters: parameters is a dict, not a list",
    ),
    (
        "path item parameters that are not a list",
        {"/x": {"parameters": "q", "get": op()}},
        f"svc.yaml#/paths/~1x/parameters: parameters is a str, not a list "
        f"(from {GET_X})",
    ),
    (
        "parameter that is not a mapping",
        get_x(parameters=["q"]),
        f"{GET_X}/parameters/0: parameter is a str, not a mapping",
    ),
    (
        "parameter schema that is not a mapping",
        get_x(parameters=[{"name": "q", "in": "query", "schema": "s"}]),
        f"{GET_X}/parameters/0/schema: parameter q schema is a str, not a mapping",
    ),
    (
        "responses that are not a mapping",
        get_x(responses=["200"]),
        f"{GET_X}/responses: responses is a list, not a mapping",
    ),
    (
        "response that is not a mapping",
        get_x(responses={"200": "ok"}),
        f"{GET_X}/responses/200: response 200 is a str, not a mapping",
    ),
    (
        "content that is not a mapping",
        get_x(responses={"200": {"content": ["application/json"]}}),
        f"{GET_X}/responses/200: response content is a list, not a mapping",
    ),
    (
        "media type that is not a mapping",
        get_x(responses={"200": {"content": {"application/json": 1}}}),
        f"{GET_X}/responses/200: application/json is a int, not a mapping",
    ),
    (
        "body schema that is not a mapping",
        get_x(responses=ok("Thing")),
        f"{SCHEMA_200}: schema is a str, not a mapping",
    ),
    (
        "request body that is not a mapping",
        {"/x": {"post": op(requestBody="Thing")}},
        f"{POST_X}/requestBody: request body is a str, not a mapping",
    ),
    (
        "$ref that is not a string",
        get_x(responses=ok({"$ref": ["Thing"]})),
        f"{SCHEMA_200}: $ref ['Thing'] is not a string",
    ),
    (
        "unresolvable path item $ref",
        {"/x": {"$ref": "#/paths/~1y"}},
        "svc.yaml#/paths/~1x: unresolvable $ref #/paths/~1y",
    ),
]


@pytest.mark.parametrize(
    ("paths", "expected"),
    [pytest.param(paths, expected, id=name) for name, paths, expected in CASES],
)
def test_unsupported_shape_is_reported(
    svc: Project, paths: dict[str, Any], expected: str
) -> None:
    problems = with_paths(svc, paths)
    assert len(problems) == 1, problems
    assert problems[0].startswith(expected), problems


# A parameter named `name`, and the other parameters and body that make the
# generated function use `name` itself.
SHADOW_CASES: list[tuple[str, list[dict[str, Any]], dict[str, Any] | None]] = [
    ("transport", [], None),
    ("params", [], None),
    ("body", [], json_body(THING)),
    ("payload", [], json_body({"type": "array", "items": THING})),
    ("response", [], None),
    ("quote", [param("id", "path")], None),
    ("str", [param("u", type="string", format="uuid")], None),
    ("headers", [param("X-Trace", "header")], None),
    ("item", [param("ids", type="array", items={"type": "string"})], None),
    ("fields", [param("f", **THING)], None),
    ("key", [param("f", **THING)], None),
    ("value", [param("f", **THING)], None),
    ("svc", [], None),
]


@pytest.mark.parametrize(
    ("name", "others", "body"),
    [pytest.param(*case, id=case[0]) for case in SHADOW_CASES],
)
def test_parameter_that_would_shadow_a_name_the_body_uses(
    svc: Project,
    name: str,
    others: list[dict[str, Any]],
    body: dict[str, Any] | None,
) -> None:
    path = "/x/{id}" if any(p["in"] == "path" for p in others) else "/x"
    operation = op(parameters=[param(name), *others], responses=ok(THING))
    if body is not None:
        operation["requestBody"] = body
    problems = with_paths(svc, {path: {"post": operation}})
    pointer = path.replace("/", "~1")
    assert problems == [
        f"svc.yaml#/paths/{pointer}/post: parameter {name} would shadow {name} "
        "in the client"
    ]


def test_parameter_may_share_a_name_its_function_does_not_use(
    svc: Project,
) -> None:
    problems = with_paths(
        svc,
        {
            "/x": {"get": op(parameters=[param("svc"), param("quote")])},
            "/y": {"get": op(operationId="other", responses=ok(THING))},
        },
    )
    assert problems == []


def with_function_named(name: str) -> dict[str, Any]:
    """`name` defined first, then a function using every module level name."""
    return {
        "/a": {"get": op(operationId=name)},
        "/b/{id}": {
            "get": op(
                operationId="uses_everything",
                parameters=[
                    param("id", "path"),
                    param("on", type="string", format="date"),
                ],
                responses=ok({"type": "array", "items": THING}),
            )
        },
    }


@pytest.mark.parametrize(
    "name", ["date", "quote", "str", "int", "float", "bool", "list", "dict"]
)
def test_function_that_would_shadow_a_name_the_module_uses(
    svc: Project, name: str
) -> None:
    assert with_paths(svc, with_function_named(name)) == [
        f"svc.yaml#/paths/~1a/get: function {name} would shadow {name} in the client"
    ]


def test_function_named_after_a_models_module(svc: Project) -> None:
    # The module is imported first, then the function would replace it ...
    paths = {
        "/a": {"get": op(operationId="a", responses=ok(THING))},
        "/b": {"get": op(operationId="svc")},
    }
    assert with_paths(svc, paths) == [
        "svc.yaml#/paths/~1b/get: function svc would shadow svc in the client"
    ]
    # ... or the function comes first and a later one needs the module.
    assert with_paths(svc, dict(reversed(paths.items()))) == [
        "svc.yaml#/paths/~1a/get: models module svc is shadowed by function svc"
    ]


def test_parameters_that_collide_once_snake_cased(svc: Project) -> None:
    problems = with_paths(svc, get_x(parameters=[param("fooBar"), param("foo_bar")]))
    assert problems == [f"{GET_X}: two parameters are named foo_bar"]


def test_query_and_header_parameters_that_collide(svc: Project) -> None:
    problems = with_paths(
        svc, get_x(parameters=[param("trace"), param("Trace", "header")])
    )
    assert problems == [f"{GET_X}: two parameters are named trace"]


def test_ignored_header_parameters(svc: Project) -> None:
    files, problems = svc.render()
    problems = with_paths(
        svc,
        get_x(
            parameters=[
                param("Accept", "header"),
                param("content-type", "header"),
                param("AUTHORIZATION", "header"),
            ]
        ),
    )
    assert problems == []
    files, _ = svc.render()
    assert "async def do_it(transport: Transport) -> None:" in files["svc.py"]


def test_duplicate_operation_ids(svc: Project) -> None:
    problems = with_paths(svc, {"/x": {"get": op()}, "/y": {"get": op()}})
    assert problems == ["svc.yaml#/paths/~1y/get: duplicate function name do_it"]


def test_operation_ids_that_collide_once_snake_cased(svc: Project) -> None:
    problems = with_paths(
        svc,
        {"/x": {"get": op(operationId="getX")}, "/y": {"get": op(operationId="get_x")}},
    )
    assert problems == ["svc.yaml#/paths/~1y/get: duplicate function name get_x"]


def test_failed_operation_leaves_no_trace_and_others_still_generate(
    svc: Project,
) -> None:
    (svc.spec_dir / "svc.yaml").write_text(
        spec(
            {
                "/bad/{id}": {
                    "get": op(
                        operationId="bad",
                        parameters=[
                            param("id", "path", type="string", format="uuid"),
                            param("when", type="string", format="date-time"),
                            param("sort", enum=["a", "b"]),
                            param("sid", "cookie"),
                        ],
                        responses=ok({"type": "array", "items": THING}),
                    )
                },
                "/good": {"get": op(operationId="good")},
            }
        )
    )
    files, problems = svc.render()
    assert problems == [
        "svc.yaml#/paths/~1bad~1{id}/get/parameters/3: cookie parameter sid"
    ]
    module = files["svc.py"]
    assert "async def good(transport: Transport) -> None:" in module
    for leftover in (
        "bad",
        "UUID",
        "AwareDatetime",
        "Literal",
        "TypeAdapter",
        "from api import",
    ):
        assert leftover not in module, leftover


def test_version_prefix_is_enforced_when_requested(svc: Project) -> None:
    (svc.spec_dir / "svc.yaml").write_text(
        spec(
            {
                "/v1/a": {"get": op(operationId="a")},
                "/v3/b": {"get": op(operationId="b")},
                "/v1": {"get": op(operationId="c")},
                "/c": {"get": op(operationId="d")},
            }
        )
    )
    files, problems = svc.render(versions=["v1", "v2"])
    assert problems == [
        f"svc.yaml#/paths/{pointer}/get: path must start with one of the versions "
        "['v1', 'v2']"
        for pointer in ("~1v3~1b", "~1v1", "~1c")
    ]
    assert "async def a(" in files["svc.py"]
    _, problems = svc.render()
    assert problems == []


def test_spec_file_that_is_not_a_module_name(svc: Project) -> None:
    (svc.spec_dir / "my-api.yaml").write_text(spec({"/x": {"get": op()}}))
    _, problems = svc.render()
    assert problems == ["my-api.yaml: my-api.yaml does not name a Python module"]


def test_paths_that_are_not_a_mapping(svc: Project) -> None:
    (svc.spec_dir / "svc.yaml").write_text(
        'openapi: 3.0.3\ninfo: {title: svc, version: "1"}\npaths: [/x]\n'
    )
    files, problems = svc.render()
    assert problems == ["svc.yaml#/paths: paths is a list"]
    assert "svc.py" not in files


def test_spec_file_that_is_not_valid_yaml(svc: Project) -> None:
    (svc.spec_dir / "broken.yaml").write_text("paths: {/x: [unclosed\n")
    _, problems = svc.render()
    assert len(problems) == 1
    assert problems[0].startswith("broken.yaml: cannot load broken.yaml"), problems


def test_spec_file_that_is_not_a_mapping(svc: Project) -> None:
    (svc.spec_dir / "broken.yaml").write_text("- just\n- a list\n")
    _, problems = svc.render()
    assert len(problems) == 1
    assert problems[0].startswith("broken.yaml: cannot load broken.yaml")


def test_spec_named_init_cannot_replace_the_transport_module(svc: Project) -> None:
    (svc.spec_dir / "__init__.yaml").write_text(spec({"/x": {"get": op()}}))
    files, problems = svc.render()
    assert problems == ["__init__.yaml: would overwrite the Transport module"]
    assert files["__init__.py"].startswith("# GENERATED by openapi-pybindings.")


def test_unimportable_models_package(svc: Project) -> None:
    (svc.spec_dir / "svc.yaml").write_text(
        spec({"/x": {"get": op(responses=ok(THING))}})
    )
    _, problems = render(svc.spec_dir, models_package="no_such_models")
    assert len(problems) == 1
    assert problems[0].startswith(f"{SCHEMA_200}: cannot import no_such_models.svc")


def test_success_responses_are_combined(svc: Project) -> None:
    thing = ok(THING)["200"]
    color = ok({"$ref": "#/components/schemas/Color"})["200"]
    (svc.spec_dir / "svc.yaml").write_text(
        spec(
            {
                "/a": {
                    "post": op(
                        operationId="a",
                        responses={"204": {"description": "none"}, "201": thing},
                    )
                },
                "/b": {
                    "get": op(
                        operationId="b",
                        responses={"2XX": thing, "default": {"description": "x"}},
                    )
                },
                "/c": {"get": op(operationId="c", responses={"404": thing})},
                "/d": {
                    "get": op(operationId="d", responses={"200": thing, "201": color})
                },
                "/e": {
                    "get": op(operationId="e", responses={"200": thing, "201": thing})
                },
            }
        )
    )
    files, problems = svc.render()
    assert problems == []
    module = files["svc.py"]
    assert "async def a(transport: Transport) -> svc.Thing | None:" in module
    assert "async def b(transport: Transport) -> svc.Thing:" in module
    assert "async def c(transport: Transport) -> None:" in module
    assert "async def d(transport: Transport) -> svc.Thing | svc.Color:" in module
    assert "async def e(transport: Transport) -> svc.Thing:" in module
    assert "return svc.Thing.model_validate(response)" in module


def test_path_item_ref_resolves_relative_to_its_own_file(
    make_project: ProjectFactory,
) -> None:
    shared = yaml.safe_dump(
        {
            "openapi": "3.0.3",
            "info": {"title": "shared", "version": "1"},
            "paths": {},
            "x-items": {
                "Thing": {
                    "parameters": [{"$ref": "#/components/parameters/Id"}],
                    "get": op(operationId="getThing", responses=ok(THING)),
                }
            },
            "components": {
                **COMPONENTS,
                "parameters": {
                    "Id": {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                },
            },
        }
    )
    project = make_project(
        {
            "shared.yaml": shared,
            "svc.yaml": spec({"/things/{id}": {"$ref": "shared.yaml#/x-items/Thing"}}),
        }
    )
    files, problems = project.render()
    assert problems == []
    assert (
        "async def get_thing(transport: Transport, *, id: int) -> shared.Thing:"
        in files["svc.py"]
    )
    assert 'f"/things/{id}"' in files["svc.py"]
