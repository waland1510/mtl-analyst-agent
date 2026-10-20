"""The access boundary. Resolved by the caller, never by the model; applied inside the SQL AST, never by prompt."""

from __future__ import annotations

import re
from dataclasses import dataclass

_BOROUGH = re.compile(r"^[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9 \-—–]{0,80}$")


class ScopeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Scope:
    """None borough is the city-wide analyst; a named borough sees only trips starting there."""

    borough: str | None = None

    def __post_init__(self) -> None:
        if self.borough is None:
            return
        if not self.borough.strip() or not _BOROUGH.match(self.borough):
            raise ScopeError("Scope borough is not a valid name; refusing to build an open filter.")

    @property
    def label(self) -> str:
        return self.borough or "city"
