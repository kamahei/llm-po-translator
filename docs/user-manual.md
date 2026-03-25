# User Manual — POTranslatorLLM

This guide explains how to use POTranslatorLLM to translate `.po` localization files using a local or shared LLM.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Quick Start — Local Mode](#3-quick-start--local-mode)
4. [Quick Start — Remote Server Mode](#4-quick-start--remote-server-mode)
5. [File Mode — Translate Only Changed & Untranslated Entries](#5-file-mode--translate-only-changed--untranslated-entries)
6. [Multi-Host Parallel Translation](#6-multi-host-parallel-translation)
7. [CLI Reference](#7-cli-reference)
8. [Configuration](#8-configuration)
9. [Understanding the Output](#9-understanding-the-output)
10. [Translation Rules and Behavior](#10-translation-rules-and-behavior)
11. [Resuming an Interrupted Translation](#11-resuming-an-interrupted-translation)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Overview

POTranslatorLLM translates `.po` (gettext) localization files using a Large Language Model (LLM) running locally on your computer or on a shared team server. No internet connection, cloud API key, or GitHub Copilot subscription is required.

**Supported workflows:**

| Mode | When to use |
|---|---|
| **Local mode** | You have a capable GPU or CPU and want to run the LLM on your own machine |
| **LAN mode** | Your team has a shared server on the local network |
| **External mode** | The shared server is accessed via Cloudflare Tunnel from outside the LAN |

---

## 2. Prerequisites

- Windows 10 or Windows 11 (64-bit)
- Python 3.9 or later — download from https://www.python.org/downloads/
- Git (optional, for cloning the repository)

For **local mode** only:
- At least 8 GB RAM (16 GB or more recommended for 7B models)
- NVIDIA GPU with 8 GB VRAM (recommended for speed); CPU-only is supported but slower

For **LAN or external mode** only:
- The server IP address or domain name
- Your Cloudflare Access credentials (if using external mode) — provided by your server administrator

---

## 3. Quick Start — Local Mode

### Step 1: Set Up Ollama

Open **PowerShell** and run the setup script:

```powershell
cd POTranslatorLLM
.\setup\install-local.ps1
```

This script installs Ollama, downloads the `qwen2.5:7b` model, and installs the required Python packages. It takes a few minutes depending on your internet connection.

You can verify Ollama is running:
```powershell
ollama list
```

You should see `qwen2.5:7b` in the list.

### Step 2: Install Python Dependencies (if not done by setup script)

```powershell
pip install -r setup\requirements.txt
```

### Step 3: Run Translation

```powershell
python scripts/translate.py --folder Localization/Game --source-lang ja
```

This translates all sibling language folders under `Localization/Game/` relative to `ja`.

To translate into a specific language:
```powershell
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en
```

To translate into multiple languages:
```powershell
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en zh fr
```

---

## 4. Quick Start — Remote Server Mode

### Step 1: Receive Credentials from Your Administrator

For **LAN access**, ask your administrator for:
- The server's LAN IP address (e.g., `192.168.1.100`)

For **external access**, ask your administrator for:
- The Cloudflare Tunnel domain (e.g., `llm.example.com`)
- Your personal `CF_ACCESS_CLIENT_ID`
- Your personal `CF_ACCESS_CLIENT_SECRET`

### Step 2: Install Python Dependencies

```powershell
pip install -r setup\requirements.txt
```

### Step 3: Configure Your `.env` File

Copy the example config:
```powershell
Copy-Item config\config.example.env .env
```

Edit `.env` with a text editor. For LAN access:
```ini
OLLAMA_HOST=http://192.168.1.100:11434
OLLAMA_MODEL=qwen2.5:7b
```

For external (Cloudflare Tunnel) access:
```ini
OLLAMA_HOST=https://llm.example.com
OLLAMA_MODEL=qwen2.5:7b
CF_ACCESS_CLIENT_ID=your-client-id-here
CF_ACCESS_CLIENT_SECRET=your-client-secret-here
```

### Step 4: Run Translation

```powershell
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en
```

No additional flags are needed — credentials are read from `.env` automatically.

---

## 5. File Mode — Translate Only Changed & Untranslated Entries

**File mode** is designed for incremental updates: when the source `.po` file has been updated
and you only want to (re-)translate what actually changed, without touching entries that already
have a valid human translation.

### When to use file mode

- The game or app has shipped with an existing translated `.po` file.
- The source text was updated (new entries added, or existing `msgid`/`msgstr` changed).
- You want to re-translate only the updated and missing entries, leaving the rest untouched.

### How it works

1. **Untranslated entries** (target `msgstr` empty or equal to source text) are always translated.
2. **Changed-source entries** (entries that exist in `--old-source-file` with different text than in
   `--source-file`) are re-translated even if the target already had a translation.
3. **Unchanged, already-translated entries** are preserved exactly as-is.

### Basic usage (untranslated entries only)

```powershell
# Translate only untranslated entries in Game.po → English and French
python scripts/translate.py --source-file Localization/Game/ja/Game.po --target-lang en fr
```

The tool infers the localization root and source language from the file path:
- `Localization/Game/ja/Game.po` → root = `Localization/Game`, source lang = `ja`
- Target files are resolved at `Localization/Game/<lang>/Game.po`

### Changed-source detection (with old version of source file)

Supply the previous version of the source `.po` file with `--old-source-file`.
Any entry whose source text differs between the old and current file will be re-translated.

```powershell
python scripts/translate.py \
  --source-file Localization/Game/ja/Game.po \
  --old-source-file Localization/Game/ja/Game_old.po \
  --target-lang en fr
```

### Dry run to preview what will be translated

```powershell
python scripts/translate.py \
  --source-file Localization/Game/ja/Game.po \
  --old-source-file Localization/Game/ja/Game_old.po \
  --target-lang en fr \
  --dry-run
```

Output example:
```
[translate] File mode: Game.po (12 changed-source entries + untranslated)
[translate] Target languages: en fr
[translate] Game.po → en: 14 to translate (233 preserved, 0 already checkpointed)
[translate] --dry-run: skipping actual translation for en
```

---

## 6. Multi-Host Parallel Translation

When translating into many languages, you can use multiple Ollama servers simultaneously to significantly reduce total translation time.

### How it works

There are two levels of parallelism:

| Level | When | Behaviour |
|---|---|---|
| **Language-level** | Multiple languages, multiple hosts | Each language runs in its own thread, one per unique host |
| **Batch-level** | One language, multiple hosts assigned | Batches are distributed concurrently across all hosts for that language |

- Languages are distributed **round-robin** across the host pool automatically.
- You can **pin a language to multiple hosts** (repeat `--lang-host` for the same language) — batches are then split across all those hosts in parallel.
- You can **pin a language to a single host** for cache locality (the LLM's KV cache is warmer when the same host always handles the same language).

### Configuration — via `.env`

```ini
# Multiple hosts (comma-separated)
OLLAMA_HOSTS=http://server1:11434,http://server2:11434,http://server3:11434

# Pin languages to hosts (comma-separated LANG=URL pairs).
# Repeat the same language to assign multiple hosts (batch distribution).
OLLAMA_LANG_HOSTS=en=http://server1:11434,en=http://server2:11434,fr=http://server3:11434
```

### Configuration — via CLI

```powershell
# Translate en/fr/de in parallel across two servers (round-robin: en→s1, fr→s2, de→s1)
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en fr de `
    --hosts http://server1:11434 http://server2:11434

# Pin fr to a single server; auto-assign en and de round-robin
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en fr de `
    --hosts http://server1:11434 http://server2:11434 `
    --lang-host fr=http://server3:11434

# Assign TWO hosts to English — batches distributed in parallel across both
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en fr `
    --lang-host en=http://server1:11434 --lang-host en=http://server2:11434 `
    --lang-host fr=http://server3:11434
```

### Output with multiple hosts

```
[translate] Model: qwen2.5:7b
[translate] Hosts (3 unique, parallel):
[translate]   en → http://server1:11434, http://server2:11434  (2 hosts, batches distributed)
[translate]   fr → http://server3:11434
[translate]   de → http://server1:11434
[translate] Cache: C:\Users\...\AppData\Local\Temp\po_translator_MyGame
```

When a language has multiple hosts, each batch progress line shows which host handled it:

```
[translate] en: batch 1/13 (20/247 entries) [http://server1:11434]
[translate] en: batch 2/13 (40/247 entries) [http://server2:11434]
```

Progress lines from different languages or hosts appear interleaved — this is normal. The final summary reports each language separately.

---

## 7. CLI Reference

### Basic Usage — Folder mode

```
python scripts/translate.py --folder <path> --source-lang <code> [options]
```

### Basic Usage — File mode

```
python scripts/translate.py --source-file <current.po> [--old-source-file <old.po>] --target-lang <code...> [options]
```

### Folder Mode Arguments

| Argument | Description | Example |
|---|---|---|
| `--folder <path>` | Path to the localization root folder | `Localization/Game` |
| `--source-lang <code>` | Source language directory name | `ja` |

### File Mode Arguments

| Argument | Description | Example |
|---|---|---|
| `--source-file <file>` | Current source `.po` file (triggers file mode) | `Localization/Game/ja/Game.po` |
| `--old-source-file <file>` | Previous version of source file (for changed-source detection) | `Game_old.po` |

### Shared Optional Arguments

| Argument | Default | Description |
|---|---|---|
| `--target-lang <code...>` | all siblings | Target language code(s). Specify one or more separated by spaces. |
| `--host <url>` | `http://localhost:11434` | Ollama server URL (single host) |
| `--hosts <url...>` | *(none)* | Multiple Ollama server URLs for parallel translation (space-separated). Overrides `--host`. |
| `--lang-host <LANG=URL>` | *(none)* | Assign a host to a specific language. Repeat the same `LANG` to assign multiple hosts — batches are distributed across all of them in parallel. |
| `--model <name>` | `qwen2.5:7b` | Model to use |
| `--api-key <id>` | *(from `.env`)* | Cloudflare Access Client ID |
| `--api-secret <secret>` | *(from `.env`)* | Cloudflare Access Client Secret |
| `--batch-size <n>` | `20` | Entries per LLM request (reduce if you see errors) |
| `--timeout <seconds>` | `120` | Max wait time per LLM request |
| `--reset` | false | Discard previous progress and restart from scratch |
| `--dry-run` | false | Show what would be translated without writing any files |
| `--verbose` | false | Show detailed per-batch progress |
| `--context <text>` | *(none)* | Translation context hint, e.g., `"video game dialogue"` |
| `--project <name>` | *(none)* | Project name for the checkpoint cache folder. When set, cache is stored in `%TEMP%\po_translator_<name>` — predictable and consistent across machines. Env: `TRANSLATE_PROJECT`. |

### Examples

```powershell
# Translate everything (all sibling languages)
python scripts/translate.py --folder Localization/Game --source-lang ja

# Translate Japanese → English only
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en

# Translate Japanese → English and Chinese
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en zh

# Use a different model
python scripts/translate.py --folder Localization/Game --source-lang ja --model llama3.1:8b

# Dry run (check what needs translation, no writes)
python scripts/translate.py --folder Localization/Game --source-lang ja --dry-run

# Reset progress and retranslate everything
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en --reset

# Add translation context
python scripts/translate.py --folder Localization/Game --source-lang ja --context "action RPG game dialogue and UI"

# Name the cache folder (recommended for teams — same path on every machine)
python scripts/translate.py --folder Localization/Game --source-lang ja --project MyGame

# File mode — untranslated entries only
python scripts/translate.py --source-file Localization/Game/ja/Game.po --target-lang en fr

# File mode — re-translate entries whose source changed since old version
python scripts/translate.py --source-file Localization/Game/ja/Game.po --old-source-file Localization/Game/ja/Game_old.po --target-lang en fr

# Multi-host: translate en/fr/de in parallel across two servers
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en fr de \
    --hosts http://server1:11434 http://server2:11434

# Multi-host: pin fr to a specific server, auto-assign the rest
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en fr de \
    --hosts http://server1:11434 http://server2:11434 \
    --lang-host fr=http://server3:11434
```

---

## 8. Configuration

### `.env` File

Create a `.env` file in the **repo root directory** (the same folder as `README.md`) to set default values for all CLI options. CLI arguments override `.env` values.

```ini
# Ollama server URL (single host)
OLLAMA_HOST=http://localhost:11434

# Multiple Ollama hosts for parallel translation (comma-separated, overrides OLLAMA_HOST)
# Example: OLLAMA_HOSTS=http://server1:11434,http://server2:11434
OLLAMA_HOSTS=

# Pin languages to hosts (comma-separated LANG=URL pairs).
# Repeat the same language for multiple hosts (batches distributed across all of them).
# Example: OLLAMA_LANG_HOSTS=en=http://server1:11434,en=http://server2:11434,fr=http://server3:11434
OLLAMA_LANG_HOSTS=

# Model name
OLLAMA_MODEL=qwen2.5:7b

# Cloudflare Access credentials (leave empty if not using external server)
CF_ACCESS_CLIENT_ID=
CF_ACCESS_CLIENT_SECRET=

# Entries per LLM request
TRANSLATE_BATCH_SIZE=20

# LLM request timeout in seconds
TRANSLATE_TIMEOUT=120

# Default translation context
TRANSLATE_CONTEXT=

# Project name for the checkpoint cache directory.
# When set, checkpoints are stored in %TEMP%\po_translator_<NAME> so the cache
# path is predictable and consistent across all team members' machines.
# Leave empty to use an auto-generated hash based on the source folder path.
TRANSLATE_PROJECT=
```

> **Security note:** Never commit your `.env` file to version control if it contains credentials. Add `.env` to your `.gitignore`.

### Choosing a Model

**Recommended models for translation:**

| Model | Best for | VRAM | Notes |
|---|---|---|---|
| `translategemma:4b` | Translation-only tasks | 4–6 GB | Purpose-built for translation; good starting point |
| `translategemma:12b` | Higher translation quality | 8–12 GB | Best quality/speed balance |
| `qwen2.5:7b` | Japanese / Chinese / Korean source text | 6–8 GB | Strong East-Asian language understanding |
| `qwen2.5:14b` | Maximum quality, East-Asian | 12–16 GB | Slow but accurate |
| `llama3.1:8b` | English / European languages | 6–8 GB | Good for Latin-script targets |

**Which to choose:**
- Start with `translategemma:4b` — it is purpose-built for translation and uses less VRAM.
- If the source language is Japanese and quality matters (honorifics, game terminology), try `qwen2.5:7b`.
- For a dedicated shared server with more VRAM, `translategemma:12b` gives the best results.

### Pulling a model

Run once before first use. Requires Ollama to be running.

```powershell
# Translation-specialized models (recommended)
ollama pull translategemma:4b
ollama pull translategemma:12b

# General multilingual models
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b
ollama pull llama3.1:8b

# List installed models
ollama list

# Remove a model you no longer need
ollama rm llama3.1:8b
```

### Using a different model

Pass `--model` on the command line:

```powershell
python scripts/translate.py --folder Localization/Game --source-lang ja --model translategemma:4b
python scripts/translate.py --folder Localization/Game --source-lang ja --model translategemma:12b
python scripts/translate.py --folder Localization/Game --source-lang ja --model qwen2.5:14b
```

Or set it permanently in `.env`:

```ini
OLLAMA_MODEL=translategemma:4b
```

---

## 9. Understanding the Output

### Progress Output

During translation, the tool prints progress to the terminal:

```
[translate] Source: Localization/Game/ja (1 file, 412 entries)
[translate] Target languages: en
[translate] Checkpoint loaded: en — 0 entries already done
[translate] Translating en: batch 1/21...
[translate] Translating en: batch 7/21 (140/412 entries)...
[translate] Completed en: 412 entries translated, 0 preserved, 0 failed
[translate] Done. Output written: Localization/Game/en/Game.po
```

### Output Files

- Translated `.po` files are written to `<folder>/<target-lang>/<filename>.po`.
- The file structure mirrors the source file exactly.
- The `Language:` header is updated to the target language code.
- The `PO-Revision-Date:` header is updated to the current date.
- All source references, comments, and metadata are preserved.
- Existing translations (where `msgstr` already differs from source) are preserved unchanged.

### Checkpoint Files

Progress is saved after each batch in a temporary directory (`%TEMP%\po_translator_<hash>\translations.<lang>.json`). If translation is interrupted, re-running the same command will resume from where it stopped.

---

## 10. Translation Rules and Behavior

### What Gets Translated

- Entries where the target `msgstr` is empty.
- Entries where the target `msgstr` is identical to the source text (i.e., not yet translated).
- Entries that exist in the source but are missing from the target file.

### What Gets Preserved

- Entries where the target `msgstr` already differs from the source text — these are considered human-approved translations and are not overwritten.

### What Gets Removed

- Entries that exist in the target file but no longer exist in the source file (stale entries).

### Placeholder Preservation

The tool preserves placeholders and engine markup exactly as-is. Ruby is handled separately by flattening it to visible text before translation:

| Type | Example | Preserved? |
|---|---|---|
| Variable placeholders | `{PlayerName}`, `%d`, `%s` | ✅ Yes |
| Engine markup tags | `<b>`, `<color=#FF0000>` | ✅ Yes |
| Ruby markup | `<ruby displaytext="X" rubytext="Y"/>` | ✅ Visible text only (`displaytext` is translated; ruby markup itself is removed before translation) |
| Line breaks | `\n` in source | ✅ Yes |
| Names and codenames | `BTG`, `DLG_Assistant` | ✅ Yes |

---

## 11. Resuming an Interrupted Translation

If translation is stopped (Ctrl+C, power loss, network disconnect), simply re-run the same command:

```powershell
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en
```

The tool will load the checkpoint and continue from where it left off. Already-translated entries are not re-sent to the LLM.

To **restart from scratch** (discard progress):
```powershell
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en --reset
```

### Cache location

Checkpoints are stored under `%TEMP%\po_translator_<id>` on each machine. The startup line `[translate] Cache: <path>` shows the exact folder.

By default the `<id>` is a hash of the source folder's absolute path, which differs between machines. Use `--project <name>` to give the cache a fixed, human-readable name:

```powershell
python scripts/translate.py --folder Localization/Game --source-lang ja --project MyGame
# Cache: C:\Users\...\AppData\Local\Temp\po_translator_MyGame
```

This is especially useful in a team setting: every team member uses the same cache name, so you know which folder to look in when troubleshooting or sharing progress.

---

## 12. Troubleshooting

### "File cannot be loaded. The file is not digitally signed." (PowerShell execution policy error)

When running `.\setup\install-local.ps1` you may see:

```
.\setup\install-local.ps1 : File ... is not digitally signed. You cannot run this script on the current system.
```

This is a Windows PowerShell security policy restriction. To allow the script to run, execute the following command **once** in an elevated PowerShell session (Run as Administrator):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then re-run the setup script:

```powershell
.\setup\install-local.ps1
```

> **What this does:** `RemoteSigned` allows locally-created scripts to run without a digital signature, while still requiring scripts downloaded from the internet to be signed. This is the recommended policy for developer machines.
>
> If you prefer not to change your global policy, you can unblock only this script for the current session:
> ```powershell
> Unblock-File .\setup\install-local.ps1
> .\setup\install-local.ps1
> ```

### "Connection refused" or "Failed to connect to Ollama"

- **Local mode:** Make sure Ollama is running. Open a terminal and run `ollama list`. If it fails, restart Ollama from the system tray or run `ollama serve`.
- **LAN mode:** Check that the server IP is correct and that port `11434` is not blocked by a firewall.
- **External mode:** Verify your `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` are correct in `.env`. Contact your administrator if in doubt.

### "Model not found"

The model specified with `--model` is not available on the server. Run `ollama list` (on the server for LAN mode) to see available models, or ask your administrator.

### Translation quality is poor

- Try adding context: `--context "action RPG game dialogue, medical terminology"`
- Try a larger model: `--model qwen2.5:14b`
- Reduce batch size: `--batch-size 5` (sends fewer entries per request, may improve focus)

### Translation is very slow

- On local mode with CPU only: this is expected. A 7B model on CPU may take 10–30 seconds per batch. Consider using a GPU or connecting to a shared server.
- Reduce batch size to see progress more frequently: `--batch-size 10`

### "JSON decode error" or "Count mismatch" warnings

These are transient errors where the LLM returned a malformed response. The tool retries automatically. If a batch fails after all retries, those entries are skipped (remain untranslated) and translation continues. Re-run the tool to retry skipped entries.

### Output `.po` file has encoding issues

Ensure your source `.po` file is UTF-8 encoded. The tool always writes output as UTF-8.
