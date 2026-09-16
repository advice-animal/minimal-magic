# API details

## `alias()`

Maps a config file key name to a Python attribute name. Useful for kebab-case TOML keys:

```python
import dataclasses
from minimal_magic import load, alias

@dataclasses.dataclass
class RetryConfig:
    retry_count: int = alias("retry-count", default=3)
    connect_timeout: float = alias("connect-timeout", default=5.0)

config = load("config.toml", type=RetryConfig)
# reads "retry-count" and "connect-timeout" from the file,
# exposes them as config.retry_count and config.connect_timeout
```

`alias()` is a thin wrapper around `dataclasses.field(metadata={"alias": ...})` and accepts all the same keyword arguments.

## Error handling

```python
from minimal_magic import load, ParseError

try:
    config = load("config.yaml", type=ServerConfig)
except ParseError as exc:
    print(exc)           # "config.yaml:3:7: Expected `int`, got `str`"
    print(exc.filename)  # "config.yaml" — always a str, never a Path
    print(exc.line)      # 3
    print(exc.column)    # 7
```

`ParseError` is re-exported from the `parse-errors` package (pinned to `>= 0.5.0, < 1.0`) so
catching it doesn't need a second import. `ParseContext` and the source-map types
(`Location`, `Entry`, `TSourceMap`) are `parse-errors`' own manual location-extraction
building blocks — nothing here calls them, so import them from `parse_errors` directly
if you need them.

## CLI

Validate a config file against a type without writing a wrapper script — handy in pre-commit or CI:

```bash
python -m minimal_magic validate config.toml --type mypkg.config:AppConfig
# or, after install: minimal-magic validate config.toml --type mypkg.config:AppConfig
```

`--type` is `MODULE:ATTR` (dotted `ATTR` paths like `Outer.Inner` work too); `--format` and `--forbid-unknown-fields` are also accepted. Exits 0 and prints `<file>: OK` on success; exits 1 with the located error on stderr on failure.
