import dataclasses
import json

import pytest

from minimal_magic import alias, Candidate, convert, load, load_candidate, ParseError

from ._types import (
    DcConfig,
    DcNested,
    TupleHolder,
    TypeSampler,
    WithCircularValue,
    WithLevel,
)


def test_load_json_dataclass(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"host": "localhost", "port": 8080}')
    result = load(f, type=DcConfig)
    assert isinstance(result, DcConfig)
    assert result.port == 8080


def test_load_json_dataclass_validation_error(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"host": "localhost", "port": "not-an-int"}')
    with pytest.raises(ParseError) as exc_info:
        load(f, type=DcConfig)
    err = exc_info.value
    assert err.line == 1
    assert str(err) == f"{f}:1:31: Expected `int`, got `str`"


def test_load_json_dataclass_nested_validation_error(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"server": {"host": "localhost", "port": "not-an-int"}}')
    with pytest.raises(ParseError) as exc_info:
        load(f, type=DcNested)
    err = exc_info.value
    assert err.line == 1
    assert str(err) == f"{f}:1:42: Expected `int`, got `str`"


def test_load_json_dataclass_missing_field(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"host": "localhost"}')
    with pytest.raises(ParseError) as exc_info:
        load(f, type=DcConfig)
    err = exc_info.value
    assert err.line == 1
    assert str(err) == f"{f}:1:1: Missing required field `port` in `DcConfig`"


def test_convert_json_dataclass_validation_error(tmp_path):
    f = tmp_path / "config.json"
    data = b'{"host": "localhost", "port": "not-an-int"}'
    raw = json.loads(data)
    with pytest.raises(ParseError) as exc_info:
        convert(raw, data=data, format="json", filename=f, type=DcConfig)
    err = exc_info.value
    assert err.line == 1
    assert str(err) == f"{f}:1:31: Expected `int`, got `str`"


def test_convert_json_dataclass_validation_error_without_bytes(tmp_path):
    f = tmp_path / "config.json"
    raw = {"host": "localhost", "port": "not-an-int"}
    with pytest.raises(ParseError) as exc_info:
        convert(raw, filename=f, type=DcConfig)
    err = exc_info.value
    assert err.line == 0
    assert str(err) == f"{f}: Expected `int`, got `str` - at `/port`"


def test_single_file_source_map_is_lazy_on_success(tmp_path, monkeypatch):
    from minimal_magic import api

    def fail_if_called(data, fmt):
        raise AssertionError("source map should not be built on successful conversion")

    monkeypatch.setattr(api, "build_source_map", fail_if_called)

    f = tmp_path / "config.json"
    f.write_bytes(b'{"host": "localhost", "port": 8080}')
    assert load(f, type=DcConfig) == DcConfig(host="localhost", port=8080)


def test_single_file_uses_source_map_locate_when_available(tmp_path, monkeypatch):
    from parse_errors.source_map import Entry, Location

    from minimal_magic import _errors, api

    calls = []

    def locate_pointer(data, fmt, pointer):
        calls.append((data, fmt, pointer))
        loc = Location(line=4, column=8, position=0)
        return Entry(value_start=loc, value_end=loc)

    def fail_if_called(data, fmt):
        raise AssertionError("source map should not be built when locate_pointer() is available")

    monkeypatch.setattr(_errors._source_maps, "locate_pointer", locate_pointer, raising=False)
    monkeypatch.setattr(api, "build_source_map", fail_if_called)

    f = tmp_path / "config.json"
    data = b'{"host": "localhost", "port": "not-an-int"}'
    f.write_bytes(data)
    with pytest.raises(ParseError) as exc_info:
        load(f, type=DcConfig)

    err = exc_info.value
    assert calls == [(data, "json", "/port")]
    assert err.line == 5
    assert err.column == 9


def test_convert_without_data_reports_pointer_only_list_item(tmp_path):
    f = tmp_path / "config.json"
    with pytest.raises(ParseError) as exc_info:
        convert(
            {
                "annotated": 1,
                "any_val": 0,
                "optional": None,
                "items": [1, "x"],
                "mapping": {},
                "score": 1,
            },
            filename=f,
            type=TypeSampler,
        )
    err = exc_info.value
    assert err.line == 0
    assert str(err) == f"{f}: Expected `int`, got `str` - at `/items/1`"


def test_load_yaml_dataclass_validation_error(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_bytes(b"host: localhost\nport: not-an-int\n")
    with pytest.raises(ParseError) as exc_info:
        load(f, type=DcConfig)
    err = exc_info.value
    assert err.line == 2
    assert str(err) == f"{f}:2:7: Expected `int`, got `str`"


def test_load_toml_dataclass_validation_error(tmp_path):
    f = tmp_path / "config.toml"
    f.write_bytes(b'host = "localhost"\nport = "not-an-int"\n')
    with pytest.raises(ParseError) as exc_info:
        load(f, type=DcConfig)
    err = exc_info.value
    assert err.line == 2
    assert str(err) == f"{f}:2:8: Expected `int`, got `str`"



# --- _convert branch coverage ---
# One JSON file drives all the type-annotation edge cases.



def test_convert_annotated_and_any(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"annotated": 1, "any_val": "whatever", "optional": null, "items": [1, 2], "mapping": {"a": 1}, "score": 3}')
    result = load(f, type=TypeSampler)
    assert result.annotated == 1
    assert result.any_val == "whatever"
    assert result.optional is None
    assert result.score == 3.0  # int coerced to float


def test_convert_optional_non_none(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"annotated": 1, "any_val": 0, "optional": 42, "items": [], "mapping": {}, "score": 1}')
    assert load(f, type=TypeSampler).optional == 42


def test_convert_list_items(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"annotated": 1, "any_val": 0, "optional": null, "items": [1, 2, 3], "mapping": {}, "score": 1}')
    assert load(f, type=TypeSampler).items == [1, 2, 3]


def test_convert_dict_field(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"annotated": 1, "any_val": 0, "optional": null, "items": [], "mapping": {"x": 9}, "score": 1}')
    assert load(f, type=TypeSampler).mapping == {"x": 9}


def test_convert_none_for_non_optional(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"host": null, "port": 1}')
    with pytest.raises(ParseError, match="Expected `str`, got `NoneType`"):
        load(f, type=DcConfig)


def test_convert_wrong_type_for_list_field(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"annotated": 1, "any_val": 0, "optional": null, "items": "oops", "mapping": {}, "score": 1}')
    with pytest.raises(ParseError, match="Expected `list`"):
        load(f, type=TypeSampler)


def test_convert_wrong_type_for_dict_field(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"annotated": 1, "any_val": 0, "optional": null, "items": [], "mapping": "oops", "score": 1}')
    with pytest.raises(ParseError, match="Expected `dict`"):
        load(f, type=TypeSampler)


def test_convert_non_dict_for_dataclass_field(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"server": "not-a-dict"}')
    with pytest.raises(ParseError, match="Expected `DcConfig`"):
        load(f, type=DcNested)


def test_convert_bool_rejected_for_int(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"host": "h", "port": true}')
    with pytest.raises(ParseError, match="Expected `int`, got `bool`"):
        load(f, type=DcConfig)


def test_convert_multi_union_error(tmp_path):
    @dataclasses.dataclass
    class MultiUnion:
        val: int | float

    f = tmp_path / "config.json"
    f.write_bytes(b'{"val": "oops"}')
    with pytest.raises(ParseError):
        load(f, type=MultiUnion)


def test_forbid_unknown_fields_ok(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"port": 8080, "host": "localhost"}')
    result = load(f, type=DcConfig, forbid_unknown_fields=True)
    assert result.port == 8080


def test_forbid_unknown_fields_error(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"port": 8080, "typo": true}')
    with pytest.raises(ParseError) as exc_info:
        load(f, type=DcConfig, forbid_unknown_fields=True)
    assert str(exc_info.value) == f"{f}:1:16: Unexpected field `typo` in `DcConfig`"


def test_forbid_unknown_fields_nested(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"server": {"host": "localhost", "port": 8080, "extra": 1}}')
    with pytest.raises(ParseError) as exc_info:
        load(f, type=DcNested, forbid_unknown_fields=True)
    assert str(exc_info.value) == f"{f}:1:48: Unexpected field `extra` in `DcConfig`"


def test_forbid_unknown_fields_default_ignores(tmp_path):
    # Default behaviour: extra fields are silently ignored
    f = tmp_path / "config.json"
    f.write_bytes(b'{"port": 8080, "host": "localhost", "extra": 99}')
    result = load(f, type=DcConfig)
    assert result == DcConfig(host="localhost", port=8080)


def test_field_init_false_skipped(tmp_path):
    @dataclasses.dataclass
    class WithAddress:
        host: str
        port: int
        address: str = dataclasses.field(init=False)
        def __post_init__(self):
            self.address = f"{self.host}:{self.port}"

    f = tmp_path / "config.json"
    f.write_bytes(b'{"host": "localhost", "port": 8080}')
    result = load(f, type=WithAddress)
    assert result.address == "localhost:8080"


def test_post_init_exception_becomes_parse_error(tmp_path):
    @dataclasses.dataclass
    class Validated:
        port: int
        def __post_init__(self):
            if not (1 <= self.port <= 65535):
                raise ValueError(f"port must be 1-65535, got {self.port}")

    f = tmp_path / "config.json"
    f.write_bytes(b'{"port": 99999}')
    with pytest.raises(ParseError) as exc_info:
        load(f, type=Validated)
    assert "port must be 1-65535" in str(exc_info.value)
    assert str(f) in str(exc_info.value)


# --- config inheritance (load_candidate) ---

def test_candidate_basic_merge(tmp_path):
    base = tmp_path / "base.json"
    override = tmp_path / "override.json"
    base.write_bytes(b'{"host": "localhost", "port": 8080}')
    override.write_bytes(b'{"port": 9090}')
    result = load_candidate([base, override], type=DcConfig)
    assert result.host == "localhost"
    assert result.port == 9090


def test_candidate_nested_merge(tmp_path):
    @dataclasses.dataclass
    class Inner:
        x: int
        y: int

    @dataclasses.dataclass
    class Outer:
        inner: Inner
        label: str

    base = tmp_path / "base.json"
    override = tmp_path / "override.json"
    base.write_bytes(b'{"inner": {"x": 1, "y": 2}, "label": "base"}')
    override.write_bytes(b'{"inner": {"y": 99}}')
    result = load_candidate([base, override], type=Outer)
    assert result.inner.x == 1
    assert result.inner.y == 99
    assert result.label == "base"


def test_candidate_error_mentions_last_file(tmp_path):
    base = tmp_path / "base.json"
    override = tmp_path / "override.json"
    base.write_bytes(b'{"host": "localhost", "port": 8080}')
    override.write_bytes(b'{"port": "bad"}')
    with pytest.raises(ParseError) as exc_info:
        load_candidate([base, override], type=DcConfig)
    assert str(override) in str(exc_info.value)


def test_candidate_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        load_candidate([])


def test_candidate_prefix_basic(tmp_path):
    f = tmp_path / "pyproject.toml"
    f.write_bytes(b'[tool.myapp]\nhost = "localhost"\nport = 8080\n')
    result = load_candidate([Candidate(f, prefix="tool.myapp")], type=DcConfig)
    assert result.host == "localhost"
    assert result.port == 8080


def test_candidate_prefix_missing_is_not_error(tmp_path):
    base = tmp_path / "base.json"
    extra = tmp_path / "extra.json"
    base.write_bytes(b'{"host": "localhost", "port": 8080}')
    # extra doesn't have the prefix key at all
    extra.write_bytes(b'{"other": "stuff"}')
    result = load_candidate([base, Candidate(extra, prefix="myapp")], type=DcConfig)
    assert result.host == "localhost"


def test_candidate_prefix_overrides_base(tmp_path):
    base = tmp_path / "base.json"
    override = tmp_path / "app.json"
    base.write_bytes(b'{"host": "localhost", "port": 8080}')
    override.write_bytes(b'{"myapp": {"port": 9090}, "unrelated": 1}')
    result = load_candidate([base, Candidate(override, prefix="myapp")], type=DcConfig)
    assert result.host == "localhost"
    assert result.port == 9090


def test_candidate_prefix_list_form(tmp_path):
    f = tmp_path / "pyproject.toml"
    f.write_bytes(b'[tool.myapp]\nhost = "localhost"\nport = 8080\n')
    result = load_candidate([Candidate(f, prefix=["tool", "myapp"])], type=DcConfig)
    assert result.port == 8080


# --- field-level merge callables ---

def test_merge_callable_list_concat(tmp_path):
    @dataclasses.dataclass
    class Tagged:
        host: str
        tags: list[str] = dataclasses.field(
            default_factory=list,
            metadata={"merge": lambda base, override: base + override},
        )

    base = tmp_path / "base.json"
    override = tmp_path / "override.json"
    base.write_bytes(b'{"host": "localhost", "tags": ["a", "b"]}')
    override.write_bytes(b'{"tags": ["c"]}')
    result = load_candidate([base, override], type=Tagged)
    assert result.tags == ["a", "b", "c"]


def test_merge_callable_overrides_dict_recursion(tmp_path):
    # Even when both values are dicts, a merge callable wins
    @dataclasses.dataclass
    class Inner:
        x: int

    @dataclasses.dataclass
    class Outer:
        inner: Inner = dataclasses.field(
            default=None,
            metadata={"merge": lambda base, override: {**base, **override, "x": 99}},
        )

    base = tmp_path / "base.json"
    override = tmp_path / "override.json"
    base.write_bytes(b'{"inner": {"x": 1}}')
    override.write_bytes(b'{"inner": {"x": 2}}')
    result = load_candidate([base, override], type=Outer)
    assert result.inner.x == 99


def test_merge_callable_nested_field(tmp_path):
    @dataclasses.dataclass
    class Inner:
        x: int
        tags: list[str] = dataclasses.field(
            default_factory=list,
            metadata={"merge": lambda base, override: sorted(set(base) | set(override))},
        )

    @dataclasses.dataclass
    class Outer:
        inner: Inner

    base = tmp_path / "base.json"
    override = tmp_path / "override.json"
    base.write_bytes(b'{"inner": {"x": 1, "tags": ["a", "b"]}}')
    override.write_bytes(b'{"inner": {"tags": ["b", "c"]}}')
    result = load_candidate([base, override], type=Outer)
    assert result.inner.x == 1
    assert result.inner.tags == ["a", "b", "c"]


def test_merge_callable_exception_has_location(tmp_path):
    def bad_merge(base, override):
        raise ValueError("incompatible tags")

    @dataclasses.dataclass
    class Cfg:
        tags: list[str] = dataclasses.field(
            default_factory=list,
            metadata={"merge": bad_merge},
        )

    base = tmp_path / "base.json"
    override = tmp_path / "override.json"
    base.write_bytes(b'{"tags": ["a"]}')
    override.write_bytes(b'{"tags": ["b"]}')
    with pytest.raises(ParseError) as exc_info:
        load_candidate([base, override], type=Cfg)
    err = str(exc_info.value)
    assert str(override) in err
    assert "incompatible tags" in err
    assert exc_info.value.line > 0


def test_literal_valid(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"level": "info"}')
    assert load(f, type=WithLevel).level == "info"


def test_literal_invalid(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"level": "bad"}')
    with pytest.raises(ParseError) as exc_info:
        load(f, type=WithLevel)
    assert str(exc_info.value) == f"{f}:1:11: Expected one of ['debug', 'info', 'warn'], got 'bad'"


def test_yaml_circular_reference(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_bytes(b"&a\nkey: *a\n")
    with pytest.raises(ParseError, match="circular reference"):
        load(f, type=WithCircularValue)


def test_yaml_circular_reference_rejected_even_without_a_type(tmp_path):
    # The cycle is rejected at parse time, before _convert ever runs — so it's
    # caught here even though a bare `dict`/`list`/no-type load would never
    # walk far enough into the value to find it on its own.
    f = tmp_path / "config.yaml"
    f.write_bytes(b"&a\nkey: *a\n")
    with pytest.raises(ParseError, match="circular reference"):
        load(f)


def test_yaml_shared_anchor_without_a_cycle_is_fine(tmp_path):
    # Reusing the same anchor in two sibling branches is ordinary YAML, not a
    # cycle: the shared node is never its own ancestor, so this must load.
    f = tmp_path / "config.yaml"
    f.write_bytes(b"a: &x\n  n: 1\nb: *x\nc: *x\n")
    result = load(f)
    assert result["b"] is result["c"] is result["a"]


def test_convert_none_for_non_optional_union(tmp_path):
    @dataclasses.dataclass
    class NonOptionalUnion:
        val: int | str

    f = tmp_path / "config.json"
    f.write_bytes(b'{"val": null}')
    with pytest.raises(ParseError, match="Expected"):
        load(f, type=NonOptionalUnion)


# --- tuple ---

def test_tuple_fixed_ok(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"fixed": [1, "hello"], "variadic": []}')
    result = load(f, type=TupleHolder)
    assert result.fixed == (1, "hello")


def test_tuple_variadic_ok(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"fixed": [1, "x"], "variadic": [10, 20, 30]}')
    result = load(f, type=TupleHolder)
    assert result.variadic == (10, 20, 30)


def test_tuple_fixed_wrong_element_type(tmp_path):
    # second element should be str, but gets int — error points at element [1]
    f = tmp_path / "config.json"
    f.write_bytes(b'{"fixed": [1, 2], "variadic": []}')
    with pytest.raises(ParseError) as exc_info:
        load(f, type=TupleHolder)
    err = exc_info.value
    assert str(err) == f"{f}:1:15: Expected `str`, got `int`"


def test_tuple_variadic_wrong_element_type(tmp_path):
    # third element is a string, not int — error points at element [2]
    f = tmp_path / "config.json"
    f.write_bytes(b'{"fixed": [1, "x"], "variadic": [10, 20, "oops"]}')
    with pytest.raises(ParseError) as exc_info:
        load(f, type=TupleHolder)
    err = exc_info.value
    assert str(err) == f"{f}:1:42: Expected `int`, got `str`"


def test_tuple_fixed_wrong_length(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"fixed": [1], "variadic": []}')
    with pytest.raises(ParseError) as exc_info:
        load(f, type=TupleHolder)
    assert str(exc_info.value) == f"{f}:1:11: Expected `tuple[int, str]` (2 elements), got 1"


def test_tuple_not_a_sequence(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"fixed": "nope", "variadic": []}')
    with pytest.raises(ParseError) as exc_info:
        load(f, type=TupleHolder)
    assert str(exc_info.value) == f"{f}:1:11: Expected `tuple`, got `str`"


def test_tuple_empty(tmp_path):
    @dataclasses.dataclass
    class WithEmpty:
        coords: tuple[()]

    f = tmp_path / "config.json"
    f.write_bytes(b'{"coords": []}')
    assert load(f, type=WithEmpty).coords == ()


def test_tuple_empty_wrong_length(tmp_path):
    @dataclasses.dataclass
    class WithEmpty:
        coords: tuple[()]

    f = tmp_path / "config.json"
    f.write_bytes(b'{"coords": [1]}')
    with pytest.raises(ParseError, match="Expected `tuple`"):
        load(f, type=WithEmpty)


# --- field aliases ---

def test_alias_basic(tmp_path):
    @dataclasses.dataclass
    class Cfg:
        retry_count: int = alias("retry-count")

    f = tmp_path / "config.json"
    f.write_bytes(b'{"retry-count": 3}')
    assert load(f, type=Cfg).retry_count == 3


def test_alias_with_default(tmp_path):
    @dataclasses.dataclass
    class Cfg:
        retry_count: int = alias("retry-count", default=1)

    f = tmp_path / "config.json"
    f.write_bytes(b'{}')
    assert load(f, type=Cfg).retry_count == 1


def test_alias_type_error_points_at_raw_key(tmp_path):
    @dataclasses.dataclass
    class Cfg:
        retry_count: int = alias("retry-count")

    f = tmp_path / "config.json"
    f.write_bytes(b'{"retry-count": "oops"}')
    with pytest.raises(ParseError, match="Expected `int`, got `str`"):
        load(f, type=Cfg)


def test_alias_forbid_unknown_accepts_alias(tmp_path):
    @dataclasses.dataclass
    class Cfg:
        retry_count: int = alias("retry-count")

    f = tmp_path / "config.json"
    f.write_bytes(b'{"retry-count": 3}')
    assert load(f, type=Cfg, forbid_unknown_fields=True).retry_count == 3


def test_alias_forbid_unknown_rejects_python_name(tmp_path):
    @dataclasses.dataclass
    class Cfg:
        retry_count: int = alias("retry-count")

    f = tmp_path / "config.json"
    f.write_bytes(b'{"retry_count": 3}')
    with pytest.raises(ParseError, match="Unexpected field `retry_count`"):
        load(f, type=Cfg, forbid_unknown_fields=True)
