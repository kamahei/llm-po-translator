"""
translate.py — Main CLI entry point for POTranslatorLLM.

Usage:
    python translate.py --folder <path> --source-lang <code> [options]

See docs/user-manual.md for full usage documentation.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys
import time
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
class Config:
    folder: str
    source_lang: str
    target_langs: list[str] = field(default_factory=list)
    host: str = "http://localhost:11434"
    model: str = "qwen2.5:7b"
    api_key: str = ""
    api_secret: str = ""
    batch_size: int = 20
    timeout: float = 120.0
    reset: bool = False
    dry_run: bool = False
    verbose: bool = False
    context: str = ""
    project: str = ""
    # Multi-host fields
    hosts: list[str] = field(default_factory=list)      # all available hosts (non-empty)
    lang_hosts: dict[str, list[str]] = field(default_factory=dict)  # lang -> [host, ...] override
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
            "Translate .po files using a local LLM (Ollama).\n\n"
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
        help="Ollama server base URL (default: http://localhost:11434)",
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
            "Assign a host to a specific language (e.g. en=http://host2:11434). "
            "Repeat the same LANG to assign multiple hosts — batches are distributed "
            "across all assigned hosts in parallel. "
            "Env: OLLAMA_LANG_HOSTS (comma-separated LANG=URL pairs)."
        ),
    )
    parser.add_argument(
        "--model",
        default=_env("OLLAMA_MODEL", "qwen2.5:7b"),
        help="Ollama model name (default: qwen2.5:7b)",
    )
    parser.add_argument(
        "--api-key",
        default=_env("CF_ACCESS_CLIENT_ID"),
        help="Cloudflare Access Client ID (for external server)",
    )
    parser.add_argument(
        "--api-secret",
        default=_env("CF_ACCESS_CLIENT_SECRET"),
        help="Cloudflare Access Client Secret",
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

    # --- Resolve host pool ------------------------------------------------
    # Priority: --hosts CLI > OLLAMA_HOSTS env > --host CLI > OLLAMA_HOST env
    hosts: list[str] = []
    if args.hosts:
        hosts = args.hosts
    elif env_hosts := _env("OLLAMA_HOSTS"):
        hosts = [h.strip() for h in env_hosts.split(",") if h.strip()]
    else:
        hosts = [args.host]

    # --- Resolve language-to-host overrides -------------------------------
    # Priority: --lang-host CLI > OLLAMA_LANG_HOSTS env
    # Multiple --lang-host entries for the same language assign multiple hosts,
    # and batches are distributed across all of them in parallel.
    lang_hosts: dict[str, list[str]] = {}
    for item in (args.lang_host or []):
        if "=" in item:
            lang, host_url = item.split("=", 1)
            lang_hosts.setdefault(lang.strip(), []).append(host_url.strip())
        else:
            parser.error(f"--lang-host must be in LANG=URL format, got: {item!r}")
    if env_lang_hosts := _env("OLLAMA_LANG_HOSTS"):
        for item in env_lang_hosts.split(","):
            item = item.strip()
            if "=" in item:
                lang, host_url = item.split("=", 1)
                if lang.strip() not in lang_hosts:
                    lang_hosts.setdefault(lang.strip(), []).append(host_url.strip())
                elif host_url.strip() not in lang_hosts[lang.strip()]:
                    lang_hosts[lang.strip()].append(host_url.strip())

    return Config(
        folder=args.folder,
        source_lang=args.source_lang,
        target_langs=args.target_lang,
        host=hosts[0],
        model=args.model,
        api_key=args.api_key or "",
        api_secret=args.api_secret or "",
        batch_size=max(1, args.batch_size),
        timeout=max(10.0, args.timeout),
        reset=args.reset,
        dry_run=args.dry_run,
        verbose=args.verbose,
        context=args.context,
        project=args.project,
        hosts=hosts,
        lang_hosts=lang_hosts,
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


def _assign_hosts(target_langs: list[str], config: Config) -> dict[str, list[str]]:
    """
    Return {lang: [host_url, ...]} for all target languages.

    Manual overrides (--lang-host / OLLAMA_LANG_HOSTS) take priority and may
    specify multiple hosts per language — batches are distributed across all of
    them in parallel.
    Remaining languages receive a single host, assigned round-robin from the pool.
    """
    result: dict[str, list[str]] = {}
    pool = config.hosts  # guaranteed non-empty by parse_args

    # Apply manual overrides first (already a list[str])
    for lang in target_langs:
        if lang in config.lang_hosts:
            result[lang] = config.lang_hosts[lang]

    # Round-robin assignment for unassigned langs (single host each)
    unassigned = [l for l in target_langs if l not in result]
    for i, lang in enumerate(unassigned):
        result[lang] = [pool[i % len(pool)]]

    return result


def translate_language(
    config: Config,
    source_files: list[str],
    lang: str,
    host_list: list[str],
    changed_keys: set[str] | None = None,
) -> dict:
    """
    Translate all source files for one target language.

    host_list: one or more Ollama host URLs for this language.  When multiple
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
    clients = [LLMClient(dataclasses.replace(config, host=h)) for h in host_list]
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
                src_script = _dominant_script(src_text or "")
                tgt_script = _dominant_script(translated)
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
                if same_script_reject or foreign_chars_reject or wrong_script_reject:
                    stats["skipped_untranslated"] += 1
                    if config.verbose:
                        if foreign_chars_reject:
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
                _apply_batch_results(batch_idx, batch, batch_entries, results, host_list[0])

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
                    host_tag = host_list[batch_idx % len(host_list)]
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

    # Assign hosts to languages (round-robin + manual overrides)
    host_assignment = _assign_hosts(target_langs, config)
    unique_hosts = sorted({h for hosts in host_assignment.values() for h in hosts})

    total_entries = sum(po_helper.count_entries(f) for f in source_files)
    if not config.source_file:
        print(
            f"[translate] Source: {config.folder}/{config.source_lang} "
            f"({len(source_files)} file(s), {total_entries} entries)"
        )
    print(f"[translate] Target languages: {', '.join(target_langs)}")
    print(f"[translate] Model: {config.model}")
    if len(unique_hosts) == 1:
        print(f"[translate] Host: {unique_hosts[0]}")
    else:
        print(f"[translate] Hosts ({len(unique_hosts)} unique, parallel):")
        for lang in target_langs:
            hosts = host_assignment[lang]
            if len(hosts) == 1:
                print(f"[translate]   {lang} → {hosts[0]}")
            else:
                print(f"[translate]   {lang} → {', '.join(hosts)}  ({len(hosts)} hosts, batches distributed)")
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
