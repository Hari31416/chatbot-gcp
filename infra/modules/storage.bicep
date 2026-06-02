param location string
param environmentName string
param resourceToken string

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'stchatbot${resourceToken}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  tags: { 'azd-env-name': environmentName }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource uploadsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'uploads'
  properties: { publicAccess: 'None' }
}

resource stagingContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'staging'
  properties: { publicAccess: 'None' }
}

resource ragTempContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'rag-temp'
  properties: { publicAccess: 'None' }
}

// Lifecycle management: auto-delete blobs after 7 days in staging and rag-temp
resource lifecyclePolicy 'Microsoft.Storage/storageAccounts/managementPolicies@2023-01-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'expire-staging-uploads'
          type: 'Lifecycle'
          definition: {
            actions: {
              baseBlob: { delete: { daysAfterModificationGreaterThan: 7 } }
            }
            filters: {
              blobTypes: ['blockBlob']
              prefixMatch: ['staging/', 'rag-temp/']
            }
          }
        }
      ]
    }
  }
}

// ── Queue Service (Phase 5) ──
resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource ingestionQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-01-01' = {
  parent: queueService
  name: 'ingestion-queue'
  properties: {
    metadata: {
      purpose: 'RAG document ingestion pipeline'
      maxDequeueCount: '3'
    }
  }
}

// Connect Blob Storage events to the Storage Queue
resource eventGridSubscription 'Microsoft.EventGrid/eventSubscriptions@2023-12-15-preview' = {
  name: 'blob-to-storage-queue'
  scope: storageAccount
  properties: {
    destination: {
      endpointType: 'StorageQueue'
      properties: {
        resourceId: storageAccount.id
        queueName: 'ingestion-queue'
        queueMessageTimeToLiveInSeconds: 1209600  // 14 days (matches SQS DLQ retention)
      }
    }
    filter: {
      subjectBeginsWith: '/blobServices/default/containers/staging/blobs/'
      includedEventTypes: ['Microsoft.Storage.BlobCreated']
    }
  }
}

output storageAccountName string = storageAccount.name
output storageAccountId string = storageAccount.id
output storageAccountKey string = storageAccount.listKeys().keys[0].value
