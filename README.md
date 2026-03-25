# POTranslatorLLM

A standalone command-line tool for translating gettext `.po` localization files using a locally running Large Language Model (LLM) powered by [Ollama](https://ollama.com). No cloud API keys, no GitHub Copilot, no internet connection required.

---

## Features

- **100% local** — runs entirely on your Windows PC with no external API calls
- **Shared server support** — connect to a team LAN server or a Cloudflare-tunneled server
- **Multi-host parallel translation** — distribute languages (or even batches within one language) across multiple Ollama servers simultaneously
- **Resumable** — saves progress after each batch; interrupted jobs continue from the checkpoint
- **Smart diff** — preserves existing human translations; only re-translates what needs it
- **PO-spec compliant** — handles `msgctxt`, plural forms, fuzzy flags, ruby markup, and placeholders
- **Configurable** — model, batch size, timeout, and server credentials via `.env` file

---

## Quick Start

### 1. Set Up Ollama (Local Mode)

```powershell
cd POTranslatorLLM
.\setup\install-local.ps1
```

This installs Ollama, downloads the `qwen2.5:7b` model, and installs Python dependencies.

> **PowerShell execution policy error?** If you see *"The file is not digitally signed"*, run this once in an elevated PowerShell session (Run as Administrator), then re-run the script:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> See [Troubleshooting](docs/user-manual.md#file-cannot-be-loaded-the-file-is-not-digitally-signed-powershell-execution-policy-error) in the user manual for details.

### 2. Install Python Dependencies

```powershell
pip install -r setup\requirements.txt
```

### 3. Run Translation

```powershell
# Translate all sibling languages
python scripts/translate.py --folder Localization/Game --source-lang ja

# Translate Japanese → English only
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en

# Translate Japanese → English and Chinese
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en zh
```

---

## Repository Structure

```
POTranslatorLLM/
├── README.md                    # This file
├── scripts/
│   ├── translate.py             # Main CLI translation script
│   ├── po_helper.py             # PO file parsing, comparison, and merge
│   └── llm_client.py            # Ollama/OpenAI-compatible LLM client
├── setup/
│   ├── install-local.ps1        # Windows: set up local Ollama
│   ├── install-server.ps1       # Windows: set up shared server + cloudflared
│   └── requirements.txt         # Python dependencies
├── config/
│   └── config.example.env       # Example .env configuration
└── docs/
    ├── design.md                # System architecture and design
    ├── user-manual.md           # End-user guide
    ├── admin-guide.md           # Shared server admin guide
    └── cloudflare-setup.md      # Cloudflare Tunnel setup procedure
```

---

## Connection Modes

| Mode | Configuration | Auth |
|---|---|---|
| **Local** | `OLLAMA_HOST=http://localhost:11434` | None |
| **LAN** | `OLLAMA_HOST=http://<server-ip>:11434` | None |
| **External** | `OLLAMA_HOST=https://llm.example.com` + CF credentials | Cloudflare Service Auth |

Copy `config/config.example.env` to `.env` and fill in your values.

---

## CLI Reference

### Folder mode — translate a whole localization directory

```
python scripts/translate.py --folder <path> --source-lang <code> [options]

Required:
  --folder <path>          Localization root folder (e.g., Localization/Game)
  --source-lang <code>     Source language directory (e.g., ja)
```

### File mode — translate only changed + untranslated entries

Pass the current source `.po` file and an optional previous version of the same file.
Only entries that are untranslated **or** whose source text changed since the old version
are sent to the LLM. Already-translated, unchanged entries are preserved.

```
python scripts/translate.py --source-file <current.po> [--old-source-file <old.po>] --target-lang <code...> [options]

Required:
  --source-file <current.po>   Current source .po file
  --target-lang <code...>      One or more target language codes

Optional:
  --old-source-file <old.po>   Previous version of the source file (enables changed-source detection)
```

Examples:

```powershell
# Translate only untranslated entries in a single source file
python scripts/translate.py --source-file Localization/Game/ja/Game.po --target-lang en fr

# Also re-translate entries whose source text changed since the old version
python scripts/translate.py --source-file Localization/Game/ja/Game.po --old-source-file Localization/Game/ja/Game_old.po --target-lang en fr
```

### Shared options (both modes)

```
  --target-lang <code...>  Target language(s) — default: all sibling directories
  --host <url>             Ollama server URL (single host)
  --hosts <url...>         Multiple Ollama hosts for parallel translation (space-separated)
  --lang-host <LANG=URL>   Assign a host to a language; repeat same LANG for multiple hosts
  --model <name>           Model name (default: qwen2.5:7b)
  --project <name>         Cache folder name — %TEMP%\po_translator_<name>
  --api-key <id>           CF-Access-Client-Id (for external server)
  --api-secret <secret>    CF-Access-Client-Secret
  --batch-size <n>         Entries per LLM request (default: 20)
  --timeout <seconds>      Request timeout (default: 120)
  --reset                  Discard checkpoint and restart from scratch
  --dry-run                Show what would be translated; do not write files
  --context <text>         Translation context hint
  --verbose                Show detailed progress
```

---

## Multi-Host Parallel Translation

When you have multiple Ollama servers, translation can be parallelised at two levels:

| Level | How | Effect |
|---|---|---|
| **Language-level** | Multiple hosts, multiple target languages | Each language runs on its own host simultaneously |
| **Batch-level** | Multiple hosts assigned to one language | Batches of entries are distributed across all hosts concurrently |

### Language-level: one host per language

```powershell
# en → server1, fr → server2, de → server1 (round-robin)
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en fr de `
    --hosts http://server1:11434 http://server2:11434
```

### Batch-level: multiple hosts for one language

```powershell
# English batches split across two servers in parallel
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en fr `
    --lang-host en=http://server1:11434 --lang-host en=http://server2:11434 `
    --lang-host fr=http://server3:11434
```

### Via `.env`

```ini
OLLAMA_HOSTS=http://server1:11434,http://server2:11434
# Repeat same language for batch distribution:
OLLAMA_LANG_HOSTS=en=http://server1:11434,en=http://server2:11434,fr=http://server3:11434
```

See [User Manual — Section 6](docs/user-manual.md#6-multi-host-parallel-translation) for full details.

---

## Documentation

| Document | Description |
|---|---|
| [User Manual](docs/user-manual.md) | How to install, configure, and run translations (local and remote) |
| [Admin Guide](docs/admin-guide.md) | How to set up and manage the shared Ollama server |
| [Cloudflare Setup](docs/cloudflare-setup.md) | Step-by-step manual for Cloudflare Tunnel + Service Auth |
| [Design](docs/design.md) | System architecture, data flow, and component design |

---

## Requirements

- Windows 10 / 11 (64-bit)
- Python 3.9 or later
- Ollama (installed by setup script)
- NVIDIA GPU with 8 GB+ VRAM recommended for local mode

---

## Recommended Models

| Model | Best for | VRAM | Notes |
|---|---|---|---|
| `translategemma:4b` | Translation-only tasks, fast hardware | 4–6 GB | Purpose-built for translation; recommended starting point |
| `translategemma:12b` | Higher quality translation | 8–12 GB | Best quality/speed balance for a dedicated server |
| `qwen2.5:7b` | Japanese / Chinese / Korean source text | 6–8 GB | Strong East-Asian language understanding |
| `qwen2.5:14b` | Maximum quality, East-Asian languages | 12–16 GB | Slow but high accuracy |
| `llama3.1:8b` | English / European languages | 6–8 GB | Good for Latin-script targets |

### Pulling a model

```powershell
# Pull a model (run once before first use)
ollama pull translategemma:4b
ollama pull translategemma:12b
ollama pull qwen2.5:7b

# List installed models
ollama list
```

### Using a different model

Pass `--model` on the command line:

```powershell
python scripts/translate.py --folder Localization/Game --source-lang ja --model translategemma:4b
```

Or set it as the default in your `.env` file:

```ini
OLLAMA_MODEL=translategemma:4b
```
