import subprocess
import sys
from pathlib import Path

import pytest

from minimal_magic.__main__ import _resolve_type, _validate, build_parser, main

REPO_ROOT = Path(__file__).parent.parent


def run_cli(*args, cwd=REPO_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "minimal_magic", "validate", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_cli_validate_success(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"host": "localhost", "port": 8080}')
    result = run_cli(str(f), "--type", "tests._types:DcConfig")
    assert result.returncode == 0
    assert result.stdout.strip() == f"{f}: OK"
    assert result.stderr == ""


def test_cli_validate_type_mismatch(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"host": "localhost", "port": "not-an-int"}')
    result = run_cli(str(f), "--type", "tests._types:DcConfig")
    assert result.returncode == 1
    assert result.stdout == ""
    assert f"{f}:1:31" in result.stderr
    assert "Expected `int`, got `str`" in result.stderr


def test_cli_validate_bad_type_spec(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"host": "localhost", "port": 8080}')
    result = run_cli(str(f), "--type", "tests._types:NoSuchType")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "NoSuchType" in result.stderr


# The subprocess tests above check the wiring end to end but run in another
# interpreter, so the branches below are exercised in-process instead.


def parse(*args):
    return build_parser().parse_args(["validate", *args])


def test_resolve_type_dotted_attr():
    assert _resolve_type("tests._types:DcConfig").__name__ == "DcConfig"
    assert _resolve_type("collections:OrderedDict.fromkeys") is not None


def test_resolve_type_requires_colon():
    with pytest.raises(ValueError, match="MODULE:ATTR"):
        _resolve_type("tests._types.DcConfig")


def test_validate_reports_unimportable_module(tmp_path, capsys):
    f = tmp_path / "config.json"
    f.write_bytes(b"{}")
    assert _validate(parse(str(f), "--type", "no_such_module:Thing")) == 1
    err = capsys.readouterr().err
    assert "Cannot resolve --type" in err
    assert "no_such_module" in err


def test_validate_reports_missing_attribute(tmp_path, capsys):
    f = tmp_path / "config.json"
    f.write_bytes(b"{}")
    assert _validate(parse(str(f), "--type", "tests._types:Nope")) == 1
    assert "Nope" in capsys.readouterr().err


def test_validate_honours_format_override(tmp_path, capsys):
    # .ini is not a detectable extension; --format is what makes this parse.
    f = tmp_path / "config.ini"
    f.write_bytes(b'{"host": "h", "port": 1}')
    assert _validate(parse(str(f), "--type", "tests._types:DcConfig", "--format", "json")) == 0
    assert capsys.readouterr().out.strip() == f"{f}: OK"


def test_validate_honours_forbid_unknown_fields(tmp_path, capsys):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"host": "h", "port": 1, "extra": 2}')
    assert _validate(parse(str(f), "--type", "tests._types:DcConfig")) == 0
    capsys.readouterr()
    args = parse(str(f), "--type", "tests._types:DcConfig", "--forbid-unknown-fields")
    assert _validate(args) == 1
    assert "Unexpected field `extra`" in capsys.readouterr().err


def test_validate_reports_syntax_error(tmp_path, capsys):
    f = tmp_path / "config.json"
    f.write_bytes(b"{not json")
    assert _validate(parse(str(f), "--type", "tests._types:DcConfig")) == 1
    assert f"{f}:1:2" in capsys.readouterr().err


def test_main_exits_with_validate_status(tmp_path):
    f = tmp_path / "config.json"
    f.write_bytes(b'{"host": "h", "port": 1}')
    with pytest.raises(SystemExit) as exc_info:
        main(["validate", str(f), "--type", "tests._types:DcConfig"])
    assert exc_info.value.code == 0


def test_main_requires_a_subcommand():
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2
