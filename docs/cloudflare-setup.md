# Cloudflare Tunnel Setup Guide

This document describes the manual steps required to expose the shared Ollama LLM server to the internet securely using Cloudflare Tunnel and Cloudflare Access Service Auth tokens.

**Who this guide is for:** Server administrators only. End users receive credentials from the admin and do not need to perform any of these steps.

---

## Prerequisites

Before starting, ensure:

- [ ] You have a [Cloudflare account](https://dash.cloudflare.com/sign-up) (free tier is sufficient)
- [ ] You have a domain managed in Cloudflare DNS (e.g., `example.com`)
- [ ] The Ollama server is installed and running on the server PC (see [`docs/admin-guide.md`](admin-guide.md))
- [ ] `cloudflared` is installed on the server (`C:\cloudflared\cloudflared.exe`)
- [ ] `cloudflared` is in the system `PATH` (verify: `cloudflared --version` in PowerShell)

---

## Part 1: Create a Cloudflare Tunnel

### Step 1.1: Log In to cloudflared

On the server PC, open **PowerShell** and run:

```powershell
cloudflared tunnel login
```

This opens a browser window. Log in to your Cloudflare account and select the domain you want to use. A credentials file is saved to `C:\Users\<user>\.cloudflared\cert.pem`.

### Step 1.2: Create the Tunnel

```powershell
cloudflared tunnel create ollama-server
```

This creates a new tunnel and saves a credentials JSON file to:
```
C:\Users\<user>\.cloudflared\<tunnel-id>.json
```

Note the **Tunnel ID** (UUID) shown in the output. You will need it.

### Step 1.3: Create the Tunnel Configuration File

Create a file at `C:\Users\<user>\.cloudflared\config.yml` with the following content:

```yaml
tunnel: <tunnel-id>
credentials-file: C:\Users\<user>\.cloudflared\<tunnel-id>.json

ingress:
  - hostname: llm.example.com
    service: http://localhost:11434
  - service: http_status:404
```

Replace:
- `<tunnel-id>` with the UUID from Step 1.2
- `<user>` with your Windows username
- `llm.example.com` with your actual subdomain

### Step 1.4: Add a DNS Record for the Tunnel

```powershell
cloudflared tunnel route dns ollama-server llm.example.com
```

This automatically creates a CNAME record in Cloudflare DNS pointing `llm.example.com` to your tunnel.

Verify in the Cloudflare DNS dashboard: you should see a CNAME record for `llm` pointing to `<tunnel-id>.cfargotunnel.com`.

### Step 1.5: Test the Tunnel

Start the tunnel manually to verify it works:

```powershell
cloudflared tunnel run ollama-server
```

In another terminal, test:
```powershell
curl https://llm.example.com/v1/models
```

If successful, stop the manual run (Ctrl+C) and proceed to register it as a service.

### Step 1.6: Register cloudflared as a Windows Service

```powershell
cloudflared service install
```

This installs `cloudflared` as a Windows service that starts automatically on boot.

Verify:
```powershell
Get-Service -Name "Cloudflare Tunnel"
```

Start it:
```powershell
Start-Service -Name "Cloudflare Tunnel"
```

---

## Part 2: Configure Cloudflare Access

Cloudflare Access protects the tunnel endpoint so only authorized clients can reach it.

### Step 2.1: Enable Cloudflare Zero Trust

1. Go to [https://one.dash.cloudflare.com/](https://one.dash.cloudflare.com/)
2. If prompted, create a Zero Trust organization. The free plan supports up to 50 users.
3. Choose a team name (e.g., `yourcompany`). This is only used internally.

### Step 2.2: Create an Access Application

1. In the Zero Trust Dashboard, go to **Access** → **Applications**.
2. Click **Add an application**.
3. Select **Self-hosted**.
4. Fill in the details:
   - **Application name:** `Ollama LLM Server`
   - **Session duration:** `24 hours` (or as appropriate)
   - **Application domain:**
     - Subdomain: `llm`
     - Domain: `example.com` (select your domain)
5. Click **Next**.

### Step 2.3: Add a Service Auth Policy

On the **Policies** page:

1. Click **Add a policy**.
2. Set:
   - **Policy name:** `Service Token Access`
   - **Action:** `Service Auth`
3. Under **Configure rules** → **Include**:
   - Click **Add include**.
   - Selector: **Service Token**
   - Leave the token field empty for now (you will add tokens in Part 3).
4. Click **Save policy**.
5. Click **Next** through remaining steps and **Save application**.

> **Why "Service Auth"?** Unlike user-facing policies that redirect to a login page, Service Auth validates `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers. This is suitable for programmatic API access.

---

## Part 3: Create and Issue Service Tokens

Each team member who needs external access gets a unique service token.

### Step 3.1: Create a Service Token

1. In Zero Trust Dashboard, go to **Access** → **Service Auth** → **Service Tokens**.
2. Click **Create new service token**.
3. Enter a descriptive name: `user-alice-translation`.
4. Set duration: **Non-expiring** (or set an expiry date for tighter control).
5. Click **Generate token**.
6. **Copy and save both values immediately:**
   - `CF-Access-Client-Id` (Client ID)
   - `CF-Access-Client-Secret` (Client Secret — shown ONLY ONCE)
7. Click **Done**.

### Step 3.2: Link the Token to the Access Policy

1. Go to **Access** → **Applications** → **Ollama LLM Server** → **Edit**.
2. Select the **Service Token Access** policy → **Edit**.
3. Under **Include** → **Service Token**, select the token you just created.
4. If you need multiple tokens (one per user), click **Add include** and add each token.
5. Save the policy.

> **Best practice:** Create one token per user so you can revoke individual access without affecting others.

### Step 3.3: Share Credentials with the User

Send the following to the user via a secure channel (encrypted email, password manager sharing, etc.):

```
Ollama Server External Access Credentials
==========================================
Host URL:       https://llm.example.com
Model:          qwen2.5:7b
Client ID:      <CF-Access-Client-Id>
Client Secret:  <CF-Access-Client-Secret>

Instructions: See docs/user-manual.md → Section 4 (Remote Server Mode)
```

The user copies these values into their `.env` file:

```ini
OLLAMA_HOST=https://llm.example.com
OLLAMA_MODEL=qwen2.5:7b
CF_ACCESS_CLIENT_ID=<Client ID>
CF_ACCESS_CLIENT_SECRET=<Client Secret>
```

### Step 3.4: Test the Token

Ask the user to run a dry-run:

```powershell
python scripts/translate.py --folder Localization/Game --source-lang ja --dry-run
```

Or verify manually with curl:

```bash
curl -H "CF-Access-Client-Id: <CLIENT_ID>" \
     -H "CF-Access-Client-Secret: <CLIENT_SECRET>" \
     https://llm.example.com/v1/models
```

---

## Part 4: Revoking Access

### Revoke a Single Token

1. Go to Zero Trust Dashboard → **Access** → **Service Auth** → **Service Tokens**.
2. Find the token to revoke.
3. Click the **⋮** menu → **Revoke**.

The token is invalidated immediately. The user will receive `403 Forbidden` on their next request.

### Emergency: Revoke All External Access

If the server or all tokens are compromised:

1. In Zero Trust Dashboard → **Access** → **Applications** → **Ollama LLM Server** → **Edit**.
2. Delete the **Service Token Access** policy (or disable the application).
3. External access is immediately blocked for all users.
4. Create new tokens for authorized users after the incident.

---

## Part 5: Ongoing Management

### Viewing Tunnel Status

In Zero Trust Dashboard → **Networks** → **Tunnels** — the tunnel should show **HEALTHY**.

On the server:
```powershell
Get-Service -Name "Cloudflare Tunnel" | Select-Object Status
cloudflared tunnel info ollama-server
```

### Updating cloudflared

Download the latest release from https://github.com/cloudflare/cloudflared/releases/latest.

```powershell
Stop-Service -Name "Cloudflare Tunnel"
# Replace C:\cloudflared\cloudflared.exe with new binary
Start-Service -Name "Cloudflare Tunnel"
```

### Monitoring Access Logs

In Zero Trust Dashboard → **Logs** → **Access** — you can see all requests including token-authenticated ones.

---

## Appendix: Architecture Reference

```
[User's PC (external)]
        |
        | HTTPS POST /v1/chat/completions
        | Headers:
        |   CF-Access-Client-Id: <id>
        |   CF-Access-Client-Secret: <secret>
        ↓
[Cloudflare Edge]
        |
        | Validates CF-Access headers against Access policy
        | Rejects unauthorized requests (403)
        ↓
[Cloudflare Tunnel (cloudflared on server)]
        |
        | Forwards to http://localhost:11434
        ↓
[Ollama service on Windows Server PC]
        |
        | Generates translation
        ↓
[Response back to user]
```

```
[Team member on LAN]
        |
        | HTTP POST http://192.168.1.100:11434/v1/chat/completions
        | (No auth headers needed — LAN is trusted)
        ↓
[Ollama service on Windows Server PC (0.0.0.0:11434)]
```
