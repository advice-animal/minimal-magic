from __future__ import annotations

import dataclasses
import os
import typing
from pathlib import Path
from types import UnionType

from parse_errors import ParseError
from parse_errors.source_map import build_source_map, closest_entry, detect_format

from ._convert import _convert, _dataclass_meta
from ._errors import (
    _esc,
    _FixedSource,
    _raise_no_location,
    _Source,
    _source_map_can_locate,
    _source_map_locate,
)
from ._parsing import _parse_syntax

T = typing.TypeVar("T")


@dataclasses.dataclass
class Candidate:
    """A config file with an optional key-path prefix.

    ``prefix`` is a dot-separated path (e.g. ``"tool.myapp"``) or a list of
    keys used to navigate into the parsed file before merging.  If the prefix
    is absent in the file, the candidate contributes nothing — it is not an
    error.
    """

    filename: str | os.PathLike
    prefix: str | list[str] | None = None


def load(
    filename: str | os.PathLike,
    *,
    data: bytes | None = None,
    format: str | None = None,
    type: type[T] | None = None,
    forbid_unknown_fields: bool = False,
) -> typing.Any:
    """Load a single JSON/YAML/TOML file, re-raising errors with filename and location.

    Handles both syntax errors in the file itself and type conversion errors
    when ``type`` is given.  Both are raised as :class:`ParseError` with the
    filename and 1-based line/column included in the message.  A location of
    ``line=0, column=0`` means the file parsed to something the source map
    cannot point into, such as an empty YAML document.

    For loading and merging multiple files (with optional per-file key prefixes)
    use :func:`load_candidate`.

    Args:
        filename: Path to the file to load.
        data: The already-read bytes, otherwise ``filename`` will be read.
        format: One of ``"json"``, ``"yaml"``, or ``"toml"``.  Inferred from
                the file extension if omitted.
        type: If given, the parsed data is recursively converted into this
              type.  Supports dataclasses, ``TypedDict``,
              ``Optional``/``Union`` (including tagged unions), ``Literal``,
              ``Enum``, the collection generics, the rich scalars
              (``Path``, ``Decimal``, ``date``, ``datetime``, ``time``), and
              the primitives.
        forbid_unknown_fields: If True, raise :class:`ParseError` for any key
              in the file that has no matching field on ``type``.

    Raises:
        ParseError: On a syntax error or a type conversion failure.
        ValueError: If the format is neither given nor detectable from the
              extension, or is not one of the three supported formats.
        ImportError: For a YAML file when PyYAML is not installed; install the
              ``yaml`` extra.
    """
    path = Path(filename)
    data = data if data is not None else path.read_bytes()
    fmt = format or detect_format(path)
    if fmt is None:
        raise ValueError(
            f"Cannot detect format for {path!r}; pass format= explicitly"
        )

    raw = _parse_syntax(data, fmt, path)
    if type is None:
        return raw

    return _convert_typed(raw, data, fmt, path, type, forbid_unknown_fields)


def convert(
    raw: typing.Any,
    *,
    filename: str | os.PathLike,
    type: type[T],
    data: bytes | None = None,
    format: str | None = None,
    forbid_unknown_fields: bool = False,
) -> typing.Any:
    """Convert already-parsed config data into ``type`` with located errors.

    This is the lower-level companion to :func:`load`. Use it when another
    parser already produced the raw Python data structure, but you still want
    minimal-magic's type conversion and filename-aware errors.

    If ``data`` is provided, the original bytes are used to build a source map
    so validation errors can report exact line and column numbers. If ``data``
    is omitted, errors still include the filename and JSON pointer path, but not
    exact line/column locations.

    Args:
        raw: Parsed JSON/YAML/TOML data.
        filename: The filename to report in any :class:`ParseError`.
        type: The target type to convert into.
        data: Optional original file bytes used to build a source map.
        format: One of ``"json"``, ``"yaml"``, or ``"toml"``. Used when
                ``data`` is provided to build a source map if the filename
                does not already make the format clear.
        forbid_unknown_fields: Passed through to the type conversion step;
                see :func:`load` for which paths honour it.

    Raises:
        ParseError: On a type conversion failure.
        ValueError: If ``data`` is given but the format is neither passed nor
                detectable from the filename.  With no ``data`` the format is
                never needed, so no such error is raised.
    """
    path = Path(filename)
    if data is None:
        return _convert_typed(raw, None, None, path, type, forbid_unknown_fields)
    fmt = format or detect_format(path)
    if fmt is None:
        raise ValueError(
            f"Cannot detect format for {path!r}; pass format= explicitly"
        )
    return _convert_typed(raw, data, fmt, path, type, forbid_unknown_fields)


def load_candidate(
    candidates: list[Candidate | str | os.PathLike],
    *,
    format: str | None = None,
    type: type[T] | None = None,
    forbid_unknown_fields: bool = False,
) -> typing.Any:
    """Load and merge multiple config files, with optional per-file key prefixes.

    Files are merged left to right: later entries override earlier ones for any
    key they define.  A field's ``metadata={"merge": fn}`` callable decides that
    key, if it has one; otherwise two dicts merge recursively and everything
    else — lists, sets, scalars, ``None`` — is replaced wholesale.  If a
    candidate's ``prefix`` is absent in its file, that candidate contributes
    nothing — it is not an error.

    Every candidate is read, so a file that is missing from disk raises
    ``FileNotFoundError``; there is no "optional candidate" flag.

    Conversion runs once on the merged result, but errors are reported against
    the candidate that actually supplied the offending value: the merge records
    where each key came from, and a failure looks up that key's own file, line
    and column.  A value inherited from the first of five files is blamed on
    the first file.

    Two cases have no single file to name.  A value built by a merge callable
    exists in none of them, and is attributed to the candidate whose value was
    passed as ``override``, whose bytes are the ones being validated.  An error
    at a pointer no candidate supplied — a missing required field at the root,
    say — falls back to the last candidate.

    Args:
        candidates: A list of :class:`Candidate` objects or plain paths (treated
                    as ``Candidate(path)`` with no prefix).  Must not be empty.
        format: Format override applied to every file.  Inferred per-file from
                the extension when omitted.
        type: If given, the merged data is converted into this type.
        forbid_unknown_fields: Passed through to the type conversion step;
                see :func:`load` for which paths honour it.

    Raises:
        ParseError: On a syntax error in any candidate, a top-level value that
                is not a mapping, an exception raised inside a merge callable,
                or a type conversion failure.
        ValueError: If ``candidates`` is empty, or a file's format is neither
                given nor detectable.

    Example::

        config = load_candidate([
            "defaults.toml",
            Candidate("pyproject.toml", prefix="tool.myapp"),
            "local.toml",
        ], type=AppConfig)
    """
    if not candidates:
        raise ValueError("candidates list must not be empty")

    merged: dict = {}
    # Which candidate supplied the value at each pointer of the merged tree, so
    # a conversion error can name the file the value actually came from.
    provenance: dict[str, tuple[Path, bytes, str, str]] = {}
    last_data: bytes = b""
    last_fmt: str = ""
    last_path: Path = Path(".")
    last_base_pointer: str = ""

    for entry in candidates:
        candidate = entry if isinstance(entry, Candidate) else Candidate(entry)
        path = Path(candidate.filename)
        raw_bytes = path.read_bytes()
        fmt = format or detect_format(path)
        if fmt is None:
            raise ValueError(
                f"Cannot detect format for {path!r}; pass format= explicitly"
            )
        raw = _parse_syntax(raw_bytes, fmt, path)
        if not isinstance(raw, dict):
            raise ParseError(
                f"{path}: top-level value must be a mapping for config inheritance",
                filename=path,
                line=0,
                column=0,
            )
        base_pointer = _prefix_to_pointer(candidate.prefix)
        section = _navigate(raw, candidate.prefix)
        if section is not None:
            raw_bytes_ref, fmt_ref = raw_bytes, fmt
            merged = _deep_merge(
                merged, section, type,
                source_map_factory=lambda: build_source_map(raw_bytes_ref, fmt_ref),
                filename=path,
                base_pointer=base_pointer,
                provenance=provenance,
                origin=(path, raw_bytes, fmt),
            )
        last_data, last_fmt, last_path = raw_bytes, fmt, path
        last_base_pointer = base_pointer

    if type is None:
        return merged

    return _convert_typed(
        merged,
        last_data,
        last_fmt,
        last_path,
        type,
        forbid_unknown_fields,
        source=_MergedSource(
            provenance,
            fallback=(last_path, last_data, last_fmt, last_base_pointer),
        ),
    )


def _prefix_to_pointer(prefix: str | list[str] | None) -> str:
    if prefix is None:
        return ""
    keys = prefix.split(".") if isinstance(prefix, str) else list(prefix)
    return "".join(f"/{_esc(k)}" for k in keys)


def _navigate(raw: dict, prefix: str | list[str] | None) -> dict | None:
    """Navigate *raw* to *prefix*; return None if any key along the path is absent."""
    if prefix is None:
        return raw
    keys = prefix.split(".") if isinstance(prefix, str) else list(prefix)
    current: typing.Any = raw
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current if isinstance(current, dict) else None


class _MergedSource(_Source):
    """Per-pointer locations for a tree merged from several candidate files.

    ``provenance`` maps a pointer in the merged tree to the candidate that
    supplied the value sitting there, and to where that value lives in *that*
    file.  The two pointers differ whenever a candidate was read through a
    ``prefix``: ``/host`` in the merged tree may be ``/tool/myapp/host`` in the
    file it came from.

    A pointer with no entry of its own walks up to its nearest recorded
    ancestor, because a subtree taken wholesale from one candidate records only
    its root — an error at ``/server/port`` resolves through ``/server`` and
    keeps the ``/port`` suffix. A pointer with no recorded ancestor at all
    falls back to the last candidate, which is the best guess available for
    something no candidate claims, such as the root itself.

    Source maps are built on first use and cached, so a merge that converts
    cleanly builds none at all.
    """

    __slots__ = ("_fallback", "_maps", "provenance")

    def __init__(
        self,
        provenance: dict[str, tuple[Path, bytes, str, str]],
        *,
        fallback: tuple[Path, bytes, str, str],
    ) -> None:
        self.provenance = provenance
        self._fallback = fallback
        self._maps: dict[Path, typing.Any] = {}

    def _source_map(self, path: Path, data: bytes, fmt: str) -> typing.Any:
        cached = self._maps.get(path)
        if cached is None:
            cached = self._maps[path] = build_source_map(data, fmt)
        return cached

    def _entry(self, path: Path, data: bytes, fmt: str, pointer: str) -> typing.Any | None:
        if _source_map_can_locate():
            return _source_map_locate(data, fmt, pointer)
        return closest_entry(self._source_map(path, data, fmt), pointer)

    def locate(self, pointer: str) -> tuple[Path, typing.Any | None]:
        node = pointer
        while True:
            owner = self.provenance.get(node)
            if owner is not None:
                path, data, fmt, file_pointer = owner
                target = file_pointer + pointer[len(node):]
                return path, self._entry(path, data, fmt, target)
            if not node:
                break
            node = node.rsplit("/", 1)[0]
        path, data, fmt, file_pointer = self._fallback
        if not data:
            return path, None
        return path, self._entry(path, data, fmt, file_pointer + pointer)


def _unwrap_dataclass(tp: typing.Any) -> type | None:
    """Return *tp* if it's a dataclass type; unwrap ``Optional[T]``/``T | None`` first."""
    if tp is None:
        return None
    if dataclasses.is_dataclass(tp) and isinstance(tp, type):
        return tp
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin in (typing.Union, UnionType):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _unwrap_dataclass(non_none[0])
    return None


def _deep_merge(
    base: dict,
    override: dict,
    tp: type | None = None,
    *,
    source_map_factory: typing.Callable[[], typing.Any] | None = None,
    filename: Path | None = None,
    base_pointer: str = "",
    provenance: dict[str, tuple[Path, bytes, str, str]] | None = None,
    merged_pointer: str = "",
    origin: tuple[Path, bytes, str] | None = None,
) -> dict:
    """Deep-merge *override* into *base*, returning a new dict.

    Rules (applied in order for each key in *override*):

    1. If the field's ``dataclasses.field`` metadata contains a ``"merge"``
       callable, call ``merge(base_value, override_value)`` and use the result.
       This takes priority over all other rules, including dict recursion.
    2. If both the base value and the override value are dicts (or the field
       type is a dataclass), the dicts are merged recursively by the same rules.
    3. Otherwise the override value replaces the base value entirely — this
       applies to lists, scalars, ``None``, and type changes.

    Keys present only in *base* are kept unchanged.
    Keys present only in *override* are added as-is.

    When *provenance* is given, every key this call decides is recorded there as
    ``merged_pointer -> (*origin, base_pointer)``, naming the candidate whose
    bytes now back that pointer.  Rule 2 records nothing at its own level: it
    recurses instead, which leaves keys contributed only by *base* pointing at
    the earlier candidate that supplied them.  Rule 1 records the *override*
    candidate, since a merge callable's result is a new value that exists in no
    file and the override's bytes are the ones being validated.

    *base_pointer* is the pointer within the candidate's own file, which the
    prefix makes differ from *merged_pointer*, the pointer within the merged
    tree.  Both are needed: the first to index the file's source map, the
    second as the key conversion will look up.
    """
    # Build per-raw-key lookups when we have a dataclass type
    raw_to_merge_fn: dict[str, typing.Callable] = {}
    raw_to_nested_tp: dict[str, type] = {}
    if tp is not None and dataclasses.is_dataclass(tp) and isinstance(tp, type):
        hints, aliases = _dataclass_meta(tp)
        for field in dataclasses.fields(tp):
            if not field.init:
                continue
            raw_key = aliases[field.name]
            merge_fn = field.metadata.get("merge")
            if merge_fn is not None:
                raw_to_merge_fn[raw_key] = merge_fn
            nested = _unwrap_dataclass(hints.get(field.name))
            if nested is not None:
                raw_to_nested_tp[raw_key] = nested

    source_map: typing.Any = None

    def record(merged_ptr: str, file_ptr: str) -> None:
        if provenance is not None and origin is not None:
            provenance[merged_ptr] = (*origin, file_ptr)

    result = dict(base)
    for k, v in override.items():
        key = _esc(str(k))
        file_ptr = f"{base_pointer}/{key}"
        merged_ptr = f"{merged_pointer}/{key}"
        merge_fn = raw_to_merge_fn.get(k)
        if merge_fn is not None and k in result:
            try:
                result[k] = merge_fn(result[k], v)
            except ParseError:
                raise
            except Exception as exc:
                if source_map_factory is not None and filename is not None:
                    if source_map is None:
                        source_map = source_map_factory()
                    entry = closest_entry(source_map, file_ptr)
                    if entry is None:
                        _raise_no_location(str(exc), filename, file_ptr)
                    loc = entry.value_start
                    raise ParseError(
                        f"{filename}:{loc.line + 1}:{loc.column + 1}: {exc}",
                        filename=filename,
                        line=loc.line + 1,
                        column=loc.column + 1,
                    ) from exc
                raise
            record(merged_ptr, file_ptr)
        elif k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(
                result[k], v, raw_to_nested_tp.get(k),
                source_map_factory=source_map_factory,
                filename=filename,
                base_pointer=file_ptr,
                provenance=provenance,
                merged_pointer=merged_ptr,
                origin=origin,
            )
        else:
            result[k] = v
            record(merged_ptr, file_ptr)
    return result


def _convert_typed(
    raw: typing.Any,
    data: bytes | None,
    fmt: str | None,
    path: Path,
    type: type[T],
    forbid_unknown_fields: bool,
    source: _Source | None = None,
) -> typing.Any:
    # *source* overrides the single-file location lookup; load_candidate passes
    # one that resolves each pointer against the candidate it came from.
    try:
        if source is None:
            if data is not None:
                assert fmt is not None
                source = _FixedSource(
                    path,
                    lambda: build_source_map(data, fmt),
                    locator=(lambda pointer: _source_map_locate(data, fmt, pointer))
                    if _source_map_can_locate()
                    else None,
                )
            else:
                source = _FixedSource(path, None)
        return _convert(raw, type, source, "", forbid_unknown_fields)
    except RecursionError:
        raise ParseError(
            f"{path}: structure is too deeply nested or contains a circular reference",
            filename=path,
            line=0,
            column=0,
        )


def alias(name: str, **kwargs: typing.Any) -> typing.Any:
    """Shorthand for ``dataclasses.field(metadata={"alias": name}, **kwargs)``.

    Use this when a config file uses a key name that isn't a valid Python
    identifier or doesn't match Python naming conventions (e.g. kebab-case).

    Example::

        @dataclasses.dataclass
        class Config:
            retry_count: int = alias("retry-count", default=3)
    """
    return dataclasses.field(metadata={"alias": name}, **kwargs)
