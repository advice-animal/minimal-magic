import dataclasses
import json

from minimal_magic import load

from ._types import TaggedExpr


@dataclasses.dataclass
class BigListPayload:
    items: list[int]


@dataclasses.dataclass
class BigDictPayload:
    items: dict[str, int]


def test_large_list_payload(tmp_path):
    size = 20_000
    f = tmp_path / "big-list.json"
    f.write_text(json.dumps({"items": list(range(size))}))

    result = load(f, type=BigListPayload)
    assert len(result.items) == size
    assert result.items[0] == 0
    assert result.items[-1] == size - 1


def test_large_dict_payload(tmp_path):
    size = 20_000
    f = tmp_path / "big-dict.json"
    f.write_text(json.dumps({"items": {str(i): i for i in range(size)}}))

    result = load(f, type=BigDictPayload)
    assert len(result.items) == size
    assert result.items["0"] == 0
    assert result.items[str(size - 1)] == size - 1


def test_large_recursive_tagged_union(tmp_path):
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

    result = load(f, type=TaggedExpr)
    cursor = result
    steps = 0
    while hasattr(cursor, "right"):
        cursor = cursor.right
        steps += 1
    assert steps == depth
    assert cursor.value == 0
