param location string
param resourceToken string

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: 'cosmos-chatbot-${resourceToken}'
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    enableFreeTier: true
    databaseAccountOfferType: 'Standard'
    capabilities: [
      { name: 'EnableNoSQLVectorSearch' }
    ]
    locations: [{ locationName: location, failoverPriority: 0 }]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: 'chatbot'
  properties: {
    resource: { id: 'chatbot' }
  }
}

resource conversationsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'conversations'
  properties: {
    resource: {
      id: 'conversations'
      partitionKey: { paths: ['/conversationId'], kind: 'Hash' }
      defaultTtl: -1  // Enable per-item TTL
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [{ path: '/*' }]
        excludedPaths: [{ path: '/_etag/?' }]
      }
    }
    options: { throughput: 400 }  // Manual 400 RU/s (within free tier)
  }
}

resource vectorsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'vectors'
  properties: {
    resource: {
      id: 'vectors'
      partitionKey: { paths: ['/userId'], kind: 'Hash' }
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [{ path: '/*' }]
        excludedPaths: [
          { path: '/embedding/*' }
          { path: '/_etag/?' }
        ]
        vectorIndexes: [
          { path: '/embedding', type: 'quantizedFlat' }
        ]
      }
      vectorEmbeddingPolicy: {
        vectorEmbeddings: [
          {
            path: '/embedding'
            dataType: 'float32'
            dimensions: 768
            distanceFunction: 'cosine'
          }
        ]
      }
    }
    options: { throughput: 400 }
  }
}

output cosmosAccountName string = cosmosAccount.name
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output cosmosDatabaseName string = database.name

@secure()
output cosmosKey string = cosmosAccount.listKeys().primaryMasterKey

