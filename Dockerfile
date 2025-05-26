FROM python:3.13-slim AS builder

WORKDIR /app
COPY . /app/

RUN pip install --no-cache-dir poetry
RUN poetry build --format wheel --output dist

FROM python:3.13-alpine AS runtime

WORKDIR /app
COPY --from=builder /app/dist/*.whl /app/
RUN pip install --no-cache-dir /app/*.whl

ENTRYPOINT ["jellyplex-sync"]
