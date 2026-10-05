# Toolpath audit service: pure Python 3.12 standard library, no pip installs.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 appuser
WORKDIR /srv/app

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser scripts ./scripts
COPY --chown=appuser:appuser tests ./tests

USER appuser
EXPOSE 8000

# Container listens on 8000; map any host port via docker-compose (AUDIT_PORT).
CMD ["python", "-m", "app.main"]
