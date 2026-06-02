param location string
param environmentName string
param resourceToken string
param containerImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'
param logAnalyticsWorkspaceCustomerId string
@secure()
param logAnalyticsWorkspaceSharedKey string
param keyVaultName string
param cosmosEndpoint string
param storageAccountName string
param clerkIssuer string = ''
param clerkAuthorizedParties string = ''

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'crchatbot${resourceToken}'
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: 'cae-chatbot-${environmentName}'
  location: location
  tags: { 'azd-env-name': environmentName }
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspaceCustomerId
        sharedKey: logAnalyticsWorkspaceSharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: 'chatbot-backend'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        allowInsecure: false
        transport: 'auto' // Supports SSE streaming
      }
      registries: [
        {
          server: containerRegistry.properties.loginServer
          username: containerRegistry.name
          passwordSecretRef: 'registry-password'
        }
      ]
      secrets: [
        {
          name: 'registry-password'
          value: containerRegistry.listCredentials().passwords[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'fastapi-backend'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
          env: [
            {
              name: 'COSMOS_ENDPOINT'
              value: cosmosEndpoint
            }
            {
              name: 'AZURE_KEYVAULT_NAME'
              value: keyVaultName
            }
            {
              name: 'AZURE_STORAGE_ACCOUNT_NAME'
              value: storageAccountName
            }
            {
              name: 'AZURE_STORAGE_STAGING_CONTAINER'
              value: 'staging'
            }
            {
              name: 'CLERK_ISSUER'
              value: clerkIssuer
            }
            {
              name: 'CLERK_AUTHORIZED_PARTIES'
              value: clerkAuthorizedParties
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0 // Scale to zero for free tier
        maxReplicas: 5
        rules: [
          {
            name: 'http-rule'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn
output containerAppPrincipalId string = containerApp.identity.principalId
output containerRegistryName string = containerRegistry.name
output containerRegistryLoginServer string = containerRegistry.properties.loginServer
