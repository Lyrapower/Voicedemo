FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.6 "uvicorn[standard]==0.34.0" httpx==0.28.1 pydantic==2.10.4
COPY voice_bridge.py /app/
EXPOSE 8796
CMD ["uvicorn","voice_bridge:APP","--host","0.0.0.0","--port","8796"]
