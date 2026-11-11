FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY distributor_sim ./distributor_sim
USER nobody
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "distributor_sim", "run"]
