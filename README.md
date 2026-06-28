# Developer Agents Workflow

Autonomous coding agent that fetches tickets from a database, generates code patches using LLMs, and creates GitHub pull requests automatically.

## Quick Start

### 1. Setup Environment

```bash
# Copy example config
cp .env.example .env

# Edit .env with your credentials
nano .env
```

### 2. Choose Your LLM Provider

#### Option A: Ollama (Local, FREE) ⭐ Recommended for M1/M2/M3/M4

```bash
# Install Ollama
brew install ollama

# Download a model (choose one):
ollama pull qwen2.5-coder:7b     # Fast, 5-6GB RAM
ollama pull qwen2.5-coder:14b    # Better quality, 10GB RAM
ollama pull deepseek-coder-v2:16b # Excellent quality, 12GB RAM

# Start Ollama server
ollama serve
```

In your `.env`:
```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5-coder:7b  # or 14b, 16b, etc.
```

#### Option B: OpenRouter (API, Paid)

Get your API key from https://openrouter.ai/

In your `.env`:
```bash
LLM_PROVIDER=openrouter
LLM_MODEL=deepseek/deepseek-v4-flash
OPENROUTER_API_KEY=your_key_here
```

### 3. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Run the Agent

```bash
python main.py
```

## Switching Between Models

Just update your `.env` file:

### Switch to Ollama 7B (fastest, free):
```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5-coder:7b
```

### Switch to Ollama 14B (better quality, free):
```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5-coder:14b
```

## 📊 Observability (Optional)

Track all LLM calls, costs, and workflow performance with **Langfuse**:

1. Sign up at https://cloud.langfuse.com (free tier)
2. Add to `.env`:
   ```bash
   LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxx
   LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxx
   LANGFUSE_HOST=https://cloud.langfuse.com
   ```
3. Run workflow → View traces in dashboard

**What you get:**
- 🔍 Full LLM prompt/response traces
- 💰 Cost tracking per ticket (<$0.0066 target)
- 📈 Success rates and retry patterns
- 🐛 Debug failed workflows with full context

**See**: [OBSERVABILITY.md](OBSERVABILITY.md) for complete setup guide

## 🚀 API Server

Run as an API server for n8n/Open WebUI integration:

```bash
uvicorn api:api --host 0.0.0.0 --port 8000
```

**Endpoints:**
- `POST /process-ticket` - Trigger workflow for a ticket
- `GET /health` - Health check

**Example:**
```bash
curl -X POST http://localhost:8000/process-ticket \
  -H "Content-Type: application/json" \
  -d '{"ticket_id": "YOUR-TICKET-ID"}'
```


## 🚀 Systemd Service

For production deployment, run the API server as a systemd service with auto-restart, log rotation, and health monitoring.

### Service Unit File

A template systemd service unit file is provided at `systemd/developer-agents-api.service`.  
Use the installation script below to copy it to `/etc/systemd/system/` and configure it for your environment.

### Service Management Commands

| Action | Command |
|--------|---------|
| **Enable** on boot | `sudo systemctl enable developer-agents-api` |
| **Start** | `sudo systemctl start developer-agents-api` |
| **Stop** | `sudo systemctl stop developer-agents-api` |
| **Restart** | `sudo systemctl restart developer-agents-api` |
| **Status** | `sudo systemctl status developer-agents-api` |
| **View logs** (journald) | `sudo journalctl -u developer-agents-api -f` |
| **Reload config** after unit file change | `sudo systemctl daemon-reload && sudo systemctl restart developer-agents-api` |

### Installation Script

For automated installation, run the provided script:

```bash
sudo bash scripts/install-systemd-service.sh
```

This script will:
- Copy the service template from `systemd/developer-agents-api.service` to `/etc/systemd/system/`
- Set the correct user, group, working directory, and environment file paths
- Reload systemd and enable the service on boot

### Uninstall Script

To remove the systemd service:

```bash
sudo bash scripts/uninstall-systemd-service.sh
```

This script will stop the service, disable it, remove the unit file, and reload systemd.

### Log Rotation

The service uses journald by default. To limit log size and enable rotation:

```bash
# Optional: Add a logrotate config if you prefer file-based logging
sudo tee /etc/logrotate.d/developer-agents-api << 'EOF'
/var/log/developer-agents-api/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
    postrotate
        systemctl kill -s USR2 developer-agents-api
    endscript
}
EOF
```

Alternatively, keep journald logs with:

```bash
sudo journalctl --vacuum-size=200M                  # Keep only 200MB
sudo journalctl --vacuum-time=7days                 # Keep 7 days
```

### Health Check Monitoring

The API exposes a `GET /health` endpoint. Integrate with systemd health checks using a timer or use an external monitoring tool:

**Manual check:**
```bash
curl -f http://localhost:8000/health || systemctl restart developer-agents-api
```

**Automatic health check (systemd timer):** Create `/etc/systemd/system/developer-agents-api-healthcheck.service` and `.timer` to periodically check and restart on failure.

### Enable on Boot

```bash
sudo systemctl enable developer-agents-api
```


## Model Comparison

| Model | Provider | Speed | Quality | Cost |
|-------|----------|-------|---------|------|
| qwen2.5-coder:7b | Ollama | ⚡⚡⚡ | ⭐⭐⭐½ | FREE |
| qwen2.5-coder:14b | Ollama | ⚡⚡ | ⭐⭐⭐⭐ | FREE |
| deepseek-coder-v2:16b | Ollama | ⚡⚡ | ⭐⭐⭐⭐⭐ | FREE |
| deepseek/deepseek-v4-flash | OpenRouter | ⚡⚡ | ⭐⭐⭐⭐⭐ | $0.14/M |

## Architecture

- **LangGraph**: Orchestrates the workflow (coder → QA → PR)
- **Supabase**: Stores tickets and patch history
- **Git**: Manages workspaces and branches
- **GitHub API**: Creates pull requests
- **LLM**: Generates code patches

## Project Structure

```
main.py                 # LangGraph workflow orchestration
helpers/
  llm.py               # LLM integration (Ollama/OpenRouter)
  workspace.py         # Git operations and file selection
  github_pr.py         # PR creation and patch application
  supabase.py          # Database operations
  context.py           # Project context loading
  tickets.py           # Ticket data structures
```

## Features

- ✅ Multi-model support (local + API)
- ✅ Intelligent file selection
- ✅ Project context awareness
- ✅ Patch validation
- ✅ Automatic PR creation
- ✅ Error recovery and retries
- ✅ Cost optimization

## Cost Estimate

- **Ollama (local)**: $0.00 forever ✅
- **OpenRouter**: ~$0.0066 per ticket (~$13.20 for 2000 tickets)
