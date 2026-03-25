# Administrator Guide — POTranslatorLLM Shared Server

This guide is for administrators who set up and manage the shared Ollama server used by the team for PO file translation.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Server Requirements](#2-server-requirements)
3. [Installation](#3-installation)
4. [Model Management](#4-model-management)
5. [LAN Access Configuration](#5-lan-access-configuration)
6. [Cloudflare Tunnel Setup (Summary)](#6-cloudflare-tunnel-setup-summary)
7. [Issuing Access Credentials to Users](#7-issuing-access-credentials-to-users)
8. [Revoking Access Credentials](#8-revoking-access-credentials)
9. [Open WebUI (Optional)](#9-open-webui-optional)
10. [Monitoring and Maintenance](#10-monitoring-and-maintenance)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Overview

The shared server runs [Ollama](https://ollama.com) on a Windows PC. It accepts translation requests from team members either:

- **On the LAN**: directly via `http://<server-ip>:11434` (no authentication required)
- **Externally**: via a Cloudflare Tunnel at a secure domain (requires Cloudflare Access Service Auth tokens)

Your responsibilities as admin:
- Install and maintain Ollama and models on the server
- Keep the server running (auto-start service)
- Set up and maintain the Cloudflare Tunnel
- Issue and revoke per-user Cloudflare Access Service Tokens

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

## 3. Installation

### Step 1: Run the Server Setup Script

Open **PowerShell as Administrator** and run:

```powershell
cd POTranslatorLLM
.\setup\install-server.ps1
```

This script will:
1. Install Ollama on Windows
2. Configure `OLLAMA_HOST=0.0.0.0` so Ollama accepts connections from other machines
3. Register Ollama as a Windows scheduled task (auto-start on login)
4. Open Windows Firewall for port `11434`
5. Pull the default model (`qwen2.5:7b`)
6. Install `cloudflared` for Cloudflare Tunnel

### Step 2: Assign a Static IP Address

Assign a static LAN IP to the server in your router/DHCP settings, or configure a static IP directly on the Windows network adapter. This ensures clients can always reach the server at the same address.

### Step 3: Verify Ollama is Running

```powershell
ollama list
curl http://localhost:11434/v1/models
```

### Step 4: Set Up Cloudflare Tunnel

Follow the step-by-step procedure in [`docs/cloudflare-setup.md`](cloudflare-setup.md).

---

## 4. Model Management

### Listing Available Models

```powershell
ollama list
```

### Pulling a New Model

```powershell
ollama pull qwen2.5:7b       # Recommended for Asian languages
ollama pull llama3.1:8b      # Good for European languages
ollama pull qwen2.5:14b      # Higher quality, requires more VRAM
```

### Removing a Model

```powershell
ollama rm qwen2.5:7b
```

### Recommended Models

| Model | Languages | VRAM | Speed |
|---|---|---|---|
| `qwen2.5:7b` | Japanese, Chinese, Korean, multilingual | 6–8 GB | Fast |
| `llama3.1:8b` | English, European languages | 6–8 GB | Fast |
| `qwen2.5:14b` | Multilingual, higher quality | 12–16 GB | Medium |
| `gemma2:9b` | Multilingual | 8–10 GB | Medium |

> **Note:** Models are stored in `C:\Users\<user>\.ollama\models`. Ensure sufficient disk space before pulling large models.

---

## 5. LAN Access Configuration

### Verify Ollama Listens on All Interfaces

The `install-server.ps1` script sets `OLLAMA_HOST=0.0.0.0`. Verify:

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
curl http://<server-ip>:11434/v1/models
```

You should receive a JSON list of available models.

### Find the Server's LAN IP

On the server:
```powershell
ipconfig | Select-String "IPv4"
```

Share this IP with LAN users.

---

## 6. Cloudflare Tunnel Setup (Summary)

> For the full step-by-step procedure including screenshots guidance, see [`docs/cloudflare-setup.md`](cloudflare-setup.md).

**Overview of what needs to be configured:**

1. Create a Cloudflare Tunnel on the server using `cloudflared`
2. Map a public hostname (e.g., `llm.example.com`) to `http://localhost:11434`
3. Create a Cloudflare Access Application for that hostname
4. Add a **Service Auth** policy so only clients with valid tokens can access it
5. Issue Service Tokens to each user (see section 7)

After setup:
- LAN users: use `http://<server-ip>:11434` (no credentials needed)
- External users: use `https://llm.example.com` + their Service Token credentials

---

## 7. Issuing Access Credentials to Users

Each external user needs a unique Cloudflare Service Token. Do NOT share the same token between users — unique tokens allow you to revoke access individually.

### Creating a Service Token

1. Go to [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/) → **Access** → **Service Auth** → **Service Tokens**.
2. Click **Create new service token**.
3. Enter a name for the token (e.g., `user-alice-translation`).
4. Cloudflare generates:
   - `CF-Access-Client-Id` (the "Client ID")
   - `CF-Access-Client-Secret` (the "Client Secret")
5. **Copy both values immediately** — the secret is shown only once.

### Sharing Credentials with the User

Send the following information securely (e.g., via encrypted email or a password manager):

```
OLLAMA_HOST=https://llm.example.com
OLLAMA_MODEL=qwen2.5:7b
CF_ACCESS_CLIENT_ID=<Client ID>
CF_ACCESS_CLIENT_SECRET=<Client Secret>
```

The user places these values in their `.env` file (see the [User Manual](user-manual.md)).

### Tracking Issued Tokens

Keep a record of which token was issued to which person. Suggested format:

| Token Name | User | Issued | Notes |
|---|---|---|---|
| user-alice-translation | Alice Smith | 2026-01-01 | |
| user-bob-translation | Bob Jones | 2026-01-15 | |

---

## 8. Revoking Access Credentials

To revoke access for a specific user:

1. Go to Cloudflare Zero Trust Dashboard → **Access** → **Service Auth** → **Service Tokens**.
2. Find the token for that user.
3. Click **Revoke**.

The user's requests will be immediately rejected by Cloudflare. Other users are not affected.

> If you suspect credentials were leaked, revoke the affected token immediately and issue a new one.

---

## 9. Open WebUI (Optional)

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

## 10. Monitoring and Maintenance

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
.\setup\install-server.ps1
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

## 11. Troubleshooting

### Ollama not accessible from LAN

1. Check `OLLAMA_HOST` is set to `0.0.0.0`: `[System.Environment]::GetEnvironmentVariable("OLLAMA_HOST", "Machine")`
2. Verify Ollama is running: `Get-Process ollama`
3. Verify firewall rule: `Get-NetFirewallRule -DisplayName "Ollama LLM Port 11434"`
4. Test locally: `curl http://localhost:11434/v1/models`
5. Test from another PC: `curl http://<server-ip>:11434/v1/models`

### Cloudflare Tunnel connection issues

1. Check `cloudflared` is running: `Get-Process cloudflared`
2. Check tunnel status in Cloudflare Zero Trust Dashboard → Networks → Tunnels
3. View cloudflared logs: `cloudflared tunnel info <tunnel-name>`
4. Restart cloudflared: `Stop-Process -Name cloudflared; Start-ScheduledTask -TaskName "cloudflared"`

### External users getting "403 Forbidden"

- Their Service Token credentials are wrong or expired
- Revoke the old token and issue a new one
- Ensure the Access policy includes the correct Service Token

### Server is slow / high memory usage

- Check active model: `ollama ps`
- Stop unused model: `ollama stop <model>`
- Verify NVIDIA GPU is being used: `nvidia-smi` (GPU utilization should be high during translation)
- If CPU-only, this is expected behavior

### Model returns poor quality translations

- Try a larger model: `ollama pull qwen2.5:14b`
- Ask users to add context with `--context "game dialogue"`
- Check GPU memory is sufficient: small VRAM causes model offloading to CPU
