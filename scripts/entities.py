"""Table-driven entity resolution for DGCA source labels.

DGCA source files label airports and airlines inconsistently, and a label's
meaning can change over time. The canonical example: the domestic label ``GOA``
means Dabolim (``GOI``) through 2018 (the only Goa airport then) and Mopa
(``GOX``) from 2023, after Mopa airport opened on 2023-01-05. A flat alias would
therefore be wrong by construction, so each source label may carry a validity
window (``valid_from`` / ``valid_to``, ``"YYYY-MM"``) in ``mappings.yaml``.

Resolution is table-driven, never fuzzy. The resolver is built once from the
reviewed tables; if any source label maps to two different canonical entities
with *overlapping* validity windows, that is an unresolved ambiguity and building
the resolver raises :class:`EntityConflictError` rather than guessing.

    GOI:                                    # Dabolim
      variants:
        - {label: GOA, valid_to: "2018-12"}
        - {label: DABOLIM, valid_from: "2019-01"}
        - {label: GOA DABOLIM SOUTH GOA}
    GOX:                                    # Mopa, opened 2023-01
      variants:
        - {label: GOA, valid_from: "2023-01"}
        - {label: MOPA GOA, valid_from: "2023-01"}
        - {label: GOA MOPA NORTH GOA}

    r = build_airport_resolver(mappings)
    r.resolve("GOA", 2017, 6)    -> "GOI"   # Dabolim era
    r.resolve("GOA", 2024, 6)    -> "GOX"   # Mopa era
    r.resolve("DABOLIM", 2021, 1)-> "GOI"
    r.resolve("WAKANDA", 2024, 1)-> None    # unmapped; caller keeps the raw label

Airlines use the same machinery via ``build_airline_resolver`` against an
``airlines:`` table, but airline brand/legal mergers are deliberately *not*
collapsed here (see ``succeeded_by`` handling in clean.py): a merged brand keeps
its own canonical entity so its standalone series survives.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


class EntityConflictError(ValueError):
    """A source label maps to two canonical entities with overlapping windows."""


def _norm(label) -> str:
    """Canonical comparison form for a source label: upper, single-spaced."""
    return " ".join(str(label).strip().upper().split())


def _month_index(year: int, month: int) -> int:
    """A total order over (year, month). January 2020 -> 24240."""
    return year * 12 + (month - 1)


def _parse_ym(value) -> int | None:
    """Parse a ``"YYYY-MM"`` bound into a month index, or None for an open bound."""
    if value is None:
        return None
    year, month = str(value).strip().split("-")
    return _month_index(int(year), int(month))


@dataclass(frozen=True)
class _Window:
    canonical: str
    lo: int | None  # inclusive lower month index, None = open
    hi: int | None  # inclusive upper month index, None = open
    source_label: str

    def contains(self, idx: int) -> bool:
        return (self.lo is None or idx >= self.lo) and (self.hi is None or idx <= self.hi)


def _overlaps(a: _Window, b: _Window) -> bool:
    a_lo = float("-inf") if a.lo is None else a.lo
    a_hi = float("inf") if a.hi is None else a.hi
    b_lo = float("-inf") if b.lo is None else b.lo
    b_hi = float("inf") if b.hi is None else b.hi
    return a_lo <= b_hi and b_lo <= a_hi


class EntityResolver:
    """Resolve a (source label, year, month) to a canonical entity key."""

    def __init__(self, index: dict[str, list[_Window]]):
        self._index = index

    def resolve(self, label, year: int, month: int) -> str | None:
        windows = self._index.get(_norm(label))
        if not windows:
            return None
        idx = _month_index(year, month)
        for window in windows:
            if window.contains(idx):
                return window.canonical
        return None

    def source_labels(self, canonical: str) -> list[str]:
        """Every source label that maps to ``canonical`` (for reporting/tests)."""
        return sorted(
            {w.source_label for windows in self._index.values() for w in windows if w.canonical == canonical}
        )

    @property
    def labels(self) -> set[str]:
        return set(self._index)


def _build(table: dict, *, implicit_keys=("city", "name"), extra_aliases=None) -> EntityResolver:
    index: dict[str, list[_Window]] = defaultdict(list)

    for canonical, info in (table or {}).items():
        if not isinstance(info, dict):
            continue
        variants = info.get("variants")
        if variants:
            for variant in variants:
                if isinstance(variant, str):
                    label, lo, hi = variant, None, None
                else:
                    label = variant["label"]
                    lo = _parse_ym(variant.get("valid_from"))
                    hi = _parse_ym(variant.get("valid_to"))
                index[_norm(label)].append(_Window(canonical, lo, hi, label))
        else:
            # No explicit variants: fall back to city/name as all-time labels.
            for key in implicit_keys:
                value = info.get(key)
                if value:
                    index[_norm(value)].append(_Window(canonical, None, None, value))

    for label, canonical in (extra_aliases or {}).items():
        index[_norm(label)].append(_Window(canonical, None, None, label))

    _assert_no_conflicts(index)
    return EntityResolver(dict(index))


def _assert_no_conflicts(index: dict[str, list[_Window]]) -> None:
    conflicts = []
    for label, windows in index.items():
        for i in range(len(windows)):
            for j in range(i + 1, len(windows)):
                a, b = windows[i], windows[j]
                if a.canonical != b.canonical and _overlaps(a, b):
                    conflicts.append(f"{label!r} -> {a.canonical} & {b.canonical} (overlapping windows)")
    if conflicts:
        raise EntityConflictError("; ".join(conflicts))


def build_airport_resolver(mappings: dict, *, extra_aliases=None) -> EntityResolver:
    """Resolver for airport source labels, from the ``airports:`` table."""
    return _build(mappings.get("airports", {}), implicit_keys=("city", "name"), extra_aliases=extra_aliases)


def build_airline_resolver(mappings: dict) -> EntityResolver:
    """Resolver for airline source labels, from the ``airlines:`` table.

    Note: this only canonicalizes spelling/label variants. Brand/legal mergers
    are kept as distinct entities (linked via ``succeeded_by`` in the table and
    handled in clean.py), so an analyst can still see each airline's own series.
    """
    return _build(mappings.get("airlines", {}), implicit_keys=("name",))
