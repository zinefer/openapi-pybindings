from __future__ import annotations

import hashlib
import importlib
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from openapi_pybindings import generate, render

SPECS = Path(__file__).parent / "specs"
GOLDEN = Path(__file__).parent / "golden"


def codegen_models(spec_dir: Path, package_dir: Path) -> None:
    """Run datamodel-codegen the way a project using this tool would."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "datamodel_code_generator",
            "--input",
            str(spec_dir),
            "--input-file-type",
            "openapi",
            "--output",
            str(package_dir),
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--disable-timestamp",
            "--formatters",
            "black",
            "isort",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"datamodel-codegen failed:\n{result.stderr}")
    # A single input file yields a module, not a package; this tool always
    # expects a package.
    (package_dir / "__init__.py").touch()


@dataclass
class Project:
    root: Path
    spec_dir: Path
    models_package: str = "api"

    @property
    def client_package(self) -> str:
        return f"{self.models_package}.client"

    @property
    def client_dir(self) -> Path:
        return self.root / self.models_package / "client"

    def generate(self, **kwargs: Any) -> list[str]:
        return generate(
            self.spec_dir,
            self.client_dir,
            models_package=self.models_package,
            **kwargs,
        )

    def render(self, **kwargs: Any) -> tuple[dict[str, str], list[str]]:
        return render(self.spec_dir, models_package=self.models_package, **kwargs)

    def client(self, module: str) -> Any:
        importlib.invalidate_caches()
        return importlib.import_module(f"{self.client_package}.{module}")

    def models(self, module: str) -> Any:
        return importlib.import_module(f"{self.models_package}.{module}")

    def mypy(self, *paths: Path) -> subprocess.CompletedProcess[str]:
        """mypy --strict over the client package and `paths`."""
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "mypy",
                "--strict",
                "--no-incremental",
                "--cache-dir",
                str(self.root / ".mypy_cache"),
                str(self.client_dir),
                *map(str, paths),
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            env={"MYPYPATH": str(self.root), "PATH": ""},
        )


@dataclass
class ProjectFactory:
    tmp_path: Path
    cache_dir: Path
    packages: set[str] = field(default_factory=set)

    def __call__(
        self,
        specs: Path | Mapping[str, str] = SPECS,
        models_package: str = "api",
    ) -> Project:
        """A project root holding `specs` and the models generated from them,
        with the root on sys.path."""
        spec_dir = self.tmp_path / "openapi"
        if spec_dir.exists():
            shutil.rmtree(spec_dir)
        if isinstance(specs, Path):
            shutil.copytree(specs, spec_dir)
        else:
            spec_dir.mkdir()
            for name, text in specs.items():
                (spec_dir / name).write_text(text)

        digest = hashlib.sha256()
        for path in sorted(spec_dir.iterdir()):
            digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
        cached = self.cache_dir / digest.hexdigest()
        if not cached.exists():
            codegen_models(spec_dir, cached)

        root = self.tmp_path / "project"
        package_dir = root / models_package
        if package_dir.exists():
            shutil.rmtree(package_dir)
        shutil.copytree(cached, package_dir)

        _forget(models_package)
        self.packages.add(models_package)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return Project(root, spec_dir, models_package)


def _forget(package: str) -> None:
    for name in list(sys.modules):
        if name == package or name.startswith(f"{package}."):
            del sys.modules[name]


@pytest.fixture(scope="session")
def models_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("models-cache")


@pytest.fixture
def make_project(tmp_path: Path, models_cache: Path) -> Iterator[ProjectFactory]:
    saved_path = list(sys.path)
    factory = ProjectFactory(tmp_path, models_cache)
    yield factory
    sys.path[:] = saved_path
    for package in factory.packages:
        _forget(package)


@pytest.fixture
def project(make_project: ProjectFactory) -> Project:
    """The fixture specs in tests/specs, with their models generated."""
    return make_project()


@dataclass
class Call:
    method: str
    path: str
    params: Sequence[tuple[str, Any]] | None
    headers: Mapping[str, str] | None
    json: Any


@dataclass
class RecordingTransport:
    """A Transport that records each request and answers with `response`."""

    response: Any = None
    calls: list[Call] = field(default_factory=list)

    async def __call__(
        self,
        method: str,
        path: str,
        *,
        params: tuple[tuple[str, Any], ...] | None,
        headers: Mapping[str, str] | None,
        json: Any,
    ) -> Any:
        query = None if params is None else list(params)
        self.calls.append(Call(method, path, query, headers, json))
        return self.response

    @property
    def last(self) -> Call:
        return self.calls[-1]
