FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/
COPY simulator/ /app/simulator/
RUN useradd --system --no-create-home app && chown -R app /app
USER app
# Default = the API; docker-compose overrides the command for the subscriber / simulator.
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
