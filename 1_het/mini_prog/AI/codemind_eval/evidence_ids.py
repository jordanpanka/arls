import re

from app.services.evidence_service import normalize_path, short_symbol_name

ANY_PATH = "*"


def norm_path(path: str | None) -> str:
    return normalize_path(path).lower()


def norm_symbol(symbol: str | None) -> str:
    name = (symbol or "").split("(", 1)[0].strip()
    name = re.sub(r"<.*?>", "", name)
    return short_symbol_name(name).lower()


def file_id(path: str | None) -> str:
    return f"file:{norm_path(path)}"


def symbol_id(path: str | None, symbol: str | None) -> str:
    return f"symbol:{norm_path(path) or ANY_PATH}::{norm_symbol(symbol)}"


def path_matches(expected: str | None, actual: str | None) -> bool:
    expected_n = norm_path(expected)
    actual_n = norm_path(actual)
    if not expected_n or not actual_n:
        return False
    return actual_n == expected_n or actual_n.endswith("/" + expected_n) or expected_n.endswith("/" + actual_n)


def symbol_matches(expected_path: str | None, expected_symbol: str, actual_path: str | None, actual_symbol: str | None) -> bool:
    if not actual_symbol or norm_symbol(expected_symbol) != norm_symbol(actual_symbol):
        return False
    return not norm_path(expected_path) or path_matches(expected_path, actual_path)


def file_units(items: list[dict]) -> list[str]:
    units: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        path = norm_path(item.get("path"))
        if path and path not in seen:
            seen.add(path)
            units.append(path)
    return units


def symbol_units(items: list[dict]) -> list[tuple[str, str]]:
    units: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items or []:
        name = norm_symbol(item.get("symbol"))
        if not name:
            continue
        key = (norm_path(item.get("path")), name)
        if key not in seen:
            seen.add(key)
            units.append(key)
    return units
