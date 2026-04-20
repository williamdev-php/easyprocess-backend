"""
Email translation loader.

Loads JSON translation files once and caches them for the process lifetime.
To add a new language, create a new JSON file in the translations/ directory
(e.g. translations/de.json) and add the locale to SUPPORTED_LOCALES.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

TRANSLATIONS_DIR = Path(__file__).parent / "translations"
DEFAULT_LOCALE = "sv"
FALLBACK_LOCALE = "en"
SUPPORTED_LOCALES = {"sv", "en"}


@lru_cache(maxsize=None)
def _load(locale: str) -> dict:
    path = TRANSLATIONS_DIR / f"{locale}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def t(key: str, locale: str = DEFAULT_LOCALE, **kwargs: object) -> str:
    """
    Look up a translated string by dotted key.

    Examples:
        t("password_reset.subject", "en")
        t("common.greeting", "sv", name="Anna")
    """
    if locale not in SUPPORTED_LOCALES:
        locale = FALLBACK_LOCALE

    data = _load(locale)
    value: dict | str = data
    for part in key.split("."):
        value = value[part]  # type: ignore[index]

    if kwargs and isinstance(value, str):
        return value.format(**kwargs)
    return value  # type: ignore[return-value]
