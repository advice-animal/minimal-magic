# Supported types


| Category | Types |
|---|---|
| Structured | `dataclass`, `TypedDict` |
| Collections | `list`, `tuple`, `dict`, `set`, `frozenset`, `Sequence`, `Mapping`, `AbstractSet` |
| Unions | `Optional[T]`, `Union[A, B]`, `A \| B`, tagged unions (discriminator auto-detected) |
| Scalars | `str`, `int`, `float`, `bool`, `Literal[...]`, `Enum` |
| Rich scalars | `Path`, `Decimal`, `date`, `datetime`, `time` |
| Unchecked | `Any` (passed through), `Annotated[T, ...]`, `Required[T]`, `NotRequired[T]` (unwrapped, then `T` is checked) |

`bool` is rejected for `int` fields. Bare `int` is coerced to `float` when a `float` field is expected.

A collection type used bare, with no type argument (`dict` rather than `dict[str, int]`), is checked no more than `Any` is: only that the value is a `dict`. Parameterize it if you want its contents checked too.
