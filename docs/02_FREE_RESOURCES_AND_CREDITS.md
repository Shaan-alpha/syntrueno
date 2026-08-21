# 💳 02. Free Resources, Credits & Cost-Optimization Guide

> **Research document — written 2026-08-21, before implementation.**
> This records planning and intent, not current behaviour. For what the system
> actually does see the [README](../README.md) and
> [the system design](specs/2026-08-22-live-system-design.md). Where they
> disagree, the code is authoritative.


Maximize your development velocity without spending personal funds. Here is the comprehensive breakdown of all available free tiers, promo credits, learning sandboxes, and cloud cost-optimization patterns.

---

## 1. Hackathon Credits & Sandbox Access

### A. $150 Google Cloud Promo Credits
- **Where to claim:** On the [Hackathon Resources Tab](https://allthingsagentichackathon.devpost.com/resources) via the official **Credit Request Form**.
- **Deadline to request:** **August 28, 2026 @ 12:00 PM PT**.
- **Processing Time:** Up to **72 business hours** (request immediately!).
- **Usage:** Usable across Vertex AI, Cloud Run, Firestore, Cloud SQL, Cloud Storage, and Pub/Sub.

### B. Google Enterprise Agent Ready (GEAR) Sandbox Credits
- **What it is:** Google Cloud's official agent skilling program under the Google Developer Program.
- **Link:** [developers.google.com/program/gear](https://developers.google.com/program/gear)
- **Perks:**
  - **35 Monthly Learning Credits** on Google Skills.
  - Zero-cost interactive sandboxes to test Google ADK, Gemini, and Vertex AI without touching your personal billing account.
  - Official badges on your Google Developer Profile.
  - Path: Start with *Introduction to Agents* at [skills.google/paths/3546](https://www.skills.google/paths/3546).

### C. Standard Google Cloud Free Trial ($300)
- **Link:** [cloud.google.com/free](https://cloud.google.com/free)
- **Details:** 90-day $300 free trial for new Google Cloud accounts.

---

## 2. Google AI Studio & Gemini Free Tier Limits

When developing and prototyping locally or with the Gemini API:

| Model | Free Tier (Google AI Studio) | Ideal Usage |
| :--- | :--- | :--- |
| **Gemini 2.5 / 1.5 Flash** | **15 RPM** (Requests / min)<br>**1,000,000 TPM**<br>**1,500 RPD** (Requests / day) | High-speed routing, tool extraction, sub-agent coordination, intermediate summarization. |
| **Gemini 2.5 / 1.5 Pro** | **2 RPM**<br>**32,000 TPM**<br>**50 RPD** | Deep planning, complex code generation, final synthesis, complex reflection. |

> [!TIP]
> **Flash-First Strategy:** Build your multi-agent architecture to use **Gemini Flash** for 90% of intermediate task execution, tool calls, and parser checks. Only route to **Gemini Pro** when complex multi-step reasoning is required.

---

## 3. Official Documentation, Frameworks & Starter Kits

| Resource | Description | Link |
| :--- | :--- | :--- |
| **Google ADK (Agent Development Kit)** | Official open-source agent development kit in Python. Built-in state, memory, and multi-agent coordination. | [google.github.io/adk-docs](https://google.github.io/adk-docs/)<br>[github.com/google/adk-python](https://github.com/google/adk-python) |
| **Google GenAI SDK** | The modern unified client library for Python, TypeScript, Java, and Go (`google-genai`). | [github.com/google-gemini/generative-ai-python](https://github.com/google-gemini/generative-ai-python) |
| **Firebase Genkit** | Open-source framework for building AI apps with plugins, flows, and observability. | [firebase.google.com/docs/genkit](https://firebase.google.com/docs/genkit) |
| **Google Cloud Run Docs** | Fully managed serverless containers with scale-to-zero. | [cloud.google.com/run/docs](https://cloud.google.com/run/docs) |
| **Cloud Firestore Docs** | Serverless document database with real-time listeners and generous free tier. | [cloud.google.com/firestore/docs](https://cloud.google.com/firestore/docs) |
| **Model Armor (Google Cloud)** | Enterprise security service to detect prompt injections, jailbreaks, and sensitive data leakage. | [cloud.google.com/security/model-armor](https://cloud.google.com/security/model-armor) |

---

## 4. Architectural Cost-Reduction Playbook

To ensure your $150 credits last through the entire hackathon and demonstration phase:

1. **Scale-to-Zero on Cloud Run:**
   - Configure `--min-instances 0` and `--max-instances 2` during development:
     ```bash
     gcloud run deploy agent-service --image gcr.io/YOUR_PROJECT/agent --min-instances 0 --max-instances 2 --memory 512Mi
     ```
   - Cloud Run charges $0.00 when there are no active requests.

2. **Use Serverless Firestore instead of Dedicated SQL:**
   - Cloud Firestore includes **1 GiB storage, 50,000 reads, and 20,000 writes free daily** in the GCP free tier.
   - Avoid always-on Cloud SQL or GKE clusters during initial prototyping.

3. **Client-Side Session Caching:**
   - Cache tool execution outputs in-memory or in Redis/Firestore with a TTL so repetitive testing does not re-invoke LLM generation.

4. **Set Budget Alerts:**
   - Set a $50 and $100 budget alert in Google Cloud Console (`Billing > Budgets & Alerts`) to get email notifications before unexpected spikes.

5. **Clean Up Ephemeral Resources:**
   - Once your demo video is recorded, teardown unused test containers, IP addresses, or vector indexes.
