import dataclasses
import sys
import typing

import pytest

from minimal_magic import _parsing, convert, load, load_candidate, ParseError

from ._types import DcConfig


def test_load_unknown_extension(tmp_path):
    f = tmp_path / "config.ini"
    f.write_bytes(b"[section]\nkey = value\n")
    with pytest.raises(ValueError, match="Cannot detect format"):
        load(f)


# One syntax-error test per format, each failing on a line after the first,
# so a location bug (off-by-one, or reporting line 1 unconditionally) can't
# hide behind a single-line fixture.


def test_load_json_syntax_error_location(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{\n  "host": "x"\n  "port": 1\n}\n')
    with pytest.raises(ParseError) as exc_info:
        load(f)
    err = exc_info.value
    assert err.line == 3
    assert err.column == 3
    assert str(err) == f"{f}:3:3: Expecting ',' delimiter"


def test_load_yaml_syntax_error_location(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_bytes(b"host: x\n  port: 1\n")
    with pytest.raises(ParseError) as exc_info:
        load(f)
    err = exc_info.value
    assert err.line == 2
    assert err.column == 7
    assert "mapping values are not allowed" in str(err)
    assert str(err).startswith(f"{f}:2:7: ")


def test_load_toml_syntax_error_location(tmp_path):
    # The message text isn't asserted verbatim: tomllib sets .msg (a clean,
    # non-redundant message) only from Python 3.14 on and on tomli's
    # backport (used here for Python <3.11); stdlib tomllib on 3.11-3.13 has
    # no .msg, so parse-errors' decode_error_message() falls back to
    # str(exc), which already has the position folded in.
    f = tmp_path / "config.toml"
    f.write_bytes(b'host = "x"\nport ! 1\n')
    with pytest.raises(ParseError) as exc_info:
        load(f)
    err = exc_info.value
    assert err.line == 2
    assert err.column == 6
    assert str(err).startswith(f"{f}:2:6: Expected '=' after a key in a key/value pair")


def test_load_toml_syntax_error_at_end_of_document(tmp_path):
    # tomllib phrases an error at EOF as "(at end of document)" instead of
    # "(at line N, column N)", with no digits left for the regex fallback to
    # find. .lineno/.colno sidestep that, but only exist on tomli (used here
    # for Python <3.11) and on tomllib from Python 3.14 on; stdlib tomllib
    # on 3.11-3.13 has neither, so this failure is genuinely unlocatable
    # there -- parse-errors' ParseContext has no better answer available.
    try:
        _parsing.tomllib.loads("x")
    except _parsing.tomllib.TOMLDecodeError as probe:
        has_position = hasattr(probe, "lineno")

    f = tmp_path / "config.toml"
    f.write_bytes(b"port = ")
    with pytest.raises(ParseError) as exc_info:
        load(f)
    err = exc_info.value
    assert err.line == 1
    if has_position:
        assert err.column == 8
        assert str(err) == f"{f}:1:8: Invalid value"
    else:
        assert err.column == 0
        assert str(err) == f"{f}: TOMLDecodeError('Invalid value (at end of document)')"


def test_load_toml_syntax_error_falls_back_to_regex_without_lineno_attrs(tmp_path, monkeypatch):
    # Python 3.11-3.13's stdlib tomllib doesn't set .lineno/.colno/.msg at
    # all (added in 3.14; tomli's backport, used on 3.10, already has them),
    # so this path has to keep working from the message text alone. A plain
    # stand-in exception reproduces that shape on any Python version --
    # locate_decode_error() only duck-types the attributes, so it doesn't
    # need a real TOMLDecodeError, and this sidesteps that class's own
    # deprecated single-string-arg constructor form, which warns.
    class FakeTOMLDecodeError(Exception):
        pass

    def fake_loads(data):
        raise FakeTOMLDecodeError("Expected '=' after a key in a key/value pair (at line 2, column 6)")

    monkeypatch.setattr(_parsing.tomllib, "loads", fake_loads)
    f = tmp_path / "config.toml"
    f.write_bytes(b'host = "x"\nport ! 1\n')
    with pytest.raises(ParseError) as exc_info:
        load(f)
    err = exc_info.value
    assert err.line == 2
    assert err.column == 6


def test_load_unknown_format(tmp_path):
    f = tmp_path / "config.ini"
    f.write_bytes(b"[section]\n")
    with pytest.raises(ValueError, match="Unknown format"):
        load(f, format="ini")


def test_load_explicit_format(tmp_path):
    f = tmp_path / "config.ini"
    f.write_bytes(b'{"host": "localhost", "port": 8080}')
    assert load(f, format="json")["port"] == 8080


def test_load_empty_yaml_dataclass_no_location(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_bytes(b"")
    with pytest.raises(ParseError) as exc_info:
        load(f, type=DcConfig)
    err = exc_info.value
    assert err.line == 0
    assert str(err) == f"{f}: Expected `DcConfig`, got `NoneType`"


def test_load_blank_yaml_dataclass_no_location(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_bytes(b"   \n\n")
    with pytest.raises(ParseError) as exc_info:
        load(f, type=DcConfig)
    err = exc_info.value
    assert err.line == 0
    assert str(err) == f"{f}: Expected `DcConfig`, got `NoneType`"


def test_load_empty_yaml_literal_no_location(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_bytes(b"")
    with pytest.raises(ParseError) as exc_info:
        load(f, type=typing.Literal["a", "b"])
    err = exc_info.value
    assert err.line == 0
    assert str(err) == f"{f}: Expected one of ['a', 'b'], got None"


def test_yaml_without_pyyaml_names_the_extra(tmp_path, monkeypatch):
    # PyYAML is imported lazily so that JSON/TOML users need not install it.
    # Hide it and check the caller is told which extra to install.
    f = tmp_path / "config.yaml"
    f.write_bytes(b"host: localhost\n")
    monkeypatch.setitem(sys.modules, "yaml", None)
    with pytest.raises(ImportError, match=r"minimal-magic\[yaml\]"):
        load(f)


def test_convert_without_detectable_format(tmp_path):
    with pytest.raises(ValueError, match="Cannot detect format"):
        convert({"host": "h"}, filename=tmp_path / "config.ini", type=DcConfig, data=b"{}")


def test_convert_without_data_needs_no_format(tmp_path):
    # No data means no source map, so the format is never consulted.
    result = convert({"host": "h", "port": 1}, filename=tmp_path / "config.ini", type=DcConfig)
    assert result == DcConfig(host="h", port=1)


def test_load_candidate_rejects_empty_list():
    with pytest.raises(ValueError, match="must not be empty"):
        load_candidate([])


def test_load_candidate_rejects_non_mapping_top_level(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b"[1, 2]")
    with pytest.raises(ParseError, match="top-level value must be a mapping"):
        load_candidate([f], type=DcConfig)


def test_load_candidate_without_detectable_format(tmp_path):
    f = tmp_path / "config.ini"
    f.write_bytes(b"{}")
    with pytest.raises(ValueError, match="Cannot detect format"):
        load_candidate([f])


def test_load_candidate_untyped_returns_merged_dict(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_bytes(b'{"host": "a", "port": 1}')
    b.write_bytes(b'{"host": "b"}')
    assert load_candidate([a, b]) == {"host": "b", "port": 1}


def test_merge_callable_parse_error_passes_through(tmp_path):
    # A ParseError raised inside a merge callable already carries a location,
    # so it must not be re-wrapped against the override's position.
    def explode(base, override):
        raise ParseError("deliberate", filename="elsewhere.toml", line=9, column=3)

    @dataclasses.dataclass
    class Cfg:
        tags: list[str] = dataclasses.field(default_factory=list, metadata={"merge": explode})

    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_bytes(b'{"tags": ["x"]}')
    b.write_bytes(b'{"tags": ["y"]}')
    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b], type=Cfg)
    assert exc_info.value.filename == "elsewhere.toml"
    assert exc_info.value.line == 9


def test_unknown_field_without_source_map_has_no_location(tmp_path):
    # forbid_unknown_fields looks up the key's own position, which needs a
    # source map. Without data= there is none, so it degrades to the pointer.
    with pytest.raises(ParseError) as exc_info:
        convert(
            {"host": "h", "port": 1, "typo": 2},
            filename="config.json",
            type=DcConfig,
            forbid_unknown_fields=True,
        )
    err = exc_info.value
    assert err.line == 0
    assert str(err) == "config.json: Unexpected field `typo` in `DcConfig` - at `/typo`"


def test_merge_skips_non_init_fields(tmp_path):
    @dataclasses.dataclass
    class Cfg:
        tags: list[str] = dataclasses.field(default_factory=list)
        derived: int = dataclasses.field(init=False, default=0)

    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_bytes(b'{"tags": ["x"]}')
    b.write_bytes(b'{"tags": ["y"]}')
    assert load_candidate([a, b], type=Cfg).tags == ["y"]


def test_optional_dataclass_field_still_merges_recursively(tmp_path):
    # _unwrap_dataclass has to see through Optional[T] for the nested field's
    # own merge metadata to apply.
    @dataclasses.dataclass
    class Inner:
        tags: list[str] = dataclasses.field(
            default_factory=list,
            metadata={"merge": lambda base, override: base + override},
        )

    @dataclasses.dataclass
    class Outer:
        inner: Inner | None = None

    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_bytes(b'{"inner": {"tags": ["x"]}}')
    b.write_bytes(b'{"inner": {"tags": ["y"]}}')
    assert load_candidate([a, b], type=Outer).inner.tags == ["x", "y"]
