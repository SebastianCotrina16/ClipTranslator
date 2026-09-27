from __future__ import annotations

import re

_LANGUAGE_CODE = re.compile(r"^[a-z]{2,3}$")

ENGLISH_NAMES = {
    "en": "English",
    "es": "Latin American Spanish",
    "pt": "Portuguese",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ru": "Russian",
    "pl": "Polish",
    "tr": "Turkish",
    "nl": "Dutch",
    "ar": "Arabic",
    "uk": "Ukrainian",
    "sv": "Swedish",
    "cs": "Czech",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "th": "Thai",
    "hu": "Hungarian",
    "ro": "Romanian",
    "el": "Greek",
    "fi": "Finnish",
    "da": "Danish",
    "no": "Norwegian",
    "he": "Hebrew",
    "hi": "Hindi",
    "tl": "Tagalog",
    "ca": "Catalan",
}

TARGET_LANGUAGES = {"es": "Español", "en": "English", "pt": "Português", "fr": "Français"}


class InvalidLanguageCodeError(ValueError):
    pass


def parse_language_code(value: str) -> str:
    code = value.strip().lower()
    if not _LANGUAGE_CODE.match(code):
        raise InvalidLanguageCodeError(f"Invalid language code: {value!r} (e.g. es, en, pt).")
    return code


def english_name(code: str) -> str:
    return ENGLISH_NAMES.get(code, code)
