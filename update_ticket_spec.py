"""
Update ticket spec to be more precise
"""
from helpers.supabase import supabase

ticket_id = "PORTFOLIO-SKILLS-UPDATE-001"

new_spec = """
Update Skills Section on Personal Website Homepage

**IMPORTANT: Only modify index.html. Do NOT modify html/ai.html or html/webdev.html.**

Objective:
Update the skills section on the homepage (index.html) to accurately reflect the latest technical expertise. Ensure the list is comprehensive and formatted cleanly without any emojis.

File to modify: index.html (homepage only)

Skills to be listed:
- Python
- FastAPI, Flask
- React, TailWindCSS
- Node.JS, JavaScript and TypeScript
- Data Science
- Agentic AI - LangGraph, N8N, Cursor, GitHub Copilot
- Full-Stack Development
- MYSQL and PostgreSQL
- GoLang
- Elastic Search
- Grafana
- Docker/Containerization
- AWS (EC2, S3)

Implementation Requirements:
- Locate the "My Skills" section in index.html (not the AI page or webdev page)
- Replace the existing descriptive paragraphs with a clean, bulleted list of skills
- Add any missing skills from the list above
- Ensure there are no emojis in the skills section
- Maintain the existing styling and layout
- Keep the "code.gif" image if present
- Do NOT modify html/ai.html or html/webdev.html

Success Criteria:
- The skills section on index.html contains all the listed skills in a clean format
- No emojis in the skills section
- The page's styling and responsiveness are not broken
- html/ai.html and html/webdev.html remain unchanged
"""

# Update the spec and reset the ticket
data, count = supabase.table("tickets").update({
    "spec": new_spec,
    "status": "coding",
    "pr_url": None,
    "current_patch": None,
    "error_logs": [],
    "qa_retry_count": 0
}).eq("external_issue_id", ticket_id).execute()

print(f"✅ Ticket {ticket_id} spec updated and reset to 'coding' status")
print(f"\nNew spec:\n{new_spec}")
