param location string
param resourceToken string

resource docIntelligence 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: 'doc-intel-${resourceToken}'
  location: location
  kind: 'FormRecognizer'
  sku: {
    name: 'S0' // Standard tier
  }
  properties: {
    customSubDomainName: 'doc-intel-${resourceToken}'
    publicNetworkAccess: 'Enabled'
  }
}

output endpoint string = docIntelligence.properties.endpoint
output key string = docIntelligence.listKeys().key1
