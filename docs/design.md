# System Design — POTranslatorLLM

## 1. Overview

POTranslatorLLM is a standalone command-line tool that translates gettext `.po` files using a locally running Large Language Model (LLM) via [Ollama](https://ollama.com). It does not require GitHub Copilot, cloud API keys, or an internet connection (unless using a remote shared server).

The tool is designed for game localization workflows where the source language can be any language and target languages may include English, Japanese, Chinese, French, Korean, and many others.

---

## 2. Goals

- Translate `.po` files from a source language to one or more target languages using a local LLM.
- Run entirely on Windows without WSL or Docker.
- Support both a personal local install and a shared team LLM server.
- Resume interrupted translations from a checkpoint without restarting.
- Produce output identical in structure to the input `.po` files, preserving all metadata, comments, and untouched translations.

---

## 3. Non-Goals

- This tool does not replace a human localization review step.
- This tool does not compile `.po` files into `.mo` binary files.
- This tool does not manage Ollama models (use `ollama pull`/`ollama rm` directly).

---

## 4. Component Diagram

```
┌──────────────────────────────────────────────────────┐
│                   translate.py (CLI)                  │
│  - Parses CLI arguments and .env config               │
│  - Orchestrates the full translation workflow         │
│  - Emits progress to stdout                           │
└───────────────┬──────────────────┬───────────────────┘
                │                  │
      ┌─────────▼──────┐   ┌───────▼────────┐
      │  po_helper.py  │   │  llm_client.py │
      │                │   │                │
      │ - Parse .po    │   │ - OpenAI-compat│
      │ - Compare      │   │   REST client  │
      │ - Detect       │   │ - Batch send   │
      │   untranslated │   │ - Retry logic  │
      │ - Write .po    │   │ - CF-Access    │
      │ - Checkpoint   │   │   header inject│
      └────────────────┘   └───────┬────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │       LLM Backend            │
                    │                              │
                    │  Option A: Local Ollama      │
                    │  http://localhost:11434       │
                    │                              │
                    │  Option B: Shared Server     │
                    │  http://<lan-ip>:11434        │
                    │                              │
                    │  Option C: External via CF   │
                    │  https://llm.example.com     │
                    │  + CF-Access-Client headers  │
                    └──────────────────────────────┘
```

---

## 5. Module Responsibilities

### 5.1 `translate.py` — CLI Entry Point

- Reads arguments and `.env` configuration.
- Discovers source `.po` files in `<folder>/<source-lang>/`.
- Determines target languages (from arguments or sibling directories).
- Calls `po_helper.py` to extract entries needing translation.
- Calls `llm_client.py` to translate batches of entries.
- Polls and displays progress.
- Calls `po_helper.py` to merge results back into `.po` files.

### 5.2 `po_helper.py` — PO File Utilities

- Parses `.po` files using the `polib` library.
- Compares source and target files entry-by-entry using `msgctxt` as the key.
- Detects which entries need translation (empty, identical to source, missing).
- Detects stale entries (exist in target but not source) and marks them for removal.
- Reads and writes checkpoint files (`translations.<lang>.json`).
- Merges checkpoint data back into `.po` files after all batches complete.
- Ensures output `.po` files follow the same entry order as the source file.

### 5.3 `llm_client.py` — LLM API Client

- Wraps the Ollama REST API using the `openai` Python library.
- Supports three connection modes: local, LAN (no auth), external (CF-Access headers).
- Sends batch translation requests with a structured system prompt.
- Parses JSON responses from the LLM.
- Retries on transient errors (network, timeout, malformed JSON).
- Handles timeout configuration.

---

## 6. Data Flow

```
1. User runs:
   python scripts/translate.py --folder Localization/Game --source-lang ja --target-lang en

2. translate.py discovers:
   - Source: Localization/Game/ja/Game.po
   - Target: Localization/Game/en/Game.po  (create if missing)

3. po_helper.py loads source and target .po files.
   Compares entries by msgctxt:
   - Entries with empty msgstr          → needs_translation
   - Entries with msgstr == source text → needs_translation
   - Entries with msgstr != source text → preserved
   - Entries missing in target          → add + needs_translation
   - Entries only in target             → stale → remove

4. po_helper.py loads checkpoint:  translations.en.json
   Filters out already-translated entries.

5. translate.py sends remaining entries in batches of 20 to llm_client.py.

6. llm_client.py:
   POST /v1/chat/completions
   Content-Type: application/json
   CF-Access-Client-Id: <id>           ← only for external mode
   CF-Access-Client-Secret: <secret>   ← only for external mode

   {
     "model": "qwen2.5:7b",
     "messages": [
       {"role": "system", "content": "...translation rules..."},
       {"role": "user",   "content": "[{\"msgctxt\":\"...\",\"msgid\":\"...\",\"msgstr\":\"...\"},...]"}
     ]
   }

7. LLM returns JSON array of translated entries.

8. translate.py appends results to checkpoint file after each batch.

9. After all batches: po_helper.py merges checkpoint into target .po file.
   - Writes Localization/Game/en/Game.po
```

---

## 7. File Layout

```
POTranslatorLLM/
├── README.md                        # Project overview and quick start
├── .env                             # Local configuration (git-ignored)
├── scripts/
│   ├── translate.py                 # Main CLI translation script
│   ├── po_helper.py                 # PO file parsing, comparison, merge
│   └── llm_client.py                # LLM API client
├── setup/
│   ├── install-local.ps1            # Windows: install Ollama locally
│   ├── install-server.ps1           # Windows: install shared server + cloudflared
│   └── requirements.txt             # Python dependencies
├── config/
│   └── config.example.env           # Example configuration with comments
├── docs/
│   ├── design.md                    # This file: system design
│   ├── user-manual.md               # End-user guide
│   ├── admin-guide.md               # Server admin guide
│   └── cloudflare-setup.md          # Cloudflare Tunnel manual procedure
└── Localization/
    └── Game/
        ├── ja/
        │   └── Game.po              # Source PO file (Japanese)
        ├── en/
        │   └── Game.po              # Translated PO file (English)
        ├── zh/
        │   └── Game.po              # Translated PO file (Chinese)
        ├── fr/
        │   └── Game.po              # Translated PO file (French)
        └── es/
            └── Game.po              # Translated PO file (Spanish)
```

---

## 8. Checkpoint File Format

Progress is saved in a JSON checkpoint file per language, stored in the system temporary directory.

**File path (default — hash-based):** `%TEMP%\po_translator_<hash>\translations.<lang>.json`

The `<hash>` is a 12-character SHA-256 hash of the absolute path of the source folder. This path differs between machines.

**File path (with `--project`):** `%TEMP%\po_translator_<name>\translations.<lang>.json`

When `--project <name>` is passed (or `TRANSLATE_PROJECT=<name>` in `.env`), a fixed human-readable name is used instead of a hash. This gives a predictable, consistent path across all team members' machines.

**Format:**
```json
[
  {
    "file": "Game.po",
    "msgctxt": "DLG_Assistant,DD946BB948783560898A6090D391AC55",
    "msgstr": "Good morning."
  },
  {
    "file": "Game.po",
    "msgctxt": "DLG_Assistant,838F4C42485FCA298D6FE98CE9B4A929",
    "msgstr": "I got {0}."
  }
]
```

The file is overwritten atomically after each batch (write to `.tmp` then rename).

---

## 9. Connection Modes

### 9.1 Local Mode (default)

Ollama runs on the same machine as `translate.py`.

```
translate.py → http://localhost:11434/v1/chat/completions
```

No authentication required. Configure via:
```
OLLAMA_HOST=http://localhost:11434
```

### 9.2 LAN Mode

Ollama runs on a shared server on the local network.

```
translate.py → http://192.168.1.100:11434/v1/chat/completions
```

No authentication required (LAN is trusted). Configure via:
```
OLLAMA_HOST=http://192.168.1.100:11434
```

### 9.3 External Mode (Cloudflare Tunnel)

Ollama is exposed externally through a Cloudflare Tunnel protected by Access Service Auth.

```
translate.py → https://llm.example.com/v1/chat/completions
              ↓ (with CF-Access headers)
           Cloudflare Zero Trust
              ↓
           Shared Ollama Server (LAN)
```

Configure via:
```
OLLAMA_HOST=https://llm.example.com
CF_ACCESS_CLIENT_ID=<id>
CF_ACCESS_CLIENT_SECRET=<secret>
```

---

## 10. Server Topology

```
┌─────────────────────────────────────────────────────────┐
│                   Windows Server PC                      │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Ollama Service                                    │  │
│  │  OLLAMA_HOST=0.0.0.0:11434                        │  │
│  │  Models: qwen2.5:7b, llama3.1:8b, ...             │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  cloudflared (Windows Service)                     │  │
│  │  Tunnel: llm.example.com → http://localhost:11434  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Open WebUI (optional, port 3000)                  │  │
│  │  Browser-based UI for testing models               │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
         │ LAN (port 11434, no auth)
         │ Internet (via Cloudflare Tunnel, Service Auth)
```

**LAN access:** Any machine on the local network can use `http://<server-ip>:11434` directly.

**External access:** Only clients with valid `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers can reach the server through the Cloudflare Tunnel.

---

## 11. Security Model

| Access Path | Authentication | Notes |
|---|---|---|
| `localhost:11434` | None | Local use only |
| LAN `<ip>:11434` | None | Trust LAN; restrict via firewall if needed |
| Cloudflare Tunnel | CF Service Auth tokens | Per-user tokens; revocable |
| Open WebUI (LAN) | None | Admin access only; not exposed externally |

Service tokens are issued per user/team by the server administrator. Compromised tokens can be revoked instantly from the Cloudflare Zero Trust dashboard without affecting other users.

---

## 12. PO File Specification (Reference)

The tool follows the GNU gettext PO file format as documented at:
https://www.gnu.org/software/gettext/manual/html_node/PO-Files.html

**Supported features:**
- Header entry (`msgid ""` / `msgstr ""` with metadata)
- Standard entries: `msgctxt`, `msgid`, `msgstr`
- Plural forms: `msgid_plural`, `msgstr[0]`, `msgstr[1]`, ...
- Translator comments (`# ...`)
- Extracted comments (`#. ...`)
- Source references (`#: ...`)
- Flags (`#, fuzzy`, `#, no-python-format`, etc.)
- Obsolete entries (`#~ ...`) — preserved but not translated

**Translation key:** `msgctxt` is used as the unique key for matching entries across source and target files. If `msgctxt` is absent, `msgid` is used as the fallback key.
