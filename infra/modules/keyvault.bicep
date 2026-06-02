param location string
param environmentName string
param resourceToken string
param containerAppPrincipalId string = ''
param functionAppPrincipalId string = ''

@secure()
param cosmosKey string = ''
@secure()
param storageConnectionString string = ''
param docIntelEndpoint string = ''
@secure()
param docIntelKey string = ''
@secure()
param litellmApiKey string = ''
@secure()
param litellmVisionApiKey string = ''
@secure()
param clerkSecretKey string = ''

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-chatbot-${resourceToken}'
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

resource cosmosKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (cosmosKey != '') {
  parent: keyVault
  name: 'cosmos-key'
  properties: {
    value: cosmosKey
  }
}

resource storageConnStringSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (storageConnectionString != '') {
  parent: keyVault
  name: 'storage-connection-string'
  properties: {
    value: storageConnectionString
  }
}

resource docIntelEndpointSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (docIntelEndpoint != '') {
  parent: keyVault
  name: 'azure-document-intelligence-endpoint'
  properties: {
    value: docIntelEndpoint
  }
}

resource docIntelKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (docIntelKey != '') {
  parent: keyVault
  name: 'azure-document-intelligence-key'
  properties: {
    value: docIntelKey
  }
}

resource litellmApiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (litellmApiKey != '') {
  parent: keyVault
  name: 'litellm-api-key'
  properties: {
    value: litellmApiKey
  }
}

resource litellmVisionApiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (litellmVisionApiKey != '') {
  parent: keyVault
  name: 'litellm-vision-api-key'
  properties: {
    value: litellmVisionApiKey
  }
}

resource clerkSecretKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (clerkSecretKey != '') {
  parent: keyVault
  name: 'clerk-secret-key'
  properties: {
    value: clerkSecretKey
  }
}

output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
