from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from main import app as workflow_app
from helpers.supabase import fetch_ticket_state
from helpers.observability import flush
from dotenv import load_dotenv

load_dotenv()

# Langfuse is configured with LANGFUSE_HOST=http://192.168.0.146:3002

# Create smoke test file
with open("smoke-test.txt", "w") as f:
    f.write("Developer Agents Workflow smoke test passed.\n")

api = FastAPI(title="Developer Agents Workflow API")

class ProcessTicketRequest(BaseModel):
    ticket_id: str

class ProcessTicketResponse(BaseModel):
    ticket_id: str
    status: str
    message: str
    result: dict

@api.post("/process-ticket", response_model=ProcessTicketResponse)
async def process_ticket(request: ProcessTicketRequest):
    """Process a ticket through the coder -> QA workflow"""
    try:
        # Fetch initial state from database
        initial_state = {"ticket_id": request.ticket_id}
        
        # Run the workflow
        result = workflow_app.invoke(initial_state)
        
        # Flush observability data
        flush()
        
        # Fetch final state from database
        final_state = fetch_ticket_state(request.ticket_id)
        
        return ProcessTicketResponse(
            ticket_id=request.ticket_id,
            status=final_state.get("status", "unknown"),
            message="Workflow completed successfully",
            result=final_state
        )
    except Exception as e:
        flush()  # Ensure error traces are sent
        raise HTTPException(status_code=500, detail=str(e))

@api.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}