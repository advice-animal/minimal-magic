import dataclasses
import json

import pytest

from minimal_magic import load, ParseError

from ._types import TaggedExpr


@dataclasses.dataclass
class BigListPayload:
    items: list[int]


@dataclasses.dataclass
class BigDictPayload:
    items: dict[str, int]


def test_benchmark_large_list_load(benchmark, tmp_path):
    size = 20_000
    f = tmp_path / "big-list.json"
    f.write_text(json.dumps({"items": list(range(size))}))

    def run():
        return load(f, type=BigListPayload)

    result = benchmark.pedantic(run, rounds=5, iterations=1)
    assert len(result.items) == size


def test_benchmark_large_list_load_validation_failure(benchmark, tmp_path):
    # Same shape and size as test_benchmark_large_list_load, but the last item
    # is invalid. A clean load never builds a source map (see
    # test_single_file_source_map_is_lazy_on_success); reporting *this*
    # error's location does, over the whole 20k-item document -- this is
    # that cost in isolation, not the conversion cost measured above.
    size = 20_000
    items: list = list(range(size))
    items[-1] = "not-an-int"
    f = tmp_path / "big-list-invalid.json"
    f.write_text(json.dumps({"items": items}))

    def run():
        with pytest.raises(ParseError) as exc_info:
            load(f, type=BigListPayload)
        return exc_info.value

    result = benchmark.pedantic(run, rounds=5, iterations=1)
    assert "Expected `int`" in str(result)


def test_benchmark_large_dict_load(benchmark, tmp_path):
    size = 20_000
    f = tmp_path / "big-dict.json"
    f.write_text(json.dumps({"items": {str(i): i for i in range(size)}}))

    def run():
        return load(f, type=BigDictPayload)

    result = benchmark.pedantic(run, rounds=5, iterations=1)
    assert len(result.items) == size


def test_benchmark_recursive_tagged_union_load(benchmark, tmp_path):
    depth = 150
    node = {"kind": "leaf", "value": 0}
    for i in range(depth):
        node = {
            "kind": "branch",
            "left": {"kind": "leaf", "value": i},
            "right": node,
        }

    f = tmp_path / "expr.json"
    f.write_text(json.dumps(node))

    def run():
        return load(f, type=TaggedExpr)

    result = benchmark.pedantic(run, rounds=5, iterations=1)
    cursor = result
    steps = 0
    while hasattr(cursor, "right"):
        cursor = cursor.right
        steps += 1
    assert steps == depth
    assert cursor.value == 0
