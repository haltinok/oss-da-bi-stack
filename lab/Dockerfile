# The SQL lab. Build contexts: this directory, plus the dashspec package and the Cube model (docker-compose.yml: additional_contexts), for the schema browser.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=dashboards dashspec ./dashspec
COPY --from=dashboards schema ./schema
COPY --from=cubemodel cubes ./cube-model/cubes
# the model's own settings sit beside its cube folder (cube-model/)
COPY --from=modelconfig model.config.yml ./model.config.yml
COPY main.py sqlcheck.py store.py queries.py ./
ENV PYTHONPATH=/app LAB_MODEL_DIR=/app/cube-model
USER nobody
EXPOSE 8450
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8450"]
