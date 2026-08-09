"""Devanagari/ASCII digit folding.

Maharashtra GRs are written with Devanagari numerals (५० टक्के, दि.०७.१०.२०१७).
The archived-PDF corpus extracted them as ASCII because the legacy fonts' broken
ToUnicode maps happened to preserve digit code points; the clean mahGRs text
keeps them in Devanagari — 97.5% of all digit runs.

Every comparison in this project that treats digits as *values* (citation
matching, digit audits, pair mining) must therefore fold the script first.
Comparisons that treat digits as *rendering* (gr_layout) must not.
"""

DEV_DIGITS = "०१२३४५६७८९"
_TO_ASCII = str.maketrans(DEV_DIGITS, "0123456789")
_TO_DEV = str.maketrans("0123456789", DEV_DIGITS)


def to_ascii_digits(s: str) -> str:
    """Fold Devanagari numerals to ASCII, leaving everything else alone."""
    return s.translate(_TO_ASCII) if s else s


def to_dev_digits(s: str) -> str:
    """Fold ASCII numerals to Devanagari (idempotent — unmapped chars pass through)."""
    return s.translate(_TO_DEV) if s else s


def has_dev_digit(s: str) -> bool:
    return any(c in DEV_DIGITS for c in (s or ""))
