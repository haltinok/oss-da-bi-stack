FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py keycloak.py access.py cubes.py access_resolve.py rls_registry.py ./
# the one registry file, shared with Cube and the auth service
COPY --from=modelconfig rls_dimensions.json ./rls_dimensions.json
COPY --from=dashboards dashspec ./dashspec
COPY --from=cubemodel cubes ./cube-model/cubes
# the model's own settings sit beside its cube folder (cube-model/)
COPY --from=modelconfig model.config.yml ./model.config.yml
ENV PYTHONPATH=/app MODELS_FILE=/srv/models/models.yml
USER nobody
EXPOSE 8400
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8400"]
