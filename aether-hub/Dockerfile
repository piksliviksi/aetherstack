FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV AETHER_HUB_HOST=0.0.0.0
ENV AETHER_HUB_PORT=8766
ENV REDIS_URL=redis://redis:6379/0
ENV OLLAMA_BASE_URL=http://host.docker.internal:11434
EXPOSE 8766
CMD ["python", "server.py"]
