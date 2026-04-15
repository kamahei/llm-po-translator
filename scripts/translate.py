"""
translate.py — Main CLI entry point for POTranslatorLLM.

Usage:
    python translate.py --folder <path> --source-lang <code> [options]

See docs/user-manual.md for full usage documentation.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time

import openai
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

# Load .env from the repo root (one level above this scripts/ directory).
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

import po_helper
from po_helper import _dominant_script
from llm_client import LLMClient


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class HostEntry:
    """A single LLM host endpoint with its authentication configuration."""
    url: str
    api_key: str = ""       # CF-Access-Client-Id (cf) or Bearer token (bearer)
    api_secret: str = ""    # CF-Access-Client-Secret (cf only)
    auth_type: str = "none" # "none" | "cf" | "bearer"
    model: str = ""         # empty = inherit Config.model
    backend: str = "ollama"


@dataclass
class Config:
    folder: str
    source_lang: str
    target_langs: list[str] = field(default_factory=list)
    host: str = "http://localhost:11434"
    model: str = "qwen2.5:7b"
    api_key: str = ""
    api_secret: str = ""
    auth_type: str = "none"
    backend: str = "ollama"
    batch_size: int = 20
    timeout: float = 120.0
    reset: bool = False
    dry_run: bool = False
    verbose: bool = False
    context: str = ""
    char_rules: list[dict] = field(default_factory=list)
    project: str = ""
    # Multi-host fields
    hosts: list[HostEntry] = field(default_factory=list)
    lang_hosts: dict[str, list[HostEntry]] = field(default_factory=dict)
    # Per-language model overrides
    ollama_lang_models: dict[str, str] = field(default_factory=dict)  # {lang: ollama_model}
    lms_lang_models: dict[str, str] = field(default_factory=dict)     # {lang: lms_model}
    vllm_lang_models: dict[str, str] = field(default_factory=dict)    # {lang: vllm_model}
    # File mode fields
    source_file: str = ""
    old_source_file: str = ""


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> Config:
    parser = argparse.ArgumentParser(
        prog="translate.py",
        description=(
            "Translate .po files using a local or shared LLM (Ollama, LM Studio, or vLLM).\n\n"
            "Folder mode:  --folder <path> --source-lang <code> [--target-lang ...]\n"
            "File mode:    --source-file <current.po> --old-source-file <old.po> --target-lang ..."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # --- Folder mode ---
    folder_group = parser.add_argument_group("Folder mode")
    folder_group.add_argument(
        "--folder",
        default="",
        help="Localization root folder (e.g., Localization/Game)",
    )
    folder_group.add_argument(
        "--source-lang",
        default="",
        help="Source language directory name (e.g., ja)",
    )

    # --- File mode ---
    file_group = parser.add_argument_group("File mode (diff against old version)")
    file_group.add_argument(
        "--source-file",
        default="",
        metavar="CURRENT.PO",
        help="Current source .po file path (triggers file mode)",
    )
    file_group.add_argument(
        "--old-source-file",
        default="",
        metavar="OLD.PO",
        help="Previous version of the source .po file (for changed-source detection)",
    )

    # --- Common ---
    parser.add_argument(
        "--target-lang",
        nargs="+",
        default=[],
        metavar="LANG",
        help="Target language code(s). Default: all sibling directories.",
    )
    parser.add_argument(
        "--host",
        default=_env("OLLAMA_HOST", "http://localhost:11434"),
        help="Ollama server base URL. Env: OLLAMA_HOST (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--hosts",
        nargs="+",
        default=[],
        metavar="URL",
        help=(
            "Multiple Ollama server URLs for parallel translation. "
            "Languages are distributed round-robin across all hosts. "
            "Overrides --host. Env: OLLAMA_HOSTS (comma-separated)."
        ),
    )
    parser.add_argument(
        "--lang-host",
        action="append",
        default=[],
        metavar="LANG=URL",
        help=(
            "Assign an Ollama host to a specific language (e.g. en=http://host2:11434). "
            "Repeat the same LANG to assign multiple hosts — batches are distributed "
            "across all assigned hosts in parallel. "
            "Env: OLLAMA_LANG_HOSTS (comma-separated LANG=URL pairs)."
        ),
    )
    parser.add_argument(
        "--model",
        default=_env("OLLAMA_MODEL", "qwen2.5:7b"),
        help="Ollama model name. Env: OLLAMA_MODEL (default: qwen2.5:7b)",
    )
    parser.add_argument(
        "--lang-model",
        action="append",
        default=[],
        metavar="LANG=MODEL",
        help=(
            "Use a specific Ollama model for a target language (e.g. zh=qwen2.5:7b). "
            "Repeat for multiple languages. "
            "Hosts that do not have the required model are skipped automatically. "
            "Env: OLLAMA_LANG_MODELS (comma-separated LANG=MODEL pairs)."
        ),
    )
    parser.add_argument(
        "--api-key",
        default=_env("CF_ACCESS_CLIENT_ID"),
        help="Cloudflare Access Client ID for Ollama external servers. Env: CF_ACCESS_CLIENT_ID.",
    )
    parser.add_argument(
        "--api-secret",
        default=_env("CF_ACCESS_CLIENT_SECRET"),
        help="Cloudflare Access Client Secret for Ollama external servers. Env: CF_ACCESS_CLIENT_SECRET.",
    )

    # --- LM Studio backend ---
    lms_group = parser.add_argument_group("LM Studio backend (alternative / additional to Ollama)")
    lms_group.add_argument(
        "--lms-host",
        default=_env("LMS_HOST", ""),
        help="LM Studio server base URL (e.g. http://localhost:1234). Env: LMS_HOST.",
    )
    lms_group.add_argument(
        "--lms-hosts",
        nargs="+",
        default=[],
        metavar="URL",
        help=(
            "Multiple LM Studio server URLs for parallel translation. "
            "Overrides --lms-host. Env: LMS_HOSTS (comma-separated)."
        ),
    )
    lms_group.add_argument(
        "--lms-lang-host",
        action="append",
        default=[],
        metavar="LANG=URL",
        help=(
            "Assign an LM Studio host to a specific language (e.g. en=http://host:1234). "
            "Repeat the same LANG to assign multiple hosts. "
            "Env: LMS_LANG_HOSTS (comma-separated LANG=URL pairs)."
        ),
    )
    lms_group.add_argument(
        "--lms-model",
        default=_env("LMS_MODEL", ""),
        help="LM Studio model name. Env: LMS_MODEL.",
    )
    lms_group.add_argument(
        "--lms-lang-model",
        action="append",
        default=[],
        metavar="LANG=MODEL",
        help=(
            "Use a specific LM Studio model for a target language (e.g. en=llama3.1-8b). "
            "Repeat for multiple languages. "
            "Hosts that do not have the required model are skipped automatically. "
            "Env: LMS_LANG_MODELS (comma-separated LANG=MODEL pairs)."
        ),
    )
    lms_group.add_argument(
        "--lms-api-key",
        default=_env("LMS_API_KEY", "lm-studio"),
        help=(
            "LM Studio API key for Bearer token authentication. "
            "Use any non-empty string when LM Studio has no auth enforced. "
            "Env: LMS_API_KEY (default: lm-studio)."
        ),
    )
    vllm_group = parser.add_argument_group("vLLM backend (existing server connection)")
    vllm_group.add_argument(
        "--vllm-host",
        default=_env("VLLM_HOST", ""),
        help="vLLM server base URL (e.g. http://server:8000). Env: VLLM_HOST.",
    )
    vllm_group.add_argument(
        "--vllm-hosts",
        nargs="+",
        default=[],
        metavar="URL",
        help=(
            "Multiple vLLM server URLs for parallel translation. "
            "Overrides --vllm-host. Env: VLLM_HOSTS (comma-separated)."
        ),
    )
    vllm_group.add_argument(
        "--vllm-lang-host",
        action="append",
        default=[],
        metavar="LANG=URL",
        help=(
            "Assign a vLLM host to a specific language (e.g. en=http://host:8000). "
            "Repeat the same LANG to assign multiple hosts. "
            "Env: VLLM_LANG_HOSTS (comma-separated LANG=URL pairs)."
        ),
    )
    vllm_group.add_argument(
        "--vllm-model",
        default=_env("VLLM_MODEL", ""),
        help="vLLM model name. Env: VLLM_MODEL.",
    )
    vllm_group.add_argument(
        "--vllm-lang-model",
        action="append",
        default=[],
        metavar="LANG=MODEL",
        help=(
            "Use a specific vLLM model for a target language (e.g. en=meta-llama/Llama-3.1-8B-Instruct). "
            "Repeat for multiple languages. "
            "Hosts that do not have the required model are skipped automatically. "
            "Env: VLLM_LANG_MODELS (comma-separated LANG=MODEL pairs)."
        ),
    )
    vllm_group.add_argument(
        "--vllm-api-key",
        default=_env("VLLM_API_KEY", "vllm"),
        help=(
            "vLLM API key for Bearer token authentication. "
            "Use any non-empty string when the server does not enforce auth. "
            "Env: VLLM_API_KEY (default: vllm)."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_env_int("TRANSLATE_BATCH_SIZE", 20),
        help="Entries per LLM request (default: 20)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_env_float("TRANSLATE_TIMEOUT", 120.0),
        help="LLM request timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Discard checkpoint and restart from scratch",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze without writing any files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed per-batch progress",
    )
    parser.add_argument(
        "--context",
        default=_env("TRANSLATE_CONTEXT", ""),
        help="Translation context hint injected into the system prompt",
    )
    parser.add_argument(
        "--char-rules-file",
        default=_env("TRANSLATE_CHAR_RULES_FILE", ""),
        metavar="FILE",
        help=(
            "Path to a JSON file with per-character translation rules. "
            "Each rule is {\"pattern\": \"<substring>\", \"context\": \"<guidance>\"}. "
            "Entries whose msgctxt contains the pattern receive the context field. "
            "Env: TRANSLATE_CHAR_RULES_FILE."
        ),
    )
    parser.add_argument(
        "--project",
        default=_env("TRANSLATE_PROJECT", ""),
        metavar="NAME",
        help=(
            "Project name for the checkpoint cache directory. "
            "When set, checkpoints are stored in %%TEMP%%\\po_translator_<NAME> "
            "instead of a hash-based path, so the cache is shared across machines "
            "that point to the same project. Env: TRANSLATE_PROJECT."
        ),
    )

    args = parser.parse_args()

    # Load character/context rules file if specified.
    char_rules: list[dict] = []
    if args.char_rules_file:
        try:
            with open(args.char_rules_file, encoding="utf-8") as _f:
                char_rules = json.load(_f)
            if not isinstance(char_rules, list):
                parser.error(
                    f"--char-rules-file: expected a JSON array, got {type(char_rules).__name__}"
                )
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"--char-rules-file: failed to load {args.char_rules_file!r}: {exc}")

    # Validate mode
    in_file_mode = bool(args.source_file)
    in_folder_mode = bool(args.folder or args.source_lang)

    if in_file_mode and in_folder_mode:
        parser.error("--source-file and --folder/--source-lang are mutually exclusive.")
    if not in_file_mode and not (args.folder and args.source_lang):
        parser.error(
            "Provide either --source-file (file mode) "
            "or both --folder and --source-lang (folder mode)."
        )
    if args.old_source_file and not in_file_mode:
        parser.error("--old-source-file requires --source-file.")

    # --- Build per-host HostEntry factories --------------------------------
    ollama_api_key = args.api_key or ""
    ollama_api_secret = args.api_secret or ""
    ollama_auth_type = "cf" if (ollama_api_key and ollama_api_secret) else "none"
    ollama_model = args.model

    def _ollama_entry(url: str) -> HostEntry:
        return HostEntry(
            url=url,
            api_key=ollama_api_key,
            api_secret=ollama_api_secret,
            auth_type=ollama_auth_type,
            model=ollama_model,
            backend="ollama",
        )

    lms_api_key = args.lms_api_key or "lm-studio"
    lms_model = args.lms_model

    def _lms_entry(url: str) -> HostEntry:
        return HostEntry(
            url=url,
            api_key=lms_api_key,
            api_secret="",
            auth_type="bearer",
            model=lms_model,
            backend="lmstudio",
        )

    vllm_api_key = args.vllm_api_key or "vllm"
    vllm_model = args.vllm_model

    def _vllm_entry(url: str) -> HostEntry:
        return HostEntry(
            url=url,
            api_key=vllm_api_key,
            api_secret="",
            auth_type="bearer",
            model=vllm_model,
            backend="vllm",
        )

    # --- Resolve Ollama host pool -----------------------------------------
    # Priority: --hosts CLI > OLLAMA_HOSTS env > --host CLI > OLLAMA_HOST env
    ollama_urls: list[str] = []
    if args.hosts:
        ollama_urls = args.hosts
    elif env_hosts := _env("OLLAMA_HOSTS"):
        ollama_urls = [h.strip() for h in env_hosts.split(",") if h.strip()]
    else:
        ollama_urls = [h.strip() for h in args.host.split(",") if h.strip()]

    # --- Resolve LM Studio host pool --------------------------------------
    # Priority: --lms-hosts CLI > LMS_HOSTS env > --lms-host CLI > LMS_HOST env
    lms_urls: list[str] = []
    if args.lms_hosts:
        lms_urls = args.lms_hosts
    elif env_lms_hosts := _env("LMS_HOSTS"):
        lms_urls = [h.strip() for h in env_lms_hosts.split(",") if h.strip()]
    elif args.lms_host:
        lms_urls = [h.strip() for h in args.lms_host.split(",") if h.strip()]

    # --- Resolve vLLM host pool -------------------------------------------
    # Priority: --vllm-hosts CLI > VLLM_HOSTS env > --vllm-host CLI > VLLM_HOST env
    vllm_urls: list[str] = []
    if args.vllm_hosts:
        vllm_urls = args.vllm_hosts
    elif env_vllm_hosts := _env("VLLM_HOSTS"):
        vllm_urls = [h.strip() for h in env_vllm_hosts.split(",") if h.strip()]
    elif args.vllm_host:
        vllm_urls = [h.strip() for h in args.vllm_host.split(",") if h.strip()]

    # --- Merge host pools -------------------------------------------------
    hosts: list[HostEntry] = (
        [_ollama_entry(u) for u in ollama_urls]
        + [_lms_entry(u) for u in lms_urls]
        + [_vllm_entry(u) for u in vllm_urls]
    )
    if not hosts:
        hosts = [_ollama_entry("http://localhost:11434")]

    # --- Resolve language-to-host overrides (Ollama) ----------------------
    # Priority: --lang-host CLI > OLLAMA_LANG_HOSTS env
    # Multiple entries for the same language assign multiple hosts;
    # batches are distributed across all of them in parallel.
    lang_hosts: dict[str, list[HostEntry]] = {}
    for item in (args.lang_host or []):
        if "=" in item:
            lang, host_url = item.split("=", 1)
            lang_hosts.setdefault(lang.strip(), []).append(_ollama_entry(host_url.strip()))
        else:
            parser.error(f"--lang-host must be in LANG=URL format, got: {item!r}")
    if env_lang_hosts := _env("OLLAMA_LANG_HOSTS"):
        for item in env_lang_hosts.split(","):
            item = item.strip()
            if "=" in item:
                lang, host_url = item.split("=", 1)
                lang_key = lang.strip()
                entry = _ollama_entry(host_url.strip())
                if lang_key not in lang_hosts:
                    lang_hosts.setdefault(lang_key, []).append(entry)
                elif host_url.strip() not in [e.url for e in lang_hosts[lang_key]]:
                    lang_hosts[lang_key].append(entry)

    # --- Resolve language-to-host overrides (LM Studio) -------------------
    # Priority: --lms-lang-host CLI > LMS_LANG_HOSTS env
    for item in (args.lms_lang_host or []):
        if "=" in item:
            lang, host_url = item.split("=", 1)
            lang_hosts.setdefault(lang.strip(), []).append(_lms_entry(host_url.strip()))
        else:
            parser.error(f"--lms-lang-host must be in LANG=URL format, got: {item!r}")
    if env_lms_lang_hosts := _env("LMS_LANG_HOSTS"):
        for item in env_lms_lang_hosts.split(","):
            item = item.strip()
            if "=" in item:
                lang, host_url = item.split("=", 1)
                lang_key = lang.strip()
                entry = _lms_entry(host_url.strip())
                if lang_key not in lang_hosts:
                    lang_hosts.setdefault(lang_key, []).append(entry)
                elif host_url.strip() not in [e.url for e in lang_hosts.get(lang_key, [])]:
                    lang_hosts[lang_key].append(entry)

    # --- Resolve language-to-host overrides (vLLM) ------------------------
    for item in (args.vllm_lang_host or []):
        if "=" in item:
            lang, host_url = item.split("=", 1)
            lang_hosts.setdefault(lang.strip(), []).append(_vllm_entry(host_url.strip()))
        else:
            parser.error(f"--vllm-lang-host must be in LANG=URL format, got: {item!r}")
    if env_vllm_lang_hosts := _env("VLLM_LANG_HOSTS"):
        for item in env_vllm_lang_hosts.split(","):
            item = item.strip()
            if "=" in item:
                lang, host_url = item.split("=", 1)
                lang_key = lang.strip()
                entry = _vllm_entry(host_url.strip())
                if lang_key not in lang_hosts:
                    lang_hosts.setdefault(lang_key, []).append(entry)
                elif host_url.strip() not in [e.url for e in lang_hosts.get(lang_key, [])]:
                    lang_hosts[lang_key].append(entry)

    # --- Resolve per-language model overrides (Ollama) --------------------
    # Priority: --lang-model CLI > OLLAMA_LANG_MODELS env
    ollama_lang_models: dict[str, str] = {}
    for item in (args.lang_model or []):
        if "=" in item:
            lang, model = item.split("=", 1)
            ollama_lang_models[lang.strip()] = model.strip()
        else:
            parser.error(f"--lang-model must be in LANG=MODEL format, got: {item!r}")
    if env_ollama_lang_models := _env("OLLAMA_LANG_MODELS"):
        for item in env_ollama_lang_models.split(","):
            item = item.strip()
            if "=" in item:
                lang, model = item.split("=", 1)
                lang_key = lang.strip()
                if lang_key not in ollama_lang_models:
                    ollama_lang_models[lang_key] = model.strip()

    # --- Resolve per-language model overrides (LM Studio) -----------------
    # Priority: --lms-lang-model CLI > LMS_LANG_MODELS env
    lms_lang_models: dict[str, str] = {}
    for item in (args.lms_lang_model or []):
        if "=" in item:
            lang, model = item.split("=", 1)
            lms_lang_models[lang.strip()] = model.strip()
        else:
            parser.error(f"--lms-lang-model must be in LANG=MODEL format, got: {item!r}")
    if env_lms_lang_models := _env("LMS_LANG_MODELS"):
        for item in env_lms_lang_models.split(","):
            item = item.strip()
            if "=" in item:
                lang, model = item.split("=", 1)
                lang_key = lang.strip()
                if lang_key not in lms_lang_models:
                    lms_lang_models[lang_key] = model.strip()

    # --- Resolve per-language model overrides (vLLM) ----------------------
    # Priority: --vllm-lang-model CLI > VLLM_LANG_MODELS env
    vllm_lang_models: dict[str, str] = {}
    for item in (args.vllm_lang_model or []):
        if "=" in item:
            lang, model = item.split("=", 1)
            vllm_lang_models[lang.strip()] = model.strip()
        else:
            parser.error(f"--vllm-lang-model must be in LANG=MODEL format, got: {item!r}")
    if env_vllm_lang_models := _env("VLLM_LANG_MODELS"):
        for item in env_vllm_lang_models.split(","):
            item = item.strip()
            if "=" in item:
                lang, model = item.split("=", 1)
                lang_key = lang.strip()
                if lang_key not in vllm_lang_models:
                    vllm_lang_models[lang_key] = model.strip()

    first_host = hosts[0]
    return Config(
        folder=args.folder,
        source_lang=args.source_lang,
        target_langs=args.target_lang,
        host=first_host.url,
        model=first_host.model or "",
        api_key=first_host.api_key,
        api_secret=first_host.api_secret,
        auth_type=first_host.auth_type,
        backend=first_host.backend,
        batch_size=max(1, args.batch_size),
        timeout=max(10.0, args.timeout),
        reset=args.reset,
        dry_run=args.dry_run,
        verbose=args.verbose,
        context=args.context,
        char_rules=char_rules,
        project=args.project,
        hosts=hosts,
        lang_hosts=lang_hosts,
        ollama_lang_models=ollama_lang_models,
        lms_lang_models=lms_lang_models,
        vllm_lang_models=vllm_lang_models,
        source_file=args.source_file,
        old_source_file=args.old_source_file,
    )


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def discover_po_files(folder: str, source_lang: str) -> list[str]:
    """Return sorted list of .po file paths in <folder>/<source_lang>/."""
    source_dir = Path(folder) / source_lang
    if not source_dir.is_dir():
        return []
    return sorted(str(p) for p in source_dir.rglob("*.po"))


def resolve_target_langs(config: Config) -> list[str]:
    """Return the list of target language codes to process."""
    if config.target_langs:
        return config.target_langs

    root = Path(config.folder)
    if not root.is_dir():
        return []
    return sorted(
        d.name
        for d in root.iterdir()
        if d.is_dir() and d.name != config.source_lang
    )


def resolve_target_path(source_path: str, source_lang: str, target_lang: str) -> str:
    """Compute the target .po file path from the source path."""
    p = Path(source_path)
    # Replace the source_lang component in the path with target_lang
    parts = list(p.parts)
    for i, part in enumerate(parts):
        if part == source_lang:
            parts[i] = target_lang
            break
    return str(Path(*parts))


# ---------------------------------------------------------------------------
# Core translation logic
# ---------------------------------------------------------------------------

def _chunk(lst: list, size: int) -> list[list]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]


# ---------------------------------------------------------------------------
# Host probing and model-aware host assignment
# ---------------------------------------------------------------------------

def _probe_host(entry: HostEntry, timeout: float = 10.0) -> tuple[bool, list[str], str]:
    """
    Probe a host for connectivity and return its full list of available model IDs.

    Uses the OpenAI-compatible ``GET /v1/models`` endpoint (Ollama, LM Studio,
    and vLLM support this).

    Returns ``(True, [model_ids], message)`` on success.
    Returns ``(False, [], reason)`` on connection failure.
    """
    headers: dict[str, str] = {}
    if entry.auth_type == "cf":
        if entry.api_key and entry.api_secret:
            headers["CF-Access-Client-Id"] = entry.api_key
            headers["CF-Access-Client-Secret"] = entry.api_secret
        api_key = "ollama"
    elif entry.auth_type == "bearer":
        api_key = entry.api_key or ("vllm" if entry.backend == "vllm" else "lm-studio")
    else:
        api_key = "ollama"

    try:
        client = openai.OpenAI(
            base_url=f"{entry.url.rstrip('/')}/v1",
            api_key=api_key,
            default_headers=headers if headers else None,
            timeout=timeout,
        )
        model_ids = [m.id for m in client.models.list().data]
        return True, model_ids, f"{len(model_ids)} model(s) available"
    except Exception as exc:
        return False, [], f"unreachable — {exc.__class__.__name__}: {exc}"


def _probe_and_plan_host_assignment(
    config: Config,
    target_langs: list[str],
) -> tuple[list[str], dict[str, list[HostEntry]]]:
    """
    Probe all configured hosts in parallel, then plan which hosts serve each
    target language based on model availability and per-language model overrides.

    For each language, a host qualifies when:
    - The host is reachable, AND
    - The required model (from ``ollama_lang_models`` / ``lms_lang_models`` /
      ``vllm_lang_models``, or the host's default model) appears in the host's
      available model list.

    When ``OLLAMA_LANG_HOSTS`` / ``LMS_LANG_HOSTS`` / ``VLLM_LANG_HOSTS`` pins
    specific hosts to a language, those hosts are still validated in the same
    way.

    Returns ``(processable_langs, {lang: [HostEntry_with_model_set]})``.
    """
    # Collect unique hosts by URL (one representative HostEntry per URL).
    url_to_entry: dict[str, HostEntry] = {}
    for e in config.hosts:
        url_to_entry[e.url] = e
    for entries in config.lang_hosts.values():
        for e in entries:
            url_to_entry[e.url] = e

    if not url_to_entry:
        return list(target_langs), {}

    print(f"[translate] Probing {len(url_to_entry)} host(s)...")
    probe: dict[str, tuple[bool, list[str], str]] = {}
    with ThreadPoolExecutor(max_workers=len(url_to_entry)) as probe_pool:
        future_to_url = {
            probe_pool.submit(_probe_host, entry): entry.url
            for entry in url_to_entry.values()
        }
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                ok, models, msg = future.result()
            except Exception as exc:
                ok, models, msg = False, [], str(exc)
            probe[url] = (ok, models, msg)

    # Display results sorted by URL.
    for url, (ok, models, msg) in sorted(probe.items()):
        status = "OK" if ok else "NG"
        if ok and models:
            models_str = ", ".join(models[:6])
            if len(models) > 6:
                models_str += f" … ({len(models)} total)"
            print(f"[translate]   {status} {url}  models: {models_str}")
        else:
            print(f"[translate]   {status} {url}  {msg}")

    def _required_model(e: HostEntry, lang: str) -> str:
        """Return the model that should be used for *lang* on host *e*."""
        if e.backend == "lmstudio":
            return config.lms_lang_models.get(lang, e.model)
        if e.backend == "vllm":
            return config.vllm_lang_models.get(lang, e.model)
        return config.ollama_lang_models.get(lang, e.model or config.model)

    assignment: dict[str, list[HostEntry]] = {}
    processable: list[str] = []
    for lang in target_langs:
        candidates = config.lang_hosts.get(lang, config.hosts)
        lang_entries: list[HostEntry] = []
        for e in candidates:
            ok, available_models, _ = probe.get(e.url, (False, [], ""))
            if not ok:
                continue
            required = _required_model(e, lang)
            if required and required not in available_models:
                continue
            lang_entries.append(dataclasses.replace(e, model=required))

        if lang_entries:
            assignment[lang] = lang_entries
            processable.append(lang)

    return processable, assignment


def translate_language(
    config: Config,
    source_files: list[str],
    lang: str,
    host_list: list[HostEntry],
    changed_keys: set[str] | None = None,
) -> dict:
    """
    Translate all source files for one target language.

    host_list: one or more host entries for this language.  When multiple
    hosts are given, batches are submitted to all of them concurrently (one
    request per host at a time) to maximise throughput.

    Returns a stats dict:
      translated      -- entries newly sent to the LLM and translated this run
      from_checkpoint -- entries reused from a previous checkpoint
      preserved       -- entries kept unchanged from the existing target file
      failed_batches  -- number of batches the LLM could not complete
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

    stats = {"translated": 0, "from_checkpoint": 0, "preserved": 0, "failed_batches": 0, "skipped_untranslated": 0}

    # Build one LLMClient per host for this language.
    clients = [
        LLMClient(dataclasses.replace(
            config,
            host=h.url,
            api_key=h.api_key,
            api_secret=h.api_secret,
            auth_type=h.auth_type,
            backend=h.backend,
            model=h.model or "",
        ))
        for h in host_list
    ]
    multi_host = len(clients) > 1

    for source_path in source_files:
        target_path = resolve_target_path(source_path, config.source_lang, lang)
        source_basename = Path(source_path).name

        entries = po_helper.get_untranslated(
            source_path, target_path, lang, changed_keys,
            ignore_existing=config.reset,
        )
        total = po_helper.count_entries(source_path)

        checkpoint = po_helper.load_checkpoint(config.folder, lang, config.reset, config.project)
        # Filter entries already in checkpoint.
        # Changed-source entries always bypass the checkpoint so their new
        # source text gets re-translated (the checkpoint may hold a stale
        # translation based on the old source text).
        # Entries whose checkpointed translation looks wrong (foreign unique
        # chars or wrong script for the target language) are also re-queued.
        remaining = [
            e for e in entries
            if e.msgctxt not in checkpoint
            or (changed_keys and e.msgctxt in changed_keys)
            or po_helper._needs_requeue_from_checkpoint(
                checkpoint.get(e.msgctxt, ""), e.source_text(), lang
            )
        ]

        preserved = total - len(entries)
        already_done = len(entries) - len(remaining)
        changed_count = sum(1 for e in entries if changed_keys and e.msgctxt in changed_keys)

        stats["preserved"] += preserved
        stats["from_checkpoint"] += already_done

        status_parts = [f"{preserved} preserved", f"{already_done} already checkpointed"]
        if changed_count:
            status_parts.append(f"{changed_count} changed-source")
        print(
            f"[translate] {source_basename} → {lang}: "
            f"{len(entries)} to translate ({', '.join(status_parts)})"
        )

        if config.dry_run:
            print(f"[translate] --dry-run: skipping actual translation for {lang}")
            continue

        if not remaining:
            print(f"[translate] {lang}: nothing to do — merging checkpoint.")
            po_helper.merge(source_path, target_path, checkpoint, lang)
            continue

        batches = _chunk(remaining, config.batch_size)
        total_batches = len(batches)
        completed = already_done
        last_progress_time = time.time()
        _PROGRESS_INTERVAL = 180  # seconds — always print at least this often

        def _apply_batch_results(
            batch_idx: int,
            batch: list,
            batch_entries: list[dict],
            results: list[dict],
            host_tag: str,
        ) -> None:
            """Apply translated results to checkpoint and update stats (called from main thread)."""
            nonlocal completed, last_progress_time

            if len(results) < len(batch_entries):
                stats["failed_batches"] += 1

            for r in results:
                src_text = next(
                    (e["msgstr"] for e in batch_entries if e["msgctxt"] == r["msgctxt"]),
                    None,
                )
                translated = r["msgstr"]
                ruby_reject = po_helper._has_ruby_markup(translated)
                normalized_translated = po_helper._flatten_ruby_to_visible_text(translated)
                src_script = _dominant_script(src_text or "")
                tgt_script = _dominant_script(normalized_translated)
                expected_tgt_script = po_helper._lang_script(lang)
                # Reject if LLM returned same non-Latin script as source (bad translation),
                # but skip this check when source and target legitimately share a script
                # (e.g. ja→zh: both are CJK, so same-script output is expected to be correct).
                same_script_reject = (
                    src_text is not None
                    and src_script not in ("latin", "other")
                    and tgt_script == src_script
                    and expected_tgt_script != src_script
                )
                # Reject if the translation contains characters from the unique Unicode
                # ranges of a language other than the target (e.g. kana in ZH output,
                # Hangul in ZH output).  Catches shared-script pairs where same_script_reject
                # is intentionally skipped.
                foreign_chars_reject = po_helper._has_foreign_unique_chars(translated, lang)
                # Reject if source is non-Latin AND target expects a non-Latin script,
                # but the translation arrived in a completely different script
                # (e.g. "Good morning" as Chinese Traditional output).
                wrong_script_reject = (
                    src_text is not None
                    and src_script not in ("latin", "other")
                    and expected_tgt_script not in ("latin", "other")
                    and tgt_script != expected_tgt_script
                )
                placeholder_reject = (
                    src_text is not None
                    and po_helper._has_placeholder_mismatch(src_text, translated)
                )
                if ruby_reject or same_script_reject or foreign_chars_reject or wrong_script_reject or placeholder_reject:
                    stats["skipped_untranslated"] += 1
                    if config.verbose:
                        if ruby_reject:
                            reason = "ruby-markup"
                        elif placeholder_reject:
                            reason = "placeholder-mismatch"
                        elif foreign_chars_reject:
                            reason = "foreign-unique-chars"
                        elif wrong_script_reject:
                            reason = "wrong-script"
                        else:
                            reason = "source-script"
                        print(
                            f"[translate] WARNING: LLM returned {reason} text for "
                            f"{r['msgctxt']!r} — will retry next run"
                        )
                else:
                    checkpoint[r["msgctxt"]] = translated

            po_helper.save_checkpoint(config.folder, lang, checkpoint, source_basename, config.project)
            completed += len(batch)
            stats["translated"] += len(results)

            now = time.time()
            time_due = (now - last_progress_time) >= _PROGRESS_INTERVAL
            if multi_host or config.verbose \
                    or time_due \
                    or (batch_idx + 1) % max(1, total_batches // 5) == 0 \
                    or (batch_idx + 1) == total_batches:
                host_info = f" [{host_tag}]" if multi_host else ""
                print(
                    f"[translate] {lang}: batch {batch_idx + 1}/{total_batches} "
                    f"({completed}/{total} entries){host_info}"
                )
                last_progress_time = now

        if not multi_host:
            # ---- Single-host: sequential batches (original behaviour) -------
            client = clients[0]
            for batch_idx, batch in enumerate(batches):
                batch_entries = [
                    {"msgctxt": e.msgctxt, "msgstr": e.source_text()}
                    for e in batch
                ]
                try:
                    results = client.translate_batch(batch_entries, config.source_lang, lang)
                except Exception as exc:
                    print(
                        f"[translate] WARNING: batch {batch_idx + 1}/{total_batches} failed "
                        f"({exc.__class__.__name__}: {exc}) — skipping batch"
                    )
                    stats["failed_batches"] += 1
                    continue
                _apply_batch_results(batch_idx, batch, batch_entries, results, host_list[0].url)

        else:
            # ---- Multi-host: submit all batches concurrently ----------------
            # Each batch is assigned round-robin to a client; all LLM calls run
            # in parallel threads.  Results are applied sequentially in the
            # order they finish so the checkpoint is always consistent.
            all_batch_entries = [
                [{"msgctxt": e.msgctxt, "msgstr": e.source_text()} for e in batch]
                for batch in batches
            ]
            future_to_meta: dict = {}
            with ThreadPoolExecutor(max_workers=len(clients)) as batch_executor:
                for batch_idx, (batch, batch_entries) in enumerate(
                    zip(batches, all_batch_entries)
                ):
                    client = clients[batch_idx % len(clients)]
                    host_tag = host_list[batch_idx % len(host_list)].url
                    f = batch_executor.submit(
                        client.translate_batch, batch_entries, config.source_lang, lang
                    )
                    future_to_meta[f] = (batch_idx, batch, batch_entries, host_tag)

                for future in _as_completed(future_to_meta):
                    batch_idx, batch, batch_entries, host_tag = future_to_meta[future]
                    try:
                        results = future.result()
                    except Exception as exc:
                        print(
                            f"[translate] WARNING: batch {batch_idx + 1}/{total_batches} "
                            f"failed ({exc.__class__.__name__}: {exc}) — skipping batch"
                        )
                        stats["failed_batches"] += 1
                        continue
                    _apply_batch_results(batch_idx, batch, batch_entries, results, host_tag)

        po_helper.merge(source_path, target_path, checkpoint, lang)
        print(f"[translate] {lang}: written → {target_path}")

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    config = parse_args()
    changed_keys: set[str] = set()

    if config.source_file:
        # ---- File mode ------------------------------------------------
        source_path = Path(config.source_file)
        if not source_path.is_file():
            print(f"[translate] ERROR: Source file not found: {config.source_file}", file=sys.stderr)
            return 3

        # Infer folder and source_lang from file path
        # e.g. Localization/Game/ja/Game.po → source_lang=ja, folder=Localization/Game
        config.source_lang = source_path.parent.name
        config.folder = str(source_path.parent.parent)
        source_files = [config.source_file]

        if config.old_source_file:
            old_path = Path(config.old_source_file)
            if not old_path.is_file():
                print(f"[translate] ERROR: Old source file not found: {config.old_source_file}", file=sys.stderr)
                return 3
            changed_keys = po_helper.get_changed_msgctxts(config.source_file, config.old_source_file)
            print(
                f"[translate] File mode: {source_path.name} "
                f"({len(changed_keys)} changed-source entries + untranslated)"
            )
        else:
            print(f"[translate] File mode: {source_path.name} (untranslated entries only)")
    else:
        # ---- Folder mode ----------------------------------------------
        source_files = discover_po_files(config.folder, config.source_lang)
        if not source_files:
            source_dir = Path(config.folder) / config.source_lang
            print(f"[translate] ERROR: No .po files found in {source_dir}", file=sys.stderr)
            return 3

    target_langs = resolve_target_langs(config)
    if not target_langs:
        print(
            f"[translate] ERROR: No target languages found. "
            f"Specify --target-lang or add sibling directories to {config.folder}",
            file=sys.stderr,
        )
        return 2

    # Probe all hosts and plan model-aware assignment per language.
    processable, host_assignment = _probe_and_plan_host_assignment(config, target_langs)

    skipped_by_probe = [lang for lang in target_langs if lang not in processable]
    if skipped_by_probe:
        print(
            f"[translate] WARNING: Skipping languages (no available host/model): "
            f"{', '.join(skipped_by_probe)}",
            file=sys.stderr,
        )
    if not processable:
        print(
            "[translate] ERROR: No languages can be processed — all configured hosts "
            "are unreachable or the required model is not loaded.",
            file=sys.stderr,
        )
        return 4

    target_langs = processable
    unique_hosts = sorted({h.url for hosts in host_assignment.values() for h in hosts})

    total_entries = sum(po_helper.count_entries(f) for f in source_files)
    if not config.source_file:
        print(
            f"[translate] Source: {config.folder}/{config.source_lang} "
            f"({len(source_files)} file(s), {total_entries} entries)"
        )
    print(f"[translate] Target languages: {', '.join(target_langs)}")

    # Model display: one line when uniform across all languages, per-lang table otherwise.
    all_lang_models = {
        lang: sorted({h.model for h in host_assignment[lang]})
        for lang in target_langs
    }
    distinct_models = {m for ms in all_lang_models.values() for m in ms}
    if len(distinct_models) == 1:
        print(f"[translate] Model: {next(iter(distinct_models))}")
    else:
        print("[translate] Models (per language):")
        for lang in target_langs:
            print(f"[translate]   {lang:<6} → {', '.join(all_lang_models[lang])}")

    if len(unique_hosts) == 1:
        print(f"[translate] Host: {unique_hosts[0]}")
    else:
        print(f"[translate] Hosts ({len(unique_hosts)} unique, parallel):")
        for lang in target_langs:
            hosts = host_assignment[lang]
            model_info = (
                "" if len(distinct_models) == 1
                else f"  [{', '.join(sorted({h.model for h in hosts}))}]"
            )
            if len(hosts) == 1:
                print(f"[translate]   {lang:<6} → {hosts[0].url}{model_info}")
            else:
                print(
                    f"[translate]   {lang:<6} → "
                    f"{', '.join(h.url for h in hosts)}"
                    f"  ({len(hosts)} hosts, batches distributed){model_info}"
                )
    cache_dir = po_helper._checkpoint_dir(config.folder, config.project)
    print(f"[translate] Cache: {cache_dir}")

    if config.dry_run:
        print("[translate] --dry-run mode: no files will be written")

    all_ok = True
    lang_stats: dict[str, dict] = {}
    run_start = time.perf_counter()

    # Use one worker per unique host so each host gets exactly one concurrent
    # request (Ollama processes requests sequentially per model anyway).
    max_workers = len(unique_hosts)

    def _run_lang(lang: str) -> tuple[str, dict]:
        lang_start = time.perf_counter()
        stats = translate_language(config, source_files, lang, host_assignment[lang], changed_keys or None)
        stats["elapsed"] = time.perf_counter() - lang_start
        return lang, stats

    if max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_run_lang, lang): lang for lang in target_langs}
            for future in as_completed(futures):
                lang, stats = future.result()
                lang_stats[lang] = stats
                if stats["failed_batches"]:
                    all_ok = False
    else:
        for lang in target_langs:
            lang, stats = _run_lang(lang)
            lang_stats[lang] = stats
            if stats["failed_batches"]:
                all_ok = False

    total_elapsed = time.perf_counter() - run_start

    # ---- Summary --------------------------------------------------------
    def _fmt_time(seconds: float) -> str:
        s = int(seconds)
        h, remainder = divmod(s, 3600)
        m, sec = divmod(remainder, 60)
        if h:
            return f"{h}h {m}m {sec}s"
        if m:
            return f"{m}m {sec}s"
        return f"{seconds:.1f}s"

    print()
    print("[translate] ================================================")
    print("[translate]  Summary")
    print("[translate] ------------------------------------------------")
    for lang, s in lang_stats.items():
        if config.dry_run:
            note = "  (dry run)"
            print(f"[translate]   {lang:<6}  {s['translated']:>5} translated"
                  f"  {s['from_checkpoint']:>5} from checkpoint"
                  f"  {s['preserved']:>5} preserved{note}")
        else:
            warn = ""
            if s["failed_batches"]:
                warn += f"  [{s['failed_batches']} batch(es) failed]"
            if s["skipped_untranslated"]:
                warn += f"  [{s['skipped_untranslated']} untranslated by LLM]"
            print(f"[translate]   {lang:<6}  {s['translated']:>5} translated"
                  f"  {s['from_checkpoint']:>5} from checkpoint"
                  f"  {s['preserved']:>5} preserved"
                  f"  [{_fmt_time(s['elapsed'])}]{warn}")
    print("[translate] ------------------------------------------------")
    print(f"[translate]  Total time: {_fmt_time(total_elapsed)}")
    print("[translate] ================================================")

    if all_ok:
        return 0
    else:
        print("[translate] Done with warnings. Some batches failed — re-run to retry.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
