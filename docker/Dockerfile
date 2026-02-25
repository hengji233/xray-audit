FROM node:20-alpine AS web_builder
WORKDIR /build

COPY web_admin/package.json /build/web_admin/package.json
RUN cd /build/web_admin && npm install

COPY web_admin /build/web_admin
COPY xray_audit /build/xray_audit
RUN cd /build/web_admin && npm run build

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN groupadd --system app && useradd --system --gid app --create-home app
WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md
COPY .env.example /app/.env.example
COPY sql /app/sql
COPY xray_audit /app/xray_audit
COPY docker /app/docker
COPY --from=web_builder /build/xray_audit/frontend_dist /app/xray_audit/frontend_dist

RUN chmod +x /app/docker/entrypoint.sh && \
    chown -R app:app /app

USER app
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "-m", "xray_audit.run_api"]
