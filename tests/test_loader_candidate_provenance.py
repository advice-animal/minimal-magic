"""Which candidate file a merged config's errors get blamed on."""

import dataclasses
import typing

import pytest

from minimal_magic import Candidate, load_candidate, ParseError


@dataclasses.dataclass
class Inner:
    port: int


@dataclasses.dataclass
class Cfg:
    host: str
    port: int = 0
    server: Inner | None = None
    tags: list[str] = dataclasses.field(default_factory=list)


def write(tmp_path, name, text):
    f = tmp_path / name
    f.write_text(text)
    return f


def test_error_blames_the_candidate_that_supplied_the_value(tmp_path):
    # The bad port comes from a.toml and b.toml never mentions it, so the
    # error must point into a.toml — not the last file read.
    a = write(tmp_path, "a.toml", 'host = "h"\nport = "not-an-int"\n')
    b = write(tmp_path, "b.toml", 'host = "h2"\n')

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b], type=Cfg)
    err = exc_info.value
    assert err.filename == str(a)
    assert (err.line, err.column) == (2, 8)


def test_error_blames_the_overriding_candidate(tmp_path):
    # Both files set port; the later one wins, so it owns the error too.
    a = write(tmp_path, "a.toml", 'host = "h"\nport = 1\n')
    b = write(tmp_path, "b.toml", 'host = "h2"\nport = "bad"\n')

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b], type=Cfg)
    err = exc_info.value
    assert err.filename == str(b)
    assert (err.line, err.column) == (2, 8)


def test_error_inside_a_subtree_taken_wholesale(tmp_path):
    # Nothing records /server/port: the whole `server` table came from a.toml
    # untouched, so resolution walks up to /server and keeps the /port suffix.
    a = write(tmp_path, "a.toml", 'host = "h"\n\n[server]\nport = "bad"\n')
    b = write(tmp_path, "b.toml", 'host = "h2"\n')

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b], type=Cfg)
    err = exc_info.value
    assert err.filename == str(a)
    assert (err.line, err.column) == (4, 8)


def test_error_inside_a_subtree_both_candidates_touched(tmp_path):
    # Here /server is merged key by key, so /server/port is recorded against
    # whichever file supplied it last.
    a = write(tmp_path, "a.toml", 'host = "h"\n\n[server]\nport = 1\n')
    b = write(tmp_path, "b.toml", '[server]\nport = "bad"\n')

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b], type=Cfg)
    err = exc_info.value
    assert err.filename == str(b)
    assert (err.line, err.column) == (2, 8)


def test_prefix_translates_to_the_pointer_inside_that_file(tmp_path):
    # /port in the merged tree is /tool/myapp/port in b.toml. The recorded
    # file pointer has to be the latter or the lookup lands nowhere.
    a = write(tmp_path, "a.toml", 'host = "h"\nport = 1\n')
    b = write(tmp_path, "b.toml", '[tool.myapp]\nport = "bad"\n')

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, Candidate(b, prefix="tool.myapp")], type=Cfg)
    err = exc_info.value
    assert err.filename == str(b)
    assert (err.line, err.column) == (2, 8)


def test_mixed_formats_use_each_candidates_own_parser(tmp_path):
    a = write(tmp_path, "a.json", '{\n  "host": "h",\n  "port": "bad"\n}\n')
    b = write(tmp_path, "b.toml", 'host = "h2"\n')

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b], type=Cfg)
    err = exc_info.value
    assert err.filename == str(a)
    assert (err.line, err.column) == (3, 11)


def test_middle_candidate_of_three_is_blamed(tmp_path):
    a = write(tmp_path, "a.toml", 'host = "h"\nport = 1\n')
    b = write(tmp_path, "b.toml", 'port = "bad"\n')
    c = write(tmp_path, "c.toml", 'host = "h3"\n')

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b, c], type=Cfg)
    err = exc_info.value
    assert err.filename == str(b)
    assert (err.line, err.column) == (1, 8)


def test_absent_prefix_contributes_no_provenance(tmp_path):
    # b.toml has no [tool.myapp], so it contributes nothing and cannot be
    # blamed for a value only a.toml supplied.
    a = write(tmp_path, "a.toml", 'host = "h"\nport = "bad"\n')
    b = write(tmp_path, "b.toml", 'unrelated = 1\n')

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, Candidate(b, prefix="tool.myapp")], type=Cfg)
    assert exc_info.value.filename == str(a)


def test_unknown_field_blames_the_candidate_that_introduced_it(tmp_path):
    a = write(tmp_path, "a.toml", 'host = "h"\ntypo = 1\n')
    b = write(tmp_path, "b.toml", 'host = "h2"\n')

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b], type=Cfg, forbid_unknown_fields=True)
    err = exc_info.value
    assert err.filename == str(a)
    assert (err.line, err.column) == (2, 1)


def test_merge_callable_result_is_blamed_on_the_override(tmp_path):
    # A merge callable's output exists in no file. It is attributed to the
    # override candidate, whose bytes are the ones being validated.
    @dataclasses.dataclass
    class Tagged:
        tags: list[int] = dataclasses.field(
            default_factory=list,
            metadata={"merge": lambda base, override: base + override},
        )

    a = write(tmp_path, "a.toml", "tags = [1]\n")
    b = write(tmp_path, "b.toml", 'tags = ["bad"]\n')

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b], type=Tagged)
    assert exc_info.value.filename == str(b)


def test_list_element_pointer_resolves_through_its_parent(tmp_path):
    # Only /tags is recorded, so /tags/1 resolves by appending the suffix to
    # the recorded file pointer. JSON source maps index array elements, so the
    # column lands on the offending element rather than the list.
    a = write(tmp_path, "a.json", '{\n  "host": "h",\n  "tags": ["ok", 2]\n}\n')
    b = write(tmp_path, "b.toml", 'host = "h2"\n')

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b], type=Cfg)
    err = exc_info.value
    assert err.filename == str(a)
    assert (err.line, err.column) == (3, 18)


def test_source_maps_are_built_only_when_locate_pointer_unavailable(tmp_path, monkeypatch):
    """Falls back to build_source_map() + closest_entry() -- lazily, only for
    the candidate actually blamed, and only when something fails -- if
    locate_pointer() is unavailable."""
    from minimal_magic import _errors, api

    monkeypatch.delattr(_errors._source_maps, "locate_pointer", raising=False)

    calls = []
    real = api.build_source_map

    def counting(data, fmt):
        calls.append(fmt)
        return real(data, fmt)

    monkeypatch.setattr(api, "build_source_map", counting)

    a = write(tmp_path, "a.toml", 'host = "h"\nport = 1\n')
    b = write(tmp_path, "b.toml", 'host = "h2"\n')

    assert load_candidate([a, b], type=Cfg).port == 1
    assert calls == []

    bad = write(tmp_path, "bad.toml", 'host = "h"\nport = "bad"\n')
    with pytest.raises(ParseError):
        load_candidate([bad, b], type=Cfg)
    # Only the file actually blamed gets mapped, not every candidate.
    assert len(calls) == 1


def test_source_maps_are_never_built_when_locate_pointer_available(tmp_path, monkeypatch):
    """parse-errors' locate_pointer() answers the one pointer that failed
    directly, so build_source_map() never maps a whole document -- not even
    the blamed candidate's, and not even on failure."""
    from minimal_magic import api

    calls = []
    real = api.build_source_map

    def counting(data, fmt):
        calls.append(fmt)
        return real(data, fmt)

    monkeypatch.setattr(api, "build_source_map", counting)

    a = write(tmp_path, "a.toml", 'host = "h"\nport = 1\n')
    b = write(tmp_path, "b.toml", 'host = "h2"\n')

    assert load_candidate([a, b], type=Cfg).port == 1
    assert calls == []

    bad = write(tmp_path, "bad.toml", 'host = "h"\nport = "bad"\n')
    with pytest.raises(ParseError):
        load_candidate([bad, b], type=Cfg)
    assert calls == []


def test_typed_dict_candidate_errors_are_attributed(tmp_path):
    class TdCfg(typing.TypedDict):
        host: str
        port: int

    a = write(tmp_path, "a.toml", 'port = "bad"\n')
    b = write(tmp_path, "b.toml", 'host = "h2"\n')

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b], type=TdCfg)
    err = exc_info.value
    assert err.filename == str(a)
    assert (err.line, err.column) == (1, 8)


def test_empty_last_candidate_has_no_bytes_to_locate_against(tmp_path):
    # An empty file still parses to {}, so it is a valid candidate. It leaves
    # the fallback with no bytes to map, which reports without a location.
    a = write(tmp_path, "a.toml", "port = 1\n")
    b = write(tmp_path, "b.toml", "")

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b], type=Cfg)
    err = exc_info.value
    assert err.filename == str(b)
    assert (err.line, err.column) == (0, 0)
    assert "Missing required field `host`" in str(err)


def test_missing_field_at_root_falls_back_to_last_candidate(tmp_path):
    # No candidate supplies `host`, so no candidate owns the root pointer the
    # error is raised at. The last file read is the documented fallback.
    a = write(tmp_path, "a.toml", "port = 1\n")
    b = write(tmp_path, "b.toml", "port = 2\n")

    with pytest.raises(ParseError) as exc_info:
        load_candidate([a, b], type=Cfg)
    err = exc_info.value
    assert "Missing required field `host`" in str(err)
    assert err.filename == str(b)
