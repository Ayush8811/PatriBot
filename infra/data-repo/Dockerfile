# PatriBot API image, built from the PRIVATE data repo (D15: RailKit-derived data never leaves private hosting).
# The build clones the public code repo, builds the warehouse from this repo's raw data + timetable cache
# (bronze -> silver -> gold with dbt), then serves the FastAPI app. Rebuilt daily by .github/workflows/deploy.yml.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

ARG CODE_REPO=https://github.com/Ayush8811/PatriBot.git
ARG CODE_REF=main
# changes whenever main moves, so a rebuild never reuses a stale clone from the layer cache
ADD https://api.github.com/repos/Ayush8811/PatriBot/commits/main /tmp/code-version.json
RUN git clone --depth 1 --branch "${CODE_REF}" "${CODE_REPO}" /app
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev

COPY raw /data/raw
COPY state /data/state
ENV PATRIBOT_DATA_DIR=/data PATRIBOT_WAREHOUSE_DIR=/app/warehouse DBT_SEND_ANONYMOUS_USAGE_STATS=false
RUN uv run --no-dev python -m patribot.transform.bronze \
    && uv run --no-dev python -m patribot.transform.timetable \
    && uv run --no-dev dbt build --project-dir dbt --profiles-dir dbt \
    && rm -rf /data/raw dbt/target dbt/logs

ENV PATRIBOT_API_HOST=0.0.0.0 PORT=10000
EXPOSE 10000
CMD ["uv", "run", "--no-dev", "--no-sync", "patribot-api"]
