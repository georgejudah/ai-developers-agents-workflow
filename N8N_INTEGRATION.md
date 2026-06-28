# n8n + Open WebUI Integration Guide

This guide shows how to connect Open WebUI → n8n → Developer Agents Workflow.

## Architecture

```
┌──────────────┐     ┌──────────┐     ┌──────────────┐     ┌───────────────┐
│  Open WebUI  │────▶│   n8n    │────▶│  Supabase    │────▶│   LangGraph   │
│  (Chat UI)   │     │ Workflow │     │   Database   │     │   Workflow    │
└──────────────┘     └──────────┘     └──────────────┘     └───────────────┘
                          │                                         │
                          └─────────────────────────────────────────┘
                                    Direct API Call
```

## 🚀 Setup Steps

### 1. Start Your API Server

```bash
cd /path/to/developer-agents-workflow
source venv/bin/activate
uvicorn api:api --host 0.0.0.0 --port 8000
```

**Test it:**
```bash
curl http://localhost:8000/health
# Should return: {"status":"healthy"}
```

### 2. Set Up n8n

#### Install n8n

**Option A: Docker (Recommended)**
```bash
docker run -d --name n8n \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  n8nio/n8n
```

**Option B: npm**
```bash
npm install -g n8n
n8n start
```

Access n8n at: http://localhost:5678

#### Configure Supabase Credentials

1. Open n8n: http://localhost:5678
2. Go to **Credentials** → **Add Credential**
3. Select **Supabase**
4. Fill in:
   - **Host**: `https://your-project.supabase.co`
   - **Service Role Key**: Your Supabase service role key (from .env)

### 3. Import Workflow

1. Download [`n8n-workflow-example.json`](n8n-workflow-example.json)
2. In n8n: **Workflows** → **Import from File**
3. Select the JSON file
4. Update the workflow:
   - **"Trigger LangGraph Workflow" node**: Change URL to your API server
     - Local: `http://host.docker.internal:8000/process-ticket` (if n8n in Docker)
     - Or: `http://localhost:8000/process-ticket`
   - **Supabase nodes**: Select your Supabase credential

### 4. Get Webhook URL

1. Open the imported workflow
2. Click **"Webhook Trigger"** node
3. Copy the **Production Webhook URL**
   - Example: `https://your-n8n.com/webhook/process-ticket`

### 5. Configure Open WebUI

#### Option A: Custom Function (Recommended)

Create a new function in Open WebUI:

```python
"""
title: Developer Agent Trigger
author: Your Name
version: 1.0
"""

import requests
from typing import Callable, Any

class Tools:
    def __init__(self):
        self.n8n_webhook = "https://your-n8n.com/webhook/process-ticket"
    
    async def create_coding_ticket(
        self,
        ticket_id: str,
        spec: str,
        repo_url: str,
        __user__: dict = {},
    ) -> str:
        """
        Create a coding ticket and trigger the autonomous agent workflow.
        
        :param ticket_id: Unique ticket identifier (e.g., "FEAT-123")
        :param spec: Description of the code changes needed
        :param repo_url: Git repository URL
        """
        
        payload = {
            "ticket_id": ticket_id,
            "spec": spec,
            "repo_url": repo_url
        }
        
        try:
            response = requests.post(
                self.n8n_webhook,
                json=payload,
                timeout=300
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get("success"):
                pr_url = result.get("pr_url")
                if pr_url:
                    return f"✅ Ticket {ticket_id} completed! PR: {pr_url}"
                else:
                    return f"⏳ Ticket {ticket_id} queued. Status: {result.get('status')}"
            else:
                return f"❌ Failed to process ticket: {result.get('message')}"
                
        except Exception as e:
            return f"❌ Error: {str(e)}"
```

**Usage in Open WebUI:**
```
User: Create a ticket to add dark mode to the homepage

AI: I'll create a ticket for that. What's the ticket ID and repo URL?

User: DARK-MODE-001, https://github.com/myorg/website

AI: [calls create_coding_ticket("DARK-MODE-001", "Add dark mode to homepage", "https://github.com/myorg/website")]
    ✅ Ticket DARK-MODE-001 completed! PR: https://github.com/myorg/website/pull/42
```

#### Option B: Direct HTTP Call

If Open WebUI supports HTTP actions:

1. **Actions** → **Add HTTP Action**
2. **URL**: `https://your-n8n.com/webhook/process-ticket`
3. **Method**: POST
4. **Body**:
```json
{
  "ticket_id": "{{ticket_id}}",
  "spec": "{{spec}}",
  "repo_url": "{{repo_url}}"
}
```

## 📋 Workflow Diagram

```
1. User sends message in Open WebUI
   ↓
2. Open WebUI function calls n8n webhook
   POST https://n8n.com/webhook/process-ticket
   {
     "ticket_id": "FEAT-123",
     "spec": "Add dark mode",
     "repo_url": "https://github.com/..."
   }
   ↓
3. n8n creates ticket in Supabase
   INSERT INTO tickets (external_issue_id, spec, repo_url, status)
   VALUES ('FEAT-123', 'Add dark mode', '...', 'coding')
   ↓
4. n8n triggers LangGraph workflow
   POST http://localhost:8000/process-ticket
   {"ticket_id": "FEAT-123"}
   ↓
5. LangGraph workflow executes
   - Coder Agent: Generates code patch
   - QA Agent: Validates patch
   - PR Agent: Creates GitHub PR
   ↓
6. n8n updates Supabase with result
   UPDATE tickets SET status='completed', pr_url='...'
   WHERE external_issue_id='FEAT-123'
   ↓
7. n8n responds to Open WebUI
   {
     "success": true,
     "ticket_id": "FEAT-123",
     "pr_url": "https://github.com/.../pull/42"
   }
```

## 🔄 Asynchronous Processing (Recommended)

For long-running workflows, use async processing:

### 1. Modify n8n Workflow

Add a **Split In Batches** node to process multiple tickets in parallel.

### 2. Use Webhooks for Status Updates

```javascript
// In n8n, add HTTP Request node at the end:
POST https://your-open-webui.com/webhook/ticket-complete
{
  "ticket_id": "{{ $json.ticket_id }}",
  "status": "{{ $json.status }}",
  "pr_url": "{{ $json.result.pr_url }}"
}
```

### 3. Open WebUI Receives Notification

Create a webhook endpoint in Open WebUI to receive updates.

## 🔍 Monitoring with Langfuse

All workflows are automatically tracked in Langfuse (if configured):

1. Open https://cloud.langfuse.com
2. Filter traces by `ticket_id`
3. See:
   - Full workflow timeline
   - All LLM calls with prompts
   - Costs per ticket
   - Success/failure reasons

**Connect n8n to Langfuse:**
Add to n8n workflow after completion:
```javascript
// HTTP Request Node
POST https://api.langfuse.com/api/public/scores
Headers: {
  "Authorization": "Bearer {{ $env.LANGFUSE_SECRET_KEY }}"
}
Body: {
  "traceId": "workflow_{{ $json.ticket_id }}",
  "name": "workflow_completed",
  "value": 1,
  "comment": "Triggered via n8n"
}
```

## 🧪 Testing

### Test n8n Webhook

```bash
curl -X POST https://your-n8n.com/webhook/process-ticket \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "TEST-001",
    "spec": "Add a console.log statement to the main function",
    "repo_url": "https://github.com/your-org/test-repo"
  }'
```

Expected response:
```json
{
  "success": true,
  "ticket_id": "TEST-001",
  "status": "completed",
  "pr_url": "https://github.com/your-org/test-repo/pull/1"
}
```

### Check Supabase

```sql
SELECT * FROM tickets WHERE external_issue_id = 'TEST-001';
```

### Check Langfuse

Search for `workflow_TEST-001` in traces.

## 📚 Advanced: Scheduled Batch Processing

Process multiple tickets in batches:

### 1. Add Cron Trigger to n8n

- **Trigger**: Schedule Trigger (every 5 minutes)
- **Action**: Supabase → Get rows where `status = 'pending'`
- **Loop**: For each ticket → Call `/process-ticket`

### 2. Create Batch API Endpoint

Add to `api.py`:

```python
@api.post("/process-batch")
async def process_batch(ticket_ids: list[str]):
    """Process multiple tickets in parallel"""
    results = []
    for ticket_id in ticket_ids:
        result = await process_ticket(ProcessTicketRequest(ticket_id=ticket_id))
        results.append(result)
    return {"results": results}
```

## 🚨 Error Handling

### n8n Error Notifications

Add an **Error Trigger** node:
- **Trigger**: On Workflow Error
- **Action**: Send notification (Slack, Email, Discord)

### Retry Failed Tickets

Add to n8n workflow:
```javascript
// Check retry count
if ($json.qa_retry_count > 3) {
  // Send alert
} else {
  // Retry
  POST /process-ticket
}
```

## 🎉 Next Steps

1. ✅ Set up API server
2. ✅ Configure n8n webhook
3. ✅ Import workflow
4. ✅ Test with sample ticket
5. 🔜 Connect Open WebUI
6. 🔜 Add error notifications
7. 🔜 Set up batch processing
8. 🔜 Monitor costs in Langfuse

---

**Questions?** Check the [main README](README.md) or [OBSERVABILITY.md](OBSERVABILITY.md)
