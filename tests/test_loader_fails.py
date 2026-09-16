import dataclasses
import sys
import typing

import pytest

from minimal_magic import convert, load, load_candidate, ParseError

from ._types import DcConfig


def test_load_unknown_extension(tmp_path):
    f = tmp_path / "config.ini"
    f.write_bytes(b"[section]\nkey = value\n")
    with pytest.raises(ValueError, match="Cannot detect format"):
        load(f)


def test_load_toml_syntax_error_no_location(tmp_path):
    f = tmp_path / "config.toml"
    f.write_bytes(b"port = ")
    with pytest.raises(ParseError) as exc_info:
        load(f)
    err = exc_info.value
    assert err.line == 0
    assert str(err) == f"{f}: Invalid value (at end of document)"


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
