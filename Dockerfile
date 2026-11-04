FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai \
    FUNDPILOT_STATE_DIR=/app/data/cloud
WORKDIR /app
COPY requirements.txt requirements-cloud.txt requirements-sms.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt
# Explicit sources only; existing accounts, credentials and local reports stay out.
COPY server.py cloud_server.py cloud_admin.py research_*.py ./
COPY dist/ ./dist/
RUN mkdir -p /app/data/cloud \
    && groupadd -g 10001 app \
    && useradd -r -u 10001 -g app -d /app/data/cloud -s /usr/sbin/nologin app \
    && chown -R app:app /app/data
USER app
EXPOSE 8080
CMD ["python", "-B", "-u", "cloud_server.py"]
