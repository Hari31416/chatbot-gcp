targetScope = 'subscription'

@description('Environment name (dev, staging, prod)')
param environmentName string

@description('Primary Azure region for all resources')
param location string

@secure()
param liteLlmApiKey string = ''
@secure()
param liteLlmVisionApiKey string = ''
@secure()
param clerkSecretKey string = ''
param clerkIssuer string = ''
param clerkAuthorizedParties string = ''

@description('Unique resource token for naming')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

var keyVaultName = 'kv-chatbot-${resourceToken}'

// ──────────────────────────────────────────────
// Resource Group
// ──────────────────────────────────────────────
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: 'rg-chatbot-${environmentName}'
  location: location
  tags: {
    'azd-env-name': environmentName
    project: 'chatbot-azure'
  }
}

// ──────────────────────────────────────────────
// Monitoring Module (Phase 9)
// ──────────────────────────────────────────────
module monitoring './modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    location: location
    environmentName: environmentName
  }
}

// ──────────────────────────────────────────────
// Storage Module (Phase 2)
// ──────────────────────────────────────────────
module storage './modules/storage.bicep' = {
  name: 'storage'
  scope: rg
  params: {
    location: location
    environmentName: environmentName
    resourceToken: resourceToken
  }
}

// ──────────────────────────────────────────────
// Cosmos DB Module (Phase 3)
// ──────────────────────────────────────────────
module cosmos './modules/cosmos.bicep' = {
  name: 'cosmos'
  scope: rg
  params: {
    location: location
    resourceToken: resourceToken
  }
}

// ──────────────────────────────────────────────
// Document Intelligence Module (Phase 5)
// ──────────────────────────────────────────────
module docIntelligence './modules/document-intelligence.bicep' = {
  name: 'doc-intelligence'
  scope: rg
  params: {
    location: location
    resourceToken: resourceToken
  }
}

// ──────────────────────────────────────────────
// Functions Module (Phase 5)
// ──────────────────────────────────────────────
var storageConnectionString = 'DefaultEndpointsProtocol=https;AccountName=${storage.outputs.storageAccountName};AccountKey=${storage.outputs.storageAccountKey};EndpointSuffix=${environment().suffixes.storage}'

module functions './modules/functions.bicep' = {
  name: 'functions'
  scope: rg
  params: {
    location: location
    environmentName: environmentName
    resourceToken: resourceToken
    storageAccountConnectionString: storageConnectionString
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    cosmosEndpoint: cosmos.outputs.cosmosEndpoint
    keyVaultName: keyVaultName
    storageAccountName: storage.outputs.storageAccountName
  }
}

// ──────────────────────────────────────────────
// Container Apps Module (Phase 7)
// ──────────────────────────────────────────────
module containerApps './modules/container-apps.bicep' = {
  name: 'container-apps'
  scope: rg
  params: {
    location: location
    environmentName: environmentName
    resourceToken: resourceToken
    logAnalyticsWorkspaceCustomerId: monitoring.outputs.logAnalyticsCustomerId
    logAnalyticsWorkspaceSharedKey: monitoring.outputs.logAnalyticsSharedKey
    keyVaultName: keyVaultName
    cosmosEndpoint: cosmos.outputs.cosmosEndpoint
    storageAccountName: storage.outputs.storageAccountName
    clerkIssuer: clerkIssuer
    clerkAuthorizedParties: clerkAuthorizedParties
  }
}

// ──────────────────────────────────────────────
// Static Web App Module (Phase 8)
// ──────────────────────────────────────────────
module staticWebApp './modules/static-web-app.bicep' = {
  name: 'static-web-app'
  scope: rg
  params: {
    location: location
    environmentName: environmentName
  }
}

// ──────────────────────────────────────────────
// Key Vault Module (Phase 6)
// ──────────────────────────────────────────────
module keyvault './modules/keyvault.bicep' = {
  name: 'keyvault'
  scope: rg
  params: {
    location: location
    environmentName: environmentName
    resourceToken: resourceToken
    functionAppPrincipalId: functions.outputs.functionAppPrincipalId
    containerAppPrincipalId: containerApps.outputs.containerAppPrincipalId
    cosmosKey: cosmos.outputs.cosmosKey
    storageConnectionString: storageConnectionString
    docIntelEndpoint: docIntelligence.outputs.endpoint
    docIntelKey: docIntelligence.outputs.key
    litellmApiKey: liteLlmApiKey
    litellmVisionApiKey: liteLlmVisionApiKey
    clerkSecretKey: clerkSecretKey
  }
}

// ──────────────────────────────────────────────
// Outputs
// ──────────────────────────────────────────────
output AZURE_STORAGE_ACCOUNT_NAME string = storage.outputs.storageAccountName
output COSMOS_ENDPOINT string = cosmos.outputs.cosmosEndpoint
output COSMOS_DATABASE_NAME string = cosmos.outputs.cosmosDatabaseName
output AZURE_KEYVAULT_NAME string = keyvault.outputs.keyVaultName
output AZURE_CONTAINER_REGISTRY string = containerApps.outputs.containerRegistryName
output AZURE_CONTAINER_REGISTRY_LOGIN_SERVER string = containerApps.outputs.containerRegistryLoginServer
output BACKEND_URL string = containerApps.outputs.containerAppFqdn
output FRONTEND_URL string = staticWebApp.outputs.staticWebAppUrl
output AZURE_SWA_DEPLOYMENT_TOKEN string = staticWebApp.outputs.deploymentToken
output AZURE_FUNCTION_APP_NAME string = functions.outputs.functionAppName
