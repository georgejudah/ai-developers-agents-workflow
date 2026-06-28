from helpers.supabase import supabase
from dotenv import load_dotenv

load_dotenv()

print("Testing database connection...")
print("\n1. Fetching all tickets:")
result = supabase.table('tickets').select('*').execute()
print(f"Found {len(result.data)} tickets")
for ticket in result.data:
    print(f"  - external_issue_id: {ticket.get('external_issue_id')}")
    print(f"    status: {ticket.get('status')}")
    print()

print("\n2. Searching for 'job-12345':")
result2 = supabase.table('tickets').select('*').eq('external_issue_id', 'job-12345').execute()
print(f"Result: {result2.data}")

print("\n3. Creating smoke-test.txt...")
with open("smoke-test.txt", "w") as f:
    f.write("Developer Agents Workflow smoke test passed.")
print("Created smoke-test.txt successfully.")