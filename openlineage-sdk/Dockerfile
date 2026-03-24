FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY openlineage_sdk/ openlineage_sdk/

RUN pip install --no-cache-dir .

CMD ["python"]
