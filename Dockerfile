# The React frontend is built here so the runtime image needs no Node.
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.13-slim-bookworm
# The image always contains the React build, so it serves the new frontend by
# default; FUNDPILOT_FRONTEND=legacy in deploy/vps/.env switches back to dist/.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai \
    FUNDPILOT_STATE_DIR=/app/data/cloud FUNDPILOT_FRONTEND=react
WORKDIR /app
COPY requirements.txt requirements-cloud.txt requirements-sms.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt
# Explicit sources only; existing accounts, credentials and local reports stay out.
COPY server.py cloud_server.py cloud_admin.py research_*.py ./
# Both frontends ship; the new one is the default (see ENV above), legacy keeps dist/.
COPY dist/ ./dist/
COPY --from=web /web/dist-react/ ./web/dist-react/
RUN mkdir -p /app/data/cloud \
    && groupadd -g 10001 app \
    && useradd -r -u 10001 -g app -d /app/data/cloud -s /usr/sbin/nologin app \
    && chown -R app:app /app/data
USER app
EXPOSE 8080
CMD ["python", "-B", "-u", "cloud_server.py"]
