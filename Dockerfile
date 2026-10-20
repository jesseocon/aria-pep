# PEP connector image for aria-runner. No browser.
#
#   docker build --build-arg ARIA_RUNNER_IMAGE=aria-runner:latest -t aria-connector-pep .

ARG ARIA_RUNNER_IMAGE=aria-runner:latest
FROM ${ARIA_RUNNER_IMAGE} AS aria-runner

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH=/app/pep/.venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install uv==0.5.29 \
    && useradd --create-home --uid 10001 runner

COPY --from=aria-runner /app/pyproject.toml /app/README.md /app/aria-runner/
COPY --from=aria-runner /app/src /app/aria-runner/src

WORKDIR /app/pep
COPY pyproject.toml README.md ./
COPY packages ./packages
COPY transform ./transform

RUN uv sync --no-dev \
    && python -m aria_runner connectors export pep --out /app/pep/connector-manifest.json \
    && chown -R runner:runner /app/pep

USER runner
ENTRYPOINT ["python", "-m", "aria_runner"]
CMD ["execute"]
