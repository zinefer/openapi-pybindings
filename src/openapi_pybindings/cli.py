"""Command line entry point: `openapi-pybindings`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from openapi_pybindings.generator import check, generate

DESCRIPTION = """\
Generate typed async client functions from OpenAPI specs, using the pydantic
models datamodel-codegen generated for the same specs (one module per spec file).
Each problem is printed to stderr. Exits 1 if any operation could not be generated,
or with --check if the output is not up to date.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openapi-pybindings", description=DESCRIPTION)
    parser.add_argument(
        "spec_dir", type=Path, help="directory holding the OpenAPI spec files"
    )
    parser.add_argument(
        "specs",
        nargs="*",
        help="spec file names inside SPEC_DIR to generate clients for; the "
        "modules of other specs are left alone (default: every .yaml, .yml and "
        ".json file)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="directory to write the client package into",
    )
    parser.add_argument(
        "-m",
        "--models-package",
        required=True,
        help="importable package datamodel-codegen wrote the models into, e.g. api",
    )
    parser.add_argument(
        "-c",
        "--client-package",
        help="importable name of the output package (default: MODELS_PACKAGE.client)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        metavar="GLOB",
        help="leave out spec files whose name matches GLOB, e.g. 'public_*.yaml' "
        "(repeatable)",
    )
    parser.add_argument(
        "--versions",
        nargs="+",
        metavar="VERSION",
        help="require every path to start with /VERSION/ for one of these, e.g. v1 v2",
    )
    parser.add_argument(
        "--import-path",
        action="append",
        type=Path,
        metavar="DIR",
        help="directory to put on sys.path to import the models package "
        "(repeatable; default: the current directory)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; fail if the output differs from what would be generated",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_intermixed_args(argv)
    for directory in reversed(args.import_path or [Path.cwd()]):
        sys.path.insert(0, str(directory.resolve()))
    if not args.spec_dir.is_dir():
        print(f"error: {args.spec_dir} is not a directory", file=sys.stderr)
        return 2
    run = check if args.check else generate
    problems = run(
        args.spec_dir,
        args.output,
        models_package=args.models_package,
        client_package=args.client_package,
        specs=args.specs or None,
        exclude=args.exclude,
        versions=args.versions,
    )
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
