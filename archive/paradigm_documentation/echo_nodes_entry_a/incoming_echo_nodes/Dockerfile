FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8500
ENV SESSION_MODE=PRESENCE-ONLY
ENV TEMPLATE_ENGINE=DISABLED
ENV FALLBACK_PERSONA=NULL
CMD ["python3", "echo_nodes_fastapi.py"]
