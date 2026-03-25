"""
po_helper.py — PO file parsing, comparison, checkpoint, and merge utilities.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
import polib


def _dominant_script(text: str) -> str:
    """
    Return the dominant Unicode script family of *text*, ignoring whitespace,
    digits, and punctuation.

    Recognised families (returned as strings):
        'cjk'         — CJK unified ideographs + Japanese kana
        'hangul'      — Korean Hangul syllables
        'arabic'      — Arabic / Persian / Urdu
        'cyrillic'    — Cyrillic (Russian, Ukrainian, Bulgarian, …)
        'devanagari'  — Hindi, Marathi, Nepali, …
        'thai'        — Thai
        'hebrew'      — Hebrew
        'greek'       — Greek
        'latin'       — Latin-based scripts (English, French, Spanish, …)
        'other'       — Unclassified or mixed / no alphabetic content
    """
    tally: dict[str, int] = {}
    for ch in text:
        if not ch.isalpha():
            continue  # skip punctuation, whitespace, digits
        cp = ord(ch)
        if 0x3040 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF:
            s = "cjk"
        elif 0xAC00 <= cp <= 0xD7FF:
            s = "hangul"
        elif 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F:
            s = "arabic"
        elif 0x0400 <= cp <= 0x04FF:
            s = "cyrillic"
        elif 0x0900 <= cp <= 0x097F:
            s = "devanagari"
        elif 0x0E00 <= cp <= 0x0E7F:
            s = "thai"
        elif 0x0590 <= cp <= 0x05FF:
            s = "hebrew"
        elif 0x0370 <= cp <= 0x03FF:
            s = "greek"
        elif 0x0041 <= cp <= 0x007A or 0x00C0 <= cp <= 0x024F:
            s = "latin"
        else:
            s = "other"
        tally[s] = tally.get(s, 0) + 1
    if not tally:
        return "other"
    return max(tally, key=tally.get)


# Human-readable display names for BCP-47 language codes used in LLM prompts.
# Keys are lowercase. Codes not listed fall back to the code itself.
LANG_DISPLAY_NAMES: dict[str, str] = {
    "en":      "English",
    "en-us":   "English",
    "en-gb":   "English (British)",
    "en-au":   "English (Australian)",
    "en-ca":   "English (Canadian)",
    "ja":      "Japanese",
    "ko":      "Korean",
    "zh":      "Chinese",
    "zh-hans": "Chinese Simplified",
    "zh-hant": "Chinese Traditional",
    "zh-cn":   "Chinese Simplified",
    "zh-tw":   "Chinese Traditional",
    "zh-hk":   "Chinese (Hong Kong)",
    "fr":      "French",
    "fr-fr":   "French",
    "fr-ca":   "French (Canadian)",
    "de":      "German",
    "de-de":   "German",
    "es":      "Spanish",
    "es-es":   "Spanish",
    "es-mx":   "Spanish (Mexican)",
    "it":      "Italian",
    "it-it":   "Italian",
    "pt":      "Portuguese",
    "pt-br":   "Portuguese (Brazilian)",
    "pt-pt":   "Portuguese",
    "nl":      "Dutch",
    "sv":      "Swedish",
    "no":      "Norwegian",
    "da":      "Danish",
    "fi":      "Finnish",
    "pl":      "Polish",
    "cs":      "Czech",
    "sk":      "Slovak",
    "hu":      "Hungarian",
    "ro":      "Romanian",
    "ru":      "Russian",
    "uk":      "Ukrainian",
    "tr":      "Turkish",
    "ar":      "Arabic",
    "he":      "Hebrew",
    "th":      "Thai",
    "vi":      "Vietnamese",
    "id":      "Indonesian",
    "ms":      "Malay",
    "hi":      "Hindi",
}


def lang_display_name(lang: str) -> str:
    """
    Return the human-readable name for a BCP-47 language code.

    Examples:
        lang_display_name("zh-hans") → "Chinese Simplified"
        lang_display_name("en-gb")   → "English (British)"
        lang_display_name("fr")      → "French"
        lang_display_name("xyz")     → "xyz"   (unknown code)
    """
    return LANG_DISPLAY_NAMES.get(lang.lower(), lang)


# Map language codes to their expected dominant script family.
# Languages not listed here are assumed to use Latin script.
_LANG_SCRIPT_MAP: dict[str, str] = {
    # CJK (Chinese, Japanese — share the same Unicode blocks)
    "ja":      "cjk",
    "zh":      "cjk",
    "zh-cn":   "cjk", "zh-tw":   "cjk", "zh-hk":   "cjk",
    "zh-hans": "cjk", "zh-hant": "cjk",
    "yue":     "cjk",
    # Korean
    "ko": "hangul",
    # Arabic / Persian / Urdu
    "ar": "arabic", "fa": "arabic", "ur": "arabic",
    # Cyrillic
    "ru": "cyrillic", "uk": "cyrillic", "bg": "cyrillic",
    "sr": "cyrillic", "mk": "cyrillic",
    # Devanagari
    "hi": "devanagari", "mr": "devanagari", "ne": "devanagari",
    "sa": "devanagari",
    # Thai
    "th": "thai",
    # Hebrew
    "he": "hebrew",
    # Greek
    "el": "greek",
}


def _lang_script(lang: str) -> str:
    """
    Return the expected dominant script family for a BCP-47 language code.

    Examples:
        _lang_script("zh")      → "cjk"
        _lang_script("zh-hans") → "cjk"
        _lang_script("zh-CN")   → "cjk"
        _lang_script("ko")      → "hangul"
        _lang_script("en")      → "latin"
        _lang_script("fr")      → "latin"
    """
    key = lang.lower()
    if key in _LANG_SCRIPT_MAP:
        return _LANG_SCRIPT_MAP[key]
    # Try base subtag only (e.g. "zh-Hant-TW" → "zh")
    base = key.split("-")[0]
    return _LANG_SCRIPT_MAP.get(base, "latin")


# Matches self-closing <ruby .../> and paired <ruby ...>…</ruby> tags.
_RUBY_RE = re.compile(
    r"<ruby\b[^>]*(?:/>|>.*?</ruby>)",
    re.IGNORECASE | re.DOTALL,
)
_RUBY_SELFCLOSING_RE = re.compile(
    r"<ruby\b(?P<attrs>[^>]*)/>",
    re.IGNORECASE | re.DOTALL,
)
_RUBY_BLOCK_RE = re.compile(
    r"<ruby\b(?P<attrs>[^>]*)>(?P<body>.*?)</ruby>",
    re.IGNORECASE | re.DOTALL,
)
_RUBY_DISPLAYTEXT_RE = re.compile(
    r"""displaytext\s*=\s*(?P<quote>["'])(?P<value>.*?)(?P=quote)""",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _has_ruby_markup(text: str) -> bool:
    """Return True when *text* contains any ruby markup."""
    return bool(text and _RUBY_RE.search(text))


def _ruby_visible_text(attrs: str, body: str = "") -> str:
    """
    Return the visible text for a ruby tag.

    Prefer ``displaytext="..."`` when present because this is what the player
    sees in the game's source strings. Fall back to the plain body text for
    paired ruby tags.
    """
    match = _RUBY_DISPLAYTEXT_RE.search(attrs or "")
    if match:
        return match.group("value")
    if body:
        return _TAG_RE.sub("", body)
    return ""


def _flatten_ruby_to_visible_text(text: str) -> str:
    """
    Replace ruby markup with the visible text that should be translated.

    Examples:
        ``テキスト<ruby displaytext="漢字" rubytext="かんじ"/>`` → ``テキスト漢字``
        ``<ruby displaytext="漢字" rubytext="かんじ"/>`` → ``漢字``
    """
    if not _has_ruby_markup(text):
        return text

    def _replace_block(match: re.Match[str]) -> str:
        visible = _ruby_visible_text(match.group("attrs"), match.group("body"))
        return visible if visible else match.group("body")

    def _replace_self_closing(match: re.Match[str]) -> str:
        visible = _ruby_visible_text(match.group("attrs"))
        return visible if visible else match.group(0)

    flattened = _RUBY_BLOCK_RE.sub(_replace_block, text)
    return _RUBY_SELFCLOSING_RE.sub(_replace_self_closing, flattened)

# Unicode ranges that are *unique* to a specific language and should not appear
# in translations targeting other languages.  This is used to detect when the
# LLM returned source-language text in a shared-script pair (e.g. JA→ZH where
# both use CJK, but only Japanese has hiragana/katakana).
#
# Languages whose entire script is already distinct (e.g. Russian/Cyrillic,
# Arabic, Thai) are handled by the same-script check; they do not need entries
# here.
_LANG_UNIQUE_RANGES: dict[str, list[tuple[int, int]]] = {
    # Japanese: hiragana, katakana, katakana phonetic extensions, half-width katakana
    "ja": [
        (0x3040, 0x309F),  # Hiragana
        (0x30A0, 0x30FF),  # Katakana
        (0x31F0, 0x31FF),  # Katakana Phonetic Extensions
        (0xFF65, 0xFF9F),  # Halfwidth Katakana
    ],
    # Korean: Hangul syllables, Jamo, Compatibility Jamo, extended blocks
    "ko": [
        (0xAC00, 0xD7AF),  # Hangul Syllables
        (0x1100, 0x11FF),  # Hangul Jamo
        (0x3130, 0x318F),  # Hangul Compatibility Jamo
        (0xA960, 0xA97F),  # Hangul Jamo Extended-A
        (0xD7B0, 0xD7FF),  # Hangul Jamo Extended-B
    ],
}


def _has_foreign_unique_chars(text: str, target_lang: str) -> bool:
    """
    Return True if *text* contains characters that belong to the *unique*
    Unicode ranges of a language **other than** *target_lang*.

    This is used to detect when the LLM returned source-language text in a
    shared-script language pair.  For example, when translating JA→ZH both
    languages share the CJK block, so the dominant-script check cannot
    distinguish a valid Chinese translation from an untranslated Japanese one.
    However, Japanese is the only language that uses hiragana/katakana, so
    detecting those characters in a Chinese translation reliably identifies
    the failure.

    Characters inside ``<ruby>`` tags are excluded because game engines may
    keep phonetic readings (e.g. Japanese furigana in a ruby tag) even in
    non-Japanese output.

    Only languages with entries in ``_LANG_UNIQUE_RANGES`` are checked; all
    other source/target combinations are already covered by the dominant-script
    rejection logic.
    """
    if not target_lang:
        return False
    tgt_base = target_lang.lower().split("-")[0]
    stripped = _RUBY_RE.sub("", text)
    for char in stripped:
        cp = ord(char)
        for lang_code, ranges in _LANG_UNIQUE_RANGES.items():
            if lang_code == tgt_base:
                continue  # these characters are valid for the target language
            for lo, hi in ranges:
                if lo <= cp <= hi:
                    return True
    return False


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------

class POEntry:
    """Lightweight representation of a PO entry that needs translation."""

    def __init__(
        self,
        file: str,
        msgctxt: str,
        msgid: str,
        msgstr: str,
        msgid_plural: str = "",
    ) -> None:
        self.file = file
        self.msgctxt = msgctxt
        self.msgid = msgid
        # msgstr holds the *source text to translate from* (may equal msgid)
        self.msgstr = msgstr
        self.msgid_plural = msgid_plural

    def source_text(self) -> str:
        """Return the actual text the LLM should translate."""
        source = self.msgstr if self.msgstr else self.msgid
        return _flatten_ruby_to_visible_text(source)

    def __repr__(self) -> str:  # pragma: no cover
        return f"POEntry(msgctxt={self.msgctxt!r}, msgid={self.msgid!r})"


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def _checkpoint_dir(source_folder: str, project: str = "") -> Path:
    """Return a stable temporary directory path derived from the source folder."""
    if project:
        return Path(tempfile.gettempdir()) / f"po_translator_{project}"
    abs_path = os.path.abspath(source_folder)
    hash_str = hashlib.sha256(abs_path.encode()).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"po_translator_{hash_str}"


def _checkpoint_path(source_folder: str, lang: str, project: str = "") -> Path:
    return _checkpoint_dir(source_folder, project) / f"translations.{lang}.json"


def load_checkpoint(source_folder: str, lang: str, reset: bool = False, project: str = "") -> dict[str, str]:
    """
    Load the per-language translation checkpoint.

    Returns a dict mapping msgctxt → translated msgstr.
    Returns an empty dict if the checkpoint does not exist or reset=True.
    """
    if reset:
        return {}
    path = _checkpoint_path(source_folder, lang, project)
    if not path.exists():
        return {}
    try:
        entries: list[dict[str, str]] = json.loads(path.read_text(encoding="utf-8"))
        return {e["msgctxt"]: e["msgstr"] for e in entries if "msgctxt" in e}
    except (json.JSONDecodeError, KeyError):
        return {}


def save_checkpoint(
    source_folder: str,
    lang: str,
    checkpoint: dict[str, str],
    source_basename: str,
    project: str = "",
) -> None:
    """
    Atomically write the checkpoint to disk.

    checkpoint: {msgctxt: translated_msgstr}
    """
    path = _checkpoint_path(source_folder, lang, project)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = [
        {"file": source_basename, "msgctxt": ctx, "msgstr": msgstr}
        for ctx, msgstr in checkpoint.items()
    ]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Entry comparison helpers
# ---------------------------------------------------------------------------

def _entry_key(entry: polib.POEntry) -> str:
    """Return the unique key for a PO entry (msgctxt or msgid)."""
    return entry.msgctxt if entry.msgctxt else entry.msgid


def _needs_translation(
    source_entry: polib.POEntry,
    target_entry: polib.POEntry | None,
    target_lang: str = "",
) -> bool:
    """
    Return True if the target entry needs (re-)translation.

    Rules:
    - Source text is empty → skip (nothing to translate)
    - Target entry missing → needs translation
    - Target msgstr is empty → needs translation
    - Target msgstr still contains ruby markup → needs translation
    - Target msgstr equals the source visible text → needs translation
    - Target msgstr differs from source text → already translated, preserve …
      UNLESS:
      (a) target is still in the same non-Latin script as the source AND that
          script is not the expected script for target_lang (bad LLM output —
          wrote source-language text into the target file).
          Example: ja→en where LLM returned Japanese instead of English.
          Counter-example: ja→zh — both use CJK, so same script is expected.
      (b) target equals source msgid when msgid != msgstr (bad LLM run that
          translated msgid instead of msgstr).
    - Target entry has fuzzy flag → needs translation
    """
    raw_source_text = source_entry.msgstr if source_entry.msgstr else source_entry.msgid
    source_text = _flatten_ruby_to_visible_text(raw_source_text)
    if not source_text:
        return False
    if target_entry is None:
        return True
    if "fuzzy" in target_entry.flags:
        return True
    target_text = target_entry.msgstr
    if not target_text:
        return True
    if _has_ruby_markup(target_text):
        return True
    target_visible_text = _flatten_ruby_to_visible_text(target_text)
    if target_text == source_text or target_visible_text == source_text:
        return True
    # (a) If source and target share the same *non-Latin* dominant script, the
    # translation may still be in the source language (bad LLM output).
    # BUT: skip this check when the target language is expected to use the same
    # script as the source (e.g. ja→zh: both CJK, Chinese output is correct).
    src_script = _dominant_script(source_text)
    tgt_script = _dominant_script(target_visible_text)
    expected_tgt_script = _lang_script(target_lang) if target_lang else None
    if (
        src_script == tgt_script
        and src_script not in ("latin", "other")
        and expected_tgt_script != src_script
    ):
        return True
    # (b) If target equals source msgid while msgid differs from msgstr, a prior
    # LLM run likely copied msgid (treating it as the "original text") instead of
    # translating msgstr.  Only trigger when the scripts differ so we don't
    # incorrectly force re-translation of a valid match (e.g. msgid="Hello" and
    # the correct English translation is also "Hello").
    src_msgid = _flatten_ruby_to_visible_text(source_entry.msgid)
    if src_msgid and src_msgid != source_text and target_visible_text == src_msgid:
        msgid_script = _dominant_script(src_msgid)
        if msgid_script != src_script:
            return True
    # (c) Foreign unique characters: if the translated text contains characters
    # from the unique Unicode ranges of a language other than the target, the
    # LLM likely returned source-language text.  This catches shared-script pairs
    # such as JA→ZH (both CJK) or KO→ZH (both CJK) where check (a) is
    # intentionally disabled.  Characters inside <ruby> tags are excluded.
    if _has_foreign_unique_chars(target_text, target_lang):
        return True
    # (d) Wrong script: if the source is a non-Latin, non-trivial script AND
    # the expected target script is also non-Latin, but the translation is in a
    # completely different script (e.g. a Latin "Good morning" for zh-tw which
    # expects CJK), the LLM answered in the wrong language entirely.
    # Guard: if source script is Latin we cannot distinguish a legitimate
    # identical-script translation (brand names, codes) from a bad one.
    if (
        src_script not in ("latin", "other")
        and expected_tgt_script not in ("latin", "other", None)
        and tgt_script != expected_tgt_script
    ):
        return True
    return False


def _needs_requeue_from_checkpoint(
    cp_value: str,
    source_text: str,
    target_lang: str,
) -> bool:
    """
    Return True if a value stored in the checkpoint should be discarded and
    the entry re-queued for translation.

    This is applied to checkpoint entries that would otherwise bypass the LLM
    entirely. Three conditions trigger a requeue:

    1. Ruby artifacts — the translation still contains ruby markup instead of
       the flattened visible text.

    2. Foreign unique characters — the translation contains characters from a
        language-specific Unicode range that should not appear in *target_lang*
        (e.g. hiragana / katakana in a Chinese translation).

    3. Wrong script — the source text is in a clearly non-Latin script, the
        target language also expects a non-Latin script, but the stored
        translation is in a different script (e.g. English "Good morning" stored
        as the Chinese Traditional translation).  Guarded by source script so
       that Latin-original entries (brand names, codes) are never unnecessarily
       re-translated.
    """
    if not cp_value:
        return False
    if _has_ruby_markup(cp_value):
        return True
    if _has_foreign_unique_chars(cp_value, target_lang):
        return True
    normalized_cp = _flatten_ruby_to_visible_text(cp_value)
    src_script = _dominant_script(source_text)
    tgt_script = _dominant_script(normalized_cp)
    expected_tgt = _lang_script(target_lang)
    if (
        src_script == tgt_script
        and src_script not in ("latin", "other")
        and expected_tgt != src_script
    ):
        return True
    if src_script in ("latin", "other"):
        return False
    if expected_tgt in ("latin", "other"):
        return False
    return tgt_script != expected_tgt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_changed_msgctxts(current_path: str, old_path: str) -> set[str]:
    """
    Return the set of entry keys (msgctxt or msgid) whose source text changed
    between the old and current versions of the same source PO file.

    Used in file mode to force re-translation of updated entries.
    """
    current_po = polib.pofile(current_path, encoding="utf-8")
    old_po = polib.pofile(old_path, encoding="utf-8")

    old_map: dict[str, str] = {}
    for entry in old_po:
        if not entry.obsolete:
            key = _entry_key(entry)
            old_text = entry.msgstr if entry.msgstr else entry.msgid
            old_map[key] = _flatten_ruby_to_visible_text(old_text)

    changed: set[str] = set()
    for entry in current_po:
        if entry.obsolete:
            continue
        key = _entry_key(entry)
        current_raw_text = entry.msgstr if entry.msgstr else entry.msgid
        current_text = _flatten_ruby_to_visible_text(current_raw_text)
        old_text = old_map.get(key)
        # Changed = existed before AND text differs AND new text is non-empty
        if old_text is not None and current_text and current_text != old_text:
            changed.add(key)

    return changed


def get_untranslated(
    source_path: str,
    target_path: str,
    lang: str,
    changed_keys: set[str] | None = None,
    ignore_existing: bool = False,
) -> list[POEntry]:
    """
    Compare source and target PO files and return entries that need translation.

    source_path:     path to the source .po file
    target_path:     path to the target .po file (may not exist yet)
    lang:            target language code (used to create new target if needed)
    changed_keys:    set of msgctxt keys whose source text changed (file mode).
                     Entries in this set are always marked for re-translation,
                     even if the target already has a translation.
    ignore_existing: when True, treat the target as if it does not exist —
                     all entries are returned for (re-)translation.  Used by
                     --reset so that stale translations from a prior bad run
                     cannot be accidentally preserved.
    """
    source_po = polib.pofile(source_path, encoding="utf-8")
    source_basename = Path(source_path).name

    if not ignore_existing and os.path.exists(target_path):
        target_po = polib.pofile(target_path, encoding="utf-8")
        target_map: dict[str, polib.POEntry] = {_entry_key(e): e for e in target_po}
    else:
        target_map = {}

    result: list[POEntry] = []
    for src_entry in source_po:
        if src_entry.obsolete:
            continue
        key = _entry_key(src_entry)
        tgt_entry = target_map.get(key)
        # Force re-translation when source text changed (file mode)
        force = bool(changed_keys and key in changed_keys)
        if force or _needs_translation(src_entry, tgt_entry, lang):
            source_text = src_entry.msgstr if src_entry.msgstr else src_entry.msgid
            result.append(
                POEntry(
                    file=source_basename,
                    msgctxt=key,
                    msgid=src_entry.msgid,
                    msgstr=source_text,
                    msgid_plural=src_entry.msgid_plural or "",
                )
            )
    return result


def merge(
    source_path: str,
    target_path: str,
    checkpoint: dict[str, str],
    lang: str,
) -> None:
    """
    Apply checkpoint translations to the target PO file and write it.

    If the target file does not exist, it is created from the source structure.
    Entries are written in source order. Stale target entries are removed.
    """
    source_po = polib.pofile(source_path, encoding="utf-8")

    if os.path.exists(target_path):
        target_po = polib.pofile(target_path, encoding="utf-8")
        target_map: dict[str, polib.POEntry] = {_entry_key(e): e for e in target_po}
    else:
        target_po = _make_target_catalog(source_po, lang)
        target_map = {}

    # Update header
    _update_header(target_po, lang)

    # Build the final entry list in source order
    new_entries: list[polib.POEntry] = []
    for src_entry in source_po:
        if src_entry.obsolete:
            continue
        key = _entry_key(src_entry)
        tgt_entry = target_map.get(key)

        if key in checkpoint:
            # Apply translation from checkpoint
            entry = _clone_entry(src_entry, tgt_entry)
            entry.msgstr = checkpoint[key]
            if "fuzzy" in entry.flags:
                entry.flags.remove("fuzzy")
        elif tgt_entry is not None:
            source_text = src_entry.msgstr if src_entry.msgstr else src_entry.msgid
            if tgt_entry.msgstr and tgt_entry.msgstr != source_text:
                # Preserve existing human translation
                entry = tgt_entry
            else:
                # Untranslated fallback — keep source text
                entry = _clone_entry(src_entry, tgt_entry)
                entry.msgstr = src_entry.msgstr
        else:
            # New entry not yet translated
            entry = _clone_entry(src_entry, None)
            entry.msgstr = src_entry.msgstr

        new_entries.append(entry)

    # Replace entries list in-place (polib.POFile is a list subclass)
    target_po[:] = new_entries

    # Ensure output directory exists
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    target_po.save(target_path)
    _normalize_encoding(target_path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_target_catalog(source_po: polib.POFile, lang: str) -> polib.POFile:
    """Create a new empty POFile from the source catalog metadata."""
    new_po = polib.POFile()
    new_po.metadata = dict(source_po.metadata)
    new_po.metadata["Language"] = lang
    new_po.metadata_is_fuzzy = source_po.metadata_is_fuzzy
    new_po.encoding = "utf-8"
    return new_po


def _update_header(po: polib.POFile, lang: str) -> None:
    """Update the Language field in the PO header."""
    from datetime import datetime, timezone
    po.metadata["Language"] = lang
    po.metadata["PO-Revision-Date"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M+0000"
    )


def _clone_entry(
    src_entry: polib.POEntry,
    tgt_entry: polib.POEntry | None,
) -> polib.POEntry:
    """Create a new POEntry based on the source, copying target comments if available."""
    base = tgt_entry if tgt_entry is not None else src_entry
    entry = polib.POEntry(
        msgctxt=src_entry.msgctxt,
        msgid=src_entry.msgid,
        msgid_plural=src_entry.msgid_plural,
        msgstr=base.msgstr,
        msgstr_plural=dict(base.msgstr_plural) if base.msgstr_plural else {},
        occurrences=list(src_entry.occurrences),
        comment=src_entry.comment,
        tcomment=src_entry.tcomment,
        flags=list(src_entry.flags),
    )
    return entry


# ---------------------------------------------------------------------------
# Utility: count entries
# ---------------------------------------------------------------------------

def _normalize_encoding(path: str) -> None:
    """Rewrite a PO file as UTF-8 BOM + LF to match source PO convention."""
    data = Path(path).read_bytes()
    # Strip existing BOM so we can re-add exactly one
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    # Normalize CRLF → LF
    data = data.replace(b"\r\n", b"\n")
    Path(path).write_bytes(b"\xef\xbb\xbf" + data)


def count_entries(source_path: str) -> int:
    """Return the number of non-obsolete, non-header entries in a PO file."""
    po = polib.pofile(source_path, encoding="utf-8")
    return sum(1 for e in po if not e.obsolete)
