# Shapes and alternate libraries

msgspec decodes millions of records a second because its converter is a C extension driven by its own `Struct` types. pydantic validates through pydantic-core, a Rust extension, and does much more than type conversion — coercion policy, computed fields, JSON schema generation. minimal-magic does one thing, in Python, against the `dataclass` and `TypedDict` types you already declared, and spends the time it saves on ergonomics.

| | minimal-magic | msgspec | pydantic |
|---|---|---|---|
| Target types | plain `dataclass`, `TypedDict` | `msgspec.Struct` | `BaseModel` |
| 20k-item convert, converts/sec | ~150 | ~5,000 | ~2,700 |
| Library size | ~1k lines pure Python | 2,400 lines Python + C extension | Python + Rust extension (pydantic-core) |
| Syntax errors | filename, line, column | n/a | n/a |
| Type errors | filename, line, column | field path only | field path only |
| Field aliases | `alias("kebab-case")` | `rename=` on the Struct | `Field(alias=...)` |
| Tagged unions | discriminator auto-detected | declared per Struct | declared via `discriminator=` |
| Config cascade | `load_candidate()` with per-field merge | n/a | n/a |

msgspec's "field path only" errors are still wrappable by `parse-errors`' `ParseContext` today, because msgspec happens to embed a JSONPath string in its message (`"... - at \`$.port\`"`) that `parse-errors` pattern-matches. pydantic's `ValidationError` carries the same kind of structured path — `exc.errors()` gives a `loc` tuple — but not embedded in the message text, so `ParseContext` can't extract it yet; that would need its own extraction branch in `parse-errors`, the same way JSON's and YAML's `lineno`/`colno` got one.

All three convert the same already-parsed Python dict — `{"items": [0, 1, ..., 19999]}` — into a typed structure holding a `list[int]`: `minimal_magic.convert()`, `msgspec.convert()`, and `BaseModel.model_validate()`. No file I/O or text parsing in any of the three; that step is common to all of them and isn't what this table measures. Median of 11 runs after 2 warmup calls. Re-measure before quoting these; they move with the interpreter.

The ratio moves with the data's shape, not just the interpreter: a flat homogeneous array is minimal-magic's worst case — it's the same compiled converter called 20,000 times with no branching, and msgspec's/pydantic's native code has nothing else to do either. A deeply nested, heterogeneous config (many small `dataclass`/`Struct`/`BaseModel` types, `Optional` fields, `dict[str, str]` maps) narrows the gap to roughly 8x vs. msgspec and 1.5x vs. pydantic, because msgspec's and pydantic's per-object construction cost stops being negligible too.

None of the above hits a source map: it's the cost of a value that converts cleanly. A value that doesn't pays for one. `test_benchmark_large_list_load_validation_failure` / `test_benchmark_nested_envoy_config_load_validation_failure` measure exactly that against their clean-load counterparts. minimal-magic asks parse-errors' `locate_pointer()` for the one pointer that failed instead of mapping the whole document. `_FixedSource` stays lazy: nothing built on the common path, and only the failed pointer is located when something actually fails.

That failure path is doing extra work on purpose: it turns "some nested value had the wrong type" into a filename, line, and column a person can fix. On current local runs with parse-errors 0.6.0, that richer error costs on the order of tens of milliseconds, not a whole-document source-map walk. Run the benchmark tests before quoting exact timings; they depend on the parser, Python, CPU, and where the bad value sits.

See `tests/test_benchmark_loader.py` (flat) and `tests/test_benchmark_nested_loader.py` (deeply nested, Envoy-config-shaped) for the actual benchmarks this repo tracks, success and failure paths both.

Use msgspec or pydantic when throughput or heavier validation is the point. Use minimal-magic when the data is a config file, the types are already dataclasses, and the person who has to fix a bad value is a human reading the error message.
