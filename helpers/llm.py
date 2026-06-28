import os
import re
from openai import OpenAI
from helpers.context import load_context_files, build_project_context
from helpers.observability import get_traced_llm_client

# ===== LLM CONFIGURATION =====
# Set these in your .env file to switch between providers
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # "ollama" or "openrouter"
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5-coder:7b")  # Model to use

def get_llm_client():
    """Get configured LLM client based on LLM_PROVIDER (with Langfuse tracing if enabled).
    
    This wraps the OpenAI client with automatic observability:
    - If LANGFUSE_* env vars are set: Returns traced client (logs all prompts/responses)
    - If LANGFUSE_* env vars are missing: Returns standard OpenAI client (no overhead)
    
    The client creation logic is in observability.py to support drop-in tracing.
    """
    return get_traced_llm_client(LLM_PROVIDER, LLM_MODEL)

def generate_patch(spec: str, file_contexts: dict, error_logs: list = None, repo_path: str = None) -> dict:
    """Generate Search/Replace blocks using the configured LLM.

    Returns a dict mapping each file path to its S/R block string:
        {
            "src/components/TimerPiP.jsx": "<<<< SEARCH\\n...\\n>>>> REPLACE",
            "src/components/TimerPiP.css": "<<<< SEARCH\\n...\\n>>>> REPLACE",
        }
    Single-file tickets return a one-item dict.
    """

    client = get_llm_client()
    print(f"[LLM] Using {LLM_PROVIDER}/{LLM_MODEL}")

    # Load project context (conventions, architecture docs, etc.)
    project_context = ""
    if repo_path:
        context_files = load_context_files(repo_path)
        project_context = build_project_context(context_files)

    MAX_FILE_LINES = 99999  # No truncation — each file is sent in its own LLM call,
    # so token budget is per-file not total. Modern LLMs (128k ctx) handle large files fine.

    if len(file_contexts) == 1:
        path, content = list(file_contexts.items())[0]
        blocks = _generate_single_file_patch(
            client, project_context, spec, path, content, error_logs, max_lines=99999
        )
        result = {path: blocks}
        
        # Generate Playwright test for UI changes (single file case)
        ui_test = _generate_playwright_test(client, repo_path, spec, [path])
        if ui_test:
            result.update(ui_test)
        
        return result
    else:
        print(f"[LLM] Multi-file patch: generating {len(file_contexts)} patches sequentially...")
        result = {}
        for path, content in file_contexts.items():
            print(f"[LLM] Generating patch for {path}...")
            blocks = _generate_single_file_patch(
                client, project_context, spec, path, content, error_logs, MAX_FILE_LINES
            )
            if blocks and blocks.strip():
                result[path] = blocks
            else:
                print(f"[LLM] Skipped {path} - no changes generated")

        if not result:
            raise ValueError("No valid patches generated")

        # Only ask for new files when the spec signals new file creation.
        # Avoids wasted LLM calls on modification-only tickets (~95% of cases).
        NEW_FILE_SIGNALS = ["create", "new component", "new page", "new file",
                            "add a route", "build a", "typing game", "new feature"]
        if any(s in spec.lower() for s in NEW_FILE_SIGNALS):
            new_files = _generate_new_files(client, project_context, spec, list(result.keys()))
            result.update(new_files)
        
        # Generate Playwright test for UI changes
        ui_test = _generate_playwright_test(client, repo_path, spec, list(result.keys()))
        if ui_test:
            result.update(ui_test)

        return result


def _generate_new_files(client, project_context: str, spec: str, existing_patched: list) -> dict:
    """Ask the LLM if any brand-new files need to be created for this feature.

    Returns a dict of {new_file_path: sr_block_string} using the empty-SEARCH
    convention:
        <<<< SEARCH
        ====
        [full file content]
        >>>> REPLACE
    """
    patched_str = "\n".join(f"  - {p}" for p in existing_patched)

    prompt = f"""You are an expert coding agent. You just generated patches for these existing files:
{patched_str}

TASK:
{spec}

Do you need to CREATE any brand-new files (files that don't exist yet) to fully
implement this feature?

If YES, list each new file path and its COMPLETE content using this exact format:

# NEW_FILE: src/components/MyNewComponent.jsx
<<<< SEARCH
====
[complete file content here]
>>>> REPLACE

If NO new files are needed, respond with exactly: NO_NEW_FILES
"""
    try:
        response = llm_call(
            prompt,
            system_prompt="You are an expert coding agent. Create complete, production-ready new files when required.",
            max_tokens=8000,
            temperature=0.1
        )
    except Exception as e:
        print(f"[LLM] New-file generation failed: {e}")
        return {}

    if not response or "NO_NEW_FILES" in response:
        return {}

    # Parse # NEW_FILE: path sections
    new_files = {}
    sections = re.split(r'^# NEW_FILE:\s*', response, flags=re.MULTILINE)
    for section in sections[1:]:  # skip preamble before first marker
        lines = section.strip().split('\n', 1)
        if not lines:
            continue
        new_path = lines[0].strip()
        content_block = lines[1].strip() if len(lines) > 1 else ""
        if new_path and '<<<< SEARCH' in content_block:
            new_files[new_path] = content_block
            print(f"[LLM] New file queued: {new_path}")

    return new_files


def _generate_playwright_test(client, repo_path: str, spec: str, patched_files: list) -> dict:
    """Generate a Playwright test for UI changes.
    
    Only generates test for UI-related specs (button, component, page, etc.)
    Returns dict with test file path and content, or empty dict if no test needed.
    """
    
    # Only generate tests for UI changes
    UI_INDICATORS = ['button', 'component', 'page', 'ui', 'interface', 'form', 'modal',
                     'menu', 'navigation', 'fab', 'chat', 'display', 'render', 'view']
    
    if not any(indicator in spec.lower() for indicator in UI_INDICATORS):
        print("[LLM] Spec doesn't indicate UI changes - skipping test generation")
        return {}
    
    # Check if this is a UI project (has package.json with UI frameworks)
    if not repo_path:
        return {}
    
    package_json = os.path.join(repo_path, "package.json")
    if not os.path.exists(package_json):
        print("[LLM] No package.json found - skipping Playwright test")
        return {}
    
    try:
        import json as json_lib
        with open(package_json, 'r') as f:
            data = json_lib.load(f)
            deps = {**data.get('dependencies', {}), **data.get('devDependencies', {})}
            
            # Check for UI frameworks
            ui_frameworks = ['react', 'vue', 'svelte', 'next', 'vite', 'angular']
            if not any(fw in deps for fw in ui_frameworks):
                print("[LLM] Not a UI project - skipping Playwright test")
                return {}
    except:
        return {}
    
    # Generate the test
    patched_str = "\n".join(f"  - {p}" for p in patched_files)
    
    prompt = f"""You are an expert QA engineer. Generate a Playwright test to validate UI changes.

<specification>
{spec}
</specification>

<files_being_changed>
{patched_str}
</files_being_changed>

Generate a COMPLETE Playwright test file that validates the changes work correctly.

REQUIREMENTS:
1. Test file should be at: tests/playwright/auto-generated.spec.js
2. Test should:
   - Navigate to the relevant page (usually http://localhost:3000 or main route)
   - Find and verify the new UI elements exist and are visible
   - Test any interactions mentioned in the spec (clicks, inputs, etc.)
   - Check for console errors

3. Use this template structure:

import {{ test, expect }} from '@playwright/test';

test('[Brief description of what you're testing]', async ({{ page }}) => {{
  // Navigate to the page
  await page.goto('http://localhost:3000');
  
  // Wait for and verify new elements
  await page.waitForSelector('[appropriate-selector]');
  const element = page.locator('[appropriate-selector]');
  await expect(element).toBeVisible();
  
  // Test interactions if applicable
  await element.click();
  
  // Verify expected behavior
  // ...
}});

4. Use specific selectors based on the components being changed
5. Keep the test focused - test the SPECIFIC changes in the spec, not the entire app

OUTPUT FORMAT: Use the NEW_FILE format with Search/Replace blocks:

# NEW_FILE: tests/playwright/auto-generated.spec.js
<<<< SEARCH
====
[complete test file content here]
>>>> REPLACE

Generate the test file now:"""

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert QA engineer creating Playwright tests."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            temperature=0.2
        )
        
        output = response.choices[0].message.content
        
        if not output or "NO_TEST_NEEDED" in output:
            return {}
        
        # Parse the NEW_FILE format
        if '# NEW_FILE:' in output and '<<<< SEARCH' in output:
            sections = re.split(r'^# NEW_FILE:\s*', output, flags=re.MULTILINE)
            for section in sections[1:]:
                lines = section.strip().split('\n', 1)
                if not lines:
                    continue
                test_path = lines[0].strip()
                content_block = lines[1].strip() if len(lines) > 1 else ""
                if test_path and '<<<< SEARCH' in content_block:
                    print(f"[LLM] Generated Playwright test: {test_path}")
                    return {test_path: content_block}
        
    except Exception as e:
        print(f"[LLM] Playwright test generation failed: {e}")
    
    return {}


def _generate_single_file_patch(client, project_context: str, spec: str, file_path: str, content: str, error_logs: list, max_lines: int) -> str:
    """Generate Search/Replace blocks for a single file"""

    # Detect language from extension
    ext_map = {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
        '.jsx': 'jsx', '.tsx': 'tsx', '.html': 'html', '.css': 'css',
        '.json': 'json', '.md': 'markdown', '.yml': 'yaml', '.yaml': 'yaml'
    }
    ext = os.path.splitext(file_path)[1]
    lang = ext_map.get(ext, '')
    
    # Truncate large files only if max_lines is reasonable (not 99999)
    lines = content.split('\n')
    if max_lines < 99999 and len(lines) > max_lines:
        content = '\n'.join(lines[:max_lines])
        print(f"[LLM] Truncated {file_path} to {max_lines} lines")
    
    # Build structured prompt
    prompt = f"""You are an expert automated coding agent. Your task is to modify `{file_path}` based on the specification below.

<project_context>
{project_context if project_context else "No additional project context available."}
</project_context>

<specification>
{spec}
</specification>

<current_code file="{file_path}" language="{lang}">
{content}
</current_code>"""

    if error_logs:
        error_text = chr(10).join(error_logs)
        
        # Detect error type and provide context-specific guidance
        if "[Playwright Test]" in error_text or "test failed" in error_text.lower():
            guidance = """
IMPORTANT: The Playwright test failed. This means your code changes don't work correctly:
- If element not found: Check selectors, class names, data-testid attributes
- If assertion failed: The behavior doesn't match the spec
- If timeout: Element might not be rendering or takes too long
Review the test failure carefully and fix BOTH the code AND the test if needed."""
        elif "syntax error" in error_text.lower() or "cannot find" in error_text.lower():
            guidance = "IMPORTANT: There's a syntax or import error. Fix the syntax and ensure all imports are correct."
        elif "SEARCH" in error_text or "REPLACE" in error_text:
            guidance = "IMPORTANT: The SEARCH block did not match. Copy the code from <current_code> character-for-character."
        else:
            guidance = "IMPORTANT: Review the error carefully and fix the issue."
        
        prompt += f"""

<previous_errors>
The previous attempt failed with these errors:
{error_text}

{guidance}
</previous_errors>"""

    prompt += """

<rules>
1. OUTPUT FORMAT: Use ONLY Search/Replace blocks. No unified diffs, no +/- markers, no @@ headers.

2. EXACT MATCH: The content inside <<<< SEARCH must EXACTLY match the current file content, character for character, including all indentation and whitespace. Copy the code directly from <current_code> — do not retype it.

3. IMPLEMENT ALL CHANGES: Implement EVERY change requested in the specification. Do not skip any.

4. UNIQUE ANCHORS: Start each SEARCH block with a unique, distinctive line — prefer JSX comments ({/* Section Name */}), specific prop values, or unique className strings. NEVER start a SEARCH block with a generic closing tag like </div>, </section>, or </p> alone — these appear dozens of times in the file and you will pick the wrong one. If you need to insert before a section, anchor on the section's unique opening comment or tag.

5. MINIMAL CONTEXT: Use the minimum amount of context needed to uniquely identify the location. 1-3 lines is usually enough if you pick a distinctive anchor.

6. COMPLETE BLOCKS: Never truncate. If you add an opening tag, include the closing tag. Never leave expressions incomplete.

7. READ-ONLY FILES: The <project_context> section contains documentation files loaded for reference only. Do NOT generate Search/Replace blocks targeting those files (README.md, CONTRIBUTING.md, COPILOT_INSTRUCTIONS.md, etc.). Only generate blocks for files provided in <current_code> tags.

8. ZERO PREAMBLE: Output ONLY the Search/Replace blocks. No explanations, no markdown fences around blocks.
</rules>

<format>
<<<< SEARCH
[exact code from the file to find]
====
[new code to replace it with]
>>>> REPLACE
</format>

<example>
<<<< SEARCH
      <title>Old Title</title>
      <meta name="description" content="Old description" />
====
      <title>New Title | Better Keywords</title>
      <meta name="description" content="New description with keywords" />
>>>> REPLACE
</example>

Generate the Search/Replace blocks now:"""

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert coding agent. Output ONLY Search/Replace blocks using the exact format: <<<< SEARCH / ==== / >>>> REPLACE. The SEARCH content must exactly match the existing file. No explanations, no unified diffs, no markdown."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=16000,
        temperature=0.1
    )
    
    output = response.choices[0].message.content
    if not output:
        raise ValueError("LLM returned empty response")
    
    # Validate at least one block was generated
    if '<<<< SEARCH' not in output:
        raise ValueError("LLM did not generate any Search/Replace blocks")
    
    print(f"[LLM] Generated Search/Replace output ({len(output)} chars)")
    return output


def llm_call(prompt: str, system_prompt: str = None, max_tokens: int = 500, temperature: float = 0.1) -> str:
    """Simple LLM call for file selection and other tasks.
    Retries up to 3 times on empty/null responses (transient API issue).
    """
    import time
    client = get_llm_client()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    last_error = None
    for attempt in range(1, 4):  # 3 attempts
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            content = response.choices[0].message.content
            if content is None or content.strip() == "":
                raise ValueError("LLM returned empty response")
            return content
        except Exception as e:
            last_error = e
            if attempt < 3:
                wait = attempt * 2  # 2s, 4s
                print(f"[LLM] llm_call attempt {attempt} failed ({e}), retrying in {wait}s...")
                time.sleep(wait)

    raise ValueError(f"LLM API call failed after 3 attempts: {last_error}")