import dataclasses
import typing

import pytest

from minimal_magic import load, ParseError

from ._types import TaggedBranch, TaggedExpr, TaggedLeaf


def test_load_recursive_tagged_union(tmp_path):
    f = tmp_path / "expr.json"
    f.write_text(
        '{"kind":"branch","left":{"kind":"leaf","value":1},"right":{"kind":"branch","left":{"kind":"leaf","value":2},"right":{"kind":"leaf","value":3}}}'
    )

    result = load(f, type=TaggedExpr)
    assert isinstance(result, TaggedBranch)
    assert isinstance(result.left, TaggedLeaf)
    assert isinstance(result.right, TaggedBranch)
    assert result.left.value == 1
    assert result.right.left.value == 2
    assert result.right.right.value == 3


def test_load_tagged_union_missing_discriminator(tmp_path):
    f = tmp_path / "expr.json"
    f.write_text('{"value": 1}')

    with pytest.raises(ParseError, match="Missing discriminator field `kind`"):
        load(f, type=TaggedExpr)


def test_load_tagged_union_unknown_discriminator(tmp_path):
    f = tmp_path / "expr.json"
    f.write_text('{"kind": "oops", "value": 1}')

    with pytest.raises(ParseError, match="Unknown discriminator value"):
        load(f, type=TaggedExpr)


def test_load_tagged_union_rejects_non_mapping(tmp_path):
    f = tmp_path / "expr.json"
    f.write_text("[1, 2]")

    with pytest.raises(ParseError, match="got `list`"):
        load(f, type=TaggedExpr)


def test_tagged_union_dispatch_uses_typed_dicts(tmp_path):
    class TdLeaf(typing.TypedDict):
        kind: typing.Literal["leaf"]
        value: int

    class TdBranch(typing.TypedDict):
        kind: typing.Literal["branch"]
        size: int

    f = tmp_path / "expr.json"
    f.write_text('{"kind": "branch", "size": 3}')
    assert load(f, type=TdLeaf | TdBranch) == {"kind": "branch", "size": 3}


def test_tag_field_priority_prefers_kind_over_alphabetical(tmp_path):
    # Both `colour` and `kind` are single-valued Literals unique per branch.
    # `kind` outranks an alphabetically earlier name, so a row whose `colour`
    # is wrong but whose `kind` is right must still dispatch.
    @dataclasses.dataclass
    class Cat:
        colour: typing.Literal["black"]
        kind: typing.Literal["cat"]

    @dataclasses.dataclass
    class Dog:
        colour: typing.Literal["brown"]
        kind: typing.Literal["dog"]

    f = tmp_path / "pet.json"
    f.write_text('{"colour": "black", "kind": "dog"}')
    with pytest.raises(ParseError, match="Expected one of \\['brown'\\], got 'black'"):
        load(f, type=Cat | Dog)


def test_tag_field_falls_back_to_alphabetical(tmp_path):
    @dataclasses.dataclass
    class Alpha:
        flavour: typing.Literal["sweet"]
        n: int

    @dataclasses.dataclass
    class Beta:
        flavour: typing.Literal["sour"]
        n: int

    f = tmp_path / "x.json"
    f.write_text('{"flavour": "sour", "n": 2}')
    assert load(f, type=Alpha | Beta) == Beta(flavour="sour", n=2)


# When auto-detection declines, conversion falls back to trying each branch in
# order. These unions must still convert correctly — just not via the fast path.


@dataclasses.dataclass
class _NoLiteral:
    a: int


@dataclasses.dataclass
class _AlsoNoLiteral:
    b: int


@dataclasses.dataclass
class _MultiValueTag:
    kind: typing.Literal["x", "y"]
    a: int


@dataclasses.dataclass
class _OtherMultiValueTag:
    kind: typing.Literal["p", "q"]
    b: int


@dataclasses.dataclass
class _DupTagA:
    kind: typing.Literal["same"]
    a: int


@dataclasses.dataclass
class _DupTagB:
    kind: typing.Literal["same"]
    b: int


@dataclasses.dataclass
class _TagOnLeft:
    kind: typing.Literal["left"]
    a: int


@dataclasses.dataclass
class _DifferentTagName:
    flavour: typing.Literal["right"]
    b: int


@pytest.mark.parametrize(
    "union, raw, expected",
    [
        # No Literal field on either branch.
        (_NoLiteral | _AlsoNoLiteral, '{"b": 1}', _AlsoNoLiteral(b=1)),
        # Literal with more than one allowed value cannot be a discriminator.
        (_MultiValueTag | _OtherMultiValueTag, '{"kind": "q", "b": 1}', _OtherMultiValueTag(kind="q", b=1)),
        # Two branches claiming the same tag value.
        (_DupTagA | _DupTagB, '{"kind": "same", "b": 1}', _DupTagB(kind="same", b=1)),
        # No Literal field common to both branches.
        (_TagOnLeft | _DifferentTagName, '{"flavour": "right", "b": 1}', _DifferentTagName(flavour="right", b=1)),
        # A branch that is neither a dataclass nor a TypedDict.
        (_NoLiteral | int, "7", 7),
    ],
)
def test_union_without_usable_discriminator_falls_back(tmp_path, union, raw, expected):
    f = tmp_path / "x.json"
    f.write_text(raw)
    assert load(f, type=union) == expected
