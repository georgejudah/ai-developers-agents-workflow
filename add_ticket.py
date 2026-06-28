"""
Quick script to add a new ticket to Supabase
"""
from helpers.supabase import supabase
import sys

def add_ticket(ticket_id: str, spec: str, repo_url: str):
    """Add a new ticket to the database"""
    
    data = {
        "external_issue_id": ticket_id,
        "status": "coding",
        "spec": spec,
        "repo_url": repo_url,
        "qa_retry_count": 0,
        "current_patch": None,
        "error_logs": [],
        "pr_url": None,
        "file_paths": None
    }
    
    try:
        result = supabase.table("tickets").insert(data).execute()
        print(f"✅ Ticket {ticket_id} created successfully!")
        print(f"Data: {result.data}")
        return result.data
    except Exception as e:
        print(f"❌ Error creating ticket: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Add CheckYourRelationship.com project to homepage
    ticket_id = "PORTFOLIO-ADD-CYR-001"
    repo_url = "https://github.com/georgejudah/Personalwebsite"
    
    spec = """
Add "CheckYourRelationship.com" Project to Homepage

Objective:
Add the "CheckYourRelationship.com" project to the projects section on the homepage. This project should be listed at the top, as the most prominent entry.

Project Details:
- **Project Name**: CheckYourRelationship.com
- **Description**:
  - Built a privacy-first relationship safety platform (React 19, TypeScript, Supabase/PostgreSQL) featuring a 37-question red flag detector, character assessment, and deal-breaker tool with Avg 374 views/week.
  - Integrated Gemini 2.5 Flash AI via a context-aware "Clarity" coach component that injects quiz risk scores and safety flags into dynamic system prompts for personalized responses.
  - End-to-End Ownership: Managed the complete product lifecycle from UX design to backend database schema, prioritizing zero-latency interactions and strict data privacy for sensitive user inputs.

Implementation Requirements:
- Locate the projects section on the homepage.
- Add a new project entry for "CheckYourRelationship.com".
- Place this new entry at the very top of the project list.
- Use the provided description, formatted for clarity (e.g., using bullet points for the features).
- Ensure the styling is consistent with other projects on the page.
- Verify that the layout remains responsive on all devices.

Success Criteria:
- "CheckYourRelationship.com" is the first project listed on the homepage.
- The project description is correctly and attractively displayed.
- The website's design and responsiveness are preserved.
"""
    
    add_ticket(ticket_id, spec, repo_url)
