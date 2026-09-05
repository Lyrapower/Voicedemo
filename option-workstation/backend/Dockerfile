FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/
COPY frontend/ /app/static/
ENV OWS_DATA=/data/ows STATIC_DIR=/app/static
EXPOSE 8620
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8620"]
