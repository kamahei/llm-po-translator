# POTranslatorLLM

A standalone command-line tool for translating gettext `.po` localization files using a locally running Large Language Model (LLM) powered by [Ollama](https://ollama.com) or [LM Studio](https://lmstudio.ai). No cloud API keys, no GitHub Copilot, no internet connection required.

---

## Features

- **100% local** — runs entirely on your Windows PC with no external API calls
- **Ollama and LM Studio support** — use either backend, or mix them together in multi-host mode
- **Shared server support** — connect to a team LAN server or a Cloudflare-tunneled server
- **Multi-host parallel translation** — distribute languages (or even batches within one language) across multiple Ollama servers simultaneously
- **Resumable** — saves progress after each batch; interrupted jobs continue from the checkpoint
- **Smart diff** — preserves existing human translations; only re-translates what needs it
- **PO-spec compliant** — handles `msgctxt`, plural forms, fuzzy flags, ruby markup, and placeholders
- **Configurable** — model, batch size, timeout, and server credentials via `.env` file

---

## Quick Start

### Option A — Ollama (Local Mode)

```powershell
cd POTranslatorLLM
.\setup\install-ollama-local.ps1
```

This installs Ollama, downloads the `qwen2.5:7b` model, and installs Python dependencies.

### Option B — LM Studio (Local Mode)

```powershell
cd POTranslatorLLM
.\setup\install-lmstudio-local.ps1
```

This installs Python dependencies and configures `.env` for LM Studio. You must install LM Studio separately from https://lmstudio.ai/ and start its local server (Developer tab → Start Server).

> **PowerShell execution policy error?** If you see *"The file is not digitally signed"*, run this once in an elevated PowerShell session (Run as Administrator), then re-run the script:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> See [Troubleshooting](docs/user-manual.md#file-cannot-be-loaded-the-file-is-not-digitally-signed-powershell-execution-policy-error) in the user manual for details.

### 2. Install Python Dependencies

```powershell
python -m pip install -r setup\requirements.txt
```

> **`python` not recognized?** Python is not installed or was installed without adding it to PATH. Download from https://www.python.org/downloads/ and check **"Add Python to PATH"** during installation, then reopen PowerShell and try again.

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
│   └── llm_client.py            # Ollama/LM Studio OpenAI-compatible LLM client
├── setup/
│   ├── install-ollama-local.ps1  # Windows: set up local Ollama
│   ├── install-ollama-server.ps1 # Windows: set up shared Ollama server + cloudflared
│   ├── install-lmstudio-local.ps1   # Windows: set up local LM Studio
│   ├── install-lmstudio-server.ps1  # Windows: set up shared LM Studio server
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

### Ollama

| Mode | Configuration | Auth |
|---|---|---|
| **Local** | `OLLAMA_HOST=http://localhost:11434` | None |
| **LAN** | `OLLAMA_HOST=http://<server-ip>:11434` | None |
| **External** | `OLLAMA_HOST=https://llm.example.com` + CF credentials | Cloudflare Service Auth |

### LM Studio

| Mode | Configuration | Auth |
|---|---|---|
| **Local** | `LMS_HOST=http://localhost:1234` | None (or Bearer token if enabled) |
| **LAN** | `LMS_HOST=http://<server-ip>:1234` | None (or Bearer token if enabled) |

Copy `config/config.example.env` to `.env` and fill in your values.

You can configure both backends simultaneously — Ollama and LM Studio hosts are pooled together for multi-host parallel translation.

---

## LM Studio Setup

### Quick Setup

```powershell
.\setup\install-lmstudio-local.ps1
```

### Manual Setup

1. Download and install LM Studio from https://lmstudio.ai/
2. Open LM Studio and download a model from the Search tab
3. Start the local server: **Developer tab → Start Server** (default port: 1234)
4. Set your model name in `.env`:

```ini
LMS_HOST=http://localhost:1234
LMS_MODEL=qwen2.5-7b-instruct
```

### API Authentication

When LM Studio is configured with API key authentication enabled:

```ini
LMS_API_KEY=your-secret-key
```

When LM Studio has no authentication enforced, use any non-empty placeholder (e.g., `lm-studio`):

```ini
LMS_API_KEY=lm-studio
```

### Getting the Model Name

In LM Studio, the model name to use in `LMS_MODEL` is shown in the server log when you start the server, or you can query it:

```powershell
curl http://localhost:1234/v1/models
```

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
  --host <url>             Ollama server URL (single host). Env: OLLAMA_HOST
  --hosts <url...>         Multiple Ollama hosts for parallel translation
  --lang-host <LANG=URL>   Assign an Ollama host to a language; repeat same LANG for multiple hosts
  --model <name>           Ollama model name. Env: OLLAMA_MODEL (default: qwen2.5:7b)
  --api-key <id>           CF-Access-Client-Id (for external Ollama server). Env: CF_ACCESS_CLIENT_ID
  --api-secret <secret>    CF-Access-Client-Secret. Env: CF_ACCESS_CLIENT_SECRET
  --lms-host <url>         LM Studio server URL (single host). Env: LMS_HOST
  --lms-hosts <url...>     Multiple LM Studio hosts for parallel translation
  --lms-lang-host <LANG=URL>  Assign an LM Studio host to a language
  --lms-model <name>       LM Studio model name. Env: LMS_MODEL
  --lms-api-key <key>      LM Studio API key (Bearer token). Env: LMS_API_KEY (default: lm-studio)
  --project <name>         Cache folder name — %TEMP%\po_translator_<name>
  --batch-size <n>         Entries per LLM request (default: 20)
  --timeout <seconds>      Request timeout (default: 120)
  --reset                  Discard checkpoint and restart from scratch
  --dry-run                Show what would be translated; do not write files
  --context <text>         Translation context hint
  --verbose                Show detailed progress
```

---

## Multi-Host Parallel Translation

When you have multiple LLM servers (Ollama and/or LM Studio), translation can be parallelised at two levels:

| Level | How | Effect |
|---|---|---|
| **Language-level** | Multiple hosts, multiple target languages | Each language runs on its own host simultaneously |
| **Batch-level** | Multiple hosts assigned to one language | Batches of entries are distributed across all hosts concurrently |

Ollama and LM Studio hosts can be mixed freely in the same host pool.

### Language-level: one host per language

```powershell
# en → Ollama server1, fr → LM Studio, de → Ollama server1 (round-robin)
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en fr de `
    --hosts http://ollama1:11434 --lms-host http://lmstudio:1234
```

### Batch-level: multiple hosts for one language

```powershell
# English batches split across Ollama and LM Studio in parallel
python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en fr `
    --lang-host en=http://ollama1:11434 --lms-lang-host en=http://lmstudio:1234 `
    --lang-host fr=http://ollama2:11434
```

### Via `.env`

```ini
# Ollama hosts
OLLAMA_HOSTS=http://server1:11434,http://server2:11434

# LM Studio hosts (mixed into the pool alongside Ollama)
LMS_HOSTS=http://lmstudio1:1234,http://lmstudio2:1234

# Per-language overrides:
OLLAMA_LANG_HOSTS=en=http://ollama1:11434,fr=http://ollama2:11434
LMS_LANG_HOSTS=en=http://lmstudio1:1234
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
- Ollama (installed by `install-ollama-local.ps1`) **or** LM Studio (installed manually from https://lmstudio.ai/)
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

### Pulling a model (Ollama)

```powershell
# Pull a model (run once before first use)
ollama pull translategemma:4b
ollama pull translategemma:12b
ollama pull qwen2.5:7b

# List installed models
ollama list
```

### Downloading a model (LM Studio)

1. Open LM Studio → Search tab
2. Search for the model name (e.g., `qwen2.5-7b-instruct`)
3. Click Download
4. Copy the model name from the model card and set it in `.env`:
   ```ini
   LMS_MODEL=qwen2.5-7b-instruct
   ```

### Using a different model

Pass `--model` (Ollama) or `--lms-model` (LM Studio) on the command line:

```powershell
# Ollama
python scripts/translate.py --folder Localization/Game --source-lang ja --model translategemma:4b

# LM Studio
python scripts/translate.py --folder Localization/Game --source-lang ja --lms-model qwen2.5-7b-instruct
```

Or set it as the default in your `.env` file:

```ini
# Ollama
OLLAMA_MODEL=translategemma:4b

# LM Studio
LMS_MODEL=qwen2.5-7b-instruct
```

### Per-language model selection

Use a different model for specific target languages. Hosts that do not have
the required model are automatically skipped; only qualifying hosts are used
for that language.

**Via `.env`:**

```ini
# Ollama: qwen2.5:14b for Chinese, llama3.1:8b for English, default for the rest
OLLAMA_LANG_MODELS=zh=qwen2.5:14b,en=llama3.1:8b

# LM Studio equivalent
LMS_LANG_MODELS=zh=lmstudio-community/qwen2.5-14b-instruct-gguf,en=lmstudio-community/meta-llama-3.1-8b-instruct-gguf
```

**Via command line (Ollama):**

```powershell
python scripts/translate.py --folder Localization/Game --source-lang ja `
    --lang-model zh=qwen2.5:14b --lang-model en=llama3.1:8b
```

When `OLLAMA_LANG_HOSTS` / `LMS_LANG_HOSTS` is **not** configured, hosts are
automatically selected and distributed to languages based on which models are
currently loaded - no manual host pinning needed.

