from __future__ import annotations

import json
import typing
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from parse_errors import ParseContext, ParseError


def _parse_syntax(data: bytes, fmt: str, path: Path) -> typing.Any:
    if fmt == "json":
        with ParseContext(path, data=data, format="json"):
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
    elif fmt in ("yaml", "yml"):
        try:
            import yaml
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required to parse YAML files; install with `pip install minimal-magic[yaml]`"
            ) from exc
        with ParseContext(path, data=data, format="yaml"):
            # CSafeLoader (libyaml, C) when available; yaml.safe_load() always
            # uses the pure-Python SafeLoader, even when libyaml is installed.
            loader_cls = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
            raw = yaml.load(data.decode("utf-8"), Loader=loader_cls)
        # Outside ParseContext: this already raises its own located
        # ParseError, which ParseContext has no way to tell apart from an
        # ordinary exception and would otherwise try to re-locate.
        _reject_circular_references(raw, path)
        return raw
    elif fmt == "toml":
        with ParseContext(path, data=data, format="toml"):
            return tomllib.loads(data.decode("utf-8"))
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
