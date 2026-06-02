#!/bin/bash
set -euo pipefail

echo "Building frontend..."
cd frontend
pnpm install --frozen-lockfile
pnpm build

echo "Deploying to Azure Static Web Apps..."
npx @azure/static-web-apps-cli deploy ./dist \
  --deployment-token "${AZURE_SWA_DEPLOYMENT_TOKEN}" \
  --env production

echo "Frontend deployment complete!"
