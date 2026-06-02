# Azure Costing Gotchas

> A comprehensive guide to keeping your Azure bill at **$0/month** during the chatbot migration. Read this before provisioning anything.

---

## Quick Summary

| Category         | Services                                                                                              | Monthly Cost                   |
| :--------------- | :---------------------------------------------------------------------------------------------------- | :----------------------------- |
| 🟢 Always Free   | Static Web Apps, Clerk (under 10k MAU), Container Apps, Functions, Cosmos DB, Monitor, Storage Queues | **$0**                         |
| 🟡 12-Month Free | Blob Storage, Key Vault                                                                               | **$0** → ~$0.09 after expiry   |
| 🔴 Metered       | Document Intelligence, LLM APIs                                                                       | **$0–$10+** depending on usage |

**Total if configured correctly: $0/month**

---

## 🟢 Always Free Services (No Expiry)

These services have **permanent** free tiers that never expire. As long as you stay within the limits, you will never be charged.

### Azure Static Web Apps — Free Plan

| Resource         | Free Allowance                     |
| :--------------- | :--------------------------------- |
| Hosting          | Unlimited                          |
| SSL certificates | Automatic, free                    |
| Custom domains   | Supported                          |
| Global CDN       | Built-in                           |
| Bandwidth        | **100 GB/month**                   |
| Build minutes    | 250 min/month (if using GitHub CI) |

**Gotcha:** None. This is genuinely free with no catches. Even exceeding 100 GB bandwidth just degrades performance — it doesn't trigger billing on the Free plan.

---

### Clerk Authentication

| Resource                   | Free Allowance |
| :------------------------- | :------------- |
| Monthly Active Users (MAU) | **10,000**     |

**Gotcha:** None for this project. Clerk's free tier supports up to 10,000 Monthly Active Users (MAU) for free, which matches AWS Cognito's limits and is more than sufficient for internal testing and standard development deployments.

---

### Azure Container Apps

| Resource     | Free Allowance (per month)        |
| :----------- | :-------------------------------- |
| vCPU-seconds | **180,000** (~50 hours of 1 vCPU) |
| GiB-seconds  | **360,000** (~100 hours of 1 GiB) |
| Requests     | **2,000,000**                     |

**Gotcha:** See [Trap #1 — Container App Replicas](#trap-1--container-app-minreplicas--1) below. This free tier is generous but can be burned through in **3 days** if `minReplicas` is set wrong.

---

### Azure Functions — Consumption Plan

| Resource             | Free Allowance (per month) |
| :------------------- | :------------------------- |
| Executions           | **1,000,000**              |
| Compute (GB-seconds) | **400,000**                |

**Gotcha:** None for this project. A RAG ingestion worker processing a few documents per day will use < 0.1% of this allowance.

---

### Azure Cosmos DB — Free Tier

| Resource   | Free Allowance                        |
| :--------- | :------------------------------------ |
| Throughput | **1,000 RU/s** (Request Units)        |
| Storage    | **25 GB**                             |
| Duration   | **Lifetime** (per Azure subscription) |

**Gotcha:** See [Trap #2 — Cosmos DB Autoscale](#trap-2--cosmos-db-autoscale-throughput) below. Also, **only 1 free-tier Cosmos account is allowed per Azure subscription**. If you already have one from another project, this project will not get free Cosmos DB.

---

### Azure Monitor / Application Insights

| Resource       | Free Allowance (per month)                                    |
| :------------- | :------------------------------------------------------------ |
| Log ingestion  | **5 GB**                                                      |
| Data retention | **31 days** (Log Analytics), **90 days** (basic App Insights) |

**Gotcha:** See [Trap #4 — Log Accumulation](#trap-4--application-insights-log-accumulation) below. 5 GB sounds like a lot but can be consumed quickly with verbose JSON logging.

---

### Azure Storage Queues

| Resource     | Free Allowance                                     |
| :----------- | :------------------------------------------------- |
| Transactions | Bundled with Blob Storage Account (same free tier) |

**Gotcha:** None. Queues share the Storage Account from Phase 2. Zero additional cost.

---

## 🟡 12-Month Free Tier Services

These are free for the **first 12 months** from when you create your Azure account. After that, they cost real (but tiny) money.

### Azure Blob Storage

| Resource         | Free Allowance (12 months) | After Expiry    |
| :--------------- | :------------------------- | :-------------- |
| Storage          | **5 GB LRS**               | ~$0.02/GB/month |
| Read operations  | **20,000/month**           | $0.004/10k ops  |
| Write operations | **20,000/month**           | $0.05/10k ops   |

**After 12 months:** ~$0.08/month for 5 GB. Negligible.

**Gotcha:** See [Trap #3 — Blob Storage Replication](#trap-3--blob-storage-geo-redundant-replication) below. Choosing GRS instead of LRS doubles the cost.

---

### Azure Key Vault

| Resource               | Cost                            |
| :--------------------- | :------------------------------ |
| Secret operations      | **$0.03 per 10,000 operations** |
| Certificate operations | $3 per renewal                  |

**Monthly cost for this project:** < $0.01. You'll make maybe 100 secret reads/month during development.

**Gotcha:** None. This is effectively free.

---

## 🔴 Metered Services (Real Money)

These services **will cost money** if you exceed their free tiers. These are the ones to watch.

### Azure AI Document Intelligence

This is the **single biggest cost risk** in the entire stack.

| Tier          | Page Limit                      | Cost                                   |
| :------------ | :------------------------------ | :------------------------------------- |
| Free (F0)     | **500 pages/month** (recurring) | $0                                     |
| Standard (S0) | Unlimited                       | **$10 per 1,000 pages** (Layout model) |

**Why it matters:** A single 100-page PDF consumes 20% of your monthly free quota. Uploading 5 such documents hits the limit.

**Mitigation strategies:**

1. **Track page counts** — Log the page count from each Document Intelligence response. Add a warning when approaching 400 pages/month.
2. **Set a page cap per document** — The Phase 5 code already rejects documents > 100 pages. Consider lowering to 50 for tighter budgeting.
3. **Skip OCR for text files** — The ingestion worker already routes `.txt`, `.md`, `.csv` files through plain text parsing. Only binary files (PDF, images) hit Document Intelligence.
4. **Use the Free (F0) SKU explicitly** — When provisioning via Bicep, set `sku: { name: 'F0' }` to enforce the free tier. This hard-caps you at 500 pages but prevents surprise bills.

**Example Bicep (enforcing free tier):**

```bicep
resource docIntelligence 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' = {
  name: 'di-chatbot-${environmentName}'
  location: location
  kind: 'FormRecognizer'
  sku: { name: 'F0' }   // Free tier — hard limit at 500 pages/month
  properties: {
    customSubDomainName: 'di-chatbot-${environmentName}'
    publicNetworkAccess: 'Enabled'
  }
}
```

---

### LLM API Costs (Third-Party — Not Azure)

LLM calls via LiteLLM are billed by the **third-party provider** (Google Gemini, NVIDIA NIM, etc.), not Azure. These costs are **identical regardless of AWS or Azure** — the migration doesn't change them.

| Provider      | Model                            | Approximate Cost        |
| :------------ | :------------------------------- | :---------------------- |
| Google Gemini | `gemini-3.1-flash-lite` (vision) | ~$0.075/1M input tokens |
| Google Gemini | `gemini-embedding-2`             | ~$0.006/1M tokens       |
| NVIDIA NIM    | `gpt-oss-120b`                   | Varies by endpoint      |

**Mitigation:** These are pay-per-use and generally cheap for development. No action needed unless you're doing bulk processing.

---

## 🪤 Configuration Traps

These services are **free if configured correctly** but will silently drain your credits if misconfigured.

### Trap #1 — Container App `minReplicas = 1`

| Setting                    | Monthly Cost Impact               |
| :------------------------- | :-------------------------------- |
| `minReplicas: 0` (correct) | **$0** — scales to zero when idle |
| `minReplicas: 1` (wrong)   | **~$30–50/month** — runs 24/7     |

**What happens:** With `minReplicas: 1`, the container runs continuously. At 0.5 vCPU + 1 GiB memory, you consume:

- **1,296,000 vCPU-seconds/month** (vs 180,000 free)
- **2,592,000 GiB-seconds/month** (vs 360,000 free)

You'll exhaust the free tier in **~4 days** and start billing.

**How to verify:**

```bash
az containerapp show \
  --name chatbot-backend \
  --resource-group rg-chatbot-dev \
  --query "properties.template.scale"
```

**Trade-off:** `minReplicas: 0` introduces **2–3 second cold starts** on the first request after idle. This is acceptable for development. For production, consider `minReplicas: 1` only if you have credits to cover it.

---

### Trap #2 — Cosmos DB Autoscale Throughput

| Setting                          | Monthly Cost Impact                              |
| :------------------------------- | :----------------------------------------------- |
| Manual 400 RU/s (correct)        | **$0** — within 1,000 RU/s free tier             |
| Autoscale 400–4,000 RU/s (wrong) | **$0.008/RU/hour** for anything above 1,000 RU/s |

**What happens:** Autoscale mode has a minimum of 10% of max throughput. Setting max to 4,000 RU/s means minimum is 400 RU/s — that's fine. But under load, it **scales up to 4,000 RU/s**, exceeding the 1,000 RU/s free cap. You're billed for every RU above 1,000.

**How to verify:**

```bash
az cosmosdb sql container throughput show \
  --account-name cosmos-chatbot-dev \
  --database-name chatbot \
  --name conversations \
  --resource-group rg-chatbot-dev
```

Look for `"throughputPolicy": "Manual"` and `"throughput": 400`.

**Why 400, not 1,000?** The free tier gives 1,000 RU/s total across **all containers in the account**. With 2 containers (`conversations` + `vectors`), setting each to 400 RU/s uses 800 RU/s, leaving 200 RU/s headroom for system operations.

---

### Trap #3 — Blob Storage Geo-Redundant Replication

| Setting                           | Monthly Cost Impact                |
| :-------------------------------- | :--------------------------------- |
| LRS — Locally Redundant (correct) | **$0** (within free tier)          |
| GRS — Geo-Redundant (wrong)       | **~2× storage cost + egress fees** |

**What happens:** GRS replicates all data to a second Azure region. This doubles storage costs and adds outbound bandwidth charges for replication traffic. The Azure portal sometimes **defaults to GRS** when creating Storage Accounts via the UI.

**How to verify:**

```bash
az storage account show \
  --name stchatbotXXXXX \
  --resource-group rg-chatbot-dev \
  --query "sku.name"
# Should output: "Standard_LRS"
```

**Mitigation:** Always specify `sku: { name: 'Standard_LRS' }` in Bicep. The Phase 2 Bicep module already does this.

---

### Trap #4 — Application Insights Log Accumulation

| Setting                    | Monthly Cost Impact                      |
| :------------------------- | :--------------------------------------- |
| `LOG_LEVEL=INFO` (correct) | **< 1 GB/month** — well within free tier |
| `LOG_LEVEL=DEBUG` (wrong)  | **5–20+ GB/month** — overage at $2.30/GB |

**What happens:** FastAPI in DEBUG mode logs full request/response bodies, SQL-equivalent queries, and large JSON payloads. With a chatbot streaming LLM responses, debug logs can generate megabytes per conversation.

**How to check current ingestion:**

```bash
az monitor log-analytics workspace show \
  --workspace-name log-chatbot-dev \
  --resource-group rg-chatbot-dev \
  --query "properties.sku"
```

**Mitigation:** Keep `LOG_LEVEL=INFO` in all deployed environments. Only use DEBUG locally.

---

### Trap #5 — Container Registry SKU

| Setting                     | Monthly Cost Impact |
| :-------------------------- | :------------------ |
| Basic SKU (correct for dev) | **~$5/month**       |
| Standard SKU                | **~$20/month**      |
| Premium SKU                 | **~$50/month**      |

**What happens:** Azure Container Registry (ACR) is used to store Docker images for the Container App. Unlike most services, ACR has **no free tier**. The Basic SKU at ~$5/month is the cheapest option.

**Mitigation options:**

1. Use **ACR Basic** ($5/month) — cheapest option, sufficient for dev.
2. Use Docker Hub free tier and pull from there — avoids ACR entirely, but adds latency and Docker Hub rate limits.
3. Use `az containerapp up` which can deploy directly from source without ACR (builds in-cloud).

**Bicep:**

```bicep
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'crchatbot${resourceToken}'
  location: location
  sku: { name: 'Basic' }  // $5/month — cheapest option
}
```

> [!WARNING]
> ACR is the one Azure service in this stack that has **no free tier at all**. Budget ~$5/month for it, or use the source-deploy workaround.

---

### Trap #6 — Cosmos DB Multi-Region Writes

| Setting                     | Monthly Cost Impact       |
| :-------------------------- | :------------------------ |
| Single region (correct)     | **$0** (within free tier) |
| Multi-region writes enabled | **2× RU cost per write**  |

**What happens:** Enabling multi-region writes (also called "multi-master") in Cosmos DB doubles the RU charge for every write operation. The free tier's 1,000 RU/s effectively becomes 500 RU/s for writes.

**Mitigation:** Keep the Cosmos DB account as a single-region deployment. The Phase 3 Bicep module only configures one `locations` entry — leave it that way.

---

## 📋 Pre-Provisioning Checklist

Run through this before every `azd provision` or `az deployment` command:

- [ ] Container Apps: `minReplicas: 0` in Bicep template
- [ ] Cosmos DB: `enableFreeTier: true` on the account
- [ ] Cosmos DB: Manual throughput at 400 RU/s per container (not autoscale)
- [ ] Cosmos DB: Single region only (`locations` array has 1 entry)
- [ ] Blob Storage: `sku.name = 'Standard_LRS'` (not GRS/ZRS/GZRS)
- [ ] Document Intelligence: `sku.name = 'F0'` (free tier)
- [ ] Container Registry: `sku.name = 'Basic'` (cheapest, or skip ACR entirely)
- [ ] Application Insights: `LOG_LEVEL=INFO` in all app settings
- [ ] Functions: Consumption plan (not Dedicated/Premium)

---

## 💰 Monthly Cost Projection

### Development / Staging (Low Traffic)

| Service                | Configuration              | Monthly Cost     |
| :--------------------- | :------------------------- | :--------------- |
| Static Web Apps        | Free plan                  | $0               |
| Clerk Authentication   | < 10k MAU                  | $0               |
| Container Apps         | `minReplicas: 0`           | $0               |
| Azure Functions        | Consumption plan           | $0               |
| Cosmos DB              | Free tier, 400 RU/s manual | $0               |
| Blob Storage           | LRS, < 5 GB                | $0               |
| Storage Queues         | Bundled                    | $0               |
| Document Intelligence  | F0, < 500 pages            | $0               |
| Key Vault              | < 100 ops                  | $0               |
| Azure Monitor          | < 5 GB logs                | $0               |
| Container Registry     | Basic SKU                  | **$5**           |
| LLM APIs (third-party) | Light development use      | **$1–5**         |
| **Total**              |                            | **~$5–10/month** |

### Production (Moderate Traffic)

| Service                | Configuration                          | Monthly Cost       |
| :--------------------- | :------------------------------------- | :----------------- |
| Static Web Apps        | Free plan (sufficient up to 100 GB)    | $0                 |
| Clerk Authentication   | < 10k MAU                              | $0                 |
| Container Apps         | `minReplicas: 1` for availability      | **$30–50**         |
| Azure Functions        | Consumption plan                       | $0                 |
| Cosmos DB              | 400 RU/s manual (may need to increase) | $0–$24             |
| Blob Storage           | LRS, < 5 GB                            | $0.10              |
| Document Intelligence  | S0 if > 500 pages/month                | $0–$10             |
| Container Registry     | Basic SKU                              | **$5**             |
| Azure Monitor          | < 5 GB logs                            | $0                 |
| LLM APIs (third-party) | Moderate use                           | **$10–50**         |
| **Total**              |                                        | **~$45–140/month** |
