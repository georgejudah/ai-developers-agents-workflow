import os
import re
import subprocess
import requests
from datetime import datetime


def apply_search_replace_blocks(file_path: str, llm_output: str) -> tuple:
    """Parse and apply Search/Replace blocks directly to a file.

    Special convention for NEW FILE CREATION:
      <<<< SEARCH
      ====
      [full file content]
      >>>> REPLACE
    An empty SEARCH block on a non-existent file = create the file.

    Returns (success: bool, error_message: str)
    """
    file_exists = os.path.exists(file_path)

    if file_exists:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return False, f"Could not read {file_path}: {e}"
    else:
        content = ""

    pattern = re.compile(r'<<<< SEARCH\n(.*?)\n?====\n(.*?)\n?>>>> REPLACE', re.DOTALL)
    blocks = pattern.findall(llm_output)

    if not blocks:
        return False, "No valid Search/Replace blocks found in LLM output"

    original_content = content

    for i, (search_text, replace_text) in enumerate(blocks):
        search_text = search_text.rstrip('\n')
        replace_text = replace_text.rstrip('\n')

        if search_text.strip() == "" and not file_exists:
            # Empty SEARCH on a non-existent file = create the file
            content = replace_text
            print(f"[PR] Creating new file: {file_path}")
        elif search_text not in content:
            if file_exists:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(original_content)
            return False, (
                f"Block {i+1}/{len(blocks)}: SEARCH text not found in file. "
                f"Ensure SEARCH exactly matches the file content.\n"
                f"First 150 chars of failed block:\n{search_text[:150]!r}"
            )
        else:
            content = content.replace(search_text, replace_text, 1)
            print(f"[PR] Applied block {i+1}/{len(blocks)}")

    # Ensure parent directory exists (for new files in new subdirs)
    parent_dir = os.path.dirname(file_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return True, ""


def apply_patch_and_create_pr(repo_path: str, patch: dict, ticket_id: str, spec: str) -> tuple:
    """Apply Search/Replace blocks from a patch dict and create a PR.

    Args:
        patch: dict mapping rel_path → S/R block string
               e.g. {"src/components/TimerPiP.jsx": "<<<< SEARCH\\n...\\n>>>> REPLACE"}
    Returns:
        (pr_url, error_message)
    """
    if not patch:
        return None, "Patch dict is empty"

    if not isinstance(patch, dict):
        return None, f"Expected patch dict, got {type(patch).__name__}"

    branch_name = f"agent/{ticket_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    try:
        print(f"[PR] Creating branch: {branch_name}")
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=repo_path, check=True)

        print(f"[PR] Applying Search/Replace blocks ({len(patch)} files)...")

        for rel_path, file_patch in patch.items():
            if not file_patch or '<<<< SEARCH' not in file_patch:
                print(f"[PR] No S/R blocks for {rel_path}, skipping")
                continue

            full_path = os.path.join(repo_path, rel_path)
            # Note: file may not exist yet (new file creation) — apply_search_replace_blocks handles this

            success, error = apply_search_replace_blocks(full_path, file_patch)
            if not success:
                print(f"[PR] Failed on {rel_path}: {error}")
                subprocess.run(["git", "checkout", "--", "."], cwd=repo_path)  # restore dirty files
                subprocess.run(["git", "checkout", "main"], cwd=repo_path)
                subprocess.run(["git", "branch", "-D", branch_name], cwd=repo_path)
                return None, error

        # Check for actual changes
        result = subprocess.run(["git", "diff", "--name-only"], cwd=repo_path, capture_output=True, text=True)
        changed_files = result.stdout.strip()
        if not changed_files:
            print("[PR] WARNING: No file changes detected after applying blocks")
            subprocess.run(["git", "checkout", "--", "."], cwd=repo_path)  # restore dirty files
            subprocess.run(["git", "checkout", "main"], cwd=repo_path)
            subprocess.run(["git", "branch", "-D", branch_name], cwd=repo_path)
            return None, "S/R blocks applied but no file content changed (SEARCH text may equal REPLACE text)"

        print(f"[PR] Modified files: {changed_files}")

        print(f"[PR] Committing changes...")
        # Remove stale artifact from old git-apply approach if present
        stale_patch = os.path.join(repo_path, ".agent_patch.diff")
        if os.path.exists(stale_patch):
            os.remove(stale_patch)
            subprocess.run(["git", "rm", "--cached", "--ignore-unmatch", ".agent_patch.diff"], cwd=repo_path)
        subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
        commit_msg = f"[Agent] {spec[:100]}\n\nTicket: {ticket_id}"
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_path, check=True)

        print(f"[PR] Pushing to remote...")
        github_pat = os.getenv("GITHUB_PAT")
        if not github_pat:
            print("[PR] ERROR: GITHUB_PAT not set.")
            subprocess.run(["git", "checkout", "main"], cwd=repo_path)
            return None, "GITHUB_PAT environment variable not set"

        subprocess.run(["git", "push", "origin", branch_name], cwd=repo_path, check=True)

        print(f"[PR] Creating pull request...")
        pr_url = create_github_pr(repo_path, branch_name, ticket_id, spec)

        subprocess.run(["git", "checkout", "main"], cwd=repo_path, check=True)
        return pr_url, None

    except Exception as e:
        print(f"[PR] Error: {e}")
        try:
            subprocess.run(["git", "checkout", "--", "."], cwd=repo_path)  # restore dirty files
            subprocess.run(["git", "checkout", "main"], cwd=repo_path)
            subprocess.run(["git", "branch", "-D", branch_name], cwd=repo_path)
        except Exception:
            pass
        return None, str(e)


def create_github_pr(repo_path: str, branch_name: str, ticket_id: str, spec: str) -> str:
    """Create PR via GitHub API"""
    github_pat = os.getenv("GITHUB_PAT")
    if not github_pat:
        print("[PR] ERROR: GITHUB_PAT not set")
        return None

    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path, capture_output=True, text=True, check=True
    )
    remote_url = result.stdout.strip()

    if "github.com/" in remote_url:
        repo_part = remote_url.split("github.com/")[1].replace(".git", "")
    elif "github.com:" in remote_url:
        repo_part = remote_url.split("github.com:")[1].replace(".git", "")
    else:
        print(f"[PR] Could not parse remote URL: {remote_url}")
        return None

    owner, repo_name = repo_part.split("/")
    api_url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls"

    headers = {
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    body = f"""## Automated Changes by AI Agent

**Ticket:** `{ticket_id}`

**Specification:**
{spec}

---
*This PR was automatically created by the developer agent workflow.*
"""

    data = {
        "title": f"[Agent] {spec[:80]}",
        "head": branch_name,
        "base": "main",
        "body": body
    }

    response = requests.post(api_url, json=data, headers=headers)

    if response.status_code == 201:
        pr_url = response.json().get("html_url")
        print(f"[PR] Created successfully: {pr_url}")
        return pr_url
    else:
        print(f"[PR] Failed to create PR: {response.status_code} - {response.text}")
        return None
