"""
PHASE 3 — START SCRIPT
Run: python start_phase3.py
Validates environment, runs quick self-test, starts server.
"""

import asyncio, os, sys, subprocess, time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "core"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(BASE), ".env"))

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


async def self_test():
    """Quick self-test before server start."""
    print("\n[Self-test] Running pre-flight checks...")

    if not API_KEY:
        print("  ❌ ANTHROPIC_API_KEY not set")
        print("  Run: $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
        return False

    from agent_loop import AgentLoop, MemoryStore, ToolRegistry, TaskPlanner, SelfVerifier

    # Test memory store
    mem = MemoryStore()
    mem.add("test-session", "user", "Hello")
    msgs = mem.get_messages("test-session")
    assert len(msgs) == 1, "Memory store failed"
    print("  ✅ Memory store working")

    # Test tool registry (no external calls)
    tools = ToolRegistry()
    result = await tools.execute("calculate", {"expression": "2 + 2"}, "test")
    assert result == "4", f"Calculator failed: {result}"
    print("  ✅ Tool registry working (calculate: 2+2=4)")

    # Test agent loop init
    loop = AgentLoop(api_key=API_KEY)
    assert loop.memory is not None
    assert loop.tools  is not None
    print("  ✅ Agent loop initialised")

    # Test JWT
    sys.path.insert(0, os.path.join(BASE, "api", "v1"))
    from router import create_token, verify_token
    token  = create_token("test-user", "free")
    claims = verify_token(token)
    assert claims["sub"] == "test-user"
    assert claims["plan"] == "free"
    print("  ✅ JWT auth working")

    print("  ✅ All checks passed\n")
    return True


def main():
    print("\n" + "═"*60)
    print("  AGENT ACCELERATOR — PHASE 3 START")
    print("═"*60)

    ok = asyncio.run(self_test())
    if not ok:
        sys.exit(1)

    print("[Start] Launching server on http://localhost:8080")
    print("[Start] API docs: http://localhost:8080/docs")
    print("[Start] Stream:   POST http://localhost:8080/v1/agent/stream")
    print("[Start] Health:   GET  http://localhost:8080/v1/health")
    print("\n[Start] Get a token first:")
    print('  curl -X POST http://localhost:8080/v1/auth/token \\')
    print('    -H "Content-Type: application/json" \\')
    print('    -d \'{"user_id":"you","plan":"pro","secret":"admin-dev-secret"}\'')
    print("\n[Start] Then stream a query:")
    print('  curl -X POST http://localhost:8080/v1/agent/stream \\')
    print('    -H "Authorization: Bearer <token>" \\')
    print('    -H "Content-Type: application/json" \\')
    print('    -d \'{"query":"Who founded Anthropic and what do they build?"}\' --no-buffer')
    print("\n" + "═"*60 + "\n")

    try:
        subprocess.run([
            sys.executable, "-m", "uvicorn",
            "server:app",
            "--host", "0.0.0.0",
            "--port", "8080",
            "--reload",
            "--log-level", "info",
        ], cwd=BASE)
    except KeyboardInterrupt:
        print("\n[Server] Shut down successfully.")


if __name__ == "__main__":
    main()
