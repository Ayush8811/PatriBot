"""Readable train names from RailKit's abbreviated upper-case names (e.g. "RAJDHANI EXPRES" -> "Rajdhani Express").

Station codes inside names ("KOAA JAT EXPRES", "HWH BKN EXPRESS") stay upper case. The raw name is kept in the
warehouse; this only shapes what the API returns.
"""

from __future__ import annotations

import re

ABBREVIATIONS = {
    "EXP": "Express",
    "EXPRES": "Express",
    "EXPRESS": "Express",
    "EXPRESSS": "Express",
    "SPL": "Special",
    "RAJ": "Rajdhani",
    "RAJDHNI": "Rajdhani",
    "RJDHNI": "Rajdhani",
    "SHTBDI": "Shatabdi",
    "SHATBDI": "Shatabdi",
    "DRNTO": "Duronto",
    "HMSFR": "Humsafar",
    "JN": "Jn",
}
KEEP_UPPER = {"SF", "AC", "II", "III", "VB", "MEMU", "DEMU", "EMU"}


def display_train_name(raw: str | None, station_codes: set[str] | frozenset[str] = frozenset()) -> str:
    if not raw:
        return ""
    if raw != raw.upper():  # already mixed case: leave it alone
        return raw.strip()
    words = []
    for token in re.split(r"\s+", raw.strip()):
        if token in ABBREVIATIONS:
            words.append(ABBREVIATIONS[token])
        elif token in KEEP_UPPER or (token in station_codes and len(token) <= 5) or any(ch.isdigit() for ch in token):
            words.append(token)
        else:
            words.append("-".join(part.capitalize() for part in token.split("-")))
    return " ".join(words)
