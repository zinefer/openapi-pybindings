# openapi-pybindings

Generate typed, async Python client functions from OpenAPI specs, on top of the
pydantic models [datamodel-codegen] already generates for the same specs.

```python
from api.client import movies

movie = await movies.get_movie(transport, movie_id=movie_id)       # -> api.movies.Movie
found = await movies.list_movies(transport, title="Alien", limit=10)  # -> list[api.movies.Movie]
```

- **One function per operation**, keyword-only, with the spec's own path, query
  and header parameters and body, and a precise return type.
- **No `Any`.** A shape the generator cannot type precisely is reported as an
  error, never papered over, so a type checker sees every route, parameter and
  body the caller relies on.
- **Bring your own HTTP client.** Every function takes a `Transport`, a one-method
  protocol you implement with httpx, aiohttp, a test double or anything else. It
  owns the host, auth (the spec's `securitySchemes`), shared headers, retries and
  errors; the generated code depends only on pydantic.
- **Safe paths.** Path parameters that could hold reserved characters are
  percent-encoded, so a value can only ever fill its own path segment.

## Install

The generator is a development-time tool; the code it writes needs only pydantic.

```sh
uv add --dev "openapi-pybindings @ git+https://github.com/zinefer/openapi-pybindings"
# pin a release with ...openapi-pybindings@v0.1.0
```

Requires Python 3.12+.

## Usage

Generate the models first, as a package with one module per spec file, which is
what datamodel-codegen does when given a directory:

```sh
uv run datamodel-codegen --input openapi --input-file-type openapi \
    --output api --output-model-type pydantic_v2.BaseModel
uv run openapi-pybindings openapi --models-package api --output api/client
```

This writes `api/client/__init__.py` (the `Transport` protocol) and one module per
spec that has operations, e.g. `api/client/movies.py` for `openapi/movies.yaml`.

| Option | |
| --- | --- |
| `SPEC_DIR [SPEC ...]` | Directory of spec files, and optionally which of them to generate (default: every `.yaml`, `.yml` and `.json` file in it). With a list, the modules of the other specs are left alone. |
| `-m, --models-package` | Importable package datamodel-codegen wrote the models into. |
| `-o, --output` | Directory to write the client package into. |
| `-c, --client-package` | Importable name of the output package (default: `MODELS_PACKAGE.client`). |
| `--exclude GLOB` | Leave out spec files whose name matches, e.g. `--exclude 'public_*.yaml'` (repeatable). Their generated modules are removed. |
| `--versions v1 v2` | Require every path to start with `/v1/` or `/v2/`. |
| `--import-path DIR` | Put `DIR` on `sys.path` to import the models package (default: the current directory). |
| `--check` | Write nothing; exit 1 if the output is not what would be generated. Use it in CI. |

The generator imports the models package to confirm every referenced schema has a
class, so run it from your project's environment (`uv run`) and root.

Exit status is 1 if any operation could not be generated. The others are still
written, and each problem is printed to stderr with the JSON pointer of the part
of the spec at fault, and the operation that led there when that is elsewhere:

```
error: movies.yaml#/paths/~1v1~1movies/get/parameters/3: cookie parameter session
error: common.yaml#/components/schemas/Filter/properties/where: parameter filter property where is not a single value (from movies.yaml#/paths/~1v1~1movies/get)
```

It can also be called from Python: `openapi_pybindings.generate(...)`, `check(...)`
and `render(...)` take the same options as the command line.

### Writing a transport

```python
from collections.abc import Mapping
from typing import Any

import httpx

from api.client import QueryValue


class HttpxTransport:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __call__(
        self,
        method: str,
        path: str,
        *,
        params: tuple[tuple[str, QueryValue], ...] | None,
        headers: Mapping[str, str] | None,
        json: Any,
    ) -> Any:
        response = await self._client.request(
            method, path, params=params, headers=headers, json=json
        )
        response.raise_for_status()
        return response.json() if response.content else None


transport = HttpxTransport(httpx.AsyncClient(base_url="https://api.example.com"))
```

Paths are used as written in the spec, so `base_url` is the host and any prefix
not in the spec's paths. `params` is a tuple of pairs, in order, with a key
repeated for each value of a list; httpx, aiohttp and requests all take it as is. `headers`
holds only the operation's own header parameters: merge them with your own, yours
last if a spec header must never override, say, `Authorization`.

## What gets generated

| Spec | Python |
| --- | --- |
| `operationId: getMovie` | `async def get_movie(...)` (keywords get a trailing `_`, e.g. `import_`) |
| path / query / header parameter | keyword-only argument; optional ones default to `None` and are left out of the request |
| header parameter named `Accept`, `Content-Type` or `Authorization` | ignored, as OpenAPI requires |
| `string`, `integer`, `number`, `boolean` | `str`, `int`, `float`, `bool` |
| `format: uuid` / `date` / `date-time` | `UUID` / `date` / `pydantic.AwareDatetime` (sent as ISO 8601) |
| any other `format` (`double`, `int64`, `email`, ...) | the plain type |
| `nullable: true`, or 3.1 `type: [T, "null"]` | `T \| None` (an optional parameter is left out when `None`) |
| `$ref` to an enum | the generated enum class (sent as its value) |
| inline string or integer `enum` | `Literal["a", "b"]` |
| array parameter | `list[T]`; in a query, `form` style repeats the key (`explode`, the default) or joins with `,`, and `spaceDelimited` / `pipeDelimited` join with ` ` / `\|`; in a path or header, joined with `,` |
| query parameter `$ref` to an object of single values | the generated model, sent as one key per field (`form`) or `name[field]` (`deepObject`) |
| JSON body `$ref` to an object | the generated model (`model_dump(mode="json")` / `model_validate`) |
| any other JSON body: an enum, array of / `additionalProperties` map of the above, a primitive | `list[...]`, `dict[str, ...]`, ... via a pydantic `TypeAdapter` |
| `anyOf` / `oneOf` of the above, `allOf` of one schema | `A \| B`, or that schema |
| request body without `required: true` | `body: T \| None = None`, sent with no body when `None` |
| no content, or no 2xx response | `-> None` |
| several 2xx responses | the union of their types, with `None` for one without content |
| 2xx responses to a GET that are not JSON | `<operation>_path(...) -> str`, the URL to fetch yourself |

A JSON media type is `application/json`, with or without parameters, or any
`application/*+json`.

`$ref`s, including path item `$ref`s, are followed across files, relative to the
file they appear in. The models
package must have one module per spec file, named after it, so spec file names
must be valid Python module names (`movies.yaml`, not `movie-api.yaml`).

### Reported as unsupported

Cookie parameters; parameters with `content`; `label` and `matrix` path styles;
arrays of anything but single values; object parameters that are inline, outside
a query, not exploded, or have a field that is not a single value; required
parameters that are nullable; inline object schemas and `allOf` of several schemas
(give them a `components/schemas` entry instead); non-JSON request bodies; non-JSON
responses to anything but a GET without a query, header or body, or alongside JSON
ones; remote `$ref`s; a missing `operationId`; names that would collide with each
other or with what the generated code uses (an operation named after a spec file,
or `date`, `list`, ...); and malformed specs.

Auth (`securitySchemes`), servers and error responses are the transport's job, not
the generator's.

### Output directory

Only files whose first line starts with `# GENERATED by openapi-pybindings` are
treated as generated. Generated modules for specs that no longer have operations
are removed, except that a spec that cannot be read, or yields nothing but
problems, keeps its last module. Any other file in the output directory is never
touched, and a hand-written file in the way of a generated one is reported, not
overwritten.

The generated code has sorted imports and is laid out as `ruff format` and black
would format it, so it passes their checks. Lines that cannot be split (a long
path, say) may still pass 88 columns, so exclude the directory from a line
length lint.

## Development

```sh
uv sync
uv run pytest          # end-to-end: real datamodel-codegen, mypy --strict, httpx
uv run mypy
uv run ruff check && uv run ruff format --check
```

`tests/golden/` holds the exact output for `tests/specs/`. After an intended change
to the output, regenerate it with `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py`
and review the diff.

[datamodel-codegen]: https://github.com/koxudaxi/datamodel-code-generator
