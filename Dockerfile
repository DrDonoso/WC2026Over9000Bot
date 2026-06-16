FROM python:3.12-slim AS base

# Install system dependencies (ffmpeg provides ffmpeg + ffprobe for goal-clip feature)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

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

# Create writable directories for the data mount + persistent state volume
RUN mkdir -p /app/data /app/state && chown -R app:app /app/data /app/state

USER app

ENTRYPOINT ["python", "-m", "worldcup_bot"]
