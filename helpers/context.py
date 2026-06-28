"""
Project context loader - reads documentation files to teach AI about the codebase
"""

import os

# Standard context files to look for (in priority order)
CONTEXT_FILES = [
    '.github/COPILOT_INSTRUCTIONS.md',
    'COPILOT_INSTRUCTIONS.md',
    '.cursorrules',
    'ARCHITECTURE.md',
    'CONVENTIONS.md',
    'README.md',
    'CONTRIBUTING.md',
    'docs/DEVELOPMENT.md',
    'docs/ARCHITECTURE.md',
    '.aider.conf.yml',
]

MAX_LINES_PER_FILE = 200  # Limit to prevent token explosion


def load_context_files(repo_path: str) -> dict:
    """
    Load project context files that exist in the repo.
    Returns dict of {file_path: content}
    """
    
    context = {}
    total_lines = 0
    max_total_lines = 500  # Cap total context at 500 lines
    
    for file_path in CONTEXT_FILES:
        if total_lines >= max_total_lines:
            print(f"[Context] Reached max context size, stopping")
            break
        
        full_path = os.path.join(repo_path, file_path)
        
        if os.path.exists(full_path):
            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = []
                    for i, line in enumerate(f):
                        if i >= MAX_LINES_PER_FILE:
                            lines.append(f"\n... (truncated after {MAX_LINES_PER_FILE} lines)\n")
                            break
                        if total_lines >= max_total_lines:
                            break
                        lines.append(line)
                        total_lines += 1
                    
                    content = ''.join(lines)
                    if content.strip():  # Only add non-empty files
                        context[file_path] = content
                        print(f"[Context] Loaded {file_path} ({len(lines)} lines)")
            except Exception as e:
                print(f"[Context] Could not read {file_path}: {e}")
    
    if not context:
        print("[Context] No context files found in repo")
    else:
        print(f"[Context] Loaded {len(context)} context files ({total_lines} total lines)")
    
    return context


def build_project_context(context_files: dict) -> str:
    """
    Format context files for LLM prompt.
    Returns formatted string ready to prepend to prompts.
    """
    
    if not context_files:
        return ""
    
    sections = ["=== PROJECT CONTEXT ==="]
    sections.append("The following files contain important project conventions and patterns.")
    sections.append("Follow these guidelines when generating code.\n")
    
    for file_path, content in context_files.items():
        sections.append(f"\n--- {file_path} ---")
        sections.append(content.rstrip())
    
    sections.append("\n=== END PROJECT CONTEXT ===\n")
    
    return '\n'.join(sections)


def get_context_summary(repo_path: str) -> str:
    """
    Get a quick summary of what context files exist.
    Useful for debugging.
    """
    
    found = []
    for file_path in CONTEXT_FILES:
        full_path = os.path.join(repo_path, file_path)
        if os.path.exists(full_path):
            size = os.path.getsize(full_path)
            found.append(f"  ✓ {file_path} ({size} bytes)")
    
    if not found:
        return "No project context files found"
    
    return "Found context files:\n" + "\n".join(found)
