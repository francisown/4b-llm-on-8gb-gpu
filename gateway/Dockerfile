ARG PYTHON_IMAGE=python:3.10-slim@sha256:6ff506466f8b1e981719b468cc0023b8ef000b983cdec0eafe119d01f379e31d
FROM ${PYTHON_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GATEWAY_VERSION=stable

WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app

# The lock was frozen from the verified image. It contains the web and
# OpenTelemetry stacks; `--no-deps` below installs only this repository.
COPY gateway/requirements-image.lock.txt ./requirements.lock.txt
RUN python -m pip install \
    --no-cache-dir \
    --index-url "${PIP_INDEX_URL}" \
    --timeout 120 \
    -r requirements.lock.txt

COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install \
    --no-cache-dir \
    --no-build-isolation \
    --no-deps \
    .

USER app
EXPOSE 9000

ENV OTEL_SDK_DISABLED=true

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/live', timeout=2)"]

CMD ["opentelemetry-instrument", "python", "-m", "llm8g.cli", "serve", "--host", "0.0.0.0", "--port", "9000"]
