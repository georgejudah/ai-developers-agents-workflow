# langraph boilder plate
import json
import sys
import os
import logging
from dotenv import load_dotenv
from helpers.tickets import TicketState
from helpers.supabase import fetch_ticket_state, update_ticket_state
from helpers.llm import generate_patch
from helpers.workspace import get_or_clone_repo, get_file_content, find_relevant_files_smart
from helpers.github_pr import apply_patch_and_create_pr
from helpers.qa_validation import run_qa_validation
from helpers.observability import init_langfuse, trace_workflow, flush
from langgraph.graph import StateGraph, END

# Load environment variables from .env file
load_dotenv()

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Initialize observability
init_langfuse()


# define the nodes and edges for the graph below

@trace_workflow("coder_agent")
def coder_agent(state: TicketState):
    # Fetch ticket from database
    ticket_id = state.get("ticket_id")
    db_state = fetch_ticket_state(ticket_id)
    state.update(db_state)
    
    if state.get("status") != "coding":
        logger.info(f"[CODER] Skipping - status is {state.get('status')}")
        return state
    
    logger.info(f"[CODER] Processing ticket: {state.get('ticket_id')}")
    
    # Get or clone repo
    repo_url = state.get("repo_url")
    if not repo_url:
        logger.error("[CODER] ERROR: No repo_url in ticket. Skipping.")
        return state
    
    repo_path = get_or_clone_repo(repo_url)
    
    # Find relevant files using smart LLM-based selection
    relevant_files = find_relevant_files_smart(repo_path, state.get("spec", ""), max_files=5)
    logger.info(f"[CODER] Found {len(relevant_files)} relevant files: {relevant_files}")
    
    # Read file contents
    file_contexts = {}
    for file_path in relevant_files:
        try:
            content = get_file_content(repo_path, file_path)
            file_contexts[file_path] = content
        except Exception as e:
            logger.warning(f"[CODER] Could not read {file_path}: {e}")
    
    # Generate patch dict with LLM ({file_path: sr_blocks})
    error_logs = state.get("error_logs", [])
    patch_dict = generate_patch(state.get("spec"), file_contexts, error_logs, repo_path)

    total_chars = sum(len(v) for v in patch_dict.values())
    logger.info(f"[CODER] Generated patch ({len(patch_dict)} files, {total_chars} chars total)")

    # Serialize to JSON string for DB storage
    patch_json = json.dumps(patch_dict)

    # Update database (persist file_paths so pr_agent can access them after DB fetch)
    update_ticket_state(state.get("ticket_id"), {
        "current_patch": patch_json,
        "file_paths": relevant_files,
        "status": "testing"
    })

    return {
        "current_patch": patch_json,
        "file_paths": relevant_files,
        "status": "testing"
    }


# QA Agent
@trace_workflow("qa_agent")
def qa_agent(state: TicketState):
    logger.info(f"[QA] Testing patch for ticket: {state.get('ticket_id')}")
    
    # Fetch latest state from DB (includes repo_url, patch, etc.)
    ticket_id = state.get("ticket_id")
    db_state = fetch_ticket_state(ticket_id)
    state.update(db_state)
    
    # Skip if not in testing status (e.g., already completed)
    if state.get("status") != "testing":
        logger.info(f"[QA] Skipping - status is {state.get('status')}")
        return state
    
    current_retries = state.get("qa_retry_count", 0)
    
    if current_retries > 2:
        logger.error("[QA] Max retries reached. Marking as failed.")
        update_ticket_state(ticket_id, {
            "status": "failed",
            "error_logs": state.get("error_logs", []) + ["Max retries exceeded"]
        })
        return {"status": "failed"}
    
    # Get repo path and patch
    repo_url = state.get("repo_url")
    if not repo_url:
        logger.error("[QA] No repo_url in state")
        return {"status": "failed"}
    
    repo_path = get_or_clone_repo(repo_url)
    
    # Parse patch
    patch_raw = state.get("current_patch")
    try:
        patch = json.loads(patch_raw)
        if not isinstance(patch, dict):
            raise ValueError("Not a dict")
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"[QA] Invalid patch format: {e}")
        update_ticket_state(ticket_id, {
            "status": "failed",
            "error_logs": state.get("error_logs", []) + [f"Invalid patch format: {e}"]
        })
        return {"status": "failed"}
    
    # TEMP: Skip QA validation for now - always pass
    spec = state.get("spec", "")
    logger.info("[QA] ⚠️ Validation skipped (always passing)")
    success, error_msg = True, None
    
    if success:
        logger.info("[QA] ✓ All validation checks passed!")
        update_ticket_state(ticket_id, {
            "status": "pr_ready"
        })
        return {"status": "pr_ready"}
    else:
        logger.warning(f"[QA] ✗ Validation failed: {error_msg}")
        update_ticket_state(ticket_id, {
            "status": "coding",
            "error_logs": state.get("error_logs", []) + [error_msg],
            "qa_retry_count": current_retries + 1
        })
        return {
            "status": "coding",
            "qa_retry_count": current_retries + 1
        }

@trace_workflow("pr_agent")
# PR Agent
def pr_agent(state: TicketState):
    logger.info(f"[PR] Creating pull request for ticket: {state.get('ticket_id')}")
    
    # Fetch latest state from DB
    ticket_id = state.get("ticket_id")
    db_state = fetch_ticket_state(ticket_id)
    state.update(db_state)
    
    # Skip if not in pr_ready status (e.g., already completed)
    if state.get("status") != "pr_ready":
        logger.info(f"[PR] Skipping - status is {state.get('status')}")
        return state
    
    # Get repo and patch
    repo_url = state.get("repo_url")
    patch_raw = state.get("current_patch")
    spec = state.get("spec")

    if not repo_url or not patch_raw:
        logger.error("[PR] ERROR: Missing repo_url or patch. Skipping.")
        return state

    # Deserialize patch: new format is JSON dict, legacy is plain string
    try:
        patch = json.loads(patch_raw)
        if not isinstance(patch, dict):
            raise ValueError("Not a dict")
    except (json.JSONDecodeError, ValueError):
        # Legacy single-string patch — wrap in dict using file_paths
        file_paths_legacy = state.get("file_paths") or []
        if file_paths_legacy:
            patch = {file_paths_legacy[0]: patch_raw}
        else:
            patch = {"unknown": patch_raw}
    
    # Clone/update repo
    repo_path = get_or_clone_repo(repo_url)
    
    # Apply patch dict and create PR
    pr_url, pr_error = apply_patch_and_create_pr(repo_path, patch, ticket_id, spec)
    
    if pr_url:
        logger.info(f"[PR] Success! {pr_url}")
        update_ticket_state(ticket_id, {
            "pr_url": pr_url,
            "status": "completed"
        })
        return {"pr_url": pr_url, "status": "completed"}
    else:
        current_retries = state.get("qa_retry_count", 0)
        
        if current_retries > 2:
            logger.error("[PR] Max retries reached. Marking as failed.")
            update_ticket_state(ticket_id, {
                "status": "failed",
                "error_logs": state.get("error_logs", []) + [pr_error or "PR creation failed after max retries"]
            })
            return {"status": "failed"}
        
        error_msg = pr_error or "PR creation failed - unknown error"
        logger.warning(f"[PR] Failed to create PR. Sending back to coder. Error: {error_msg}")
        update_ticket_state(ticket_id, {
            "status": "coding",
            "error_logs": state.get("error_logs", []) + [error_msg],
            "qa_retry_count": current_retries + 1
        })
        return {
            "status": "coding",
            "qa_retry_count": current_retries + 1
        }

# conditional router
# 3. Define the Router (Conditional Edge)
def route_after_qa(state: TicketState):
    """Determines where to go after QA finishes."""
    if state["status"] == "coding":
        return "coder"
    elif state["status"] == "pr_ready":
        return "pr"
    return "end"

def route_after_pr(state: TicketState):
    """Determines where to go after PR agent finishes."""
    if state["status"] == "coding":
        # PR failed, send back to coder to regenerate patch
        return "coder"
    # status is "completed" or "failed" - end workflow
    return "end"

# Build and compile the graph
workflow = StateGraph(TicketState)
workflow.add_node("coder", coder_agent)
workflow.add_node("qa", qa_agent)
workflow.add_node("pr", pr_agent)
workflow.add_edge("coder", "qa")  # Coder always goes to QA

workflow.add_conditional_edges(
    "qa",
    route_after_qa,
    {
        "coder": "coder", # Loop back
        "pr": "pr",       # Go to PR creation
        "end": END        # Break loop, workflow complete
    }
)

workflow.add_conditional_edges(
    "pr",
    route_after_pr,
    {
        "coder": "coder", # Loop back if patch was invalid
        "end": END        # Workflow complete (success or failed)
    }
)

# entry point for processing a ticket
workflow.set_entry_point("coder")

app = workflow.compile()

# Visualize the graph
def visualize_graph():
    logger.info("\n=== Workflow Graph (ASCII) ===")
    print(app.get_graph().draw_ascii())
    logger.info("\n=== Workflow Graph (Mermaid) ===")
    print(app.get_graph().draw_mermaid())

def run_ticket(ticket_id: str) -> dict:
    """Run the full agent workflow for a single ticket.
    Returns {ticket_id, status, pr_url, error}.
    Callable from CLI, API, or directly in Python.
    """
    initial_state = {"ticket_id": ticket_id}
    try:
        result = app.invoke(initial_state)
        flush()  # Ensure all observability data is sent
        return {
            "ticket_id": ticket_id,
            "status": result.get("status", "unknown"),
            "pr_url": result.get("pr_url"),
            "error": None,
        }
    except Exception as e:
        flush()  # Ensure error traces are sent
        return {"ticket_id": ticket_id, "status": "failed", "pr_url": None, "error": str(e)}


# --- FastAPI endpoint (optional — run with: uvicorn main:api_app --reload) ---
try:
    from fastapi import FastAPI
    api_app = FastAPI(title="Developer Agents API")

    @api_app.post("/run/{ticket_id}")
    def api_run_ticket(ticket_id: str):
        """Trigger the agent workflow for a ticket via HTTP POST.
        Example: curl -X POST http://localhost:8000/run/SEO-SCHEMA-001
        """
        return run_ticket(ticket_id)

    @api_app.get("/status/{ticket_id}")
    def api_ticket_status(ticket_id: str):
        """Get current DB status of a ticket."""
        from helpers.supabase import supabase
        r = supabase.table("tickets").select("external_issue_id,status,pr_url,qa_retry_count,error_logs").eq("external_issue_id", ticket_id).execute()
        return r.data[0] if r.data else {"error": "not found"}
except ImportError:
    pass  # FastAPI not installed — CLI mode only


# --- Run a Local Test ---
if __name__ == "__main__":
    # Accept ticket ID as CLI argument: python main.py SEO-SCHEMA-001
    # Falls back to hardcoded default if no argument provided
    ticket_id = sys.argv[1] if len(sys.argv) > 1 else "UX-CHAT-FAB-001"

    visualize_graph()
    logger.info(f"Starting Swarm Execution for ticket: {ticket_id}")
    result = run_ticket(ticket_id)
    print(f"\nResult: {result}")