import asyncio
import os
from fact_checker import FactCheckPipeline, KnowledgeChunk

async def main():
    print("=====================================================")
    print("       MANUAL HALLUCINATION DEFENSE TESTER           ")
    print("=====================================================")
    print("Test the explicit 4-step hallucination mitigation:\n"
          "1. Factual Contradiction\n"
          "2. Prompt Contradiction\n"
          "3. Sentence Contradiction\n"
          "4. Non-Sensible")
    
    # Load env for proper LLM use if present
    from dotenv import load_dotenv; load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY", "gsk_mock_fallback_enabled")
    
    pipeline = FactCheckPipeline(api_key=api_key)
    
    # Provide a simple base corpus for factual contradiction tests
    corpus = [
        KnowledgeChunk("KC001", "The sky on Earth appears blue during a clear day due to Rayleigh scattering.", "wiki/sky", "wiki", 4, 1.0),
        KnowledgeChunk("KC002", "Python is a programming language originally created by Guido van Rossum.", "wiki/python", "wiki", 4, 1.0),
        KnowledgeChunk("KC003", "The capital of France is Paris.", "wiki/france", "wiki", 4, 1.0),
    ]
    pipeline.load_corpus(corpus)
    print("\n[Corpus Knowledge Loaded: \n - Sky is blue. \n - Python by Guido. \n - France capital is Paris.]\n")
    print("Press CTRL+C anytime to exit.\n")

    while True:
        try:
            print("-" * 55)
            # Take manual user inputs
            prompt = input("Enter the PROMPT constraint (or press enter to skip): ").strip()
            text = input("Enter the TEXT GENERATION to test: ").strip()
            
            if not text:
                continue
                
            print("\nRunning Stage 0 & Verification Engine...")
            result = await pipeline.check(text=text, prompt=prompt)
            
            print("\n" + "═"*55)
            print("                VERDICT REPORT                 ")
            print("═"*55)
            for i, v in enumerate(result.verdicts, 1):
                icon = "🚫" if v.verdict.value in ["BLOCKED", "CONFLICT"] else "✅" if v.verdict.value == "VERIFIED" else "⚠️"
                print(f"[{i}] {icon} Status: {v.verdict.value}")
                print(f"    Claim Analyzed:      {v.claim.text}")
                print(f"    Hallucination Flag:  {v.halluc_type.value.upper()}")
                print(f"    Pipeline Reason:     {v.explanation}")
                print("-" * 55)
                
        except KeyboardInterrupt:
            print("\nExiting manual tester...")
            break
        except Exception as e:
            print(f"\nError occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
