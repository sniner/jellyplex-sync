FROM python:3.13-slim AS builder

WORKDIR /app
COPY pyproject.toml uv.lock README.md /app/
COPY src/ /app/src/

RUN pip install --no-cache-dir uv
RUN uv build --wheel --out-dir dist

FROM python:3.13-alpine AS runtime

WORKDIR /app
COPY --from=builder /app/dist/*.whl /app/
RUN pip install --no-cache-dir /app/*.whl

ENTRYPOINT ["jellyplex-sync"]
