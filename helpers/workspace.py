import os
import re
import subprocess
import hashlib
from pathlib import Path

WORKSPACE_ROOT = "/tmp/agent-workspaces"

# Universal Ctags binary — prefer homebrew version (supports JSX/TSX)
# Falls back to system ctags, then None (repo map disabled gracefully)
def _find_ctags() -> str | None:
    for candidate in ["/opt/homebrew/bin/ctags", "/usr/local/bin/ctags", "ctags"]:
        try:
            result = subprocess.run([candidate, "--version"], capture_output=True, text=True)
            if "Universal Ctags" in result.stdout:
                return candidate
        except FileNotFoundError:
            continue
    return None

CTAGS_BIN = _find_ctags()

def get_or_clone_repo(repo_url: str) -> str:
    """Clone repo if needed, otherwise update it"""
    
    # Create workspace directory
    os.makedirs(WORKSPACE_ROOT, exist_ok=True)
    
    # Inject PAT for private repos
    auth_url = repo_url
    github_pat = os.getenv("GITHUB_PAT")
    if github_pat and repo_url.startswith("https://github.com"):
        # Inject token: https://TOKEN@github.com/org/repo.git
        auth_url = repo_url.replace("https://", f"https://{github_pat}@")
    
    # Generate unique path for this repo (using original URL for consistency)
    repo_hash = hashlib.md5(repo_url.encode()).hexdigest()[:8]
    repo_path = os.path.join(WORKSPACE_ROOT, repo_hash)
    
    if os.path.exists(repo_path):
        print(f"[Workspace] Updating existing repo at {repo_path}")
        # Fetch and reset to avoid branch tracking issues
        subprocess.run(["git", "fetch", "origin"], cwd=repo_path, check=True, 
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=repo_path, check=True,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    else:
        print(f"[Workspace] Cloning {repo_url} to {repo_path}")
        subprocess.run(["git", "clone", auth_url, repo_path], check=True,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    
    return repo_path


def get_file_content(repo_path: str, file_path: str) -> str:
    """Read a file from the workspace"""
    full_path = os.path.join(repo_path, file_path)
    with open(full_path, 'r') as f:
        return f.read()


def _get_ignore_patterns(repo_path: str) -> list:
    """
    Extract paths to ignore from COPILOT_INSTRUCTIONS.md 'Files to IGNORE' section.
    Falls back to empty list if not present — no hardcoding.
    """
    instructions_path = os.path.join(repo_path, ".github", "COPILOT_INSTRUCTIONS.md")
    if not os.path.exists(instructions_path):
        return []

    patterns = []
    in_ignore_section = False
    try:
        with open(instructions_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line_stripped = line.strip()
                if 'files to ignore' in line_stripped.lower():
                    in_ignore_section = True
                    continue
                if in_ignore_section:
                    # Stop at next heading
                    if line_stripped.startswith('#'):
                        break
                    # Extract path patterns from list items like "- `ios/`" or "- ios/"
                    if line_stripped.startswith('-'):
                        pattern = line_stripped.lstrip('- `').rstrip('`/ ')
                        if pattern:
                            patterns.append(pattern.lower())
    except Exception:
        pass
    return patterns


def get_all_source_files(repo_path: str) -> list:
    """Return all git-tracked source files, respecting .gitignore and
    project-specific ignore patterns from COPILOT_INSTRUCTIONS.md.
    No scoring — just a clean file list for the LLM to reason over.
    """
    ignore_patterns = _get_ignore_patterns(repo_path)

    source_extensions = {'.py', '.js', '.jsx', '.ts', '.tsx', '.html', '.htm',
                         '.css', '.scss', '.vue', '.svelte'}

    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_path, capture_output=True, text=True
    )
    all_tracked = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]

    source_files = []
    for rel_path in all_tracked:
        ext = os.path.splitext(rel_path)[1].lower()
        if ext not in source_extensions:
            continue
        rel_lower = rel_path.lower()
        if any(pattern in rel_lower for pattern in ignore_patterns):
            continue
        source_files.append(rel_path)

    return source_files


def find_relevant_files(repo_path: str, spec: str, max_files: int = 7) -> list:
    """Keyword-score source files. Used as a size-guard fallback for very large
    repos where sending the full repo map would exceed token limits.
    """
    source_files = get_all_source_files(repo_path)
    spec_lower = spec.lower()

    keywords = [word for word in spec_lower.split() if len(word) >= 3]
    for word in list(keywords):
        for part in word.split('-'):
            if len(part) >= 3 and part not in keywords:
                keywords.append(part)

    scored = []
    for rel_path in source_files:
        score = calculate_relevance_score(rel_path, spec_lower,
                                          os.path.join(repo_path, rel_path))
        scored.append((rel_path, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in scored[:max_files]]


def build_repo_map(repo_path: str, candidate_files: list) -> str:
    """
    Build a compact repo map using Universal Ctags (Aider-style).
    
    For each candidate file, extracts top-level symbols (functions, classes, hooks)
    and formats them as:
        src/components/TimerPiP.jsx → TimerPiP, getDuration, sessionInfo
        src/hooks/usePictureInPicture.js → usePictureInPicture
    
    Returns empty string if ctags not available (caller falls back gracefully).
    """
    if not CTAGS_BIN or not candidate_files:
        return ""

    # Only include top-level meaningful kinds, skip properties/variables
    USEFUL_KINDS = {'f', 'c', 'C', 'm', 'F', 'v'}  # function, class, component, method

    # Run ctags on all candidate files at once
    abs_files = [os.path.join(repo_path, f) for f in candidate_files if os.path.exists(os.path.join(repo_path, f))]
    if not abs_files:
        return ""

    try:
        result = subprocess.run(
            [
                CTAGS_BIN,
                "--languages=JavaScript,TypeScript,Python",
                "--map-JavaScript=+.jsx",
                "--map-TypeScript=+.tsx",
                "-f", "-",            # output to stdout
                "--fields=+nK",       # include line number and kind
                "--extras=-{subparser}",
            ] + abs_files,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=15
        )
    except Exception:
        return ""

    # Parse ctags output into {rel_path: [symbol, ...]}
    file_symbols: dict = {}
    for line in result.stdout.splitlines():
        if line.startswith('!'):  # ctags header lines
            continue
        parts = line.split('\t')
        if len(parts) < 4:
            continue
        symbol_name = parts[0]
        abs_file = parts[1]
        kind = parts[3] if len(parts) > 3 else ''

        # Map back to relative path
        try:
            rel = os.path.relpath(abs_file, repo_path)
        except ValueError:
            continue

        if rel not in file_symbols:
            file_symbols[rel] = []

        # Keep only top-level useful symbols, skip internal/private/anonymous names
        if kind and kind[0] in USEFUL_KINDS and not symbol_name.startswith(('_', 'anonymous')):
            if symbol_name not in file_symbols[rel]:
                file_symbols[rel].append(symbol_name)

    # Format as compact repo map
    lines = []
    for rel_path in candidate_files:
        symbols = file_symbols.get(rel_path, [])
        if symbols:
            lines.append(f"  {rel_path} → {', '.join(symbols[:12])}")
        else:
            lines.append(f"  {rel_path}")

    return "\n".join(lines)


def calculate_relevance_score(file_path: str, spec_lower: str, full_path: str) -> float:
    """Simple, generic scoring - LLM does the smart selection"""
    score = 0.0
    
    file_lower = file_path.lower()
    
    # PRIORITY: Exact file path mention in spec (e.g., "src/pages/LandingPage.tsx")
    # This handles specs like "Target: src/pages/LandingPage.tsx ONLY"
    if file_lower in spec_lower or file_path in spec_lower:
        score += 100.0  # Massive boost for exact path match
    
    # Check if file name (without path) is mentioned
    file_name = os.path.basename(file_path).lower()
    if file_name in spec_lower:
        score += 50.0  # Big boost for filename match
    
    # Basic keyword matching — include 3-char words so short identifiers like
    # 'pip', 'css', 'api', 'ux' can match file paths
    keywords = [word for word in spec_lower.split() if len(word) >= 3]
    # Also split on hyphens/parens to catch "picture-in-picture" → ["picture", "in", "picture"]
    for word in list(keywords):
        for part in word.split('-'):
            if len(part) >= 3 and part not in keywords:
                keywords.append(part)
    for keyword in keywords:
        if keyword in file_lower:
            score += 1.0  # Simple +1 per keyword match
    
    # Penalize very large files (practical constraint)
    try:
        file_size = os.path.getsize(full_path)
        if file_size > 500000:  # > 500KB
            score -= 2.0
    except:
        pass
    
    return score


def find_relevant_files_smart(repo_path: str, spec: str, max_files: int = 7) -> list:
    """Find files using LLM + project context for intelligent selection"""
    
    # PRIORITY 1: Detect explicit file mentions (e.g., "In the README.md file...")
    # Improved regex to better detect file paths and avoid matching URLs.
    # It looks for paths with extensions, optionally with directory structures.
    explicit_file_pattern = r'\b(?:[\w\-\.]+/)*[\w\-\.]+\.(?:md|py|js|ts|tsx|jsx|html|css|json|yaml|yml)\b'
    explicit_matches = re.findall(explicit_file_pattern, spec, re.IGNORECASE)
    
    if explicit_matches:
        found_files = []
        all_repo_files = []
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'venv', '__pycache__', 'dist', 'build']]
            for file in files:
                all_repo_files.append(os.path.relpath(os.path.join(root, file), repo_path))

        for mentioned_file in explicit_matches:
            for repo_file in all_repo_files:
                if repo_file.endswith(mentioned_file):
                    # Filter out binary files
                    binary_extensions = ['.gif', '.png', '.jpg', '.jpeg', '.ico', '.svg', '.woff', '.woff2', '.eot', '.ttf']
                    if not any(repo_file.lower().endswith(ext) for ext in binary_extensions):
                        if repo_file not in found_files:
                            found_files.append(repo_file)
        
        if found_files:
            print(f"[Smart Selection] Spec mentions explicit files: {explicit_matches} → found {found_files}")
            return found_files[:max_files]
        else:
            print("[Smart Selection] Explicit files mentioned but not found, falling back to LLM.")

    # PRIORITY 2: Check if spec explicitly says "ONLY" as a targeting directive.
    # Must appear after a file extension (e.g. "LandingPage.tsx ONLY") or
    # as uppercase "ONLY" — NOT as a regular English word in a sentence.
    spec_lower = spec.lower()
    has_only_directive = bool(
        re.search(r'\.\w{2,6}\s+only\b', spec_lower) or   # file.ext ONLY
        'ONLY' in spec                                        # uppercase ONLY anywhere
    )
    if has_only_directive:
        # Match any file path with at least one directory separator
        file_pattern = r'(?:[\w\-@]+/)+[\w\-\.]+\.\w{2,6}\b'
        matches = re.findall(file_pattern, spec, re.IGNORECASE)
        
        if matches:
            # Return ONLY the explicitly mentioned files
            print(f"[Smart Selection] Spec contains 'ONLY' - filtering to explicit files: {matches}")
            # Find these files in the repo
            explicit_files = []
            for root, dirs, files in os.walk(repo_path):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'venv', '__pycache__', 'dist', 'build']]
                for file in files:
                    rel_path = os.path.relpath(os.path.join(root, file), repo_path)
                    # Match if any of the patterns appear in the path
                    if any(match.lower() in rel_path.lower() for match in matches):
                        explicit_files.append(rel_path)
            
            if explicit_files:
                print(f"[Smart Selection] Found explicit files: {explicit_files}")
                return explicit_files[:1]  # Return ONLY the one file when spec says "ONLY"

    # LLM-based selection using full repo map
    print(f"[Smart Selection] Building repo map and selecting with LLM...")

    from helpers.context import load_context_files, build_project_context
    from helpers.llm import llm_call

    # Load project context
    context_files = load_context_files(repo_path)
    project_context = build_project_context(context_files)

    # Get all source files (git ls-files + ignore patterns)
    all_source_files = get_all_source_files(repo_path)
    print(f"[Smart Selection] {len(all_source_files)} source files found")

    # Build full repo map — send everything to the LLM so it can navigate by symbol name.
    # For very large repos (>300 files) fall back to keyword pre-filter to stay within token limits.
    FULL_MAP_THRESHOLD = 300
    if len(all_source_files) <= FULL_MAP_THRESHOLD:
        map_files = all_source_files
        print(f"[Smart Selection] Building full repo map ({len(map_files)} files)...")
    else:
        map_files = find_relevant_files(repo_path, spec, max_files=60)
        print(f"[Smart Selection] Large repo — keyword pre-filter to {len(map_files)} files before map")

    repo_map = build_repo_map(repo_path, map_files)
    # Guard: if repo map is too large (>80000 chars ≈ 20k tokens), trim to keyword-scored top-80.
    # This only triggers on very large codebases (500+ files). 30k chars is fine for 128k-context models.
    if repo_map and len(repo_map) > 80000:
        print(f"[Smart Selection] Repo map very large ({len(repo_map)} chars), trimming to top-80 keyword-scored files...")
        map_files = find_relevant_files(repo_path, spec, max_files=80)
        repo_map = build_repo_map(repo_path, map_files)
    if repo_map:
        candidates_section = f"REPO MAP (file → exported symbols):\n{repo_map}"
    else:
        # ctags not available — plain file list
        file_list = "\n".join(f"  {p}" for p in map_files)
        candidates_section = f"ALL SOURCE FILES:\n{file_list}"

    prompt = f"""{project_context}

TASK:
{spec}

{candidates_section}

Using the repo map above, identify which files contain the symbols most relevant
to this task. Match task keywords to symbol names
(e.g. "PiP" → TimerPiP, "picture-in-picture" → usePictureInPicture).

Select the {max_files} MOST relevant files.
Return ONLY file paths, one per line, no explanations, no numbering:
"""
    
    try:
        response = llm_call(
            prompt,
            system_prompt="You are a senior software architect. Select the most relevant files based on project structure and task requirements.",
            max_tokens=500,  # Enough for up to ~10 file paths
            temperature=0.1
        )
        
        # Safety check
        if not response:
            print(f"[Smart Selection] Empty LLM response, falling back to keyword scoring")
            return candidates[:max_files]
        
        # Parse response — use substring matching since LLM may add spaces/numbers
        selected = []
        for line in response.split('\n'):
            line = line.strip()
            # Remove common prefixes like "1. ", "- ", "* "
            line = line.lstrip('0123456789.- *')
            line = line.strip()
            if not line:
                continue
            for candidate in map_files:
                if candidate not in selected and (
                    line == candidate or
                    line.endswith(candidate) or
                    candidate.endswith(line)
                ):
                    selected.append(candidate)
                    break

        if len(selected) < 3:
            print(f"[Smart Selection] LLM returned too few files, falling back to keyword scoring")
            return find_relevant_files(repo_path, spec, max_files=max_files)

        print(f"[Smart Selection] LLM selected: {selected[:max_files]}")
        return selected[:max_files]

    except Exception as e:
        print(f"[Smart Selection] LLM selection failed: {e}, falling back to keyword scoring")
        return find_relevant_files(repo_path, spec, max_files=max_files)