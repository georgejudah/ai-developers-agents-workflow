"""Quick script to check ticket status"""
from helpers.supabase import supabase

ticket_id = "job-12345"

response = supabase.table("tickets").select("*").eq("external_issue_id", ticket_id).execute()

if response.data:
    ticket = response.data[0]
    print(f"\n📋 Ticket: {ticket_id}")
    print(f"Status: {ticket['status']}")
    print(f"QA Retries: {ticket['qa_retry_count']}")
    print(f"PR URL: {ticket.get('pr_url', 'None')}")
    print(f"Patch length: {len(ticket.get('current_patch', '')) if ticket.get('current_patch') else 0} chars")
    print(f"Error logs: {len(ticket.get('error_logs', []))} errors")
    
    if ticket['status'] == 'completed':
        print("\n✅ TICKET COMPLETED SUCCESSFULLY!")
        print(f"PR: {ticket.get('pr_url')}")
    elif ticket['status'] == 'failed':
        print("\n❌ TICKET FAILED")
        print(f"Last errors: {ticket.get('error_logs', [])[-2:]}")
    else:
        print(f"\n⏳ TICKET IN PROGRESS (status: {ticket['status']})")
else:
    print(f"❌ Ticket {ticket_id} not found")
