# Phase 6 — Secrets Management Migration

> Replace AWS SSM Parameter Store with Azure Key Vault for storing API keys and sensitive configuration.

---

## Goal

Move all secret retrieval from SSM `get_parameter(WithDecryption=True)` to Azure Key Vault secret references, accessed via Managed Identity (passwordless) in production and connection string in local dev.

---

## Current State (AWS)

### SSM Parameters Used

| Parameter Path                    | Purpose                           | Consumed By                                     |
| :-------------------------------- | :-------------------------------- | :---------------------------------------------- |
| `/chatbot/litellm_api_key`        | LiteLLM text model API key        | `get_llm_client()`                              |
| `/chatbot/litellm_vision_api_key` | Gemini vision + embedding API key | `get_vision_llm_client()`, `get_vector_store()` |

### Code Path

```python
# app/dependencies.py
def get_ssm_parameter(param_name: str) -> str | None:
    ssm = boto3.client("ssm", region_name=get_settings().aws_region)
    response = ssm.get_parameter(Name=param_name, WithDecryption=True)
    return response["Parameter"]["Value"]
```

Environment variables `LITELLM_API_KEY_PARAMETER` and `LITELLM_VISION_API_KEY_PARAMETER` contain the SSM parameter names. The code tries SSM first, falling back to direct env vars.

---

## Target State (Azure)

### Azure Key Vault Secrets

| Secret Name              | Maps to SSM Parameter             | Purpose                           |
| :----------------------- | :-------------------------------- | :-------------------------------- |
| `litellm-api-key`        | `/chatbot/litellm_api_key`        | LiteLLM text model API key        |
| `litellm-vision-api-key` | `/chatbot/litellm_vision_api_key` | Gemini vision + embedding API key |

### Access Patterns

| Environment                                 | Auth Method                                     |
| :------------------------------------------ | :---------------------------------------------- |
| **Production** (Container Apps / Functions) | System-assigned Managed Identity (passwordless) |
| **Local Development**                       | `az login` credential (DefaultAzureCredential)  |

---

## Code Changes

### 6.1 Add Azure Identity SDK

```diff
 dependencies = [
   ...
   "azure-cosmos>=4.7.0",
   "azure-ai-documentintelligence>=1.0.0",
+  "azure-identity>=1.17.0",
+  "azure-keyvault-secrets>=4.8.0",
   ...
 ]
```

### 6.2 Update `app/settings.py`

```python
# ── Azure Key Vault (Phase 6) ──
azure_keyvault_name: str | None = Field(
    default=None, validation_alias="AZURE_KEYVAULT_NAME"
)
```

### 6.3 Replace `get_ssm_parameter()` in `app/dependencies.py`

```python
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

@lru_cache
def get_keyvault_client() -> SecretClient | None:
    settings = get_settings()
    if not settings.azure_keyvault_name:
        return None
    vault_url = f"https://{settings.azure_keyvault_name}.vault.azure.net"
    credential = DefaultAzureCredential()
    return SecretClient(vault_url=vault_url, credential=credential)


@lru_cache
def get_secret(secret_name: str) -> str | None:
    """Retrieve a secret from Azure Key Vault (replaces get_ssm_parameter)."""
    client = get_keyvault_client()
    if not client:
        return None
    try:
        secret = client.get_secret(secret_name)
        return secret.value
    except Exception:
        logger.warning("Failed to retrieve secret: %s", secret_name, exc_info=True)
        return None
```

### 6.4 Update LLM Client Factories

```diff
 def get_llm_client() -> LlmClient:
     settings = get_settings()
     api_key = settings.litellm_api_key
-
-    ssm_param_name = os.getenv("LITELLM_API_KEY_PARAMETER")
-    if ssm_param_name:
-        ssm_key = get_ssm_parameter(ssm_param_name)
-        if ssm_key:
-            api_key = ssm_key
+
+    vault_key = get_secret("litellm-api-key")
+    if vault_key:
+        api_key = vault_key

     return LlmClient(
         model=settings.litellm_model,
         api_key=api_key,
         base_url=settings.litellm_base_url,
     )
```

Apply the same pattern to `get_vision_llm_client()` and `get_vector_store()`.

### 6.5 Remove SSM-related Code

- Delete `get_ssm_parameter()` function
- Remove `import boto3` from `dependencies.py` (if no other boto3 usage remains)
- Remove env vars: `LITELLM_API_KEY_PARAMETER`, `LITELLM_VISION_API_KEY_PARAMETER`, `LITELLM_EMBEDDING_API_KEY_PARAMETER`

---

## Bicep Module: `infra/modules/keyvault.bicep`

```bicep
param location string
param environmentName string
param containerAppPrincipalId string = ''
param functionAppPrincipalId string = ''

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-chatbot-${environmentName}'
  location: location
  tags: { 'azd-env-name': environmentName }
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

// Grant Key Vault Secrets User role to Container App managed identity
resource acrRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (containerAppPrincipalId != '') {
  name: guid(keyVault.id, containerAppPrincipalId, 'KeyVaultSecretsUser')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6' // Key Vault Secrets User
    )
    principalId: containerAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Grant same role to Function App managed identity
resource funcRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (functionAppPrincipalId != '') {
  name: guid(keyVault.id, functionAppPrincipalId, 'KeyVaultSecretsUser')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'
    )
    principalId: functionAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
```

---

## Populating Secrets

After provisioning, add secrets via CLI:

```bash
az keyvault secret set \
  --vault-name kv-chatbot-dev \
  --name litellm-api-key \
  --value "your-api-key-here"

az keyvault secret set \
  --vault-name kv-chatbot-dev \
  --name litellm-vision-api-key \
  --value "your-vision-key-here"
```

---

## Local Development

`DefaultAzureCredential` automatically picks up your `az login` session for local development. No special emulator needed.

```bash
# Ensure you're logged in
az login

# Set the Key Vault name in your .env
AZURE_KEYVAULT_NAME=kv-chatbot-dev
```

---

## Verification

- [ ] `get_secret("litellm-api-key")` returns the correct value from Key Vault
- [ ] `get_secret("litellm-vision-api-key")` returns the correct value
- [ ] `get_secret("nonexistent")` returns `None` without crashing
- [ ] LLM client initializes correctly with Key Vault secrets
- [ ] Vision client initializes correctly with Key Vault secrets
- [ ] Local dev works with `az login` credentials
- [ ] No SSM/boto3 imports remain in `dependencies.py`

---

## Next Phase

→ [Phase 7 — Container Apps](./PHASE_7_CONTAINER_APPS.md)
