#!/bin/bash
set -euo pipefail

# Load environment variables from .env if present (for direct script invocation)
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "Building frontend..."
cd frontend
pnpm install --frozen-lockfile
pnpm build

echo "Deploying to Firebase Hosting and Firestore Indexes..."
firebase deploy --only hosting,firestore:indexes --project "${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"

echo "Frontend deployment complete!"
