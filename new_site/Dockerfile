FROM python:3.12-slim

WORKDIR /app
COPY new_site/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY new_site/app /app/app

EXPOSE 8081
CMD ["python", "/app/app/runner.py"]
