"""minimal_magic — msgspec-style typed conversion for plain dataclasses and TypedDicts."""

from parse_errors import ParseError

from .api import alias, Candidate, convert, load, load_candidate

__all__ = ["ParseError", "convert", "load", "load_candidate", "alias", "Candidate"]
