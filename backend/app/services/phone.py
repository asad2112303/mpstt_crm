"""Phone normalization for Pakistani numbers.

The source value is always retained; the normalized form feeds indexes and
duplicate detection. Examples:
    0301-2345678   -> +923012345678
    92 301 2345678 -> +923012345678
    (051) 111 222  -> +9251111222
"""
import re


def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("92"):
        return f"+{digits}"
    if digits.startswith("0"):
        return f"+92{digits[1:]}"
    return f"+92{digits}"
