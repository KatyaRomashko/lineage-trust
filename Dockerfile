FROM registry.access.redhat.com/ubi9/python-311:latest

USER 0

WORKDIR /app

COPY requirements.txt .
COPY wheels/ wheels/
COPY openlineage-sdk/ openlineage-sdk/
RUN pip3 install --no-cache-dir -r requirements.txt && \
    pip3 install --no-cache-dir ./openlineage-sdk

COPY configs/ configs/
COPY src/ src/
COPY data/customers.csv data/customers.csv

RUN chown -R 1001:0 /app && chmod -R g=u /app

USER 1001

ENV FEAST_REPO_PATH=/app/src/feature_store
ENV PYTHONPATH=/app

CMD ["python3", "--version"]
