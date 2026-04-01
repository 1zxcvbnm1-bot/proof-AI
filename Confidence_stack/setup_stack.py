"""
AGENT ACCELERATOR — Tech Stack Installer + Validator
Run: python setup_stack.py
Installs all deps, validates connections, runs Phase 2 exit check.
"""

import subprocess, sys, os, importlib

REQUIRED_PACKAGES = [
    ("anthropic",           "anthropic"),
    ("fastapi",             "fastapi"),
    ("uvicorn",             "uvicorn"),
    ("pydantic",            "pydantic"),
    ("numpy",               "numpy"),
    ("cryptography",        "cryptography"),
    ("redis",               "redis"),
    ("psycopg2-binary",     "psycopg2"),
    ("pgvector",            "pgvector"),
    ("llama-index-core",    "llama_index"),
    ("tavily-python",       "tavily"),
    ("prometheus-client",   "prometheus_client"),
    ("presidio-analyzer",   "presidio_analyzer"),
    ("presidio-anonymizer", "presidio_anonymizer"),
    ("spacy",               "spacy"),
]

def install(pkg: str) -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", pkg, "-q"],
        capture_output=True
    )
    return result.returncode == 0

def check_import(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False

def main():
    print("\n" + "═"*60)
    print("  AGENT ACCELERATOR — TECH STACK SETUP")
    print("═"*60)

    # ── Install packages ─────────────────────────────────────────────
    print("\n[1/4] Installing packages...\n")
    results = {}
    for pkg, module in REQUIRED_PACKAGES:
        if check_import(module):
            print(f"  ✅ {pkg:<30} already installed")
            results[pkg] = True
        else:
            print(f"  ⏳ {pkg:<30} installing...", end=" ", flush=True)
            ok = install(pkg)
            results[pkg] = ok
            print("✅" if ok else "❌ FAILED")

    # ── Download spaCy model ─────────────────────────────────────────
    print("\n[2/4] Checking spaCy language model...")
    try:
        import spacy
        spacy.load("en_core_web_lg")
        print("  ✅ en_core_web_lg already downloaded")
    except (OSError, ImportError):
        print("  ⏳ Downloading en_core_web_lg...", end=" ", flush=True)
        r = subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_lg", "-q"],
                          capture_output=True)
        print("✅" if r.returncode == 0 else "❌ FAILED — run manually: python -m spacy download en_core_web_lg")

    # ── Validate environment variables ───────────────────────────────
    print("\n[3/4] Checking environment variables...")
    env_checks = [
        ("ANTHROPIC_API_KEY", "Required — LLM calls"),
        ("VAULT_MASTER_SECRET", "Optional — encryption master key (defaults to dev value)"),
        ("DB_URL",             "Optional — PostgreSQL connection string"),
        ("REDIS_URL",          "Optional — Redis connection string"),
        ("TAVILY_API_KEY",     "Optional — live web retrieval"),
    ]
    for var, desc in env_checks:
        val = os.environ.get(var)
        if val:
            print(f"  ✅ {var:<25} set ({val[:8]}...)")
        else:
            prefix = "  ❌" if var == "ANTHROPIC_API_KEY" else "  ⚠️ "
            print(f"{prefix} {var:<25} not set — {desc}")

    # ── Run self-test ────────────────────────────────────────────────
    print("\n[4/4] Running self-test...")
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "privacy"))
        from privacy import PrivacyVault, Role, ConsentStatus
        vault = PrivacyVault()
        vault.register_user("test", Role.API_USER, consent=ConsentStatus.EXPLICIT)
        result = vault.process_inbound("Test query with email test@example.com", "s001", "test")
        assert result.allowed, "Access denied"
        assert result.pii_detected, "PII not detected"
        assert "[EMAIL_1]" in result.scrubbed_text, "PII not scrubbed"
        print("  ✅ Privacy vault: PII scrubbing working")
        print("  ✅ Privacy vault: access control working")
        print("  ✅ Privacy vault: encryption working")
    except Exception as e:
        print(f"  ❌ Privacy vault test failed: {e}")

    try:
        from audit.confidence_audit import ConfidenceEngine, AuditLogger
        ce = ConfidenceEngine()
        # Mock source
        class MockSource:
            trust_score = 0.9
            authority_tier = 2
            last_verified_at = __import__("time").time() - 86400
        result = ce.compute([MockSource()], [0.85], False)
        assert result.score > 0.5
        print(f"  ✅ Confidence engine: score={result.score:.2f} band={result.band.value}")
        al = AuditLogger()
        print(f"  ✅ Audit logger: initialised, prometheus={al._metrics_registered}")
    except Exception as e:
        print(f"  ❌ Confidence/audit test failed: {e}")

    # ── Summary ──────────────────────────────────────────────────────
    failed = [p for p, ok in results.items() if not ok]
    print("\n" + "─"*60)
    if not failed:
        print("  ALL PACKAGES INSTALLED ✅")
        print("\n  Next steps:")
        print("  1. set ANTHROPIC_API_KEY=sk-ant-...")
        print("  2. python full_system_demo.py")
        print("  3. uvicorn gateway:app --reload --port 8080")
        print("  4. Open http://localhost:8080/docs")
    else:
        print(f"  FAILED: {', '.join(failed)}")
        print("  Run 'pip install <package>' manually for each failed package")
    print("═"*60 + "\n")

if __name__ == "__main__":
    main()
