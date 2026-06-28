"""
Quick script to reset a ticket to 'coding' status in Supabase
"""
import sys
from helpers.supabase import supabase

def reset_ticket(ticket_id: str):
    """Reset a ticket to coding status"""
    
    if not ticket_id:
        print("❌ Please provide a ticket ID.")
        sys.exit(1)

    try:
        print(f"🔄 Resetting ticket {ticket_id}...")
        data, count = supabase.table("tickets").update({
            "status": "coding",
            "pr_url": None,
            "current_patch": None,
            "error_logs": [],
            "qa_retry_count": 0
        }).eq("external_issue_id", ticket_id).execute()
        
        # The actual data is in the second element of the tuple
        if data and len(data) > 1 and data[1]:
            print(f"✅ Ticket {ticket_id} has been reset to 'coding' status.")
        else:
            print(f"⚠️ Ticket {ticket_id} not found or no update was needed.")

    except Exception as e:
        print(f"❌ Error resetting ticket: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        ticket_id_to_reset = sys.argv[1]
        reset_ticket(ticket_id_to_reset)
    else:
        print("Usage: python reset_ticket.py <TICKET_ID>")
