# openapi-pybindings

Generate typed Python client functions from OpenAPI specs, on top of the pydantic
models [datamodel-codegen] already generates for the same specs.

```python
from api.client import blocking, movies, run_sync

movie = await movies.get_movie(transport, movie_id=movie_id)       # -> api.movies.Movie
found = await movies.list_movies(transport, title="Alien", limit=10)  # -> list[api.movies.Movie]

movie = run_sync(movies.get_movie(blocking(send), movie_id=movie_id))  # from sync code
```

- **One function per operation**, keyword-only, with the spec's own path, query
  and header parameters and body, and a precise return type.
- **No `Any`.** A shape the generator cannot type precisely is reported as an
  error, never papered over, so a type checker sees every route, parameter and
  body the caller relies on.
- **Bring your own HTTP client.** Every function takes a `Transport`, a one-method
  protocol you implement with httpx, aiohttp, requests, a test double or anything
  else. The generated code depends only on pydantic.
- **Async or sync.** The same functions are awaited from async code and called
  through `run_sync` from synchronous code.
- **Safe paths.** Path parameters that could hold reserved characters are
  percent-encoded, so a value can only ever fill its own path segment.

## Install

The generator is a development-time tool; the code it writes needs only pydantic.

```sh
uv add --dev "openapi-pybindings @ git+https://github.com/zinefer/openapi-pybindings"
# pin a release with ...openapi-pybindings@v0.3.0
```

Requires Python 3.12+.

## Generating the client

Generate the models first, as a package with one module per spec file, which is
what datamodel-codegen does when given a directory:

```sh
uv run datamodel-codegen --input openapi --input-file-type openapi \
    --output api --output-model-type pydantic_v2.BaseModel
uv run openapi-pybindings openapi --models-package api --output api/client
```

This writes `api/client/__init__.py` (the transport protocols and helpers) and
one module per spec that has operations, e.g. `api/client/movies.py` for
`openapi/movies.yaml`. Spec file names must be valid Python module names
(`movies.yaml`, not `movie-api.yaml`).

| Option                 |                                                                                                                                                                                        |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SPEC_DIR [SPEC ...]`  | Directory of spec files, and optionally which of them to generate (default: every `.yaml`, `.yml` and `.json` file in it). With a list, the modules of the other specs are left alone. |
| `-m, --models-package` | Importable package datamodel-codegen wrote the models into.                                                                                                                            |
| `-o, --output`         | Directory to write the client package into.                                                                                                                                            |
| `-c, --client-package` | Importable name of the output package (default: `MODELS_PACKAGE.client`).                                                                                                              |
| `--exclude GLOB`       | Leave out spec files whose name matches, e.g. `--exclude 'public_*.yaml'` (repeatable). Their generated modules are removed.                                                           |
| `--versions v1 v2`     | Require every path to start with `/v1/` or `/v2/`.                                                                                                                                     |
| `--import-path DIR`    | Put `DIR` on `sys.path` to import the models package (default: the current directory).                                                                                                 |

The generator imports the models package to confirm every referenced schema has a
class, so run it from your project's environment (`uv run`) and root. It can also
be called from Python: `openapi_pybindings.generate(...)` and
`render(...)` take the same options as the command line.

Exit status is 1 if any operation could not be generated, and 2 for a usage error
such as a missing `SPEC_DIR`. The other operations are still written, and each
problem is printed to stderr with the JSON pointer of the part of the spec at
fault, and the operation that led there when that is elsewhere:

```
error: movies.yaml#/paths/~1v1~1movies/get/parameters/3: cookie parameter session
error: common.yaml#/components/schemas/Filter/properties/where: parameter filter property where is not a single value (from movies.yaml#/paths/~1v1~1movies/get)
```

### Output directory

Only files whose first line starts with `# GENERATED by openapi-pybindings` are
treated as generated. Generated modules for specs that no longer have operations
are removed, except that a spec that cannot be read, or yields nothing but
problems, keeps its last module. Any other file in the output directory is never
touched, and a hand-written file in the way of a generated one is reported, not
overwritten.

The generated code is not laid out to any formatter's style, so exclude the output
directory from formatting and line-length lints (in ruff, `extend-exclude =
["api/client"]`); otherwise each run of the generator undoes the formatter's
changes. To check in CI that the generated client is up to date, run the generator
and then `git diff --exit-code api/client`.

## Calling the client

### Writing a transport

The transport owns everything the spec leaves to the client: the host, auth (the
spec's `securitySchemes`), shared headers, retries and error handling.

```python
from collections.abc import Mapping

import httpx

from api.client import JSON, QueryValue


class Transport:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __call__(
        self,
        method: str,
        path: str,
        *,
        params: tuple[tuple[str, QueryValue], ...] | None,
        headers: Mapping[str, str] | None,
        json: JSON,
    ) -> JSON:
        response = await self._client.request(
            method, path, params=params, headers=headers, json=json
        )
        response.raise_for_status()
        return response.json() if response.content else None


transport = Transport(httpx.AsyncClient(base_url="https://api.example.com"))
```

- `path` is as written in the spec, so `base_url` is the host plus any prefix not
  in the spec's paths.
- `params` is a tuple of pairs, in order, with a key repeated for each value of a
  list; httpx, aiohttp and requests all take it as is.
- `headers` holds only the operation's own header parameters. Merge them with your
  own, yours last if a spec header must never override yours.
- `json` is the request body as a `JSON` value (`None` for no body). Return the
  decoded JSON body, or `None` for an empty one; returning anything else, such
  as the response object, is a type error. A GET route that does not return JSON
  gets a `<operation>_path` function instead, so you can fetch it however you
  like, streaming included.

### Errors

Whatever the transport raises reaches the caller unchanged, so a non-2xx status
raises whatever your transport chooses. A response that does not match the spec
raises pydantic's `ValidationError`.

### Calling from synchronous code

`run_sync` runs a client function without an event loop. Write the transport as a
plain function (or an object with a plain `__call__`) around a synchronous HTTP
client, and wrap it with `blocking` to pass it to the client functions:

```python
from collections.abc import Mapping
from uuid import UUID

import httpx

from api.client import JSON, QueryValue, blocking, run_sync
from api.client import movies


class SyncTransport:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def __call__(
        self,
        method: str,
        path: str,
        *,
        params: tuple[tuple[str, QueryValue], ...] | None,
        headers: Mapping[str, str] | None,
        json: JSON,
    ) -> JSON:
        response = self._client.request(
            method, path, params=params, headers=headers, json=json
        )
        response.raise_for_status()
        return response.json() if response.content else None


client = httpx.Client(base_url="https://api.example.com")
transport = blocking(SyncTransport(client))
movie = run_sync(
    movies.get_movie(transport, movie_id=UUID("6f1c2a52-6c55-4a7e-9a52-0d5f1f7d1a01"))
)
```

`requests` or any other synchronous client works the same way, and the return
types are the same as with `await`. `BlockingTransport` is the protocol such a
function satisfies. Since it is not `async`, linters that flag blocking calls in
async code (ruff's `ASYNC2xx` rules) have nothing to flag. Unlike `asyncio.run`,
`run_sync` also works where an event loop is already running, such as in a Jupyter
cell or a sync helper called from async code, though it blocks that loop until the
request finishes. A transport that suspends makes `run_sync` raise
`RuntimeError`, as there is no event loop to resume it.

### Testing

A transport is any object with that `__call__`, so tests can pass one that
records `method`, `path`, `params`, `headers` and `json` and returns a canned
response, instead of mocking HTTP. A plain function wrapped with `blocking` works
too, with no `async def` needed. The response still goes through the same
validation.

## What gets generated

| Spec                                                                                          | Python                                                                                                                                                                                            |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `operationId: getMovie`                                                                       | `async def get_movie(...)` (keywords get a trailing `_`, e.g. `import_`)                                                                                                                          |
| path / query / header parameter                                                               | keyword-only argument; optional ones default to `None` and are left out of the request                                                                                                            |
| header parameter named `Accept`, `Content-Type` or `Authorization`                            | ignored, as OpenAPI requires                                                                                                                                                                      |
| `string`, `integer`, `number`, `boolean`                                                      | `str`, `int`, `float`, `bool`                                                                                                                                                                     |
| `format: uuid` / `date` / `date-time`                                                         | `UUID` / `date` / `pydantic.AwareDatetime` (sent as ISO 8601)                                                                                                                                     |
| any other `format` (`double`, `int64`, `email`, ...)                                          | the plain type                                                                                                                                                                                    |
| `nullable: true`, or 3.1 `type: [T, "null"]`                                                  | `T \| None` (an optional parameter is left out when `None`)                                                                                                                                       |
| `$ref` to an enum                                                                             | the generated enum class (sent as its value)                                                                                                                                                      |
| inline string or integer `enum`                                                               | `Literal["a", "b"]`                                                                                                                                                                               |
| array parameter                                                                               | `list[T]`; in a query, `form` style repeats the key (`explode`, the default) or joins with `,`, and `spaceDelimited` / `pipeDelimited` join with ` ` / `\|`; in a path or header, joined with `,` |
| query parameter `$ref` to an object of single values                                          | the generated model, sent as one key per field (`form`) or `name[field]` (`deepObject`)                                                                                                           |
| JSON body `$ref` to an object                                                                 | the generated model (`model_dump(mode="json")` / `model_validate`)                                                                                                                                |
| any other JSON body: an enum, array of / `additionalProperties` map of the above, a primitive | `list[...]`, `dict[str, ...]`, ... via a pydantic `TypeAdapter`                                                                                                                                   |
| `anyOf` / `oneOf` of the above, `allOf` of one schema                                         | `A \| B`, or that schema                                                                                                                                                                          |
| request body without `required: true`                                                         | `body: T \| None = None`, sent with no body when `None`                                                                                                                                           |
| no content, or no 2xx response                                                                | `-> None`                                                                                                                                                                                         |
| several 2xx responses                                                                         | the union of their types, with `None` for one without content                                                                                                                                     |
| 2xx responses to a GET that are not JSON                                                      | `<operation>_path(...) -> str`, the URL to fetch yourself                                                                                                                                         |

A JSON media type is `application/json`, with or without parameters, or any
`application/*+json`. `$ref`s, including path item `$ref`s, are followed across
files, relative to the file they appear in.

### Reported as unsupported

- **Parameters:** cookie parameters; parameters with `content`; `label` and
  `matrix` path styles; arrays of anything but single values; object parameters
  that are inline, outside a query, not exploded, or have a field that is not a
  single value; required parameters that are nullable.
- **Schemas:** inline object schemas and `allOf` of several schemas (give them a
  `components/schemas` entry instead).
- **Bodies and responses:** non-JSON request bodies; non-JSON responses, except
  to a GET without a query, header or body, and never alongside JSON ones.
- **Everything else:** remote `$ref`s; a missing `operationId`; names that would
  collide with each other or with what the generated code uses (an operation
  named after a spec file, or `date`, `list`, ...; a spec file named after
  something the client package defines, such as `blocking.yaml`); malformed
  specs.

## Development

```sh
make        # everything CI runs: lint, mypy, and the tests
make test   # just the tests: end-to-end with real datamodel-codegen,
            # mypy --strict and httpx, plus the README's code blocks
make format # apply ruff's fixes and formatting
make golden # regenerate tests/golden/ after an intended output change
```

The Makefile runs everything through `uv`, so `uv sync` is the only setup.

- `tests/golden/` holds the exact output for `tests/specs/`. After an intended
  change to the output, regenerate it with `make golden` and review the diff.
- The code blocks under "Writing a transport" and "Calling from synchronous code"
  are type checked and run by the tests, which find them by those headings.
- Each generated function must await its transport exactly once and nothing else;
  `run_sync` depends on it. Multi-request behavior such as retries or pagination
  belongs in the transport.

[datamodel-codegen]: https://github.com/koxudaxi/datamodel-code-generator
