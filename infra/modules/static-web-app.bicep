param location string
param environmentName string

// Azure Static Web Apps is only supported in a subset of regions for control-plane metadata.
// Since the user might choose a region like centralindia, we fall back to a supported region (eastus2).
// The web app itself is still globally distributed via the edge CDN.
var supportedSwaLocations = [
  'centralus'
  'eastus2'
  'westus2'
  'westeurope'
  'eastasia'
]
var swaLocation = contains(supportedSwaLocations, location) ? location : 'eastasia'

resource staticWebApp 'Microsoft.Web/staticSites@2023-01-01' = {
  name: 'swa-chatbot-${environmentName}'
  location: swaLocation
  tags: { 'azd-env-name': environmentName }
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    stagingEnvironmentPolicy: 'Enabled'
    allowConfigFileUpdates: true
    buildProperties: {
      appLocation: '/frontend'
      outputLocation: 'dist'
    }
  }
}

output staticWebAppName string = staticWebApp.name
output staticWebAppUrl string = 'https://${staticWebApp.properties.defaultHostname}'
output deploymentToken string = staticWebApp.listSecrets().properties.apiKey

