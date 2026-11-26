FROM python:3.10-slim

# print() lines reach the Cloud Run log right away instead of sitting in a buffer.
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# worker.py lives here and puts the repo root (/app) on sys.path itself.
WORKDIR /app/services/discovery-agent
CMD ["python", "worker.py"]
