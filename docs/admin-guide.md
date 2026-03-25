# Administrator Guide — POTranslatorLLM Shared Server

This guide is for administrators who set up and manage the shared LLM server(s) used by the team for PO file translation. Both Ollama and LM Studio are supported as backends.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Server Requirements](#2-server-requirements)
3. [Ollama Server Setup](#3-ollama-server-setup)
4. [LM Studio Server Setup](#4-lm-studio-server-setup)
5. [Model Management](#5-model-management)
6. [LAN Access Configuration](#6-lan-access-configuration)
7. [Cloudflare Tunnel Setup (Ollama, Summary)](#7-cloudflare-tunnel-setup-ollama-summary)
8. [Issuing Access Credentials to Users](#8-issuing-access-credentials-to-users)
9. [Revoking Access Credentials](#9-revoking-access-credentials)
10. [Open WebUI (Optional)](#10-open-webui-optional)
11. [Monitoring and Maintenance](#11-monitoring-and-maintenance)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Overview

The shared server runs [Ollama](https://ollama.com) and/or [LM Studio](https://lmstudio.ai) on a Windows PC. It accepts translation requests from team members either:

- **On the LAN**: directly via `http://<server-ip>:11434` (Ollama, no auth) or `http://<server-ip>:1234` (LM Studio, optional Bearer token)
- **Externally**: via a Cloudflare Tunnel at a secure domain (Ollama, requires Cloudflare Access Service Auth tokens)

Your responsibilities as admin:
- Install and maintain Ollama and/or LM Studio and models on the server
- Keep the server running (auto-start service)
- For Ollama external access: set up and maintain the Cloudflare Tunnel and issue/revoke per-user tokens
- For LM Studio: configure the server address and optional API authentication

---

## 2. Server Requirements

**Minimum:**
- Windows 10 / Windows 11 (64-bit)
- 16 GB RAM
- NVIDIA GPU with 8 GB VRAM (GTX 1080 or newer)
- 50 GB free disk space (for models)
- Stable network connection (wired preferred)

**Recommended:**
- 32 GB RAM
- NVIDIA RTX 3080 / 4080 or better (16 GB VRAM)
- 100 GB free disk space
- Static LAN IP address

**For CPU-only (no GPU):**
- 32 GB RAM
- Translation will be significantly slower (3–5× slower than GPU)

---

## 3. Ollama Server Setup

### Step 1: Run the Server Setup Script

Open **PowerShell as Administrator** and run:

```powershell
cd POTranslatorLLM
.\setup\install-ollama-server.ps1
```

This script will:
1. Install Ollama on Windows
2. Configure `OLLAMA_HOST=0.0.0.0` so Ollama accepts connections from other machines
3. Register Ollama as a Windows scheduled task (auto-start on login)
4. Open Windows Firewall for port `11434`
5. Pull the default model (`qwen2.5:7b`)
6. Install `cloudflared` for Cloudflare Tunnel

### Step 2: Assign a Static IP Address

Assign a static LAN IP to the server in your router/DHCP settings, or configure a static IP directly on the Windows network adapter.

### Step 3: Verify Ollama is Running

```powershell
ollama list
curl http://localhost:11434/v1/models
```

### Step 4: Set Up Cloudflare Tunnel (optional, for external access)

Follow the step-by-step procedure in [`docs/cloudflare-setup.md`](cloudflare-setup.md).

---

## 4. LM Studio Server Setup

### Step 1: Run the LM Studio Server Setup Script

Open **PowerShell as Administrator** and run:

```powershell
cd POTranslatorLLM
.\setup\install-lmstudio-server.ps1
```

This script will:
1. Check for LM Studio installation (and guide manual install if not found)
2. Open Windows Firewall for port `1234` (LAN only, Private profile)
3. Install Python dependencies
4. Add LM Studio settings to `.env`

### Step 2: Install LM Studio (if not already installed)

Download from https://lmstudio.ai/ and run the installer.

### Step 3: Configure LM Studio for LAN Access

In LM Studio:
1. Open the **Developer** tab
2. Under **Server Settings**, set the server address to `0.0.0.0`
3. Set port: `1234` (default)
4. Optionally enable API key authentication and set a key
5. Click **Start Server**

> **Note:** LM Studio does not have a built-in auto-start service. You must start the server manually after each reboot, or set up a Windows Scheduled Task manually.

### Step 4: Download a Model

In LM Studio → **Search** tab, download your preferred model. Recommended:
- `qwen2.5-7b-instruct` — good multilingual quality, 6–8 GB VRAM
- `qwen2.5-14b-instruct` — higher quality, 12–16 GB VRAM

### Step 5: Share Server Address with Users

Share the following information with your team:
```ini
LMS_HOST=http://<server-ip>:1234
LMS_MODEL=<model-name>
LMS_API_KEY=<api-key-if-auth-enabled>
```

### Step 6: Assign a Static IP Address

Same as for Ollama — assign a static LAN IP so the server is always reachable at the same address.

---

## 5. Model Management

### Ollama — Listing Models

```powershell
ollama list
```

### Ollama — Pulling a New Model

```powershell
ollama pull qwen2.5:7b       # Recommended for Asian languages
ollama pull llama3.1:8b      # Good for European languages
ollama pull qwen2.5:14b      # Higher quality, requires more VRAM
```

### Ollama — Removing a Model

```powershell
ollama rm qwen2.5:7b
```

### LM Studio — Managing Models

Use the LM Studio UI → **Search** tab to browse and download models. To remove a model, go to **My Models** and delete it from there.

### Recommended Models

| Model | Backend | Languages | VRAM | Speed |
|---|---|---|---|---|
| `qwen2.5:7b` | Ollama | Japanese, Chinese, Korean, multilingual | 6–8 GB | Fast |
| `llama3.1:8b` | Ollama | English, European languages | 6–8 GB | Fast |
| `qwen2.5:14b` | Ollama | Multilingual, higher quality | 12–16 GB | Medium |
| `qwen2.5-7b-instruct` | LM Studio | Multilingual | 6–8 GB | Fast |
| `qwen2.5-14b-instruct` | LM Studio | Multilingual, higher quality | 12–16 GB | Medium |

> **Note (Ollama):** Models are stored in `C:\Users\<user>\.ollama\models`. Ensure sufficient disk space before pulling large models.

---

## 6. LAN Access Configuration

### Ollama — Verify Listens on All Interfaces

The `install-ollama-server.ps1` script sets `OLLAMA_HOST=0.0.0.0`. Verify:

```powershell
[System.Environment]::GetEnvironmentVariable("OLLAMA_HOST", "Machine")
```

Should return `0.0.0.0` or `0.0.0.0:11434`.

After changing environment variables, restart Ollama (or reboot).

### Check Firewall Rule

```powershell
Get-NetFirewallRule -DisplayName "Ollama LLM Port 11434"
```

If the rule doesn't exist, create it manually:

```powershell
New-NetFirewallRule `
  -DisplayName "Ollama LLM Port 11434" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 11434 `
  -Action Allow `
  -Profile Private
```

> **Security note:** The rule is scoped to `Private` profile (LAN only). Do not set it to `Public`.

### Test LAN Access from Another Machine

From a different PC on the same network:
```powershell
# Ollama
curl http://<server-ip>:11434/v1/models
# LM Studio
curl http://<server-ip>:1234/v1/models
```

You should receive a JSON list of available models.

### Find the Server's LAN IP

On the server:
```powershell
ipconfig | Select-String "IPv4"
```

Share this IP with LAN users.

---

## 7. Cloudflare Tunnel Setup (Ollama, Summary)

> This applies to **Ollama** only. LM Studio does not support Cloudflare Tunnel natively.
> For the full step-by-step procedure, see [`docs/cloudflare-setup.md`](cloudflare-setup.md).

**Overview of what needs to be configured:**

1. Create a Cloudflare Tunnel on the server using `cloudflared`
2. Map a public hostname (e.g., `llm.example.com`) to `http://localhost:11434`
3. Create a Cloudflare Access Application for that hostname
4. Add a **Service Auth** policy so only clients with valid tokens can access it
5. Issue Service Tokens to each user (see section 8)

After setup:
- LAN users: use `http://<server-ip>:11434` (no credentials needed)
- External users: use `https://llm.example.com` + their Service Token credentials

---

## 8. Issuing Access Credentials to Users

### Ollama External Server (Cloudflare Service Tokens)

Each external user needs a unique Cloudflare Service Token. Do NOT share the same token between users — unique tokens allow you to revoke access individually.

#### Creating a Service Token

1. Go to [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/) → **Access** → **Service Auth** → **Service Tokens**.
2. Click **Create new service token**.
3. Enter a name for the token (e.g., `user-alice-translation`).
4. Cloudflare generates:
   - `CF-Access-Client-Id` (the "Client ID")
   - `CF-Access-Client-Secret` (the "Client Secret")
5. **Copy both values immediately** — the secret is shown only once.

#### Sharing Credentials with the User

Send the following information securely (e.g., via encrypted email or a password manager):

```
OLLAMA_HOST=https://llm.example.com
OLLAMA_MODEL=qwen2.5:7b
CF_ACCESS_CLIENT_ID=<Client ID>
CF_ACCESS_CLIENT_SECRET=<Client Secret>
```

The user places these values in their `.env` file (see the [User Manual](user-manual.md)).

### LM Studio Server (API Key)

If you enabled API key authentication in LM Studio:

1. Note the API key you set in LM Studio Developer settings.
2. Share with each user:

```
LMS_HOST=http://<server-ip>:1234
LMS_MODEL=<model-name>
LMS_API_KEY=<your-api-key>
```

### Tracking Issued Tokens (Ollama)

Keep a record of which token was issued to which person. Suggested format:

| Token Name | User | Issued | Notes |
|---|---|---|---|
| user-alice-translation | Alice Smith | 2026-01-01 | |
| user-bob-translation | Bob Jones | 2026-01-15 | |

---

## 9. Revoking Access Credentials

### Ollama (Cloudflare Service Token)

1. Go to Cloudflare Zero Trust Dashboard → **Access** → **Service Auth** → **Service Tokens**.
2. Find the token for that user.
3. Click **Revoke**.

The user's requests will be immediately rejected by Cloudflare. Other users are not affected.

> If you suspect credentials were leaked, revoke the affected token immediately and issue a new one.

### LM Studio (API Key)

Change the API key in LM Studio Developer settings. All users must update their `LMS_API_KEY` in `.env` to the new key.

---

## 10. Open WebUI (Optional)

[Open WebUI](https://github.com/open-webui/open-webui) provides a browser-based chat interface for testing and managing models. It is optional but recommended for verifying model behavior.

### Installation (requires Docker Desktop on Windows)

```powershell
docker run -d -p 3000:8080 `
  --add-host=host.docker.internal:host-gateway `
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 `
  -v open-webui:/app/backend/data `
  --name open-webui `
  --restart always `
  ghcr.io/open-webui/open-webui:main
```

Access the UI at `http://localhost:3000`.

> **Security note:** Do not expose port 3000 externally. Open WebUI is for admin use on the server only.

### Without Docker (Python-based)

```powershell
pip install open-webui
open-webui serve
```

---

## 11. Monitoring and Maintenance

### Checking if Ollama is Running

```powershell
Get-Process -Name ollama -ErrorAction SilentlyContinue
```

Or check the Task Scheduler:
```powershell
Get-ScheduledTask -TaskName "OllamaServer" | Select-Object TaskName, State
```

### Restarting Ollama

```powershell
# Stop
Stop-Process -Name ollama

# Start (via scheduled task or directly)
Start-ScheduledTask -TaskName "OllamaServer"
# or
Start-Process ollama serve
```

### Checking if LM Studio Server is Running

LM Studio does not expose a Windows process you can check via PowerShell. Check the server status inside the LM Studio UI (Developer tab). To check from another machine:

```powershell
curl http://localhost:1234/v1/models
```

### Starting LM Studio Server Automatically

LM Studio has no built-in service. To approximate auto-start, create a Windows Scheduled Task manually:

1. Open Task Scheduler → Create Basic Task
2. Trigger: "When the computer starts" or "When I log on"
3. Action: Start a program → point to `LM Studio.exe`

> Note: The LM Studio server must be started manually within the UI after the app launches.

### Checking GPU Utilization

```powershell
nvidia-smi
```

### Disk Space

```powershell
Get-PSDrive C | Select-Object Used, Free
```

Models are in `C:\Users\<user>\.ollama\models`. Remove unused models with `ollama rm <model>`.

### Updating Ollama

Re-run the installer from https://ollama.com/download or run:
```powershell
.\setup\install-ollama-server.ps1
```

### Updating Models

```powershell
ollama pull qwen2.5:7b    # Pull latest version of a model
```

### Updating cloudflared

Download the latest release from:
https://github.com/cloudflare/cloudflared/releases/latest

Replace `C:\cloudflared\cloudflared.exe` with the new binary.

---

## 12. Troubleshooting

### Ollama not accessible from LAN

1. Check `OLLAMA_HOST` is set to `0.0.0.0`: `[System.Environment]::GetEnvironmentVariable("OLLAMA_HOST", "Machine")`
2. Verify Ollama is running: `Get-Process ollama`
3. Verify firewall rule: `Get-NetFirewallRule -DisplayName "Ollama LLM Port 11434"`
4. Test locally: `curl http://localhost:11434/v1/models`
5. Test from another PC: `curl http://<server-ip>:11434/v1/models`

### LM Studio not accessible from LAN

1. Verify LM Studio server is running (check the Developer tab in the UI — it should show "Server running")
2. Confirm server address is set to `0.0.0.0` (not `localhost` or `127.0.0.1`)
3. Verify firewall rule: `Get-NetFirewallRule -DisplayName "LM Studio Port 1234"`
4. Test locally: `curl http://localhost:1234/v1/models`
5. Test from another PC: `curl http://<server-ip>:1234/v1/models`

### LM Studio returns HTTP 401 Unauthorized

- The user's `LMS_API_KEY` does not match the key set in LM Studio Developer settings
- If you did **not** enable API authentication in LM Studio, the key value doesn't matter — but it must be non-empty. Default `lm-studio` works.
- If you **did** enable it, users must set the correct key in their `.env`

### LM Studio returns wrong model name error

- LM Studio model names use full IDs like `lmstudio-community/qwen2.5-7b-instruct`
- Check the exact model ID in LM Studio → My Models
- Users must set `LMS_MODEL=<exact-model-id>` in their `.env`

### Cloudflare Tunnel connection issues

1. Check `cloudflared` is running: `Get-Process cloudflared`
2. Check tunnel status in Cloudflare Zero Trust Dashboard → Networks → Tunnels
3. View cloudflared logs: `cloudflared tunnel info <tunnel-name>`
4. Restart cloudflared: `Stop-Process -Name cloudflared; Start-ScheduledTask -TaskName "cloudflared"`

### External users getting "403 Forbidden" (Ollama/Cloudflare)

- Their Service Token credentials are wrong or expired
- Revoke the old token and issue a new one
- Ensure the Access policy includes the correct Service Token

### Server is slow / high memory usage

- Check active Ollama model: `ollama ps`
- Stop unused Ollama model: `ollama stop <model>`
- Verify NVIDIA GPU is being used: `nvidia-smi` (GPU utilization should be high during translation)
- If CPU-only, this is expected behavior

### Model returns poor quality translations

- Try a larger model (`qwen2.5:14b` for Ollama, `qwen2.5-14b-instruct` for LM Studio)
- Ask users to add context with `--context "game dialogue"`
- Check GPU memory is sufficient: small VRAM causes model offloading to CPU
