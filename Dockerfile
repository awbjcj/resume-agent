FROM node:22-alpine AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app

# agno writes its diagnostics (including "Failed to convert response to
# output_schema", the only statement of WHY a structured call failed) through a
# rich handler on stdout. Without this, stdout is block-buffered in a container
# and those lines never reach the platform log, while stderr-based uvicorn and
# application logs do -- which reads as "the library said nothing".
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY skills ./skills
COPY skills-lock.json ./skills-lock.json
# Install the locked dependency set, then the package itself without deps.
# `uv pip install -e .` alone ignores uv.lock and re-resolves pyproject's
# ranges at build time, so the image could silently pick up a different agno
# than the one the lockfile and the test suite were verified against.
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt > /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt \
    && uv pip install --system --no-deps -e .

COPY templates ./templates
COPY resume-template ./resume-template
COPY config ./config.defaults
COPY --from=web /build/web/dist ./web/dist
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV BROWSER_ENABLED=false \
    SECURE_COOKIES=true \
    DISABLE_API_DOCS=true \
    REGISTRATION_MODE=open
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
