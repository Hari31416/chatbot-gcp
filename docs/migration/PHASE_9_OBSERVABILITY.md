# Phase 9 — Observability Migration

> Replace CloudWatch Logs with Azure Monitor (Log Analytics + Application Insights).

---

## Goal

Set up centralized logging and tracing for the Container App and Azure Function using Azure Monitor. The backend already uses Python's `logging` module, so this phase is mostly configuration — no application code changes required.

---

## Current State (AWS)

### CloudWatch Logging

| Component      | Log Group                                    | Retention |
| :------------- | :------------------------------------------- | :-------- |
| Backend Lambda | `/aws/lambda/ChatbotBackendFunction`         | 7 days    |
| Worker Lambda  | `/aws/lambda/ChatbotIngestionWorkerFunction` | 7 days    |

Logs are structured via Python's `logging` module → stdout → CloudWatch.

---

## Target State (Azure)

### Azure Monitor Stack

| Component                   | Azure Service | Purpose                                            |
| :-------------------------- | :------------ | :------------------------------------------------- |
| **Log Analytics Workspace** | Azure Monitor | Central log store (5 GB/month free)                |
| **Application Insights**    | Azure Monitor | Request tracing, dependency tracking, live metrics |

### Automatic Integration

- **Container Apps** automatically stream stdout/stderr to Log Analytics when a workspace is linked to the Container Apps Environment.
- **Azure Functions** automatically integrate with Application Insights when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set.

---

## Code Changes

### 9.1 Backend — No Code Changes Required

The backend already uses Python's `logging` module throughout:

- `app/logging_config.py` configures log levels
- All services use `logger = logging.getLogger(__name__)`
- Output goes to stdout, which Container Apps captures automatically

### 9.2 Optional: Add OpenTelemetry for Rich Tracing

For enhanced request tracing (optional, not required):

```bash
uv add opentelemetry-instrumentation-fastapi azure-monitor-opentelemetry-exporter
```

```python
# app/main.py (optional enhancement)
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Only enable if Application Insights is configured
app_insights_conn = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
if app_insights_conn:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider()
    exporter = AzureMonitorTraceExporter(connection_string=app_insights_conn)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
```

> [!TIP]
> OpenTelemetry integration is optional for Phase 9. Basic stdout logging works without any code changes. Add it later for production-grade distributed tracing.

### 9.3 Update `app/logging_config.py`

Ensure structured JSON logging for better Azure Monitor parsing:

```python
import json
import logging
import os
import sys


class JsonFormatter(logging.Formatter):
    """JSON log formatter for Azure Monitor ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    use_json = os.getenv("LOG_FORMAT", "text").lower() == "json"

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

    root.handlers.clear()
    root.addHandler(handler)
```

---

## Bicep Module: `infra/modules/monitoring.bicep`

```bicep
param location string
param environmentName string

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-chatbot-${environmentName}'
  location: location
  tags: { 'azd-env-name': environmentName }
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-chatbot-${environmentName}'
  location: location
  kind: 'web'
  tags: { 'azd-env-name': environmentName }
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsWorkspace.id
    IngestionMode: 'LogAnalytics'
    RetentionInDays: 30
  }
}

output logAnalyticsWorkspaceId string = logAnalyticsWorkspace.id
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output appInsightsInstrumentationKey string = appInsights.properties.InstrumentationKey
```

### Link to Container Apps Environment

Update `infra/modules/container-apps.bicep`:

```diff
 resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
   name: 'cae-chatbot-${environmentName}'
   location: location
   properties: {
+    appLogsConfiguration: {
+      destination: 'log-analytics'
+      logAnalyticsConfiguration: {
+        customerId: logAnalyticsWorkspace.properties.customerId
+        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
+      }
+    }
   }
 }
```

### Link to Azure Function

Add to Function App settings:

```bicep
{ name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
```

---

## Querying Logs

### Container Apps Logs (KQL)

```kql
// View recent backend logs
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "chatbot-backend"
| project TimeGenerated, Log_s
| order by TimeGenerated desc
| take 50

// Find errors
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "chatbot-backend"
| where Log_s contains "ERROR"
| project TimeGenerated, Log_s
| order by TimeGenerated desc
```

### Application Insights (KQL)

```kql
// Request performance
requests
| where name contains "chat/stream"
| summarize avg(duration), count() by bin(timestamp, 1h)
| render timechart

// Failures
exceptions
| order by timestamp desc
| take 20
```

---

## Environment Variables

```bash
# Add to Container App env vars
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...;IngestionEndpoint=...
LOG_FORMAT=json     # Optional: enable JSON logging
LOG_LEVEL=INFO      # Keep at INFO to stay within 5 GB free tier
```

---

## Cost Considerations

> [!WARNING]
> **Trap #3 from the migration guide applies here.** Keep `LOG_LEVEL=INFO` (not `DEBUG`) in production. Debug logging with large JSON payloads can exceed the 5 GB/month free tier quickly.

---

## Verification

- [ ] Container App logs appear in Log Analytics workspace
- [ ] Function App logs appear in Application Insights
- [ ] KQL queries return expected results
- [ ] Log retention is set to 30 days
- [ ] `LOG_LEVEL=INFO` is configured (not DEBUG)
- [ ] Free tier ingestion (5 GB/month) is sufficient for dev usage

---

## Next Phase

→ [Phase 10 — Cleanup & Cutover](./PHASE_10_CUTOVER.md)
