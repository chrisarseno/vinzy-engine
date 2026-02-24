FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
COPY alembic.ini .
COPY alembic/ alembic/

RUN pip install --no-cache-dir ".[postgres,stripe]"

RUN mkdir -p data

EXPOSE 8080

CMD ["uvicorn", "vinzy_engine.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
