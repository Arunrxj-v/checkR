FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq for psycopg, and a couple of libs Pillow/PyMuPDF benefit from.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 \
      libjpeg62-turbo \
      zlib1g \
      curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the package metadata and the package itself, then install. The rest of
# the tree (alembic migrations, tests, scripts) is added afterwards so the
# dependency layer stays cached across code edits.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install -e ".[dev]"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
