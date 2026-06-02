import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.api_core.exceptions import GoogleAPICallError

from .api.routes import router
from .logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title="Chatbot API")


@app.exception_handler(GoogleAPICallError)
async def firestore_exception_handler(request: Request, exc: GoogleAPICallError):
    logger.error("Firestore operation failed: %s", exc.message)
    return JSONResponse(
        status_code=400,
        content={"detail": f"Database operation failed: {exc.message}"}
    )


# Base allowed origins for local development
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:3333",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3333",
    "http://127.0.0.1:5173",
]

# Dynamically construct allowed origins from project configuration
firebase_project_id = os.getenv("FIREBASE_PROJECT_ID")
if firebase_project_id:
    allowed_origins.append(f"https://{firebase_project_id}.web.app")
    allowed_origins.append(f"https://{firebase_project_id}.firebaseapp.com")

gcp_project_id = os.getenv("GCP_PROJECT_ID")
if gcp_project_id and gcp_project_id != firebase_project_id:
    allowed_origins.append(f"https://{gcp_project_id}.web.app")
    allowed_origins.append(f"https://{gcp_project_id}.firebaseapp.com")

# Support custom allowed origins via environment variable
custom_origins = os.getenv("CORS_ALLOWED_ORIGINS")
if custom_origins:
    for origin in custom_origins.split(","):
        clean_origin = origin.strip()
        if clean_origin and clean_origin not in allowed_origins:
            allowed_origins.append(clean_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    logger.debug("Health check requested")
    return {"status": "ok"}


logger.info("Chatbot API initialised")
