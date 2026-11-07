"""Generate a client for the fixture specs, import it and call every function."""

from __future__ import annotations

import asyncio
import textwrap
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from conftest import Project, ProjectFactory, RecordingTransport

MOVIE_ID = UUID("6f1c2a52-6c55-4a7e-9a52-0d5f1f7d1a01")
MOVIE = {
    "id": str(MOVIE_ID),
    "title": "Plan 9 from Outer Space",
    "status": "released",
    "created": "2026-01-02T03:04:05Z",
}


@pytest.fixture
def generated(project: Project) -> Project:
    assert project.generate() == []
    return project


def test_writes_one_module_per_spec_with_operations(generated: Project) -> None:
    assert sorted(
        p.name for p in generated.client_dir.iterdir() if p.suffix == ".py"
    ) == [
        "__init__.py",
        "files.py",
        "movies.py",
    ]


async def test_list_movies_serializes_every_query_type(generated: Project) -> None:
    movies = generated.client("movies")
    common = generated.models("common")
    transport = RecordingTransport(response=[MOVIE])
    director = UUID(int=7)

    result = await movies.list_movies(
        transport,
        title="Alien",
        status=common.Status.upcoming,
        rating=common.Rating.integer_2,
        limit=10,
        since=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=-5))),
        on=date(2026, 2, 3),
        director=director,
        subtitled=False,
        score=0.5,
        page_size=50,
        class_="x",
    )

    assert transport.last.method == "GET"
    assert transport.last.path == "/v1/movies"
    assert transport.last.json is None
    assert transport.last.headers is None
    assert transport.last.params == [
        ("title", "Alien"),
        ("status", "upcoming"),
        ("rating", 2),
        ("limit", 10),
        ("since", "2026-01-02T03:04:05-05:00"),
        ("on", "2026-02-03"),
        ("director", str(director)),
        ("subtitled", False),
        ("score", 0.5),
        ("pageSize", 50),
        ("class", "x"),
    ]
    [movie] = result
    assert isinstance(movie, generated.models("movies").Movie)
    assert movie.id == MOVIE_ID
    assert movie.status is common.Status.released


async def test_optional_query_params_are_omitted(generated: Project) -> None:
    transport = RecordingTransport(response=[])
    assert await generated.client("movies").list_movies(transport, title="Alien") == []
    assert transport.last.params == [("title", "Alien")]


async def test_falsy_optional_query_values_are_still_sent(generated: Project) -> None:
    transport = RecordingTransport(response=[])
    await generated.client("movies").list_movies(
        transport, title="", limit=0, subtitled=False, score=0.0, class_=""
    )
    assert transport.last.params == [
        ("title", ""),
        ("limit", 0),
        ("subtitled", False),
        ("score", 0.0),
        ("class", ""),
    ]


async def test_create_movie_dumps_model_body(generated: Project) -> None:
    movies_models = generated.models("movies")
    common = generated.models("common")
    transport = RecordingTransport(response=MOVIE)

    movie = await generated.client("movies").create_movie(
        transport,
        body=movies_models.MovieCreate(title="Heat", status=common.Status.released),
    )

    assert (transport.last.method, transport.last.path) == ("POST", "/v1/movies")
    assert transport.last.params is None
    assert transport.last.json == {"title": "Heat", "status": "released"}
    assert isinstance(movie, movies_models.Movie)


async def test_path_item_parameters_and_component_refs(generated: Project) -> None:
    movies = generated.client("movies")
    movie_model = generated.models("movies").Movie
    transport = RecordingTransport(response=MOVIE)

    got = await movies.get_movie(transport, movie_id=MOVIE_ID)
    assert (transport.last.method, transport.last.path) == (
        "GET",
        f"/v1/movies/{MOVIE_ID}",
    )
    assert got == movie_model.model_validate(MOVIE)

    replaced = await movies.replace_movie(transport, movie_id=MOVIE_ID, body=got)
    assert transport.last.method == "PUT"
    assert transport.last.json == {**MOVIE, "created": "2026-01-02T03:04:05Z"}
    assert isinstance(replaced, movie_model)


async def test_empty_response_returns_none(generated: Project) -> None:
    transport = RecordingTransport(response=None)
    result = await generated.client("movies").delete_movie(transport, movie_id=MOVIE_ID)
    assert result is None
    assert (transport.last.method, transport.last.path) == (
        "DELETE",
        f"/v1/movies/{MOVIE_ID}",
    )


@pytest.mark.parametrize(
    ("tag", "encoded"),
    [
        ("plain", "plain"),
        ("a/b", "a%2Fb"),
        ("../../admin", "..%2F..%2Fadmin"),
        ("x?y=1#z", "x%3Fy%3D1%23z"),
        ("sp ace%", "sp%20ace%25"),
        ("ünï", "%C3%BCn%C3%AF"),
    ],
)
async def test_string_path_params_cannot_escape_their_segment(
    generated: Project, tag: str, encoded: str
) -> None:
    transport = RecordingTransport(response={"a": 1})
    counts = await generated.client("movies").get_tag_counts(
        transport, movie_id=MOVIE_ID, tag=tag
    )
    assert transport.last.path == f"/v1/movies/{MOVIE_ID}/tags/{encoded}"
    assert counts == {"a": 1}


async def test_typed_path_params_are_serialized(generated: Project) -> None:
    common = generated.models("common")
    transport = RecordingTransport(response=["x"])
    result = await generated.client("movies").find_screenings(
        transport,
        status=common.Status.upcoming,
        rating=common.Rating.integer_1,
        imax=True,
        day=date(2026, 3, 4),
        at=datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC),
        seats=3,
    )
    assert transport.last.path == (
        "/v1/screenings/upcoming/1/true/2026-03-04/2026-03-04T05%3A06%3A07%2B00%3A00/3"
    )
    assert result == ["x"]

    await generated.client("movies").find_screenings(
        transport,
        status=common.Status.released,
        rating=common.Rating.integer_5,
        imax=False,
        day=date(2026, 3, 4),
        at=datetime(2026, 3, 4, tzinfo=UTC),
        seats=-1,
    )
    assert transport.last.path.startswith("/v1/screenings/released/5/false/")
    assert transport.last.path.endswith("/-1")


def test_non_json_routes_get_path_functions(generated: Project) -> None:
    movies = generated.client("movies")
    files = generated.client("files")
    assert movies.get_poster_path(movie_id=MOVIE_ID) == f"/v1/movies/{MOVIE_ID}/poster"
    assert files.download_file_path(name="a b/c.txt") == "/v2/files/a%20b%2Fc.txt"
    assert not hasattr(movies, "get_poster")


async def test_operation_without_content_returns_none(generated: Project) -> None:
    transport = RecordingTransport(response=None)
    assert await generated.client("files").health(transport) is None
    assert transport.last.path == "/v2/health"


async def test_list_and_dict_bodies_use_type_adapters(generated: Project) -> None:
    movies = generated.client("movies")
    movies_models = generated.models("movies")
    common = generated.models("common")
    create = movies_models.MovieCreate(title="Tron", status=common.Status.upcoming)

    transport = RecordingTransport(response=[MOVIE, MOVIE])
    created = await movies.bulk_create_movies(transport, body=[create, create])
    assert transport.last.json == [{"title": "Tron", "status": "upcoming"}] * 2
    assert [type(g) for g in created] == [movies_models.Movie] * 2

    transport = RecordingTransport(response=3)
    assert await movies.import_(transport, body={"k": create}) == 3
    assert transport.last.json == {"k": {"title": "Tron", "status": "upcoming"}}


async def test_invalid_responses_raise(generated: Project) -> None:
    movies = generated.client("movies")
    with pytest.raises(ValidationError):
        await movies.get_movie(
            RecordingTransport(response={"id": "nope"}), movie_id=MOVIE_ID
        )
    with pytest.raises(ValidationError):
        await movies.list_movies(
            RecordingTransport(response={"not": "a list"}), title="Alien"
        )
    with pytest.raises(ValidationError):
        await movies.import_(RecordingTransport(response="many"), body={})


async def test_enum_bodies_use_type_adapters(generated: Project) -> None:
    movies = generated.client("movies")
    common = generated.models("common")

    transport = RecordingTransport(response="upcoming")
    status = await movies.get_movie_status(transport, movie_id=MOVIE_ID)
    assert status is common.Status.upcoming
    assert transport.last.path == f"/v1/movies/{MOVIE_ID}/status"

    transport = RecordingTransport(response=None)
    await movies.set_movie_status(
        transport, movie_id=MOVIE_ID, body=common.Status.released
    )
    assert (transport.last.method, transport.last.json) == ("PUT", "released")

    with pytest.raises(ValidationError):
        await movies.get_movie_status(
            RecordingTransport(response="lost"), movie_id=MOVIE_ID
        )


async def test_nullable_responses_may_be_none(generated: Project) -> None:
    movies = generated.client("movies")
    movies_models = generated.models("movies")
    sequel = await movies.get_sequel(
        RecordingTransport(response=MOVIE), movie_id=MOVIE_ID
    )
    assert isinstance(sequel, movies_models.Movie)
    assert (
        await movies.get_sequel(RecordingTransport(response=None), movie_id=MOVIE_ID)
        is None
    )
    assert (
        await movies.get_tagline(RecordingTransport(response=None), movie_id=MOVIE_ID)
        is None
    )
    assert (
        await movies.get_tagline(RecordingTransport(response="Hi"), movie_id=MOVIE_ID)
        == "Hi"
    )


ODD_NAMES = """\
openapi: 3.0.3
info: {title: odd, version: "1"}
paths:
  '/x"y\\z/{id}':
    get:
      operationId: fetchOdd
      parameters:
        - {name: id, in: path, required: true, schema: {type: string}}
        - {name: 'a"b\\c', in: query, schema: {type: string}}
        - {name: "new\\nline", in: query, schema: {type: string}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Thing"}
components:
  schemas:
    Thing: {type: object, properties: {a: {type: string}}}
"""


async def test_names_are_escaped_in_the_generated_code(
    make_project: ProjectFactory,
) -> None:
    project = make_project({"odd.yaml": ODD_NAMES})
    assert project.generate() == []
    odd = project.client("odd")
    transport = RecordingTransport(response={"a": "1"})
    await odd.fetch_odd(transport, id="i", a_b_c="q", new_line="n")
    assert transport.last.path == '/x"y\\z/i'
    assert transport.last.params == [('a"b\\c', "q"), ("new\nline", "n")]
    assert odd.fetch_odd.__doc__ == 'GET /x"y\\z/{id}'
    result = project.mypy()
    assert result.returncode == 0, result.stdout


LOOSE_TYPES = """\
openapi: 3.1.0
info: {title: loose, version: "1"}
paths:
  /x/{n}:
    get:
      operationId: loose
      parameters:
        - {name: n, in: path, required: true, schema: {type: integer, format: int16}}
        - {name: ratio, in: query, schema: {type: number, format: double}}
        - {name: email, in: query, schema: {type: string, format: email}}
        - {name: maybe, in: query, schema: {type: [string, "null"]}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {type: [number, "null"], format: float}
components:
  schemas:
    Thing: {type: object, properties: {a: {type: string}}}
"""


async def test_unknown_formats_fall_back_to_their_type(
    make_project: ProjectFactory,
) -> None:
    project = make_project({"loose.yaml": LOOSE_TYPES})
    files, problems = project.render()
    assert problems == []
    assert (
        "async def loose(\n"
        "    transport: Transport,\n"
        "    *,\n"
        "    n: int,\n"
        "    ratio: float | None = None,\n"
        "    email: str | None = None,\n"
        "    maybe: str | None = None,\n"
        ") -> float | None:"
    ) in files["loose.py"]
    project.generate()
    transport = RecordingTransport(response=None)
    assert await project.client("loose").loose(transport, n=3, ratio=0.5) is None
    assert transport.last.params == [("ratio", 0.5)]


async def test_array_object_and_header_parameters(generated: Project) -> None:
    movies = generated.client("movies")
    common = generated.models("common")
    movies_models = generated.models("movies")
    transport = RecordingTransport(response=[])

    await movies.search_movies(transport)
    assert (transport.last.params, transport.last.headers) == ([], {})

    await movies.search_movies(
        transport,
        genres=["noir", "drama"],
        ids=[UUID(int=1), UUID(int=2)],
        ratings=[common.Rating.integer_1, common.Rating.integer_5],
        filter=movies_models.MovieFilter(year=1982, min_score=0.5),
        sort="-created",
        x_request_id="abc",
    )
    assert transport.last.params == [
        ("genres", "noir"),
        ("genres", "drama"),
        ("ids", f"{UUID(int=1)},{UUID(int=2)}"),
        ("ratings", "1|5"),
        ("filter[year]", 1982),
        ("filter[min_score]", 0.5),
        ("sort", "-created"),
    ]
    assert transport.last.headers == {"X-Request-Id": "abc"}

    transport = RecordingTransport(response=7)
    count = await movies.count_movies(
        transport, filter=movies_models.MovieFilter(rated=common.Rating.integer_3)
    )
    assert count == 7
    assert transport.last.params == [("rated", 3)]

    transport = RecordingTransport(response=[])
    await movies.get_movies_by_ids(
        transport, movie_ids=[UUID(int=1), UUID(int=2)], x_fields=["id", "title"]
    )
    assert transport.last.path == f"/v1/movies/by-ids/{UUID(int=1)},{UUID(int=2)}"
    assert transport.last.headers == {"X-Fields": "id,title"}


async def test_optional_union_body_and_union_response(generated: Project) -> None:
    movies = generated.client("movies")
    common = generated.models("common")
    movies_models = generated.models("movies")

    transport = RecordingTransport(response=None)
    assert await movies.rate_movie(transport, movie_id=MOVIE_ID) is None
    assert transport.last.json is None

    transport = RecordingTransport(response=MOVIE)
    rated = await movies.rate_movie(
        transport, movie_id=MOVIE_ID, body=common.Rating.integer_4
    )
    assert isinstance(rated, movies_models.Movie)
    assert transport.last.json == 4
    await movies.rate_movie(transport, movie_id=MOVIE_ID, body="unrated")
    assert transport.last.json == "unrated"


async def test_path_item_ref_from_another_file(generated: Project) -> None:
    transport = RecordingTransport(response="released")
    status = await generated.client("movies").ping(transport, limit=3)
    assert status is generated.models("common").Status.released
    assert (transport.last.path, transport.last.params) == ("/v1/ping", [("limit", 3)])


def test_functions_are_keyword_only(generated: Project) -> None:
    movies = generated.client("movies")
    with pytest.raises(TypeError):
        movies.get_movie(RecordingTransport(), MOVIE_ID)  # type: ignore[call-arg]


class HttpxTransport:
    """The reference transport from the README."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __call__(
        self,
        method: str,
        path: str,
        *,
        params: tuple[tuple[str, str | int | float | bool], ...] | None,
        headers: Mapping[str, str] | None,
        json: Any,
    ) -> Any:
        response = await self._client.request(
            method, path, params=params, headers=headers, json=json
        )
        response.raise_for_status()
        return response.json() if response.content else None


async def test_works_over_httpx(generated: Project) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.url.path == "/v1/movies/missing":
            return httpx.Response(404)
        return httpx.Response(200, json=[MOVIE])

    async with httpx.AsyncClient(
        base_url="https://movies.example/", transport=httpx.MockTransport(handler)
    ) as client:
        transport = HttpxTransport(client)
        movies = generated.client("movies")
        result = await movies.list_movies(
            transport, title="The Thing", subtitled=True, limit=2
        )
        assert result[0].title == "Plan 9 from Outer Space"
        assert str(seen[-1].url) == (
            "https://movies.example/v1/movies?title=The+Thing&limit=2&subtitled=true"
        )
        assert await movies.delete_movie(transport, movie_id=MOVIE_ID) is None
        assert seen[-1].method == "DELETE"

        common = generated.models("common")
        movies_models = generated.models("movies")
        await movies.search_movies(
            transport,
            genres=["noir", "sci fi"],
            ids=[UUID(int=1), UUID(int=2)],
            ratings=[common.Rating.integer_1, common.Rating.integer_5],
            filter=movies_models.MovieFilter(year=1982, rated=common.Rating.integer_4),
            x_request_id="abc",
        )
        assert seen[-1].url.params.multi_items() == [
            ("genres", "noir"),
            ("genres", "sci fi"),
            ("ids", f"{UUID(int=1)},{UUID(int=2)}"),
            ("ratings", "1|5"),
            ("filter[year]", "1982"),
            ("filter[rated]", "4"),
        ]
        assert seen[-1].headers["X-Request-Id"] == "abc"


def test_readme_transport_satisfies_the_protocol(generated: Project) -> None:
    """The README's httpx transport type checks against the generated protocol, so
    the protocol stays one every client can implement directly."""
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    section = readme.split("### Writing a transport", 1)[1]
    code = section.split("```python\n", 1)[1].split("```", 1)[0]
    usage = generated.root / "readme_transport.py"
    usage.write_text(
        code
        + "\n\nfrom api.client import Transport  # noqa: E402\n\n"
        + "checked: Transport = transport\n"
    )
    result = generated.mypy(usage)
    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_client_passes_mypy_strict(generated: Project) -> None:
    usage = generated.root / "usage.py"
    usage.write_text(
        textwrap.dedent(
            """\
            from datetime import date
            from uuid import UUID

            from api import common, movies
            from api.client import Transport
            from api.client import files as files_client
            from api.client import movies as movies_client


            async def use(t: Transport) -> None:
                listed: list[movies.Movie] = await movies_client.list_movies(
                    t, title="Alien", status=common.Status.released, on=date.today()
                )
                one: movies.Movie = await movies_client.get_movie(
                    t, movie_id=UUID(int=1)
                )
                await movies_client.delete_movie(t, movie_id=one.id)
                counts: dict[str, int] = await movies_client.get_tag_counts(
                    t, movie_id=one.id, tag="x"
                )
                total: int = await movies_client.import_(t, body={})
                status: common.Status = await movies_client.get_movie_status(
                    t, movie_id=one.id
                )
                await movies_client.set_movie_status(t, movie_id=one.id, body=status)
                sequel: movies.Movie | None = await movies_client.get_sequel(
                    t, movie_id=one.id
                )
                tagline: str | None = await movies_client.get_tagline(
                    t, movie_id=one.id
                )
                found: list[movies.Movie] = await movies_client.search_movies(
                    t,
                    genres=["noir"],
                    ratings=[common.Rating.integer_1],
                    filter=movies.MovieFilter(year=1982),
                    sort="title",
                    x_request_id="abc",
                )
                rated: movies.Movie | None = await movies_client.rate_movie(
                    t, movie_id=one.id, body="unrated"
                )
                pong: common.Status = await movies_client.ping(t)
                path: str = files_client.download_file_path(name="f")
                await files_client.health(t)
            """
        )
    )
    result = generated.mypy(usage)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("call", "error"),
    [
        ('movies_client.get_movie(t, movie_id="not-a-uuid")', "arg-type"),
        ("movies_client.get_movie(t)", "call-arg"),
        ('movies_client.list_movies(t, title="Alien", status="released")', "arg-type"),
        ('movies_client.list_movies(t, title="Alien", limit="2")', "arg-type"),
        ('movies_client.list_movies(t, title="Alien", bogus=1)', "call-arg"),
        ("movies_client.create_movie(t, body={})", "arg-type"),
        ("movies_client.bulk_create_movies(t, body=[1])", "list-item"),
        (
            'movies_client.set_movie_status(t, movie_id=UUID(int=1), body="x")',
            "arg-type",
        ),
        ('movies_client.search_movies(t, sort="year")', "arg-type"),
        ('movies_client.search_movies(t, genres="noir")', "arg-type"),
        ("movies_client.search_movies(t, filter={})", "arg-type"),
        (
            'movies_client.rate_movie(t, movie_id=UUID(int=1), body="great")',
            "arg-type",
        ),
        (
            "movies_client.get_movies_by_ids(t, movie_ids=[UUID(int=1)])",
            "call-arg",
        ),
    ],
)
def test_mypy_rejects_wrong_calls(generated: Project, call: str, error: str) -> None:
    """Proves the client is not secretly `Any`: a wrong call must not type check."""
    usage = generated.root / "wrong.py"
    usage.write_text(
        "from uuid import UUID\n"
        "from api.client import Transport\n"
        "from api.client import movies as movies_client\n\n\n"
        f"async def use(t: Transport) -> None:\n    await {call}\n"
    )
    result = generated.mypy(usage)
    assert result.returncode == 1
    assert f"[{error}]" in result.stdout, result.stdout


def test_mypy_rejects_wrong_return_use(generated: Project) -> None:
    usage = generated.root / "wrong.py"
    usage.write_text(
        "from uuid import UUID\n"
        "from api.client import Transport\n"
        "from api.client import movies as movies_client\n\n\n"
        "async def use(t: Transport) -> None:\n"
        "    movie = await movies_client.get_movie(t, movie_id=UUID(int=1))\n"
        "    x: int = movie.title\n"
    )
    result = generated.mypy(usage)
    assert result.returncode == 1
    assert "[assignment]" in result.stdout, result.stdout


def test_mypy_rejects_ignoring_a_nullable_response(generated: Project) -> None:
    usage = generated.root / "wrong.py"
    usage.write_text(
        "from uuid import UUID\n"
        "from api.client import Transport\n"
        "from api.client import movies as movies_client\n\n\n"
        "async def use(t: Transport) -> str:\n"
        "    return await movies_client.get_tagline(t, movie_id=UUID(int=1))\n"
    )
    result = generated.mypy(usage)
    assert result.returncode == 1
    assert "[return-value]" in result.stdout, result.stdout


def test_run_sync_calls_the_client_without_an_event_loop(generated: Project) -> None:
    run_sync = generated.client("__init__").run_sync
    movies = generated.client("movies")
    transport = RecordingTransport(response=MOVIE)

    movie = run_sync(movies.get_movie(transport, movie_id=MOVIE_ID))

    assert movie.id == MOVIE_ID
    assert (transport.last.method, transport.last.path) == (
        "GET",
        f"/v1/movies/{MOVIE_ID}",
    )
    assert run_sync(movies.delete_movie(transport, movie_id=MOVIE_ID)) is None


async def test_run_sync_works_inside_a_running_event_loop(generated: Project) -> None:
    """Where asyncio.run fails, as when a loop is already running on the thread."""
    run_sync = generated.client("__init__").run_sync
    movies = generated.client("movies")
    movie = run_sync(movies.get_movie(RecordingTransport(MOVIE), movie_id=MOVIE_ID))
    assert movie.id == MOVIE_ID


def test_run_sync_raises_what_the_transport_raises(generated: Project) -> None:
    run_sync = generated.client("__init__").run_sync
    movies = generated.client("movies")

    class Failing(RecordingTransport):
        async def __call__(self, *args: Any, **kwargs: Any) -> Any:
            raise LookupError("404")

    with pytest.raises(LookupError, match="404"):
        run_sync(movies.get_movie(Failing(), movie_id=MOVIE_ID))


def test_run_sync_rejects_a_transport_that_suspends(generated: Project) -> None:
    """The coroutine is closed, so no 'never awaited' warning (an error here)."""
    run_sync = generated.client("__init__").run_sync
    movies = generated.client("movies")

    class Suspending(RecordingTransport):
        async def __call__(self, *args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(0)
            return MOVIE

    with pytest.raises(RuntimeError, match="must block instead of awaiting"):
        run_sync(movies.get_movie(Suspending(), movie_id=MOVIE_ID))


def test_readme_sync_transport_works_with_run_sync(generated: Project) -> None:
    """The README's sync example type checks and runs."""
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    section = readme.split("### Calling from synchronous code", 1)[1]
    code = section.split("```python\n", 1)[1].split("```", 1)[0]
    usage = generated.root / "readme_sync.py"
    usage.write_text(
        code.replace(
            'httpx.Client(base_url="https://api.example.com")',
            "httpx.Client(base_url=BASE_URL, transport=MOCK)",
        ).replace(
            "import httpx\n",
            "import httpx\n\nBASE_URL: str\nMOCK: httpx.MockTransport\n",
            1,
        )
    )
    result = generated.mypy(usage)
    assert result.returncode == 0, result.stdout + result.stderr

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=MOVIE)

    namespace: dict[str, Any] = {
        "BASE_URL": "https://movies.example",
        "MOCK": httpx.MockTransport(handler),
    }
    exec(compile(usage.read_text(), str(usage), "exec"), namespace)
    assert namespace["movie"].id == MOVIE_ID
    assert str(seen[-1].url) == f"https://movies.example/v1/movies/{MOVIE_ID}"


def test_run_sync_passes_mypy_strict(generated: Project) -> None:
    usage = generated.root / "sync_usage.py"
    usage.write_text(
        textwrap.dedent(
            """\
            from uuid import UUID

            from api import movies
            from api.client import Transport, run_sync
            from api.client import movies as movies_client


            def use(t: Transport) -> None:
                one: movies.Movie = run_sync(
                    movies_client.get_movie(t, movie_id=UUID(int=1))
                )
                tagline: str | None = run_sync(
                    movies_client.get_tagline(t, movie_id=one.id)
                )
                run_sync(movies_client.delete_movie(t, movie_id=one.id))
            """
        )
    )
    result = generated.mypy(usage)
    assert result.returncode == 0, result.stdout + result.stderr


def test_mypy_rejects_wrong_run_sync_return_use(generated: Project) -> None:
    usage = generated.root / "wrong.py"
    usage.write_text(
        "from uuid import UUID\n"
        "from api.client import Transport, run_sync\n"
        "from api.client import movies as movies_client\n\n\n"
        "def use(t: Transport) -> str:\n"
        "    return run_sync(movies_client.get_tagline(t, movie_id=UUID(int=1)))\n"
    )
    result = generated.mypy(usage)
    assert result.returncode == 1
    assert "[return-value]" in result.stdout, result.stdout
