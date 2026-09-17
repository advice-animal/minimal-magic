# minimal-magic

minimal-magic does two things:

1. **Type conversion.** It turns parsed JSON/YAML/TOML into typed Python — plain `dataclass`es and `TypedDict`s, checked field by field. This is `msgspec.convert()` without the C extension and without the `Struct` base class: point it at the types you already declared.
2. **File finding.** `load_candidate()` picks and merges the right config files out of a list of candidates — navigating into a section such as `[tool.myapp]` in a shared `pyproject.toml`, overriding left to right, and letting individual fields say how they merge.

It deliberately does not do a third thing. Error locations — the `filename:line:column` on every `ParseError` you see below — come from the [`parse-errors`](https://pypi.org/project/parse-errors/) package this is built on. If located exceptions are all you want, without typed conversion or file merging, use that package directly; minimal-magic consumes it rather than reimplementing it.

The cost of converting in Python is speed: tens of times slower than msgspec on flat bulk arrays, with lower overhead on config-shaped nested data. The overhead depends on the data shape and the alternate library; see [shapes and alternate libraries](https://github.com/advice-animal/minimal-magic/blob/main/docs/comparison.md) for the benchmark notes. For a config file read once at startup, that is a few milliseconds you will not notice.

## Install

```bash
pip install minimal-magic
```

YAML support needs PyYAML, an optional dependency: `pip install minimal-magic[yaml]`.

Requires Python 3.10+. Reads (or more accurately, converts) **JSON**, **YAML**, and **TOML**. Since TOML is a well-defined superset of INI, we do not plan to support `configparser` or other INI dialects.

## `load()`

Load a file without a type — returns plain `dict`/`list`, same as the underlying parser:

```python
from minimal_magic import load

config = load("config.json")
```

Load into a dataclass and get type-checked, located errors:

```python
import dataclasses
from minimal_magic import load

@dataclasses.dataclass
class ServerConfig:
    host: str
    port: int
    debug: bool = False

config = load("config.yaml", type=ServerConfig)
```

If `config.yaml` has a type mismatch, the error tells you exactly where:

```
config.yaml:3:7: Expected `int`, got `str`
```

Reject keys that don't exist on the type:

```python
config = load("config.toml", type=ServerConfig, forbid_unknown_fields=True)
# ParseError: config.toml:5:1: Unexpected field `typo` in `ServerConfig`
```

`load()` also accepts `data=` (pre-read bytes) and `format=` (override extension detection).

## `convert()`

If you already parsed the file yourself, `convert()` applies the same type
conversion and error-location logic that `load(..., type=...)` uses:

```python
from minimal_magic import convert

raw = {"host": "localhost", "port": 8080}
config = convert(
    raw,
    data=b'{"host": "localhost", "port": 8080}',
    format="json",
    filename="config.json",
    type=ServerConfig,
)
```

If you pass the original bytes as `data=`, `convert()` can build a source map
and report the exact line and column on validation errors. If you omit
`data=`, you still get the filename and JSON pointer path, just without exact
line/column locations. When `data=` is provided, `format=` is only needed if
the filename extension does not make the format detectable.

## `load_candidate()`

Loads and merges multiple config files. Each entry is either a plain path or a
`Candidate(filename, prefix=...)` that navigates to a sub-section before merging.
Files are processed left to right; later entries win.

```python
from minimal_magic import load_candidate, Candidate

config = load_candidate([
    "defaults.toml",
    Candidate("pyproject.toml", prefix="tool.myapp"),  # reads [tool.myapp]
    "local.toml",                                       # optional local overrides
], type=AppConfig)
```

If a candidate's prefix is absent in its file, that candidate contributes nothing — it is not an error. Every listed file is still read, though, so a candidate that does not exist on disk raises `FileNotFoundError`.

Errors name the candidate that actually supplied the bad value. The merge remembers where every key came from, so a value inherited from `defaults.toml` and never overridden is reported at its line in `defaults.toml`, not in whichever file happened to be read last:

```
defaults.toml:2:8: Expected `int`, got `str`
```

Two things have no single file to point at. A value built by a field's merge callable exists in none of the files, so it is blamed on the candidate whose value arrived as `override` — the bytes being validated. An error at a key no candidate supplied, such as a missing required field, falls back to the last candidate.

## More documentation

- [Merge rules](https://github.com/advice-animal/minimal-magic/blob/main/docs/merging.md): precedence, field merge callables, and `extend-ignore`-style config.
- [Supported types](https://github.com/advice-animal/minimal-magic/blob/main/docs/types.md): the conversion matrix and scalar rules.
- [API details](https://github.com/advice-animal/minimal-magic/blob/main/docs/api.md): aliases, error handling, and CLI validation.
- [Shapes and alternate libraries](https://github.com/advice-animal/minimal-magic/blob/main/docs/comparison.md): benchmark notes and tradeoffs against msgspec and pydantic.
