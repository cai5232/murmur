FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/New_York
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN cp config.example.yaml config.yaml && mkdir -p data
EXPOSE 8080
CMD ["uvicorn", "runtime:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
