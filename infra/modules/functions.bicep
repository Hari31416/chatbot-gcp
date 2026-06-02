param location string
param environmentName string
param resourceToken string
param storageAccountConnectionString string
param appInsightsConnectionString string
param cosmosEndpoint string = ''
param keyVaultName string = ''
param storageAccountName string = ''

resource hostingPlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: 'asp-chatbot-worker-${resourceToken}'
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true // Required for Linux
  }
}

resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: 'func-chatbot-worker-${resourceToken}'
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: hostingPlan.id
    siteConfig: {
      linuxFxVersion: 'Python|3.12'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: storageAccountConnectionString }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING', value: storageAccountConnectionString }
        { name: 'WEBSITE_CONTENTSHARE', value: 'func-chatbot-worker-${resourceToken}-share' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
        { name: 'AZURE_KEYVAULT_NAME', value: keyVaultName }
        { name: 'AZURE_STORAGE_ACCOUNT_NAME', value: storageAccountName }
        { name: 'AZURE_STORAGE_STAGING_CONTAINER', value: 'staging' }
        { name: 'AZURE_STORAGE_CONTAINER_NAME', value: 'uploads' }
      ]
    }
    reserved: true // Required for Linux
  }
}

output functionAppPrincipalId string = functionApp.identity.principalId
output functionAppName string = functionApp.name

