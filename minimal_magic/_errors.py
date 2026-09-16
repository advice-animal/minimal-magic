from __future__ import annotations

import typing
from pathlib import Path

from parse_errors import ParseError
from parse_errors import source_map as _source_maps

closest_entry = _source_maps.closest_entry


def _esc(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


class _Source:
    """Answers "which file, and where in it, does this pointer come from?".

    A single file has one answer for every pointer.  A tree merged from several
    candidate files has a different answer per pointer, so conversion asks the
    source rather than carrying one filename and source map of its own.
    """

    __slots__ = ()

    def locate(self, pointer: str) -> tuple[Path, typing.Any | None]:
        raise NotImplementedError  # pragma: no cover


class _FixedSource(_Source):
    """One file, one lazy source map — what :func:`load` and :func:`convert` use.

    ``source_map_factory`` is called at most once, the first time a location
    is actually needed, and the result is cached; a clean conversion never
    builds one. ``None`` means the caller gave no bytes to map, so every
    error reports without a line or column.
    """

    __slots__ = ("filename", "_factory", "_locator", "_source_map")

    def __init__(
        self,
        filename: Path,
        source_map_factory: typing.Callable[[], typing.Any] | None,
        *,
        locator: typing.Callable[[str], typing.Any | None] | None = None,
    ) -> None:
        self.filename = filename
        self._factory = source_map_factory
        self._locator = locator
        self._source_map: typing.Any | None = None

    def locate(self, pointer: str) -> tuple[Path, typing.Any | None]:
        if self._locator is not None:
            return self.filename, self._locator(pointer)
        if self._factory is None:
            return self.filename, None
        if self._source_map is None:
            self._source_map = self._factory()
        return self.filename, closest_entry(self._source_map, pointer)


def _source_map_locate(
    data: str | bytes,
    fmt: str,
    pointer: str,
) -> typing.Any | None:
    return _source_maps.locate_pointer(data, fmt, pointer)


def _source_map_can_locate() -> bool:
    return hasattr(_source_maps, "locate_pointer")


def _raise_no_location(
    msg: str,
    filename: Path,
    pointer: str,
) -> typing.NoReturn:
    # Covers both "no source map" and "source map has no entries" (e.g. an
    # empty/blank YAML document maps to nothing): line=0, column=0 is this
    # codebase's convention for "no location available".
    suffix = f" - at `{pointer}`" if pointer else ""
    raise ParseError(
        f"{filename}: {msg}{suffix}",
        filename=filename,
        line=0,
        column=0,
    )


def _raise_parse_error(
    msg: str,
    source: _Source,
    pointer: str,
) -> typing.NoReturn:
    filename, entry = source.locate(pointer)
    if entry is None:
        _raise_no_location(msg, filename, pointer)
    loc = entry.value_start
    raise ParseError(
        f"{filename}:{loc.line + 1}:{loc.column + 1}: {msg}",
        filename=filename,
        line=loc.line + 1,
        column=loc.column + 1,
    )


def _type_error(
    expected: typing.Any,
    got: typing.Any,
    source: _Source,
    pointer: str,
) -> typing.NoReturn:
    name = getattr(expected, "__name__", str(expected))
    _raise_parse_error(
        f"Expected `{name}`, got `{type(got).__name__}`",
        source,
        pointer,
    )


def _value_error(
    msg: str,
    source: _Source,
    pointer: str,
) -> typing.NoReturn:
    _raise_parse_error(msg, source, pointer)


def _missing_field(
    field_name: str,
    cls: type,
    source: _Source,
    pointer: str,
) -> typing.NoReturn:
    _raise_parse_error(
        f"Missing required field `{field_name}` in `{cls.__name__}`",
        source,
        pointer,
    )


def _length_error(
    tp: typing.Any,
    expected_len: int,
    got_len: int,
    source: _Source,
    pointer: str,
) -> typing.NoReturn:
    _raise_parse_error(
        f"Expected `{tp}` ({expected_len} elements), got {got_len}",
        source,
        pointer,
    )


def _unknown_field(
    field_name: str,
    cls: type,
    source: _Source,
    pointer: str,
) -> typing.NoReturn:
    # Unlike the others this points at the offending key, not its value.
    msg = f"Unexpected field `{field_name}` in `{cls.__name__}`"
    filename, entry = source.locate(pointer)
    if entry is None:
        _raise_no_location(msg, filename, pointer)
    loc = entry.key_start or entry.value_start
    raise ParseError(
        f"{filename}:{loc.line + 1}:{loc.column + 1}: {msg}",
        filename=filename,
        line=loc.line + 1,
        column=loc.column + 1,
    )
