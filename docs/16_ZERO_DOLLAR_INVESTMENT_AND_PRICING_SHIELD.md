# 🛡️ 16. The $0.00 Zero-Dollar Investment & Pricing Shield Guide

> **Core Guarantee:** You will spend **$0.00 out of pocket**.  
> Every tool, API, framework, and cloud service in Syntrueno is strictly configured to operate within **100% Free Tiers**, **Google Cloud Always-Free quotas**, and **Hackathon promotional credits**.

---

## 1. Complete Free Tier Audit Matrix

| Service / Tool | Free Quota / Allowance | Cost to You | Setup Requirement |
| :--- | :--- | :---: | :--- |
| **Google AI Studio (Gemini 2.5 Flash / Pro)** | **100% Free of charge** for input/output tokens on Free Tier. | **$0.00** | API key generated at [aistudio.google.com](https://aistudio.google.com) (No credit card needed). |
| **Google Cloud Run (Backend API)** | **2,000,000 free requests/month** + 180,000 vCPU-sec + 360,000 GiB-sec in `us-central1`. | **$0.00** | Configure `--min-instances 0` (scales to zero when idle). |
| **Cloud Firestore (Memory Bank)** | **1 GiB storage**, **50,000 reads/day**, **20,000 writes/day** free forever. | **$0.00** | Deploy in `us-central1` or `nam5`. Single default database. |
| **Cloud Pub/Sub (Event Triggers)** | **10 GiB of messages/month** free. | **$0.00** | Standard topic & push subscription. |
| **Cloud Storage (Artifacts/Logs)** | **5 GiB standard storage/month** in US regions. | **$0.00** | Standard regional bucket. |
| **Cloud Logging (Audit Ledger)** | **50 GiB/month** free log ingestion. | **$0.00** | Standard Google Cloud Logging. |
| **GitHub & CI/CD Actions** | **Unlimited public repos** + **2,000 free Actions min/month**. | **$0.00** | Standard public repository on `Shaan-alpha`. |
| **Next.js / Vite Frontend Hosting** | **Localhost / Cloud Run / Vercel Hobby Tier**. | **$0.00** | Free tier. |
| **Hackathon Google Cloud Credits** | **$150 promotional credits** via Devpost form. | **+$150 Free Buffer** | Submit form on Devpost Resources tab. |
| **GEAR Program Learning Credits** | **35 monthly credits** on Google Skills sandboxes. | **Free Learning** | Claim badge on Google Developer Program. |

---

## 2. ⚠️ The 4 Dangerous Traps to AVOID (The "Accidental Billing" Traps)

Certain Google Cloud services bill on an "always-on" hourly basis regardless of whether you make requests. **We will NEVER use these in our build:**

```
❌ AVOID THIS (Paid / Always-On)        ✅ USE THIS INSTEAD ($0.00 Free Forever)
────────────────────────────────────────────────────────────────────────────────
❌ Cloud SQL / PostgreSQL ($35-$90/mo)  ➔  ✅ Cloud Firestore (1GB + 50k reads/day FREE)
❌ Memorystore Redis ($40-$80/mo)       ➔  ✅ In-Memory Python Cache / Firestore ($0.00)
❌ GKE Kubernetes Cluster ($75+/mo)    ➔  ✅ Serverless Cloud Run with Scale-to-Zero ($0.00)
❌ Cloud Run min-instances = 1 ($15/mo) ➔  ✅ Cloud Run --min-instances 0 ($0.00 when idle)
```

---

## 3. Safe, Cost-Guaranteed Cloud Run Deployment Command

When we deploy the backend container to Google Cloud Run, we use these exact parameters to enforce **$0 idle spend**:

```bash
gcloud run deploy sentinel-mesh-backend \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60s
```

### Why this is 100% Safe:
1. `--min-instances 0`: The container completely shuts down ("goes to sleep") when no requests are active. It consumes **0 CPU, 0 RAM, and $0.00**.
2. `--max-instances 1`: Caps maximum concurrent instances to 1, preventing unexpected traffic spikes.
3. `--region us-central1`: Falls directly inside Google Cloud's **Always Free tier** boundary.

---

## 4. Google Cloud Console Budget Shield (Set $0 / $10 Alert)

To guarantee you are never surprised by a charge:

1. Open **Google Cloud Console** ➔ **Billing** ➔ **Budgets & alerts**.
2. Click **Create Budget**:
   - Scope: *All Projects*
   - Target amount: **$10.00** (or $1.00)
   - Set threshold alerts at **50% ($5.00)**, **90% ($9.00)**, and **100% ($10.00)**.
   - Check *"Send email alerts to billing admins"* (`shaansatsangi@gmail.com`).
3. If anything ever attempts to bill, Google will instantly notify you via email long before any real charge occurs.

---

## 5. Offline-First Development Workflow (Zero API Costs During Coding)

During local development and testing:
1. **Mock Fixtures for Tests:** All unit tests (`pytest`) run against local mock fixtures and SQLite in **< 2 seconds** with **zero Gemini API calls and zero GCP network requests**.
2. **Keynote Stream Replay for UI Building:** The frontend includes pre-recorded NDJSON agent streams (`race-condition` pattern), allowing you to build, test, and style the Cyberpunk UI without making repetitive LLM API calls.
3. **Gemini Flash for Local Agent Prototyping:** Free tier in Google AI Studio covers up to **15 requests/minute and 1,500 requests/day at $0.00**.
