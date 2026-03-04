FROM python:3.11-slim

WORKDIR /app

# sentence-transformers will cache the model here on first run
ENV TRANSFORMERS_CACHE=/app/cache
ENV HF_HOME=/app/cache

COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.5.1+cpu --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
