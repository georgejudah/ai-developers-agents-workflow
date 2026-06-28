# Langfuse Observability Setup Guide

## 🎯 What You Get

Langfuse provides complete observability for your autonomous coding agents:

- **📊 Real-time Dashboard**: Monitor all workflows, tokens, costs
- **🔍 LLM Call Tracing**: See every prompt, response, and token count
- **💰 Cost Tracking**: Per-ticket costs to meet your <$0.0066 target
- **🐛 Debug Tools**: View exact prompts when issues occur
- **📈 Analytics**: Success rates, retry patterns, performance metrics
- **⚡ Performance**: Latency tracking per agent (coder/QA/PR)

## 🚀 Quick Setup (5 minutes)

### Step 1: Get Langfuse Account

#### Option A: Cloud (Recommended - Free Tier)
1. Go to https://cloud.langfuse.com
2. Sign up (free tier: 50k events/month)
3. Create a new project
4. Copy your API keys from Settings → API Keys

#### Option B: Self-Hosted (Advanced)
```bash
docker run -d \
  -p 3000:3000 \
  -e DATABASE_URL=postgresql://... \
  langfuse/langfuse:latest
```

### Step 2: Configure Environment

Add to your `.env` file:
```bash
# Get these from https://cloud.langfuse.com → Settings → API Keys
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxx
LANGFUSE_HOST=https://cloud.langfuse.com  # or your self-hosted URL
```

**Note**: Langfuse is optional. Leave these blank to disable observability.

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

This includes `langfuse>=2.0.0`.

### Step 4: Run Your Workflow

```bash
python main.py YOUR-TICKET-ID
```

You'll see:
```
[Observability] ✓ Langfuse initialized: https://cloud.langfuse.com
[CODER] Processing ticket: YOUR-TICKET-ID
...
```

### Step 5: View Dashboard

Open https://cloud.langfuse.com and explore:
- **Traces**: Click on `workflow_YOUR-TICKET-ID` to see the full flow
- **Sessions**: Group tickets by date/user
- **Metrics**: Token usage, costs, latency
- **Errors**: Failed workflows with full context

## 📊 What Gets Tracked

### 1. Workflow Traces
Each ticket creates a trace with spans for each agent:
```
workflow_YOUR-TICKET-ID
├── coder_agent (input: spec, output: patch)
│   ├── LLM call: generate_patch
│   └── LLM call: find_relevant_files
├── qa_agent (input: patch, output: validation)
│   └── LLM call: validation_strategy
└── pr_agent (input: patch, output: pr_url)
```

### 2. LLM Calls
Every LLM call automatically tracks:
- **Prompt**: Full prompt sent to model
- **Completion**: Generated response
- **Tokens**: Input/output/total tokens
- **Cost**: Calculated based on model pricing
- **Latency**: Time to first token, total time
- **Model**: `ollama/qwen2.5-coder:7b` or `openrouter/deepseek-v4-flash`

### 3. Metadata
- Ticket ID
- Repo URL
- Retry count
- Error logs
- Files modified

### 4. Custom Events
```python
from helpers.observability import log_ticket_event, log_cost

# Log custom events
log_ticket_event("TICKET-001", "pr_created", {"pr_url": "https://..."})
log_cost("TICKET-001", cost=0.0045, tokens=1200, model="qwen2.5-coder:7b")
```

## 🔍 Using the Dashboard

### View a Specific Ticket
1. Go to **Traces** tab
2. Search for `workflow_YOUR-TICKET-ID`
3. Click to see:
   - Full workflow timeline
   - Each agent's input/output
   - All LLM calls with prompts
   - Errors and retries

### Monitor Cost per Ticket
1. Go to **Metrics** tab
2. Filter by date range
3. View:
   - Average cost per trace
   - Total tokens used
   - Cost breakdown by model

### Debug Failed Workflows
1. Go to **Traces** tab
2. Filter by status: `ERROR`
3. Click on failed trace
4. See:
   - Which agent failed
   - Exact error message
   - Full LLM prompt/response
   - Input state that caused failure

### Track Performance
1. Go to **Analytics** tab
2. View:
   - P50/P95/P99 latency
   - Success rate
   - Retry patterns
   - Agent-specific metrics

## 💰 Cost Optimization

### Set Up Alerts
1. Go to **Settings** → **Webhooks**
2. Create alert for: `cost > 0.01` per trace
3. Get notified if ticket exceeds budget

### View Cost Breakdown
```python
# In Langfuse dashboard, run SQL query:
SELECT
  trace_id,
  SUM(calculated_total_cost) as total_cost,
  SUM(usage_input_tokens) as input_tokens,
  SUM(usage_output_tokens) as output_tokens
FROM observations
WHERE type = 'GENERATION'
GROUP BY trace_id
ORDER BY total_cost DESC
LIMIT 20;
```

## 🔧 Advanced Configuration

### Custom Trace Metadata
```python
from helpers.observability import get_langfuse

langfuse = get_langfuse()
if langfuse:
    trace = langfuse.trace(
        name="workflow_TICKET-001",
        user_id="user@example.com",
        session_id="batch-2026-06-28",
        metadata={
            "repo": "https://github.com/user/repo",
            "priority": "high",
            "estimated_cost": 0.005
        }
    )
```

### Manual Span Creation
```python
from helpers.observability import get_langfuse

langfuse = get_langfuse()
if langfuse:
    trace = langfuse.trace(name="workflow_TICKET-001")
    
    with trace.span(name="custom_operation") as span:
        # Your code here
        result = do_something()
        span.end(output={"result": result})
```

### Score Traces
```python
from helpers.observability import log_ticket_event

# Mark successful PRs
log_ticket_event("TICKET-001", "pr_merged", {"merge_time": "2026-06-28T12:00:00Z"})

# Mark validation failures
log_ticket_event("TICKET-002", "validation_failed", {"reason": "syntax error"})
```

## 🐛 Troubleshooting

### Observability Not Working?

**Check 1: Credentials**
```bash
# Verify .env has correct keys
cat .env | grep LANGFUSE
```

**Check 2: Dependencies**
```bash
pip list | grep langfuse
# Should show: langfuse==2.x.x
```

**Check 3: Logs**
```bash
python main.py TICKET-ID 2>&1 | grep Observability
# Should show: [Observability] ✓ Langfuse initialized
```

### Traces Not Appearing?

**Solution**: Flush data before exit
```python
from helpers.observability import flush
flush()  # Call at end of workflow
```

This is already handled in `run_ticket()` but may be needed for custom scripts.

### High Latency?

Langfuse calls are async and non-blocking. If you see delays:
1. Check network connectivity to Langfuse host
2. Use self-hosted Langfuse for lower latency
3. Disable observability for performance testing:
   ```bash
   # Remove or comment out in .env
   # LANGFUSE_PUBLIC_KEY=...
   ```

### Cost Calculation Wrong?

Langfuse estimates costs based on model pricing tables. For Ollama (local), cost is $0.

To set custom pricing:
1. Go to Langfuse → Settings → Models
2. Add your model (e.g., `qwen2.5-coder:7b`)
3. Set input/output token cost

## 📚 Resources

- **Langfuse Docs**: https://langfuse.com/docs
- **OpenAI Integration**: https://langfuse.com/docs/integrations/openai
- **LangGraph Integration**: https://langfuse.com/docs/integrations/langchain
- **Self-Hosting**: https://langfuse.com/docs/deployment/self-host
- **API Reference**: https://langfuse.com/docs/api

## 🎓 Example Queries

### View All Failed Tickets
```sql
SELECT trace_id, metadata
FROM traces
WHERE level = 'ERROR'
AND created_at > NOW() - INTERVAL '7 days';
```

### Average Cost Per Day
```sql
SELECT
  DATE(created_at) as date,
  COUNT(*) as traces,
  SUM(calculated_total_cost) as total_cost,
  AVG(calculated_total_cost) as avg_cost
FROM traces
WHERE name LIKE 'workflow_%'
GROUP BY date
ORDER BY date DESC;
```

### Slowest Operations
```sql
SELECT
  name,
  AVG(end_time - start_time) as avg_duration,
  COUNT(*) as count
FROM observations
WHERE type = 'SPAN'
GROUP BY name
ORDER BY avg_duration DESC
LIMIT 10;
```

## 🚨 Privacy & Security

- **Data Storage**: All traces stored in Langfuse database
- **Prompt Logging**: Full prompts and completions are logged
- **Sensitive Data**: Don't include API keys, passwords in prompts
- **Self-Hosted**: Use self-hosted Langfuse for sensitive projects
- **Disable**: Remove env vars to completely disable observability

## 🎉 Next Steps

1. ✅ Set up Langfuse account
2. ✅ Configure environment variables
3. ✅ Run a test ticket
4. ✅ Explore dashboard
5. 🔜 Set up cost alerts
6. 🔜 Create custom analytics
7. 🔜 Integrate with n8n (webhooks for failed workflows)

---

**Questions?** Check logs or Langfuse docs: https://langfuse.com/docs
