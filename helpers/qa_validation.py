"""
QA Validation Module - LLM-driven intelligent testing
"""
import os
import json
import subprocess
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ===== LLM-DRIVEN QA STRATEGY =====

def decide_qa_strategy(repo_path: str, patch: dict, spec: str) -> dict:
    """
    Ask LLM what QA tests to run based on the patch.
    Returns dict with:
        - skip_all: bool
        - reason: str
        - actions: list of test actions
    """
    from helpers.llm import llm_call
    
    # Analyze patch
    files = list(patch.keys())
    file_extensions = set(f.split('.')[-1] for f in files if '.' in f)
    
    # Check repo structure
    has_package_json = os.path.exists(os.path.join(repo_path, "package.json"))
    has_pytest = os.path.exists(os.path.join(repo_path, "pytest.ini")) or \
                 os.path.exists(os.path.join(repo_path, "tests"))
    has_playwright = os.path.exists(os.path.join(repo_path, "playwright.config.js")) or \
                     os.path.exists(os.path.join(repo_path, "playwright.config.ts"))
    has_node_modules = os.path.exists(os.path.join(repo_path, "node_modules"))
    
    # Get package.json scripts if available
    available_scripts = []
    if has_package_json:
        try:
            with open(os.path.join(repo_path, "package.json"), 'r') as f:
                data = json.load(f)
                available_scripts = list(data.get('scripts', {}).keys())
        except:
            pass
    
    prompt = f"""You are a QA engineer deciding what tests to run for this code change.

PATCH SUMMARY:
- Files changed: {files}
- File types: {list(file_extensions)}
- Spec: {spec[:300]}

REPOSITORY TOOLS:
- package.json exists: {has_package_json}
- node_modules installed: {has_node_modules}
- Available npm scripts: {available_scripts}
- pytest available: {has_pytest}
- playwright configured: {has_playwright}

TASK: Decide what QA validation is needed. Guidelines:
1. Documentation files (*.md, *.txt) → skip all tests
2. Config files only (*.json, *.yaml) → minimal validation
3. Code changes → need appropriate tests based on language/framework
4. UI changes (React, components) → may need build + UI tests
5. Dependencies not installed? → need to install first
6. Backend only → skip UI tests

Return JSON only (no markdown, no explanation):
{{
  "skip_all": true or false,
  "reason": "brief explanation why",
  "actions": [
    {{"type": "install_deps", "command": "npm install"}},
    {{"type": "syntax"}},
    {{"type": "build", "command": "npm run build"}},
    {{"type": "test", "command": "npm test"}},
    {{"type": "pytest", "command": "pytest"}},
    {{"type": "playwright"}}
  ]
}}

Examples:
- README.md only → {{"skip_all": true, "reason": "documentation only", "actions": []}}
- React component change → {{"skip_all": false, "reason": "UI code change", "actions": [{{"type": "syntax"}}, {{"type": "build", "command": "npm run build"}}]}}
- Python file → {{"skip_all": false, "reason": "Python code", "actions": [{{"type": "syntax"}}, {{"type": "pytest", "command": "pytest"}}]}}
"""
    
    try:
        response = llm_call(prompt, temperature=0.1, max_tokens=500)
        
        # Parse JSON from response (strip markdown if present)
        response = response.strip()
        if response.startswith('```'):
            # Extract JSON from markdown code block
            lines = response.split('\n')
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith('```'):
                    in_block = not in_block
                    continue
                if in_block:
                    json_lines.append(line)
            response = '\n'.join(json_lines)
        
        strategy = json.loads(response)
        logger.info(f"[QA] LLM Strategy: {strategy['reason']}")
        return strategy
        
    except Exception as e:
        logger.warning(f"[QA] LLM strategy failed: {e}, using safe default")
        # Safe default: run basic validation
        return {
            "skip_all": False,
            "reason": "LLM failed, running safe defaults",
            "actions": [{"type": "syntax"}]
        }


# ===== TIER 1: STATIC VALIDATION =====

def validate_syntax(repo_path: str, patch: dict) -> tuple[bool, str]:
    """
    Run syntax checks on patched files (Python, JS, TS, etc.)
    Returns (success, error_message)
    """
    logger.info("[QA] Running static syntax validation...")
    
    errors = []
    
    for file_path in patch.keys():
        # Skip test files for now (they'll be validated when run)
        if 'test' in file_path or 'spec' in file_path:
            continue
            
        full_path = os.path.join(repo_path, file_path)
        
        # Skip if file doesn't exist yet (new file creation)
        if not os.path.exists(full_path):
            continue
        
        ext = os.path.splitext(file_path)[1]
        
        # Python files
        if ext == '.py':
            result = subprocess.run(
                ['python', '-m', 'py_compile', full_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                errors.append(f"Python syntax error in {file_path}:\n{result.stderr}")
        
        # JavaScript/TypeScript files
        elif ext in ['.js', '.jsx', '.ts', '.tsx']:
            # Try node --check first (fast)
            result = subprocess.run(
                ['node', '--check', full_path],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=repo_path
            )
            if result.returncode != 0:
                errors.append(f"JS/TS syntax error in {file_path}:\n{result.stderr}")
    
    if errors:
        return False, "\n\n".join(errors)
    
    logger.info("[QA] ✓ Static validation passed")
    return True, ""


def run_existing_tests(repo_path: str, patch: dict) -> tuple[bool, str]:
    """
    Run existing test suites (npm test, pytest, etc.)
    Only runs if tests already exist in the repo
    Returns (success, error_message)
    """
    logger.info("[QA] Checking for existing tests...")
    
    errors = []
    
    # Check for JavaScript/TypeScript tests
    package_json = os.path.join(repo_path, "package.json")
    if os.path.exists(package_json):
        try:
            with open(package_json, 'r') as f:
                data = json.load(f)
                scripts = data.get('scripts', {})
                
                # Run build if build script exists (catches TypeScript errors)
                if 'build' in scripts:
                    logger.info("[QA] Running npm run build...")
                    result = subprocess.run(
                        ['npm', 'run', 'build'],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=180
                    )
                    if result.returncode != 0:
                        errors.append(f"Build failed:\n{result.stderr[:1000]}")
                
                # Run existing tests if test script exists AND test directory exists
                if 'test' in scripts:
                    test_dirs = ['test', 'tests', '__tests__', 'src/__tests__']
                    has_tests = any(os.path.exists(os.path.join(repo_path, d)) for d in test_dirs)
                    
                    if has_tests:
                        logger.info("[QA] Running npm test...")
                        result = subprocess.run(
                            ['npm', 'test', '--', '--passWithNoTests'],
                            cwd=repo_path,
                            capture_output=True,
                            text=True,
                            timeout=120
                        )
                        if result.returncode != 0:
                            # Only fail if tests actually failed (not just warnings)
                            if 'FAIL' in result.stdout or 'failed' in result.stdout.lower():
                                errors.append(f"Unit tests failed:\n{result.stdout[:1000]}")
        except Exception as e:
            logger.warning(f"[QA] Error checking npm tests: {e}")
    
    # Check for Python tests
    pytest_indicators = ['pytest.ini', 'setup.py', 'pyproject.toml']
    has_pytest_config = any(os.path.exists(os.path.join(repo_path, f)) for f in pytest_indicators)
    test_dir_exists = os.path.exists(os.path.join(repo_path, 'tests')) or \
                     os.path.exists(os.path.join(repo_path, 'test'))
    
    if has_pytest_config or test_dir_exists:
        # Check if pytest is available
        pytest_check = subprocess.run(['pytest', '--version'], capture_output=True)
        if pytest_check.returncode == 0:
            logger.info("[QA] Running pytest...")
            result = subprocess.run(
                ['pytest', '-v', '--tb=short'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode != 0:
                errors.append(f"Python tests failed:\n{result.stdout[:1000]}")
    
    if errors:
        return False, "\n\n".join(errors)
    
    logger.info("[QA] ✓ Existing tests passed (or no tests found)")
    return True, ""


def validate_patch_integrity(patch: dict) -> tuple[bool, str]:
    """
    Verify patch structure is valid (basic sanity checks)
    Returns (success, error_message)
    """
    logger.info("[QA] Validating patch integrity...")
    
    if not patch:
        return False, "Patch is empty"
    
    if not isinstance(patch, dict):
        return False, f"Patch must be dict, got {type(patch).__name__}"
    
    # Check each file has valid S/R blocks (or is a new file)
    for file_path, content in patch.items():
        if not content:
            continue  # Empty is OK (might be deletion)
        
        # If it has S/R blocks, verify format
        if '<<<< SEARCH' in content:
            if '>>>> REPLACE' not in content:
                return False, f"{file_path}: Has SEARCH but no REPLACE block"
    
    logger.info("[QA] ✓ Patch integrity validated")
    return True, ""


# ===== TIER 2: PLAYWRIGHT TEST EXECUTION =====

def detect_project_type(repo_path: str) -> str:
    """
    Detect if project is UI, backend, or full-stack
    Returns: "ui", "backend", "fullstack", or "unknown"
    """
    package_json = os.path.join(repo_path, "package.json")
    
    if os.path.exists(package_json):
        try:
            with open(package_json, 'r') as f:
                data = json.load(f)
                deps = {**data.get('dependencies', {}), **data.get('devDependencies', {})}
                
                # Check for UI frameworks
                ui_indicators = ['react', 'vue', 'svelte', 'next', 'vite', 'angular']
                has_ui = any(indicator in deps for indicator in ui_indicators)
                
                # Check for backend frameworks
                backend_indicators = ['express', 'fastify', 'koa', 'nest']
                has_backend = any(indicator in deps for indicator in backend_indicators)
                
                if has_ui and has_backend:
                    return "fullstack"
                elif has_ui:
                    return "ui"
                elif has_backend:
                    return "backend"
        except:
            pass
    
    # Check for Python web frameworks
    requirements = os.path.join(repo_path, "requirements.txt")
    if os.path.exists(requirements):
        with open(requirements, 'r') as f:
            content = f.read().lower()
            if any(fw in content for fw in ['django', 'flask', 'fastapi']):
                return "backend"
    
    return "unknown"


def detect_dev_server_command(repo_path: str) -> str:
    """
    Detect how to start the dev server from package.json
    Returns command string like "npm run dev" or None
    """
    package_json = os.path.join(repo_path, "package.json")
    
    if not os.path.exists(package_json):
        return None
    
    try:
        with open(package_json, 'r') as f:
            data = json.load(f)
            scripts = data.get('scripts', {})
            
            # Try common dev server commands
            for cmd in ['dev', 'start', 'serve']:
                if cmd in scripts:
                    return f"npm run {cmd}"
    except:
        pass
    
    return None


def wait_for_server(url: str = "http://localhost:3000", timeout: int = 30) -> bool:
    """
    Wait for dev server to be ready
    Returns True if server responds, False if timeout
    """
    import urllib.request
    
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=2)
            logger.info(f"[QA] Server ready at {url}")
            return True
        except:
            time.sleep(1)
    
    logger.warning(f"[QA] Server not ready after {timeout}s")
    return False


def run_playwright_test(repo_path: str, test_file: str, ticket_id: str) -> tuple[bool, str]:
    """
    Execute a Playwright test file
    Returns (success, output/error_logs)
    """
    logger.info(f"[QA] Running Playwright test: {test_file}")
    
    # Ensure playwright is installed
    logger.info("[QA] Installing Playwright dependencies...")
    install_result = subprocess.run(
        ['npm', 'install', '--save-dev', '@playwright/test'],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=120
    )
    
    if install_result.returncode != 0:
        return False, f"Failed to install Playwright:\n{install_result.stderr}"
    
    # Install browsers if needed (only chromium for speed)
    subprocess.run(
        ['npx', 'playwright', 'install', 'chromium', '--with-deps'],
        cwd=repo_path,
        capture_output=True,
        timeout=180
    )
    
    # Detect dev server command
    dev_cmd = detect_dev_server_command(repo_path)
    
    if not dev_cmd:
        return False, "Could not detect dev server command (no 'dev' or 'start' script in package.json)"
    
    # Start dev server
    logger.info(f"[QA] Starting dev server: {dev_cmd}")
    server_proc = subprocess.Popen(
        dev_cmd.split(),
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    try:
        # Wait for server to be ready
        if not wait_for_server():
            return False, "Dev server failed to start within 30s"
        
        # Run the Playwright test
        logger.info(f"[QA] Executing test: {test_file}")
        test_result = subprocess.run(
            ['npx', 'playwright', 'test', test_file, '--reporter=line'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=90
        )
        
        success = test_result.returncode == 0
        output = test_result.stdout + "\n" + test_result.stderr
        
        if success:
            logger.info("[QA] ✓ Playwright test passed!")
        else:
            logger.warning(f"[QA] ✗ Playwright test failed:\n{output[:500]}")
        
        return success, output
    
    except subprocess.TimeoutExpired:
        return False, "Playwright test timed out after 90s"
    
    except Exception as e:
        return False, f"Playwright test error: {str(e)}"
    
    finally:
        # Always kill the server
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except:
            server_proc.kill()


# ===== MAIN QA ORCHESTRATOR =====

def run_qa_validation(repo_path: str, patch: dict, spec: str, ticket_id: str) -> tuple[bool, str]:
    """
    LLM-driven QA validation orchestrator
    
    Uses LLM to decide what tests to run based on the patch context.
    Returns (success, error_message)
    """
    
    # Ask LLM what tests to run
    strategy = decide_qa_strategy(repo_path, patch, spec)
    
    # If LLM says skip everything, trust it
    if strategy.get("skip_all", False):
        logger.info(f"[QA] ✓ Skipping validation: {strategy.get('reason', 'no tests needed')}")
        return True, ""
    
    # Execute actions in sequence
    logger.info(f"[QA] Running validation: {strategy.get('reason', 'standard checks')}")
    actions = strategy.get('actions', [])
    
    for action in actions:
        action_type = action.get('type')
        
        if action_type == 'install_deps':
            logger.info("[QA] Installing dependencies...")
            cmd = action.get('command', 'npm install')
            result = subprocess.run(
                cmd.split(),
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode != 0:
                return False, f"[Dependency Install] Failed:\n{result.stderr[:500]}"
        
        elif action_type == 'syntax':
            success, error = validate_syntax(repo_path, patch)
            if not success:
                return False, f"[Syntax] {error}"
        
        elif action_type == 'build':
            logger.info(f"[QA] Running build...")
            cmd = action.get('command', 'npm run build')
            result = subprocess.run(
                cmd.split(),
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=180
            )
            if result.returncode != 0:
                return False, f"[Build] Failed:\n{result.stderr[:1000]}"
        
        elif action_type == 'test':
            logger.info(f"[QA] Running tests...")
            cmd = action.get('command', 'npm test')
            result = subprocess.run(
                cmd.split() + ['--', '--passWithNoTests'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode != 0 and ('FAIL' in result.stdout or 'failed' in result.stdout.lower()):
                return False, f"[Tests] Failed:\n{result.stdout[:1000]}"
        
        elif action_type == 'pytest':
            logger.info(f"[QA] Running pytest...")
            result = subprocess.run(
                ['pytest', '-v', '--tb=short'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode != 0:
                return False, f"[Pytest] Failed:\n{result.stdout[:1000]}"
        
        elif action_type == 'playwright':
            test_files = [f for f in patch.keys() if 'playwright' in f.lower() or 'spec' in f]
            if test_files:
                success, output = run_playwright_test(repo_path, test_files[0], ticket_id)
                if not success:
                    return False, f"[Playwright] {output}"
            else:
                logger.info("[QA] Playwright requested but no test files found - skipping")
        
        else:
            logger.warning(f"[QA] Unknown action type: {action_type}")
    
    logger.info("[QA] ✓ All validation checks passed")
    return True, ""
