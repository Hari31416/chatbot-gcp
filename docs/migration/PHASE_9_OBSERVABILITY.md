# Phase 9 — Observability, Budgets & Cost Guardrails

> Replace Azure Monitor and Application Insights with Cloud Logging, Cloud Monitoring, and billing alerts.

---

## Goal

Add enough visibility for a PoC without introducing paid telemetry tooling or high-volume logs.

---

## Current State (Azure)

| Component         | Azure Service                          |
| :---------------- | :------------------------------------- |
| Container logs    | Container Apps logs                    |
| Worker logs       | Azure Functions + Application Insights |
| Central workspace | Log Analytics                          |
| Provisioning      | `infra/modules/monitoring.bicep`       |

---

## Target State (GCP)

| Component                    | GCP Service                 |
| :--------------------------- | :-------------------------- |
| API and worker stdout/stderr | Cloud Logging               |
| Service metrics              | Cloud Monitoring            |
| Error visibility             | Log-based alert policies    |
| Spend warning                | Cloud Billing budget alerts |

Cloud Run automatically sends container logs written to stdout and stderr to Cloud Logging.

---

## Code Changes

### 9.1 Keep Structured Logging

Retain `backend/app/logging_config.py`, but ensure each log event includes useful fields:

```python
logger.info(
    "rag_ingestion_completed",
    extra={
        "document_id": document_id,
        "user_id": user_id,
        "chunks_ingested": result.chunks_ingested,
    },
)
```

Never log:

- Firebase ID tokens
- LiteLLM keys
- Signed GCS URLs
- Full prompts or extracted document content
- Uploaded file bytes

### 9.2 Add Request Correlation

Propagate an inbound `X-Cloud-Trace-Context` value or create a request ID in FastAPI middleware. Include it in API and worker logs.

### 9.3 Update `get-outputs.sh`

Replace Azure output lookup with:

```bash
#!/usr/bin/env bash
set -euo pipefail

terraform -chdir=gcp-infra output
gcloud run services describe chatbot-api \
  --region "${GCP_REGION:-asia-south1}" \
  --format='value(status.url)'
gcloud run services describe chatbot-worker \
  --region "${GCP_REGION:-asia-south1}" \
  --format='value(status.url)'
```

---

## Terraform

Create a notification channel manually or pass its ID as a variable. Add an error-rate alert:

```hcl
variable "notification_channel_id" {
  type    = string
  default = ""
}

resource "google_monitoring_alert_policy" "api_errors" {
  display_name = "chatbot-api HTTP 5xx"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run 5xx responses"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = var.notification_channel_id == "" ? [] : [var.notification_channel_id]
}
```

Create the billing budget after retrieving the billing account ID:

```bash
gcloud billing budgets create \
  --billing-account="$GCP_BILLING_ACCOUNT_ID" \
  --display-name="chatbot-poc-budget" \
  --budget-amount=10USD \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0
```

Budget alerts notify; they do not automatically stop spending.

---

## Operational Commands

```bash
gcloud run services logs read chatbot-api --region asia-south1 --limit 100
gcloud run services logs read chatbot-worker --region asia-south1 --limit 100
gcloud logging read 'resource.type="cloud_run_revision" severity>=ERROR' --limit 50
```

---

## Cost Guardrails

- Keep application log level at `INFO`; do not log request bodies.
- Cap Cloud Run maximum instances.
- Set GCS lifecycle rules for temporary objects.
- Cap RAG pages and chunks before Document AI and embedding calls.
- Keep Document AI Layout Parser opt-in.
- Add a billing budget before load or document-ingestion testing.

References:

- [Cloud Logging pricing](https://cloud.google.com/stackdriver/pricing)
- [Cloud Billing budgets](https://cloud.google.com/billing/docs/how-to/budgets)

---

## Verification

- [ ] API and worker logs appear in Cloud Logging.
- [ ] A synthetic worker failure is visible and searchable.
- [ ] The 5xx alert policy exists.
- [ ] A `$10` PoC budget with `50%`, `90%`, and `100%` thresholds exists.
- [ ] Logs contain no tokens, secrets, signed URLs, prompts, or document text.

---

## Next Phase

→ [Phase 10 — Cutover & Cleanup](./PHASE_10_CUTOVER.md)
