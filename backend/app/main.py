import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from azure.cosmos.exceptions import CosmosHttpResponseError

from .api.routes import router
from .logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title="Chatbot API")

@app.exception_handler(CosmosHttpResponseError)
async def cosmos_http_exception_handler(request: Request, exc: CosmosHttpResponseError):
    logger.error("Cosmos DB operation failed: %s", exc.message)
    return JSONResponse(
        status_code=400,
        content={"detail": f"Database operation failed: {exc.message}"}
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

