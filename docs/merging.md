# Merge rules


For each key that appears in both the accumulated base and the incoming candidate:

1. **Field merge callable** — if the dataclass field declares `metadata={"merge": fn}`,
   `fn(base_value, override_value)` is called and its return value is used. This takes
   priority over all other rules, including dict recursion.
2. **Both values are dicts** — the dicts are merged recursively by the same rules,
   propagating the field's type so nested merge callables are respected.
3. **Everything else** — the override value replaces the base value entirely.
   This includes lists, sets, scalars, `None`, and type changes (e.g. dict → scalar).

Keys present only in the base are kept; keys present only in the override are added.

```python
import dataclasses
from minimal_magic import load_candidate

@dataclasses.dataclass
class AppConfig:
    host: str
    port: int
    # concatenate tags from all config files instead of replacing
    tags: list[str] = dataclasses.field(
        default_factory=list,
        metadata={"merge": lambda base, override: base + override},
    )
```

### Example: `extend-ignore`

A common config pattern is `ignore` (replace) paired with `extend-ignore` (append). The merge callable accumulates `extend-ignore` across candidates; `__post_init__` folds it into `ignore` at the end:

```python
import dataclasses
from minimal_magic import load_candidate

@dataclasses.dataclass
class LinterConfig:
    ignore: list[str] = dataclasses.field(default_factory=list)
    extend_ignore: list[str] = dataclasses.field(
        default_factory=list,
        metadata={"alias": "extend-ignore", "merge": lambda base, override: base + override},
    )

    def __post_init__(self):
        self.ignore = self.ignore + self.extend_ignore

config = load_candidate([
    "defaults.toml",          # extend-ignore = ["E001"]
    "pyproject.toml",         # extend-ignore = ["E501"]
    "local.toml",             # extend-ignore = ["W503"]
], type=LinterConfig)
# config.ignore == base_ignore + ["E001", "E501", "W503"]
```

Without the merge callable, `extend-ignore` would have last-wins semantics and only `["W503"]` would survive the merge phase.

### Notes on merge callables

**Merge is only called when a key appears in two or more candidates.** If a key
appears in only one candidate (or comes from a `default_factory`), the merge
callable is never invoked — the value is used as-is.

**Avoid `base or override` in merge callables.** If `base` is truthy and
`override` is falsy, `base or override` short-circuits and returns `base`,
silently ignoring the override. For example, `['x'] or []` returns `['x']`
even though the override explicitly set an empty list. Prefer explicit
operations: `base + override` for concatenation, `base | override` for sets and
dicts, or `base if base is not None else override` for null-coalescing.

**Merge callables receive and return raw values** (dicts, lists, scalars) as they
appear in the config files, before type conversion. A `list[LinterConfig]` field's
merge callable receives a list of dicts, not `LinterConfig` objects. If your
callable constructs a typed instance internally — even temporarily — be aware that
its `__post_init__` fires at that point, and then `_convert` constructs another
instance from the returned raw value, firing `__post_init__` a second time on a
different object.

**Exceptions raised inside a merge callable** are caught and re-raised as
`ParseError` pointing to the override value's location in the candidate file.
