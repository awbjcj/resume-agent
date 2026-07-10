FROM node:22-alpine AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app

RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv pip install --system -e .

COPY templates ./templates
COPY resume-template ./resume-template
COPY config ./config.defaults
COPY --from=web /build/web/dist ./web/dist
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV BROWSER_ENABLED=false
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
