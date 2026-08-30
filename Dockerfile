# fhir-feature-service — multi-stage image.
#
# NOTE: the image build is deferred (no Docker on the dev box) and CI does not build it yet.
# The file is kept honest by construction: it only uses the committed lockfile and package
# sources, so `docker build .` should work unchanged once a Docker host is available.

# ---- Stage 1: builder ----------------------------------------------------------------------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /build

# Lockfile-first layering: dependency resolution is cached unless the lock changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the package itself (src layout) and the project install.
COPY src ./src
COPY README.md LICENSE ./
RUN uv sync --frozen --no-dev

# ---- Stage 2: runtime ----------------------------------------------------------------------
FROM python:3.12-slim

# Non-root runtime user; /data holds the DuckDB file and is the only writable path needed.
RUN useradd -r -u 999 -d /nonexistent -s /usr/sbin/nologin ff \
    && mkdir -p /data \
    && chown ff:ff /data

COPY --from=builder /opt/venv /opt/venv

# Off-container the service deliberately defaults to FF_BIND_HOST=127.0.0.1 (no auth/TLS in
# v1). Inside a container the process must bind 0.0.0.0 to be reachable through port mapping;
# the container boundary is the network isolation layer here.
ENV PATH="/opt/venv/bin:$PATH" \
    FF_BIND_HOST=0.0.0.0 \
    FF_BIND_PORT=8000 \
    FF_DB_PATH=/data/fhir_features.duckdb

USER ff
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8000

CMD ["fhir-features", "serve"]
