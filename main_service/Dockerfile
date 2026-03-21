FROM python:3.12-slim

WORKDIR /app
COPY main_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY main_service/app /app/app
COPY scripts/init_agents.py /app/init_agents.py

EXPOSE 8080
CMD ["sh", "-c", "python /app/init_agents.py && uvicorn app.main:app --host 0.0.0.0 --port 8080"]
