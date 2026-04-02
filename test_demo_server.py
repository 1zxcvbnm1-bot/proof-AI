#!/usr/bin/env python3
"""
Test the demo server by starting it and making a sample request.
"""

import asyncio
import sys
import os
import threading
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def start_server():
    """Start the server in a thread."""
    import uvicorn
    uvicorn.run("demo_server:app", host="127.0.0.1", port=8080, log_level="error")

async def test_api():
    """Test the fact-check API."""
    print("=" * 70)
    print("TESTING PROOF-AI DEMO SERVER")
    print("=" * 70)

    # Wait for server to start
    print("\n[1] Waiting for server to start...")
    server_up = False
    for i in range(15):
        try:
            resp = requests.get("http://127.0.0.1:8080/api/health", timeout=1)
            if resp.status_code == 200:
                print("    [OK] Server is up!")
                server_up = True
                break
        except:
            time.sleep(1)
    if not server_up:
        print("    [FAIL] Server failed to start")
        return False

    # Test fact-check endpoint
    print("\n[2] Testing fact-check endpoint (non-streaming)...")
    try:
        response = requests.post(
            "http://127.0.0.1:8080/api/fact-check",
            json={
                "api_key": "mock-test-key",
                "provider": "groq",
                "query": "Python was created by Guido van Rossum in 1991.",
                "stream": False
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            print(f"    [OK] Got response:")
            print(f"       - Total claims: {data.get('total_claims')}")
            print(f"       - Verified: {data.get('verified')}")
            print(f"       - Blocked: {data.get('blocked')}")
            print(f"       - Hallucination rate: {data.get('halluc_rate', 0)*100:.1f}%")
            print(f"       - Latency: {data.get('latency_ms', 0):.1f}ms")
            return True
        else:
            print(f"    [FAIL] HTTP {response.status_code}: {response.text[:200]}")
            return False

    except Exception as e:
        print(f"    [FAIL] Request failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Start server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Run test
    try:
        success = asyncio.run(test_api())
        print("\n" + "=" * 70)
        if success:
            print("[SUCCESS] SERVER TEST PASSED")
            print("Open http://localhost:8080 in your browser to use the live demo!")
        else:
            print("[FAIL] SERVER TEST FAILED")
        print("=" * 70)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(0)
