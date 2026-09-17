from __future__ import annotations

import json
import typing
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from parse_errors import ParseError


def _parse_syntax(data: bytes, fmt: str, path: Path) -> typing.Any:
    if fmt == "json":
        try:
            # To reject duplicate object keys instead of keeping the last value:
            #
            # def reject_duplicates(pairs):
            #     out = {}
            #     for key, value in pairs:
            #         if key in out:
            #             raise ValueError(f"duplicate key: {key!r}")
            #         out[key] = value
            #     return out
            #
            # return json.loads(data, object_pairs_hook=reject_duplicates)
            return json.loads(data)
        except json.JSONDecodeError as exc:
            raise ParseError(
                f"{path}:{exc.lineno}:{exc.colno}: {exc.msg}",
                filename=path,
                line=exc.lineno,
                column=exc.colno,
            ) from exc
    elif fmt in ("yaml", "yml"):
        try:
            import yaml
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required to parse YAML files; install with `pip install minimal-magic[yaml]`"
            ) from exc
        try:
            # CSafeLoader (libyaml, C) when available; yaml.safe_load() always
            # uses the pure-Python SafeLoader, even when libyaml is installed.
            loader_cls = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
            raw = yaml.load(data.decode("utf-8"), Loader=loader_cls)
            _reject_circular_references(raw, path)
            return raw
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            if mark is not None:
                line, col = mark.line + 1, mark.column + 1
                msg = getattr(exc, "problem", None) or str(exc)
                raise ParseError(
                    f"{path}:{line}:{col}: {msg}",
                    filename=path,
                    line=line,
                    column=col,
                ) from exc
            raise  # pragma: no cover
    elif fmt == "toml":
        try:
            return tomllib.loads(data.decode("utf-8"))
        except tomllib.TOMLDecodeError as exc:
            # `str(exc)` says "(at end of document)" instead of "(at line N,
            # column N)" once `pos` reaches the end of input, but `.lineno`/
            # `.colno` are always set -- tomllib computes them from `.pos`
            # before choosing how to word the message.
            raise ParseError(
                f"{path}:{exc.lineno}:{exc.colno}: {exc.msg}",
                filename=path,
                line=exc.lineno,
                column=exc.colno,
            ) from exc
    else:
        raise ValueError(f"Unknown format: {fmt!r}")


def _reject_circular_references(raw: typing.Any, path: Path) -> None:
    """Reject a YAML alias cycle here, at the same boundary that already turns
    an unhashable mapping key into a ParseError above — not later, wherever in
    `_convert()`/`_deep_merge()` happens to be the first thing to walk it."""
    stack: set[int] = set()

    def walk(value: typing.Any) -> None:
        if not isinstance(value, (dict, list)):
            return
        ident = id(value)
        if ident in stack:
            raise ParseError(
                f"{path}: structure is too deeply nested or contains a circular reference",
                filename=path,
                line=0,
                column=0,
            )
        stack.add(ident)
        try:
            children = value.values() if isinstance(value, dict) else value
            for child in children:
                walk(child)
        finally:
            stack.remove(ident)

    try:
        walk(raw)
    except RecursionError:
        raise ParseError(
            f"{path}: structure is too deeply nested or contains a circular reference",
            filename=path,
            line=0,
            column=0,
        )
