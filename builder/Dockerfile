# The dashboard builder. Build contexts: this directory, plus the dashspec package and the Cube model (docker-compose.yml: additional_contexts).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=dashboards dashspec ./dashspec
COPY --from=dashboards schema ./schema
COPY --from=cubemodel cubes ./cube-model/cubes
COPY . ./builder
ENV PYTHONPATH=/app BUILDER_MODEL_DIR=/app/cube-model
USER nobody
EXPOSE 8350
CMD ["uvicorn", "builder.main:app", "--host", "0.0.0.0", "--port", "8350"]
