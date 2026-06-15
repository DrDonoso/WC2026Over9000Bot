FROM python:3.12-slim AS base

# Create non-root user
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --create-home app

WORKDIR /app

# Install Python dependencies (cache-friendly: only re-runs when pyproject.toml changes)
COPY pyproject.toml ./
RUN mkdir -p src/worldcup_bot && touch src/worldcup_bot/__init__.py && \
    pip install --no-cache-dir .

# Copy full source and reinstall package (deps already cached)
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .

# Create writable directory for the data mount
RUN mkdir -p /app/data && chown -R app:app /app/data

USER app

ENTRYPOINT ["python", "-m", "worldcup_bot"]
