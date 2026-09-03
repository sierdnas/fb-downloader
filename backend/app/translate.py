"""
Best-effort description translation into the UI's interface language.

Uses Google Translate's free web endpoint via the "deep-translator"
library — NO API key required, but also no guarantee: it's an
unofficial, scraping-based endpoint that can be rate-limited, blocked,
or changed by Google at any time without notice, and it requires the
container to have outbound internet access. Every call is wrapped so a
failure NEVER blocks analysis — it just falls back to the original,
untranslated text.
"""
from . import log_buffer

try:
    from deep_translator import GoogleTranslator
    _TRANSLATOR_AVAILABLE = True
except ImportError:  # noqa: BLE001 - the dependency might be missing in some environments
    _TRANSLATOR_AVAILABLE = False

# Language codes Google Translate doesn't recognize in the exact form
# our own UI language list uses.
_LANG_CODE_OVERRIDES = {
    "zh-CN": "zh-CN",
    "zh-TW": "zh-TW",
}


def translate_text(text: str, target_lang: str) -> str:
    """Translates text into target_lang. On ANY failure (no internet,
    endpoint blocked/changed, unsupported language, empty text...),
    returns the ORIGINAL text unchanged — translation is a best-effort
    nice-to-have, never a reason to lose or block a description."""
    if not text or not text.strip():
        return text
    if not _TRANSLATOR_AVAILABLE:
        log_buffer.log(0, "Translation requested but the 'deep-translator' package isn't installed")
        return text

    lang_code = _LANG_CODE_OVERRIDES.get(target_lang, target_lang)

    try:
        translated = GoogleTranslator(source="auto", target=lang_code).translate(text)
        if translated and translated.strip():
            log_buffer.log(2, f"Description translated to '{lang_code}' ({len(text)} -> {len(translated)} chars)")
            return translated
    except Exception as exc:  # noqa: BLE001 - translation is best-effort, never fatal
        log_buffer.log(0, f"Translation to '{lang_code}' failed, keeping original text: {exc}")

    return text
