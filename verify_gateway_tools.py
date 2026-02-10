import requests
import subprocess
import json
import os
import sys
from uuid import uuid4

# Gateway Endpoint
GATEWAY_URL = "https://jars-gw-afejhtqoqd.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"

def generate_token():
    print("Generating token...")
    try:
        # Run genToken.py located in agent/ directory from root
        result = subprocess.run(
            [sys.executable, "agent/genToken.py"], 
            capture_output=True, 
            text=True, 
            encoding='utf-8',
            check=True
        )
        for line in result.stdout.splitlines():
            if "AccessToken:" in line:
                return line.split("AccessToken:")[1].strip()
        print("Could not find AccessToken in output.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error generating token: {e}")
        print(e.stderr)
        return None

def invoke_mcp(method, params, token):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": method,
        "params": params or {}
    }
    
    print(f"\nExample Request [{method}]:")
    print(f"POST {GATEWAY_URL}")
    
    try:
        response = requests.post(GATEWAY_URL, headers=headers, json=payload, timeout=30)
        print(f"Status: {response.status_code}")
        
        try:
            return response.json()
        except:
            print("Response text:", response.text)
            return None
            
    except Exception as e:
        print(f"Request failed: {e}")
        return None

def main():
    # 1. Get Token
    token = generate_token()
    if not token:
        sys.exit(1)
        
    # 2. List Tools
    print("\n--- Listing Tools ---")
    list_res = invoke_mcp("tools/list", {}, token)
    
    if not list_res:
        print("Empty response from tools/list")
        sys.exit(1)
        
    if "error" in list_res:
        print(f"Error listing tools: {json.dumps(list_res['error'], indent=2)}")
        # If list fails, we likely can't call tools either, but let's try one just in case
    else:
        tools = list_res.get("result", {}).get("tools", [])
        print(f"Found {len(tools)} tools:")
        for t in tools:
            print(f"- {t['name']}")
            
    # 3. Call 'spend_analytics_v1' (Smoke Test) using prefixed name and valid User ID
    print("\n--- Calling Tool: finance-mcp___spend_analytics_v1 ---")
    
    full_tool_name = "finance-mcp___spend_analytics_v1"
    
    # User provided valid ID: 64481438-5011-7008-00f8-03e42cc06593
    user_id = os.getenv("COGNITO_USERNAME", "64481438-5011-7008-00f8-03e42cc06593")
    
    call_params = {
        "name": full_tool_name,
        "arguments": {
            "user_id": user_id,
            # spend_analytics might take other args, but defaults often work. 
            # based on screenshot, arguments was just user_id (and empty jar_id/range implicitly?)
            # The screenshot shows arguments = { user_id = ... }
        }
    }
    
    call_res = invoke_mcp("tools/call", call_params, token)
    if not call_res:
        print("Empty response from tools/call")
    elif "error" in call_res:
        print(f"Error calling tool: {json.dumps(call_res['error'], indent=2)}")
    else:
        print("Tool call successful!")
        print(json.dumps(call_res.get("result", {}), indent=2))

if __name__ == "__main__":
    main()
