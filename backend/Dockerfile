FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies into a virtual environment without the project itself (for caching)
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY app/ ./app/

# Sync the project itself to complete the installation
RUN uv sync --frozen --no-dev

# Expose default Cloud Run port
EXPOSE 8080

# Use the venv Python directly; Cloud Run injects $PORT at runtime
CMD ["/bin/sh", "-c", ".venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
