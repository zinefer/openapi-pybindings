"""Loading OpenAPI documents and walking their operations."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from yaml import CSafeLoader as _BaseLoader
except ImportError:  # PyYAML built without libyaml
    from yaml import SafeLoader as _BaseLoader  # type: ignore[assignment]

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
SPEC_SUFFIXES = (".yaml", ".yml", ".json")


_BOOL = "tag:yaml.org,2002:bool"
_TIMESTAMP = "tag:yaml.org,2002:timestamp"


class _Loader(_BaseLoader):
    """YAML 1.2 scalars, as OpenAPI expects: only true and false are booleans
    (`on`, `no` and `y` stay strings) and dates stay strings."""


_Loader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag not in (_BOOL, _TIMESTAMP)]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    _BOOL, re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


@dataclass(frozen=True)
class Operation:
    path: str
    method: str
    """Upper case, as sent on the wire."""
    operation: dict[str, Any]
    path_parameters: Any
    """Parameters declared on the path item, shared by all of its operations, as
    written (a list, unless the spec is malformed)."""


def load_spec(path: Path) -> dict[str, Any]:
    """Parse a JSON (`.json`) or YAML OpenAPI document. Raises ValueError if it
    cannot be parsed or is not a mapping."""
    with path.open(encoding="utf-8") as f:
        try:
            if path.suffix == ".json":
                data = json.load(f)
            else:
                data = yaml.load(f, Loader=_Loader)
        except yaml.YAMLError as e:
            raise ValueError(f"{path} is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not an OpenAPI document")
    return data


def discover_specs(spec_dir: Path) -> list[Path]:
    """The spec files directly inside `spec_dir`, sorted by name."""
    return sorted(
        p for p in spec_dir.iterdir() if p.is_file() and p.suffix in SPEC_SUFFIXES
    )


def iter_operations(spec: dict[str, Any]) -> Iterator[Operation]:
    """Every operation in the document, in path then method order as written."""
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in HTTP_METHODS:
            if method in item:
                yield Operation(
                    path=str(path),
                    method=method.upper(),
                    operation=item[method],
                    path_parameters=item.get("parameters") or [],
                )
