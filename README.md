# Proof-AI Platform

Proof-AI is a modular, multi-tenant system built to provide an autonomous, real-time RAG (Retrieval-Augmented Generation) engine and advanced Fact-Checking service. It is designed around high-performance architecture that not only generates answers from a secure index but actively scrutinizes LLM outputs for up to 23 types of hallucinations in real-time.

## 🚀 Key Features

* **Advanced Hallucination Detection:** 
  A comprehensive suite that parallelizes 7 unique detector modules capable of identifying:
  * *Fabrication* (Entity, Event, Numeric, Attribution)
  * *Contextual Drift* (Scope Creep, Assumption Injection)
  * *Logical Errors* (Non-sequiturs, Circular Reasoning, Causation errors)
  * *Semantic & Structural Errors*
  * *Confidence/Calibration mismatches*
* **Secure Privacy Vault:**
  Data routing strictly filters through an RBAC-controlled Gateway, executing real-time PII scrubbing and managing Right-to-be-Forgotten erasure requests securely.
* **Intelligent Agent Loop:**
  Semantic routers and evaluators autonomously redirect incoming user queries to the most appropriate backend module while inspecting output quality before returning to the user.
* **Production-Ready SaaS Layer:**
  Complete billing tiers (Free, Pro, Enterprise), API key management with token-bucket rate limiting, quota tracking, and real-time observability telemetry.
* **Confidence Tuning & Penalty Engine:**
  The `VerdictComposer` dynamically degrades query confidence scores based on the severity weight of any hallucination flags thrown across the pipeline.

## 📂 Architecture & Components

The platform comprises multiple specialized microservices:

* `hallucination_detectors/` - 7 detector classes (e.g. `entity_verification`, `logical_structure`) parsing evidence streams for nuanced LLM errors.
* `Fact_checker/` - Standalone 7-stage engine focusing purely on extracting claims, semantic conflict detection, and generating verified verdicts.
* `Rag_engine/` - High-performance answering engine generating secure outputs backed completely by isolated vector embeddings.
* `saas_layer/` - Multi-tenant wrapper managing endpoint throttling and client quotas.
* `Privacy_vault/` - Security simulation layer enforcing enterprise compliance (PII redaction, GDPR deletion).
* `Agent_loop/` - Routing engine to direct payloads correctly through the architecture.
* `Confidence_stack/` - Analytics stack detailing an audit trail for exactly how and why confidence scores were penalized. 
* `Billing_engine/` - Stripe integrations, SOC-2 readiness modules, and Product-Led Growth trackers.
* `Website/` - Front-end representation linking out to the core REST API gateways.

## ⚙️ Quick Start Use Cases

### Using as a Fact-Checking Library
```python
from Fact_checker.fact_checker import FactCheckPipeline, KnowledgeChunk

pipeline = FactCheckPipeline(api_key="your-api-key")
# Pre-load contextual truth data
pipeline.load_corpus([KnowledgeChunk(...)])

# Execute request with advanced hallucination flagging
result = await pipeline.check("The latest query to verify...")
for verdict in result.verdicts:
    print(verdict.verdict, verdict.confidence)
    for flag in verdict.hallucination_flags:
        print(f"Flag Detected: {flag.hallucination_type.value} | Severity: {flag.severity}")
```

### Deploying the SaaS Endpoint Wrapper
```python
from saas_layer.saas_wrapper import SaaSFactCheckService

service = SaaSFactCheckService()
service.register_tenant(tenant_id="client-enterprise-1", api_key="secret-key")

# The service securely runs the RAG/Fact-checking processes, throttling and logging per-tenant
result = await service.check(text="Data source query...", api_key="secret-key")
```

## 🏗️ Deployment

The system is configured for dockerized container orchestration:
1. Validate environmental dependencies in `.env`
2. Run standard deployments using Docker-compose targeting the NGINX reverse proxy inside `Integration/docker-compose.yml`.
3. Start the unified service endpoints (`Integration/phase5_server.py`).

## 🛡️ Telemetry & Observability
Continuous monitoring hooks directly into Prometheus metrics to graph real-time latency bottlenecks, active concurrent sessions, and live pie-charts breaking down the frequency distribution of triggered hallucination types across the platform.
