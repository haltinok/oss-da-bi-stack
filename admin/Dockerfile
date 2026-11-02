FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py keycloak.py access.py seed.py cubes.py access_resolve.py ./
COPY --from=dashboards dashspec ./dashspec
COPY --from=cubemodel cubes ./cube-model/cubes
ENV PYTHONPATH=/app ADMIN_MODEL_DIR=/app/cube-model
USER nobody
EXPOSE 8400
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8400"]
