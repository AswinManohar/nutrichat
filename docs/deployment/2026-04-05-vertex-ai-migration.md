# NutriChat — Google Vertex AI Migration & Deployment
**Date:** 2026-04-05
**Status:** Planning
**Source:** [vertex-ai-api-dev] Activated Skill

---

## 1. Implementation Methodology

### 1.1 SDK Transition
Migrate from `langchain-google-genai` to the **unified Google Gen AI SDK** (`google-genai`).
- **Dependency:** Add `google-genai>=0.3.0` to `pyproject.toml`.
- **Initialization:**
  ```python
  from google import genai
  # Automatically picks up ADC and environment variables
  client = genai.Client(vertexai=True)
  ```

### 1.2 Authentication & Authorization
- **Development:** Use `gcloud auth application-default login`.
- **Production:** Attach a **Custom Service Account (SA)** to the Cloud Run service.
- **IAM Roles:**
  - `roles/aiplatform.user` (Vertex AI access)
  - `roles/cloudsql.client` (Postgres access)
  - `roles/redis.editor` (Memorystore access)

### 1.3 Configuration (Environment Variables)
| Variable | Value | Purpose |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | `{PROJECT_ID}` | GCP Project ID |
| `GOOGLE_CLOUD_LOCATION` | `global` | Auto-routing to available capacity |
| `GOOGLE_GENAI_USE_VERTEXAI`| `true` | Force SDK to use Vertex AI backend |

---

## 2. Architectural Implications

### 2.1 Compute Tier (Statelessness)
- **Service:** Cloud Run (v2).
- **Impact:** Reinforces the stateless architecture of the FastAPI orchestrator.
- **Scaling:** Scales to zero when idle; triggers concurrency-based auto-scaling for logging/coaching requests.

### 2.2 Data Tier (Persistence)
- **Postgres:** Cloud SQL (Postgres 16 + pgvector).
- **Redis:** Google Memorystore.
- **Impact:** VPC Peering or Direct VPC Egress is required for Cloud Run to communicate with these internal-only services, adding infrastructure complexity.

### 2.3 Memory Tier (Context Caching)
- **Capability:** Vertex AI supports **Context Caching** for prompts >32k tokens.
- **Impact:** For Phase 2 coaching agents (which may need long-term history), this will reduce P95 latency and per-token cost significantly.

---

## 3. Possible Issues & Mitigations

| Issue | Impact | Mitigation |
|---|---|---|
| **Cloud Run Cold Starts** | High latency on first request. | Set `--min-instances 1` for production; use CPU Boost. |
| **VPC Networking** | Complexity in connecting DB/Redis. | Use **Direct VPC Egress** (Serverless VPC Access is legacy). |
| **Quota Limits** | Requests 429 (Rate Limit). | Verify Vertex AI quotas (TPM/RPM) in `us-central1` vs `global`. |
| **Managed DB Cost** | Higher than dev/hobbyist DBs. | Start with Cloud SQL **Micro instance** or **Shared Core**. |
| **SDK Compatibility** | Breaking changes in LangGraph. | Use `langchain-google-vertexai` wrapper for nodes that require LangChain's internal message formats. |

---

## 4. Cost Model (1,000 Users)

| Service | Tier | Est. Monthly Cost |
|---|---|---|
| Cloud Run | 1 vCPU / 2GB RAM | €5–10 (Pay-per-use) |
| Cloud SQL | db-f1-micro | €15–20 |
| Memorystore | 1GB Shared | €0–5 |
| Vertex AI | Gemini 3-Flash (Logging) | €5–15 |
| **Total** | | **€25–50** |

*Note: This is ~20% higher than the Railway-based PRD estimate due to the enterprise-grade managed services (Cloud SQL/Memorystore).*
