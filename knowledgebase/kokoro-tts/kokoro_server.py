import io
from fastapi import FastAPI, Response
from pydantic import BaseModel
from kokoro import KPipeline
import torch
import soundfile as sf
from fastapi.responses import JSONResponse

app = FastAPI()
pipeline = None

VOICE_MAP = {
    "alloy": "af_heart",
    "echo": "am_mind",
    "fable": "af_bella",
    "nova": "am_adam",
    "onyx": "am_michael",
    "shimmer": "af_nicole",
}


class TTSRequest(BaseModel):
    model: str = "tts-1"
    input: str
    voice: str = "alloy"
    response_format: str = "mp3"
    speed: float = 1.0


@app.on_event("startup")
def load_model():
    global pipeline
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Kokoro on {device}...")
    pipeline = KPipeline(lang_code="a")
    print(f"Kokoro loaded on {device}")


@app.post("/v1/audio/speech")
async def speech(req: TTSRequest):
    voice = VOICE_MAP.get(req.voice, req.voice)
    gen = pipeline(req.input, voice=voice, speed=req.speed)
    chunks = list(gen)
    if not chunks:
        return JSONResponse(status_code=500, content={"error": "no audio generated"})
    audio = torch.cat([chunk.audio for chunk in chunks])
    buf = io.BytesIO()
    sf.write(buf, audio.cpu().numpy(), 24000, format="wav")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="audio/wav")


@app.get("/health")
async def health():
    return {"status": "ok"}
