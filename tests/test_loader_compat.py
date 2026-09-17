import datetime as dt
import decimal
import json
import sys
import typing
from pathlib import Path

import pytest

from minimal_magic import convert, load, ParseError

from ._types import Color, CompatConfig, PartialServiceConfig, ServiceConfig


def test_load_json_compat_types(tmp_path):
    f = tmp_path / "config.json"
    f.write_text(
        json.dumps(
            {
                "color": "red",
                "root": "/opt/app",
                "amount": "12.50",
                "day": "2026-05-03",
                "moment": "2026-05-03T12:34:56",
                "clock": "12:34:56",
                "names": ["alpha", "beta"],
                "mapping": {"x": 1},
                "labels": ["one", "two"],
                "frozen": [1, 2],
            }
        )
    )

    result = load(f, type=CompatConfig)
    assert result.color is Color.RED
    assert result.root == Path("/opt/app")
    assert result.amount == decimal.Decimal("12.50")
    assert result.day == dt.date(2026, 5, 3)
    assert result.moment == dt.datetime(2026, 5, 3, 12, 34, 56)
    assert result.clock == dt.time(12, 34, 56)
    assert result.names == ["alpha", "beta"]
    assert result.mapping == {"x": 1}
    assert result.labels == {"one", "two"}
    assert result.frozen == frozenset({1, 2})


def test_load_toml_native_temporal_types(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text(
        '\n'.join(
            [
                'color = "green"',
                'root = "/srv/app"',
                'amount = "3.14"',
                "day = 2026-05-03",
                "moment = 2026-05-03T12:34:56",
                "clock = 12:34:56",
                'names = ["a", "b"]',
                'mapping = { x = 1 }',
                'labels = ["x", "y"]',
                'frozen = [2, 3]',
            ]
        )
        + "\n"
    )

    result = load(f, type=CompatConfig)
    assert result.day == dt.date(2026, 5, 3)
    assert result.moment == dt.datetime(2026, 5, 3, 12, 34, 56)
    assert result.clock == dt.time(12, 34, 56)
    assert result.color is Color.GREEN


def test_load_typed_dict(tmp_path):
    f = tmp_path / "config.json"
    f.write_text('{"host": "localhost", "port": 8080}')

    result = load(f, type=ServiceConfig)
    assert result == {"host": "localhost", "port": 8080}


def test_load_typed_dict_forbid_unknown_fields(tmp_path):
    f = tmp_path / "config.json"
    f.write_text('{"host": "localhost", "port": 8080, "extra": true}')

    with pytest.raises(ParseError, match="Unexpected field `extra`"):
        load(f, type=ServiceConfig, forbid_unknown_fields=True)


def test_load_typed_dict_optional_fields(tmp_path):
    f = tmp_path / "config.json"
    f.write_text('{"host": "localhost", "port": 8080}')

    result = load(f, type=PartialServiceConfig)
    assert result == {}


def test_load_typed_dict_rejects_non_mapping(tmp_path):
    f = tmp_path / "config.json"
    f.write_text("[1, 2]")

    with pytest.raises(ParseError, match="Expected .*ServiceConfig.*got `list`"):
        load(f, type=ServiceConfig)


def test_load_typed_dict_missing_required_key(tmp_path):
    f = tmp_path / "config.json"
    f.write_text('{"host": "localhost"}')

    with pytest.raises(ParseError, match="Missing required field `port`"):
        load(f, type=ServiceConfig)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Required/NotRequired need Python 3.11+")
def test_load_typed_dict_required_and_not_required_unwrap(tmp_path):
    class TdMixedRequired(typing.TypedDict, total=False):
        host: typing.Required[str]
        port: typing.NotRequired[int]

    f = tmp_path / "config.json"
    f.write_text('{"host": "localhost"}')
    assert load(f, type=TdMixedRequired) == {"host": "localhost"}

    f.write_text("{}")
    with pytest.raises(ParseError, match="Missing required field `host`"):
        load(f, type=TdMixedRequired)


def test_load_typed_dict_annotated_field_unwraps(tmp_path):
    class TdAnnotated(typing.TypedDict):
        port: typing.Annotated[int, "metadata get_type_hints keeps for TypedDicts"]

    f = tmp_path / "config.json"
    f.write_text('{"port": 8080}')
    assert load(f, type=TdAnnotated) == {"port": 8080}

    f.write_text('{"port": "nope"}')
    with pytest.raises(ParseError, match="Expected `int`, got `str`"):
        load(f, type=TdAnnotated)


# The rich scalars each have a wrong-type branch and an unparseable-value
# branch. Both report a location, so check the column as well as the message.


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("color", '"purple"', "Expected one of ['red', 'green'], got 'purple'"),
        ("root", "42", "Expected `Path`, got `int`"),
        ("amount", "true", "Expected `Decimal`, got `bool`"),
        ("amount", "[1]", "Expected `Decimal`, got `list`"),
        ("amount", '"not-a-number"', "Invalid `Decimal` value 'not-a-number'"),
        ("day", "42", "Expected `date`, got `int`"),
        ("day", '"2026-13-45"', "Invalid ISO date '2026-13-45'"),
        ("moment", "42", "Expected `datetime`, got `int`"),
        ("moment", '"not-a-time"', "Invalid ISO datetime 'not-a-time'"),
        ("clock", "42", "Expected `time`, got `int`"),
        ("clock", '"25:99"', "Invalid ISO time '25:99'"),
        ("labels", '"nope"', "Expected `set`, got `str`"),
    ],
)
def test_rich_scalar_errors_are_located(tmp_path, field, value, message):
    good = {
        "color": '"red"',
        "root": '"/opt/app"',
        "amount": '"12.50"',
        "day": '"2026-05-03"',
        "moment": '"2026-05-03T12:34:56"',
        "clock": '"12:34:56"',
        "names": '["a"]',
        "mapping": '{"x": 1}',
        "labels": '["one"]',
        "frozen": "[1]",
    }
    good[field] = value
    f = tmp_path / "config.json"
    f.write_text("{\n" + ",\n".join(f'  "{k}": {v}' for k, v in good.items()) + "\n}\n")

    with pytest.raises(ParseError) as exc_info:
        load(f, type=CompatConfig)
    err = exc_info.value
    assert message in str(err)
    # Field order in `good` matches the file, so the bad line is findable.
    assert err.line == list(good).index(field) + 2
    assert err.column == len(f'  "{field}": ') + 1


def test_rich_scalars_accept_already_converted_values():
    # TOML yields real date/datetime/time objects, and a caller may hand
    # convert() a dict that already holds Path/Decimal/Enum values.
    raw = {
        "color": Color.RED,
        "root": Path("/opt/app"),
        "amount": decimal.Decimal("12.50"),
        "day": dt.date(2026, 5, 3),
        "moment": dt.datetime(2026, 5, 3, 12, 34, 56),
        "clock": dt.time(12, 34, 56),
        "names": ["a"],
        "mapping": {"x": 1},
        "labels": ["one"],
        "frozen": [1],
    }
    result = convert(raw, filename="config.toml", type=CompatConfig)
    assert result.color is Color.RED
    assert result.root == Path("/opt/app")
    assert result.amount == decimal.Decimal("12.50")
    assert result.day == dt.date(2026, 5, 3)
    assert result.moment == dt.datetime(2026, 5, 3, 12, 34, 56)
    assert result.clock == dt.time(12, 34, 56)
