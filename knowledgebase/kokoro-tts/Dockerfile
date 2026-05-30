FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y python3 python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip3 install torch==2.9.1+cu128 \
    --index-url https://download.pytorch.org/whl/cu128

RUN pip3 install kokoro soundfile fastapi uvicorn python-multipart

COPY kokoro_server.py .

EXPOSE 8880
CMD ["uvicorn", "kokoro_server:app", "--host", "0.0.0.0", "--port", "8880"]
