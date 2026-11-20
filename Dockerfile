# Shopivell Backend Dockerfile
# Single-stage build keeps one copy of the large Python environment on small hosts.
# Version: 2.1.0 - Platinum Pharmacy prescription flow

FROM python:3.12-slim

WORKDIR /app

# Install Python packages and remove build-only packages in the same layer so
# their files do not remain in the production image.
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libpq5 \
    curl \
    # Playwright dependencies for Chromium
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    fonts-liberation \
    && pip install --no-cache-dir --user -r requirements.txt \
    && pip install --no-cache-dir --user 'langchain-openai>=0.3.0' 'google-auth>=2.0.0' \
    && apt-get purge -y build-essential libpq-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd -r shopivell && useradd -r -g shopivell shopivell

ENV PATH=/root/.local/bin:$PATH

# Install Playwright browsers with system dependencies
RUN playwright install --with-deps chromium

# Pre-download the self-hosted embedding model into the image so there is no
# runtime download / network dependency (default embedding provider).
ENV FASTEMBED_CACHE_PATH=/app/.fastembed_cache
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/app/.fastembed_cache')"

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p uploads/assets && chown -R shopivell:shopivell uploads

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run as non-root user (commented out for now as some operations may need root)
# USER shopivell

# Start the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
