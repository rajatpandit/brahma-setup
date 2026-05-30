import os
import tempfile
from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import JSONResponse
import whisper
import torch

app = FastAPI()
model = None


@app.on_event("startup")
def load_model():
    global model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Whisper large on {device}...")
    model = whisper.load_model("large", device=device)
    print(f"Whisper large loaded on {device}")


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile,
    model_id: str = Form("whisper-1"),
    language: str = Form(None),
    response_format: str = Form("json"),
    temperature: float = Form(0.0),
):
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp.write(await file.read())
        path = tmp.name
    try:
        result = model.transcribe(path, language=language, temperature=temperature)
        return JSONResponse({"text": result["text"].strip()})
    finally:
        os.unlink(path)


@app.get("/health")
async def health():
    return {"status": "ok"}
