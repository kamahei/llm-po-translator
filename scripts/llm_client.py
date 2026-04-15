"""
llm_client.py — LLM API client wrapping OpenAI-compatible endpoints.

Supports:
  - Local Ollama     (http://localhost:11434, no auth)
  - LAN Ollama       (http://<ip>:11434, no auth)
  - External Ollama  (https://<domain>, Cloudflare Tunnel + CF-Access headers)
  - Local LM Studio  (http://localhost:1234, Bearer token)
  - LAN LM Studio    (http://<ip>:1234, Bearer token)
  - Shared vLLM      (http://<server>:8000, optional Bearer token)
"""
from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

import openai

import po_helper

if TYPE_CHECKING:
    from translate import Config

# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are a professional game localization translator.
Translate the `msgstr` field of each entry from {source_language} to {target_language}.
The `msgctxt` field is an identifier — do NOT translate or modify it.

Rules:
- Translate only the `msgstr` value. Copy `msgctxt` unchanged to the output.
- Preserve all placeholders like {{Variable}}, {{0}}, %d, %s, %1$s exactly as-is in \
their token form, but place them where the target language's natural word order \
requires.
- Some placeholders may already be normalized to positional tokens like {{0}} and \
{{1}}. Treat each placeholder as a runtime value (a number, an item name, a list, a \
currency symbol, an amount, etc.) when deciding grammar and word order.
- Use complete, natural target-language phrases. Do not leave verb-less fragments or \
broken UI text.
- If a placeholder stands for multiple items, use plural grammar in the surrounding \
words when context requires it.
- Do not insert extra spaces inside or around placeholder formatting patterns. Keep \
`${{0}}` as `${{0}}`, not `$ {{0}}`, unless the target language truly requires \
different spacing.
- NEVER strip curly braces from placeholders. `${{0}}` must stay `${{0}}`, and \
`＄{{0}}` or `${{0}}` must never become `$0`.
- If the source text is only a formatting pattern made of placeholders and punctuation, \
keep the same structure unless the target language clearly requires reordering.
- Example: {{0}}日目 (Japanese for "Day X") → "Day {{0}}", not "{{0}} day".
- Example: {{0}}を渡す → "Give {{0}}", not "{{0}} to you".
- Example: 正解は{{0}}と{{1}}だった → "The correct answers were {{0}} and {{1}}".
- Example: 正解は{{0}}だった → "The correct answer was {{0}}", not "Even though the \
correct answer was {{0}}".
- Example: 価格[-${{0}}] → "Price[-${{0}}]", not "Price[-$ {{0}}]".
- Example: ローン[＄{{0}}] → "Loan [${{0}}]", not "Loan [$0]".
- Example: a pure format string like "{{0}}{{1}}" should usually remain "{{0}}{{1}}".
- Preserve markup inside <...> tags (treat as engine commands, not text to translate).
- Ruby markup from the source is pre-flattened to its visible text before it \
reaches you (for example, <ruby displaytext="X" rubytext="Y"/> becomes X).
- Preserve line breaks (\\n) exactly as they appear in the source.
- Preserve names, codenames, and non-localizable identifiers unchanged.
- Preserve tone: game dialogue, UI labels, tutorial text, medical terminology.
- Return ONLY a JSON array. No markdown fences. No explanations. No extra text.
- Each object must have exactly two string keys: "msgctxt" and "msgstr".
- Maintain exactly the same order as the input. One object per input entry.{char_context_rule_line}{context_line}
"""


class LLMClient:
    """Sends translation requests to an OpenAI-compatible LLM backend."""

    def __init__(self, config: Config) -> None:
        self._model = config.model
        self._timeout = config.timeout

        headers: dict[str, str] = {}
        auth_type = getattr(config, "auth_type", "none")

        if auth_type == "cf":
            # Ollama external server via Cloudflare Tunnel
            if config.api_key and config.api_secret:
                headers["CF-Access-Client-Id"] = config.api_key
                headers["CF-Access-Client-Secret"] = config.api_secret
            openai_api_key = "ollama"
        elif auth_type == "bearer":
            # LM Studio or vLLM (or any Bearer-token-authenticated OpenAI-compatible server)
            # The openai library sends "Authorization: Bearer <api_key>" automatically.
            backend = getattr(config, "backend", "")
            openai_api_key = config.api_key or ("vllm" if backend == "vllm" else "lm-studio")
        else:
            # Ollama local/LAN — no authentication required
            # The openai library still requires a non-empty api_key value.
            openai_api_key = "ollama"

        self._client = openai.OpenAI(
            base_url=f"{config.host.rstrip('/')}/v1",
            api_key=openai_api_key,
            default_headers=headers if headers else None,
            timeout=config.timeout,
        )

        self._context = config.context
        self._char_rules: list[dict] = getattr(config, "char_rules", [])

    # ------------------------------------------------------------------

    def translate_batch(
        self,
        entries: list[dict[str, str]],
        source_lang: str,
        target_lang: str,
    ) -> list[dict[str, str]]:
        """
        Translate a list of entry dicts.

        Each entry dict must have keys: msgctxt, msgstr (source text to translate).
        msgid is intentionally excluded — sending it confuses the LLM because PO
        convention treats msgid as the "original text", causing it to translate msgid
        instead of msgstr when they differ.
        Returns a list of dicts with keys: msgctxt, msgstr (translated).
        Raises ValueError or openai.APIError on unrecoverable failure.
        """
        if not entries:
            return []

        # Replace named placeholders {Day} → {0} etc. to remove semantic
        # content from placeholder names that might mislead the LLM about
        # word order.  Results are restored to original names after translation.
        subst_entries: list[dict[str, str]] = []
        ctxt_to_mapping: dict[str, list[str]] = {}
        ctxt_to_source: dict[str, str] = {}
        for entry in entries:
            modified, mapping = _substitute_placeholders(entry["msgstr"])
            subst_entry: dict[str, str] = {"msgctxt": entry["msgctxt"], "msgstr": modified}
            for rule in self._char_rules:
                if rule.get("pattern", "") in entry["msgctxt"]:
                    subst_entry["context"] = rule["context"]
                    break
            subst_entries.append(subst_entry)
            ctxt_to_mapping[entry["msgctxt"]] = mapping
            ctxt_to_source[entry["msgctxt"]] = modified

        system_prompt = self._build_system_prompt(source_lang, target_lang)
        user_message = json.dumps(subst_entries, ensure_ascii=False)

        raw_results = self._call_with_retry(system_prompt, user_message, expected_count=len(entries))

        # Restore original placeholder names in every translated entry.
        results: list[dict[str, str]] = []
        for r in raw_results:
            mapping = ctxt_to_mapping.get(r["msgctxt"], [])
            repaired = _repair_currency_adjacent_placeholders(
                ctxt_to_source.get(r["msgctxt"], ""),
                r["msgstr"],
            )
            results.append({
                "msgctxt": r["msgctxt"],
                "msgstr": _restore_placeholders(repaired, mapping),
            })
        return results

    # ------------------------------------------------------------------

    def _build_system_prompt(self, source_lang: str, target_lang: str) -> str:
        context_line = (
            f"\n- Context: {self._context}" if self._context else ""
        )
        char_context_rule_line = (
            "\n- Input entries may have an optional \"context\" field — use it as "
            "character/scene-specific guidance for that entry's translation only. "
            "Do NOT include \"context\" in your output."
            if self._char_rules else ""
        )
        return _SYSTEM_PROMPT_TEMPLATE.format(
            source_language=po_helper.lang_display_name(source_lang),
            target_language=po_helper.lang_display_name(target_lang),
            char_context_rule_line=char_context_rule_line,
            context_line=context_line,
        )

    def _call_with_retry(
        self,
        system_prompt: str,
        user_message: str,
        expected_count: int,
    ) -> list[dict[str, str]]:
        """Send the request with retry logic for transient failures."""
        max_network_retries = 3
        max_parse_retries = 2
        parse_note = ""

        for network_attempt in range(max_network_retries):
            try:
                system = system_prompt
                if parse_note:
                    system = system_prompt + f"\n\nIMPORTANT: {parse_note}"

                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_message},
                    ],
                )
                raw = response.choices[0].message.content or ""

                # Attempt to parse; retry on bad JSON or count mismatch.
                # _parse_response returns a partial list on truncation, which
                # we accept immediately (no retry — truncation won't self-heal).
                for parse_attempt in range(max_parse_retries + 1):
                    try:
                        result = _parse_response(raw, expected_count)
                        if len(result) < expected_count:
                            print(
                                f"[llm_client] WARNING: response truncated — "
                                f"recovered {len(result)}/{expected_count} entries "
                                f"(the rest will be retried on next run)"
                            )
                        return result
                    except ValueError as exc:
                        if parse_attempt < max_parse_retries:
                            parse_note = (
                                "Your previous response was not valid JSON or had the wrong "
                                "number of items. Return ONLY a JSON array of objects with "
                                '"msgctxt" and "msgstr" keys. No markdown. No extra text.'
                            )
                            # Re-send with clarification note
                            system2 = system_prompt + f"\n\nIMPORTANT: {parse_note}"
                            response = self._client.chat.completions.create(
                                model=self._model,
                                messages=[
                                    {"role": "system", "content": system2},
                                    {"role": "user", "content": user_message},
                                ],
                            )
                            raw = response.choices[0].message.content or ""
                        else:
                            # Last attempt: salvage any valid items rather than
                            # skipping the entire batch.
                            salvaged = _parse_response_unchecked(raw)
                            if salvaged:
                                print(
                                    f"[llm_client] WARNING: accepting {len(salvaged)}"
                                    f"/{expected_count} items after count mismatch "
                                    f"(remainder will be retried on next run)"
                                )
                                return salvaged
                            raise exc

            except openai.RateLimitError:
                print("[llm_client] Rate limit hit — waiting 60s before retry...")
                time.sleep(60)
                continue

            except (openai.APITimeoutError, openai.APIConnectionError) as exc:
                if network_attempt < max_network_retries - 1:
                    wait = 5 * (network_attempt + 1)
                    print(f"[llm_client] Connection error ({exc.__class__.__name__}) — retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                raise

        raise RuntimeError(f"LLM request failed after {max_network_retries} attempts")


# ---------------------------------------------------------------------------
# Placeholder substitution helpers
# ---------------------------------------------------------------------------

# Matches named placeholders like {Day}, {PlayerName}, {Count0} but NOT
# positional {0}, {1} or escaped {{ / }}.
_NAMED_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_CURRENCY_ADJACENT_PLACEHOLDER_RE = re.compile(
    r"[$＄]\{(?P<token>\d+|[A-Za-z_][A-Za-z0-9_]*)\}"
)


def _substitute_placeholders(text: str) -> tuple[str, list[str]]:
    """
    Replace named placeholders ({Day}, {Name}, …) with positional equivalents
    ({0}, {1}, …) so that the LLM cannot be misled by the semantic content of
    the placeholder name when deciding word order.

    Returns (modified_text, mapping) where mapping[i] is the original token
    that was replaced with {i}.  Duplicate occurrences of the same placeholder
    map to the same index.
    """
    seen: dict[str, int] = {}
    mapping: list[str] = []

    def _replace(m: re.Match) -> str:
        token = m.group(0)
        if token not in seen:
            seen[token] = len(mapping)
            mapping.append(token)
        return f"{{{seen[token]}}}"

    return _NAMED_PLACEHOLDER_RE.sub(_replace, text), mapping


def _restore_placeholders(text: str, mapping: list[str]) -> str:
    """
    Replace positional placeholders ({0}, {1}, …) back with the original named
    tokens.  Safe when mapping is empty (returns text unchanged).
    """
    for i, original in enumerate(mapping):
        text = text.replace(f"{{{i}}}", original)
    return text


def _repair_currency_adjacent_placeholders(source: str, translated: str) -> str:
    """
    Repair `$0` / `＄0` style corruption when the source proves a currency-adjacent
    placeholder such as `${0}` or `＄{0}` was intended.
    """
    tokens = sorted(
        {m.group("token") for m in _CURRENCY_ADJACENT_PLACEHOLDER_RE.finditer(source)},
        key=len,
        reverse=True,
    )
    if not tokens:
        return translated

    repaired = translated
    for token in tokens:
        if f"${{{token}}}" in repaired or f"＄{{{token}}}" in repaired:
            continue
        repaired = re.sub(
            rf"([$＄])\s*{re.escape(token)}(?![\w}}])",
            lambda m: f"{m.group(1)}{{{token}}}",
            repaired,
        )
    return repaired


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _lenient_json_loads(text: str) -> object:
    """
    json.loads with common LLM output quirks tolerated:
      - trailing commas before } or ]
      - BOM / leading whitespace
    Falls back to strict json.loads error if still unparseable after cleanup.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Strip trailing commas: ,<whitespace>} or ,<whitespace>]
        fixed = re.sub(r",\s*([}\]])", r"\1", text)
        return json.loads(fixed)  # let this raise if still broken


def _normalize_llm_json(text: str) -> str:
    """
    Fix common structural mistakes in LLM JSON output before parsing.

    Known patterns:
      1. Object closed with ) instead of }:
           {"msgctxt": "x", "msgstr": "y")  →  {"msgctxt": "x", "msgstr": "y"}
      2. Missing } before next object in array:
           "msgstr": "value", {"msgctxt": → "msgstr": "value"}, {"msgctxt":
    """
    # Pattern 1: "),  or ")]  → "},  or "}]
    text = re.sub(r'"\)\s*,', '"},', text)
    text = re.sub(r'"\)\s*\]', '"}]', text)
    # End of truncated response: ... "value")  → ... "value"}
    text = re.sub(r'"\)\s*$', '"}', text.rstrip())
    # Pattern 2: missing } between adjacent objects in array.
    # Matches: "string_value", {"known_key": → "string_value"}, {"known_key":
    # The regex uses a non-greedy string match to stay within a single value.
    _OBJ_KEYS = r'(?:msgctxt|msgid|msgstr|msg_ctxt|msg ctxt)'
    text = re.sub(
        r'("(?:[^"\\]|\\.)*")\s*,\s*(\{"' + _OBJ_KEYS + r'"\s*:)',
        r'\1}, \2',
        text,
    )
    return text


def _recover_partial_array(text: str) -> list:
    """
    Extract as many complete JSON objects as possible from a truncated or
    structurally broken array response.

    Strategy: find the last `}` in the text, try to parse everything up to
    that point as a closed array.  If parsing still fails (e.g. because the
    structural error is *before* that `}`) step backwards to the previous `}`
    and retry.  This iterates until a valid prefix is found or no more `}`
    characters remain.

    Returns a (possibly empty) list of parsed objects.
    """
    text = text.strip()
    if not text.startswith("["):
        return []
    search_end = len(text)
    while search_end > 1:
        last_brace = text.rfind("}", 0, search_end)
        if last_brace < 0:
            return []
        candidate = text[: last_brace + 1].rstrip().rstrip(",") + "]"
        try:
            result = _lenient_json_loads(candidate)
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, ValueError):
            search_end = last_brace  # step back and try the previous }
    return []


def _parse_response_unchecked(raw: str) -> list[dict[str, str]]:
    """Parse LLM response and return all valid items, ignoring count requirements."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = _normalize_llm_json(cleaned)
    try:
        data = _lenient_json_loads(cleaned)
    except json.JSONDecodeError:
        data = _recover_partial_array(cleaned)
    if not isinstance(data, list):
        return []
    result = []
    for i, item in enumerate(data):
        try:
            result.append(_extract_entry(i, item))
        except ValueError:
            continue
    return result


def _parse_response(raw: str, expected_count: int) -> list[dict[str, str]]:
    """
    Parse the LLM text response into a list of {msgctxt, msgstr} dicts.

    Returns the full list when the LLM produced a complete, valid response.
    Returns a *partial* list (fewer than expected_count) when the response was
    truncated — the caller is responsible for handling the missing entries.
    Raises ValueError only when no usable entries can be extracted at all.
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # Normalise common structural LLM output mistakes (e.g. ) instead of })
    cleaned = _normalize_llm_json(cleaned)

    # Full parse (with trailing-comma tolerance)
    full_parse_error: Exception | None = None
    try:
        data = _lenient_json_loads(cleaned)
        if not isinstance(data, list):
            raise ValueError(f"LLM response is not a JSON array. Got: {type(data).__name__}")
        if len(data) != expected_count:
            raise ValueError(
                f"LLM returned {len(data)} items, expected {expected_count}"
            )
        return [_extract_entry(i, item) for i, item in enumerate(data)]
    except json.JSONDecodeError as exc:
        full_parse_error = exc
    except ValueError:
        raise  # count mismatch or type error — let caller retry

    # Full parse failed (likely truncation).  Try to salvage whatever complete
    # entries arrived before the cut-off.
    partial = _recover_partial_array(cleaned)
    validated: list[dict[str, str]] = []
    for i, item in enumerate(partial):
        try:
            validated.append(_extract_entry(i, item))
        except ValueError:
            break  # stop at the first malformed entry
    if validated:
        return validated  # partial result — fewer than expected_count

    raise ValueError(
        f"LLM response is not valid JSON: {full_parse_error}\nRaw: {raw[:200]}"
    )


# Common LLM typos / variant spellings → canonical key
_KEY_ALIASES: dict[str, str] = {
    "msg_ctxt":   "msgctxt",
    "msg ctxt":   "msgctxt",
    "msg_str":    "msgstr",
    "msg str":    "msgstr",
    "msgtext":    "msgstr",
    "msg_text":   "msgstr",
    "msg text":   "msgstr",
    "translation":"msgstr",
    "context":    "msgctxt",
    "msgcontext": "msgctxt",
}


def _extract_entry(index: int, item: object) -> dict[str, str]:
    """Validate and return a single {msgctxt, msgstr} dict from a parsed object."""
    if not isinstance(item, dict):
        raise ValueError(f"Item {index} is not a dict")
    # Normalise aliased key names produced by some LLM outputs
    normalised = {_KEY_ALIASES.get(k, k): v for k, v in item.items()}
    if "msgctxt" not in normalised or "msgstr" not in normalised:
        raise ValueError(f"Item {index} missing 'msgctxt' or 'msgstr': {item}")
    return {"msgctxt": str(normalised["msgctxt"]), "msgstr": str(normalised["msgstr"])}
