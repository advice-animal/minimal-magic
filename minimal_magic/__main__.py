"""``python -m minimal_magic`` — validate a config file against a type from the command line."""

import argparse
import importlib
import sys

from . import load, ParseError


def _resolve_type(spec: str) -> type:
    if ":" not in spec:
        raise ValueError(f"--type must look like MODULE:ATTR, got {spec!r}")
    module_name, _, attr_path = spec.partition(":")
    module = importlib.import_module(module_name)
    obj = module
    for part in attr_path.split("."):
        obj = getattr(obj, part)
    return obj


def _validate(args: argparse.Namespace) -> int:
    try:
        target_type = _resolve_type(args.type)
    except Exception as exc:
        print(f"Cannot resolve --type {args.type!r}: {exc}", file=sys.stderr)
        return 1

    try:
        load(
            args.file,
            type=target_type,
            format=args.format,
            forbid_unknown_fields=args.forbid_unknown_fields,
        )
    except ParseError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"{args.file}: OK")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="minimal-magic")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate a config file against a type")
    validate.add_argument("file", help="path to the config file")
    validate.add_argument(
        "--type",
        required=True,
        help="MODULE:ATTR of the type to validate against, e.g. mypkg.config:AppConfig",
    )
    validate.add_argument("--format", choices=["json", "yaml", "toml"], default=None)
    validate.add_argument("--forbid-unknown-fields", action="store_true")
    validate.set_defaults(func=_validate)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
