from __future__ import annotations

import collections.abc as cabc
import dataclasses
import datetime as dt
import decimal
import enum
import functools
import os
import typing
from pathlib import Path
from types import UnionType

from parse_errors import ParseError

from ._errors import (
    _esc,
    _length_error,
    _missing_field,
    _Source,
    _type_error,
    _unknown_field,
    _value_error,
)

# A converter closure has signature (raw, source, pointer, forbid_unknown) -> value.
# Everything derivable from *tp* alone (which branch applies, field lists, nested
# converters, ...) is decided once, when the closure is built; only what varies
# per value (raw, source, pointer) and per call (forbid_unknown) is left as an
# argument. This is what lets a schema with 5 fields converting 20,000 rows pay
# typing.get_origin()/get_args()/is_dataclass()/... once per field, not once per
# row.
_Conv = typing.Callable[[typing.Any, _Source, str, bool], typing.Any]

_compiled: dict[typing.Any, _Conv] = {}
_MISSING = object()


@functools.lru_cache(maxsize=None)
def _dataclass_meta(tp: type) -> tuple[dict[str, typing.Any], dict[str, str]]:
    """Returns (type_hints, {field_name: raw_key}) for init fields."""
    try:
        hints = typing.get_type_hints(tp)
    except NameError:  # pragma: no cover
        hints = tp.__annotations__
    aliases = {f.name: f.metadata.get("alias", f.name) for f in dataclasses.fields(tp) if f.init}
    return hints, aliases


@functools.lru_cache(maxsize=None)
def _typeddict_meta(tp: type) -> tuple[dict[str, typing.Any], frozenset[str]]:
    """Returns (type_hints, required_keys)."""
    try:
        hints = typing.get_type_hints(tp, include_extras=True)
    except NameError:  # pragma: no cover
        hints = tp.__annotations__
    return hints, frozenset(getattr(tp, "__required_keys__", hints))


def _convert(
    raw: typing.Any,
    tp: typing.Any,
    source: _Source,
    pointer: str,
    forbid_unknown: bool = False,
) -> typing.Any:
    """Convert *raw* to *tp*, raising ParseError with location on mismatch."""
    return _compile(tp)(raw, source, pointer, forbid_unknown)


def _compile(tp: typing.Any) -> _Conv:
    """Return the converter closure for *tp*, building and caching it on first use.

    A type that refers to itself — directly, through a tagged union, through a
    list — would make an eager build recurse forever: building the closure for
    ``TaggedExpr`` needs the closure for its own ``right: TaggedExpr`` field,
    which needs the closure for ``TaggedExpr``, ... A plain ``functools.lru_cache``
    can't break that cycle, because it only records a result once the call
    returns, and this call never would.

    So the cache entry is written *before* ``_build`` runs, as a forwarding
    closure over a one-element box. A recursive `_compile(tp)` call during the
    build sees that entry and gets the forwarder back — safe to store in a field
    list or item-converter slot, because nothing invokes it until real data
    flows through, by which point the box holds the finished closure. Once
    ``_build`` returns, the cache entry is replaced with the real closure, so
    every future lookup skips the extra indirection; only converters that are
    genuinely part of a cycle keep paying for the forward.
    """
    cached = _compiled.get(tp, _MISSING)
    if cached is not _MISSING:
        return cached

    box: list[_Conv | None] = [None]

    def _forward(raw: typing.Any, source: _Source, pointer: str, forbid_unknown: bool) -> typing.Any:
        return box[0](raw, source, pointer, forbid_unknown)  # type: ignore[misc]

    _compiled[tp] = _forward
    real = _build(tp)
    box[0] = real
    _compiled[tp] = real
    return real


def _build(tp: typing.Any) -> _Conv:
    """Build the converter closure for *tp*. Called once per distinct type; see `_compile`."""
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)

    # Annotated[T, ...] — strip metadata and recurse.
    # In practice get_type_hints() strips Annotated, so this is a safety net
    # for callers who pass Annotated types directly.
    if origin is typing.Annotated:  # pragma: no cover
        return _compile(args[0])

    # Required[T] / NotRequired[T] — unwrap typing metadata.
    required = getattr(typing, "Required", None)
    not_required = getattr(typing, "NotRequired", None)
    if origin in (required, not_required):  # pragma: no cover
        return _compile(args[0])

    # Any — pass through unchanged
    if tp is typing.Any:
        return lambda raw, source, pointer, forbid_unknown: raw

    # Literal["a", "b", ...] — validate the value is one of the allowed literals
    if origin is typing.Literal:
        allowed = args

        def conv_literal(raw, source, pointer, forbid_unknown):
            if raw not in allowed:
                _value_error(f"Expected one of {list(allowed)!r}, got {raw!r}", source, pointer)
            return raw

        return conv_literal

    # Union / Optional (typing.Union and Python 3.10+ X | Y syntax)
    if origin is typing.Union or origin is UnionType:
        return _build_union(tp, args)

    # list[T] / Sequence[T]
    if origin in (list, cabc.Sequence, cabc.MutableSequence):
        item_conv = _compile(args[0] if args else typing.Any)

        def conv_list(raw, source, pointer, forbid_unknown):
            if not isinstance(raw, (list, tuple)):
                _type_error(tp, raw, source, pointer)
            return [
                item_conv(item, source, f"{pointer}/{i}", forbid_unknown)
                for i, item in enumerate(raw)
            ]

        return conv_list

    # tuple[()] / tuple[T, ...] / tuple[T1, T2, T3]
    if origin is tuple:
        return _build_tuple(tp, args)

    # set[T] / frozenset[T] / AbstractSet[T]
    if origin in (set, frozenset, cabc.Set, cabc.MutableSet):
        item_conv = _compile(args[0] if args else typing.Any)
        is_frozen = origin is frozenset

        def conv_set(raw, source, pointer, forbid_unknown):
            if not isinstance(raw, (list, tuple, set, frozenset)):
                _type_error(tp, raw, source, pointer)
            items = {
                item_conv(item, source, f"{pointer}/{i}", forbid_unknown)
                for i, item in enumerate(raw)
            }
            return frozenset(items) if is_frozen else set(items)

        return conv_set

    # dict[K, V] / Mapping[K, V]
    if origin in (dict, cabc.Mapping, cabc.MutableMapping):
        val_conv = _compile(args[1] if len(args) > 1 else typing.Any)

        def conv_dict(raw, source, pointer, forbid_unknown):
            if not isinstance(raw, dict):
                _type_error(tp, raw, source, pointer)
            return {
                k: val_conv(v, source, f"{pointer}/{_esc(str(k))}", forbid_unknown)
                for k, v in raw.items()
            }

        return conv_dict

    # dataclass
    if dataclasses.is_dataclass(tp) and isinstance(tp, type):
        return _build_dataclass(tp)

    # TypedDict
    is_typeddict = getattr(typing, "is_typeddict", None)
    if callable(is_typeddict) and is_typeddict(tp):
        return _build_typeddict(tp)

    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        def conv_enum(raw, source, pointer, forbid_unknown):
            if isinstance(raw, tp):
                return raw
            try:
                return tp(raw)
            except Exception:
                allowed = [member.value for member in tp]
                _value_error(f"Expected one of {allowed!r}, got {raw!r}", source, pointer)

        return conv_enum

    if tp is Path:
        def conv_path(raw, source, pointer, forbid_unknown):
            if isinstance(raw, Path):
                return raw
            if not isinstance(raw, (str, os.PathLike)):
                _type_error(tp, raw, source, pointer)
            return Path(raw)

        return conv_path

    if tp is decimal.Decimal:
        def conv_decimal(raw, source, pointer, forbid_unknown):
            if isinstance(raw, decimal.Decimal):
                return raw
            if isinstance(raw, bool):
                _type_error(tp, raw, source, pointer)
            if not isinstance(raw, (str, int, float, decimal.Decimal)):
                _type_error(tp, raw, source, pointer)
            try:
                return decimal.Decimal(str(raw))
            except decimal.InvalidOperation:
                _value_error(f"Invalid `Decimal` value {raw!r}", source, pointer)

        return conv_decimal

    if tp is dt.date:
        def conv_date(raw, source, pointer, forbid_unknown):
            if isinstance(raw, dt.date) and not isinstance(raw, dt.datetime):
                return raw
            if not isinstance(raw, str):
                _type_error(tp, raw, source, pointer)
            try:
                return dt.date.fromisoformat(raw)
            except ValueError:
                _value_error(f"Invalid ISO date {raw!r}", source, pointer)

        return conv_date

    if tp is dt.datetime:
        def conv_datetime(raw, source, pointer, forbid_unknown):
            if isinstance(raw, dt.datetime):
                return raw
            if not isinstance(raw, str):
                _type_error(tp, raw, source, pointer)
            try:
                return dt.datetime.fromisoformat(raw)
            except ValueError:
                _value_error(f"Invalid ISO datetime {raw!r}", source, pointer)

        return conv_datetime

    if tp is dt.time:
        def conv_time(raw, source, pointer, forbid_unknown):
            if isinstance(raw, dt.time):
                return raw
            if not isinstance(raw, str):
                _type_error(tp, raw, source, pointer)
            try:
                return dt.time.fromisoformat(raw)
            except ValueError:
                _value_error(f"Invalid ISO time {raw!r}", source, pointer)

        return conv_time

    # Primitive / concrete type
    if isinstance(tp, type):
        if tp is float:
            def conv_float(raw, source, pointer, forbid_unknown):
                # Coerce int → float (e.g. JSON integer for a float field)
                if isinstance(raw, int) and not isinstance(raw, bool):
                    return float(raw)
                if not isinstance(raw, float):
                    _type_error(tp, raw, source, pointer)
                return raw

            return conv_float

        if tp is int:
            def conv_int(raw, source, pointer, forbid_unknown):
                # bool is a subclass of int; don't silently accept True/False
                if isinstance(raw, bool):
                    _type_error(tp, raw, source, pointer)
                if not isinstance(raw, int):
                    _type_error(tp, raw, source, pointer)
                return raw

            return conv_int

        def conv_prim(raw, source, pointer, forbid_unknown):
            if not isinstance(raw, tp):
                _type_error(tp, raw, source, pointer)
            return raw

        return conv_prim

    # Not a class at all (e.g. an unhandled typing construct) — nothing to check.
    return lambda raw, source, pointer, forbid_unknown: raw


def _build_union(tp: typing.Any, args: tuple[typing.Any, ...]) -> _Conv:
    non_none = [a for a in args if a is not type(None)]
    allows_none = type(None) in args

    if len(non_none) == 1:
        inner = _compile(non_none[0])
    else:
        tagged_union = _tagged_union_spec(tuple(non_none))
        if tagged_union is not None:
            inner = _build_tagged_union(tp, tagged_union)
        else:
            branch_convs = [_compile(a) for a in non_none]

            def inner(raw, source, pointer, forbid_unknown):
                for conv in branch_convs:
                    try:
                        return conv(raw, source, pointer, forbid_unknown)
                    except (ParseError, TypeError):
                        pass
                _type_error(tp, raw, source, pointer)

    def conv_union(raw, source, pointer, forbid_unknown):
        if raw is None:
            if allows_none:
                return None
            _type_error(tp, raw, source, pointer)
        return inner(raw, source, pointer, forbid_unknown)

    return conv_union


def _build_tagged_union(
    union_tp: typing.Any, tagged_union: tuple[str, dict[typing.Any, typing.Any]]
) -> _Conv:
    tag_field, tag_map = tagged_union
    tag_pointer_suffix = _esc(tag_field)
    branch_convs = {tag_value: _compile(candidate) for tag_value, candidate in tag_map.items()}

    def conv(raw, source, pointer, forbid_unknown):
        if not isinstance(raw, dict):
            _type_error(union_tp, raw, source, pointer)
        tag_pointer = f"{pointer}/{tag_pointer_suffix}"
        if tag_field not in raw:
            _value_error(
                f"Missing discriminator field `{tag_field}` for tagged union", source, pointer
            )
        tag_value = raw[tag_field]
        branch_conv = branch_convs.get(tag_value)
        if branch_conv is None:
            expected = sorted(repr(value) for value in tag_map)
            _value_error(
                f"Unknown discriminator value {tag_value!r} for `{tag_field}`; "
                f"expected one of {expected}",
                source,
                tag_pointer,
            )
        return branch_conv(raw, source, pointer, forbid_unknown)

    return conv


def _build_tuple(tp: typing.Any, args: tuple[typing.Any, ...]) -> _Conv:
    # tuple[()] — the empty-tuple type; args is () in Python 3.14+, ((),) earlier
    if args in ((), ((),)):
        def conv_tuple_empty(raw, source, pointer, forbid_unknown):
            if not isinstance(raw, (list, tuple)):
                _type_error(tp, raw, source, pointer)
            if len(raw) != 0:
                _type_error(tp, raw, source, pointer)
            return ()

        return conv_tuple_empty

    # tuple[T, ...] — variable-length homogeneous
    if len(args) == 2 and args[1] is Ellipsis:
        item_conv = _compile(args[0])

        def conv_tuple_var(raw, source, pointer, forbid_unknown):
            if not isinstance(raw, (list, tuple)):
                _type_error(tp, raw, source, pointer)
            return tuple(
                item_conv(item, source, f"{pointer}/{i}", forbid_unknown)
                for i, item in enumerate(raw)
            )

        return conv_tuple_var

    # tuple[T1, T2, T3] — fixed-length heterogeneous
    item_convs = [_compile(a) for a in args]
    n = len(args)

    def conv_tuple_fixed(raw, source, pointer, forbid_unknown):
        if not isinstance(raw, (list, tuple)):
            _type_error(tp, raw, source, pointer)
        if len(raw) != n:
            _length_error(tp, n, len(raw), source, pointer)
        return tuple(
            conv(item, source, f"{pointer}/{i}", forbid_unknown)
            for i, (item, conv) in enumerate(zip(raw, item_convs))
        )

    return conv_tuple_fixed


def _build_dataclass(tp: type) -> _Conv:
    hints, aliases = _dataclass_meta(tp)
    field_specs = []
    for field in dataclasses.fields(tp):
        if not field.init:
            continue
        raw_key = aliases[field.name]
        has_default = not (
            field.default is dataclasses.MISSING
            and field.default_factory is dataclasses.MISSING  # type: ignore[misc]
        )
        field_specs.append(
            (field.name, raw_key, _esc(raw_key), _compile(hints[field.name]), has_default)
        )
    known = frozenset(aliases.values())

    def conv_dataclass(raw, source, pointer, forbid_unknown):
        if not isinstance(raw, dict):
            _type_error(tp, raw, source, pointer)
        if forbid_unknown:
            for key in raw:
                if key not in known:
                    _unknown_field(key, tp, source, f"{pointer}/{_esc(str(key))}")
        kwargs: dict[str, typing.Any] = {}
        for name, raw_key, esc_key, conv, has_default in field_specs:
            if raw_key in raw:
                kwargs[name] = conv(raw[raw_key], source, f"{pointer}/{esc_key}", forbid_unknown)
            elif not has_default:
                _missing_field(name, tp, source, pointer)
        try:
            return tp(**kwargs)
        except ParseError:
            raise
        except Exception as exc:
            _value_error(str(exc), source, pointer)

    return conv_dataclass


def _build_typeddict(tp: type) -> _Conv:
    hints, required_keys = _typeddict_meta(tp)
    field_specs = [
        (key, _esc(key), _compile(value_tp), key in required_keys) for key, value_tp in hints.items()
    ]
    known = frozenset(hints)

    def conv_typeddict(raw, source, pointer, forbid_unknown):
        if not isinstance(raw, dict):
            _type_error(tp, raw, source, pointer)
        if forbid_unknown:
            for key in raw:
                if key not in known:
                    _unknown_field(key, tp, source, f"{pointer}/{_esc(str(key))}")
        result: dict[str, typing.Any] = {}
        for key, esc_key, conv, required in field_specs:
            if key in raw:
                result[key] = conv(raw[key], source, f"{pointer}/{esc_key}", forbid_unknown)
            elif required:
                _missing_field(key, tp, source, pointer)
        return result

    return conv_typeddict


@functools.lru_cache(maxsize=None)
def _tagged_union_spec(candidates: tuple[typing.Any, ...]) -> tuple[str, dict[typing.Any, typing.Any]] | None:
    is_typeddict = getattr(typing, "is_typeddict", None)
    field_maps: list[dict[str, tuple[typing.Any, ...]]] = []
    for candidate in candidates:
        if dataclasses.is_dataclass(candidate) and isinstance(candidate, type):
            try:
                hints = typing.get_type_hints(candidate, include_extras=True)
            except NameError:  # pragma: no cover
                hints = candidate.__annotations__
        elif callable(is_typeddict) and is_typeddict(candidate):
            try:
                hints = typing.get_type_hints(candidate, include_extras=True)
            except NameError:  # pragma: no cover
                hints = candidate.__annotations__
        else:
            return None
        literal_fields: dict[str, tuple[typing.Any, ...]] = {}
        for name, hint in hints.items():
            if typing.get_origin(hint) is typing.Literal:
                literal_fields[name] = typing.get_args(hint)
        if not literal_fields:
            return None
        field_maps.append(literal_fields)

    common_fields = set(field_maps[0])
    for fields in field_maps[1:]:
        common_fields &= set(fields)
    if not common_fields:
        return None

    for field_name in sorted(common_fields, key=_tag_field_rank):
        tag_map: dict[typing.Any, typing.Any] = {}
        for candidate, fields in zip(candidates, field_maps):
            values = fields[field_name]
            if len(values) != 1:
                break
            tag_value = values[0]
            if tag_value in tag_map:
                break
            tag_map[tag_value] = candidate
        else:
            return field_name, tag_map
    return None


def _tag_field_rank(name: str) -> tuple[int, str]:
    preferred = ("kind", "type", "tag")
    try:
        return (preferred.index(name), name)
    except ValueError:
        return (len(preferred), name)
