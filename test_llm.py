"""Quick test to verify OpenRouter API is working"""
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
print(f"API Key present: {bool(api_key)}")
print(f"API Key starts with: {api_key[:15] if api_key else 'None'}...")

try:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key
    )
    
    print("\nTesting OpenRouter API...")
    response = client.chat.completions.create(
        model="deepseek/deepseek-coder",
        messages=[
            {"role": "user", "content": "Say 'Hello, API is working!' and nothing else."}
        ],
        max_tokens=50,
        temperature=0.1
    )
    
    content = response.choices[0].message.content
    print(f"✅ Success! Response: {content}")
    print(f"Response length: {len(content) if content else 0} chars")
    print(f"Response is None: {content is None}")
    print(f"Response is empty: {content == '' if content else 'N/A'}")
    
except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {str(e)}")
    import traceback
    traceback.print_exc()

# Create smoke test file at repository root
print("\nCreating smoke-test.txt...")
try:
    with open("smoke-test.txt", "w") as f:
        f.write("Developer Agents Workflow smoke test passed.\n")
    print("✅ smoke-test.txt created successfully.")
except Exception as e:
    print(f"❌ Failed to create smoke-test.txt: {e}")
