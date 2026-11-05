# InH-Ticketing web image.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so code changes don't re-run this slow step.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Gather CSS into /app/staticfiles for WhiteNoise. The secret here is a
# throwaway that exists only during the build; the real one comes from .env.
RUN DJANGO_SECRET_KEY=build-only-not-secret python manage.py collectstatic --noinput

# Don't run as root inside the container. /app/media holds uploaded
# attachments and is mounted as a volume by compose.yaml.
RUN useradd --system --create-home --uid 10001 app \
    && mkdir -p /app/media \
    && chown -R app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
