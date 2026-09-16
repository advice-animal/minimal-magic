import collections.abc as cabc
import dataclasses
import datetime as dt
import decimal
import enum
import pathlib
import typing


class Color(enum.Enum):
    RED = "red"
    GREEN = "green"


class ServiceConfig(typing.TypedDict):
    host: str
    port: int


class PartialServiceConfig(typing.TypedDict, total=False):
    debug: bool
    retries: int


@dataclasses.dataclass
class DcConfig:
    host: str
    port: int


@dataclasses.dataclass
class DcNested:
    server: DcConfig


@dataclasses.dataclass
class TypeSampler:
    annotated: typing.Annotated[int, "meta"]
    any_val: typing.Any
    optional: int | None
    items: list[int]
    mapping: dict[str, int]
    score: float


@dataclasses.dataclass
class TupleHolder:
    fixed: tuple[int, str]
    variadic: tuple[int, ...]


@dataclasses.dataclass
class WithLevel:
    level: typing.Literal["debug", "info", "warn"]


@dataclasses.dataclass
class WithCircularValue:
    key: dict


@dataclasses.dataclass
class CompatConfig:
    color: Color
    root: pathlib.Path
    amount: decimal.Decimal
    day: dt.date
    moment: dt.datetime
    clock: dt.time
    names: cabc.Sequence[str]
    mapping: cabc.Mapping[str, int]
    labels: set[str]
    frozen: frozenset[int]


@dataclasses.dataclass
class TaggedLeaf:
    kind: typing.Literal["leaf"]
    value: int


@dataclasses.dataclass
class TaggedBranch:
    kind: typing.Literal["branch"]
    left: "TaggedExpr"
    right: "TaggedExpr"


TaggedExpr = TaggedLeaf | TaggedBranch
