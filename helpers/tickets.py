from typing import TypedDict, List, Optional

# 1. Define the State (Mirrors your Supabase schema)
class TicketState(TypedDict):
    ticket_id: str
    spec: str
    repo_url: str
    current_patch: str
    file_paths: Optional[List[str]]
    error_logs: List[str]
    qa_retry_count: int
    status: str
    pr_url: Optional[str]