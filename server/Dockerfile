# bgtracker aggregator - stdlib only, so the image is tiny and has zero pip deps.
# Same image runs both roles; docker-compose picks the command per service.
FROM python:3.12-slim

RUN useradd -m -u 10001 app
WORKDIR /app
COPY ingest.py aggregate.py ./

USER app
# Overridden by docker-compose for the aggregate sidecar.
CMD ["python", "ingest.py"]
