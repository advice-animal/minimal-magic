import datetime as dt
import decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

pytest.importorskip("hypothesis")
from hypothesis import given, settings
from hypothesis import strategies as st

from minimal_magic import load

from ._types import Color, CompatConfig, DcConfig


@settings(max_examples=50, deadline=None)
@given(
    host=st.text(min_size=1, max_size=24),
    port=st.integers(min_value=0, max_value=65535),
)
def test_hypothesis_round_trip_dataclass(host, port):
    with TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "config.json"
        f.write_text(json.dumps({"host": host, "port": port}))

        result = load(f, type=DcConfig)
        assert result.host == host
        assert result.port == port


@settings(max_examples=50, deadline=None)
@given(
    color=st.sampled_from([member.value for member in Color]),
    root=st.text(min_size=1, max_size=16).map(lambda s: f"/tmp/{s.replace('/', '_')}"),
    amount=st.decimals(allow_nan=False, allow_infinity=False, places=2),
    day=st.dates(),
    moment=st.datetimes(timezones=st.none()),
    clock=st.times(),
    names=st.lists(st.text(min_size=0, max_size=8), max_size=4),
    mapping=st.dictionaries(st.text(min_size=1, max_size=6), st.integers(min_value=-20, max_value=20), max_size=4),
    labels=st.sets(st.text(min_size=0, max_size=6), max_size=4),
    frozen=st.sets(st.integers(min_value=0, max_value=20), max_size=4),
)
def test_hypothesis_round_trip_compat_config(
    color,
    root,
    amount,
    day,
    moment,
    clock,
    names,
    mapping,
    labels,
    frozen,
):
    with TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "config.json"
        payload = {
            "color": color,
            "root": root,
            "amount": str(amount),
            "day": day.isoformat(),
            "moment": moment.isoformat(),
            "clock": clock.isoformat(),
            "names": names,
            "mapping": mapping,
            "labels": sorted(labels),
            "frozen": sorted(frozen),
        }
        f.write_text(json.dumps(payload))

        result = load(f, type=CompatConfig)
        assert result.color.value == color
        assert result.root == Path(root)
        assert result.amount == decimal.Decimal(str(amount))
        assert result.day == dt.date.fromisoformat(day.isoformat())
        assert result.moment == dt.datetime.fromisoformat(moment.isoformat())
        assert result.clock == dt.time.fromisoformat(clock.isoformat())
        assert result.names == names
        assert result.mapping == mapping
        assert result.labels == set(labels)
        assert result.frozen == frozenset(frozen)
