import os
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Supabase (Set these as environment variables in production)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "your_supabase_url_here")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "your_supabase_anon_key_here")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_ticket_state(issue_id: str):
    """Fetches the current state of the ticket from Supabase."""
    print(f"[DB] Fetching state for {issue_id}...")
    response = supabase.table("tickets").select("*").eq("external_issue_id", issue_id).execute()
    print(f"[DB] Current state for {issue_id}: {response.data}")
    if not response.data:
        raise ValueError(f"Ticket {issue_id} not found in database.")
    
    ticket = response.data[0]
    # Map external_issue_id to ticket_id for internal consistency
    ticket['ticket_id'] = ticket.get('external_issue_id')
    return ticket

def update_ticket_state(issue_id: str, updates: dict):
    """Updates the Supabase row with the newest agent data."""
    print(f"[DB] Saving new state for {issue_id}...")
    supabase.table("tickets").update(updates).eq("external_issue_id", issue_id).execute()