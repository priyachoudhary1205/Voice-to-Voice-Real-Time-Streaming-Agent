import asyncio

class StreamingSTT:
    async def finalize(self, pcm: bytes) -> str:
        # Replace with Deepgram/Whisper streaming adapter.
        return "hello agent"

class StreamingLLM:
    async def stream(self, text: str, cancel: asyncio.Event):
        # Replace with token-streaming provider.
        for token in ("Hello, ", "how ", "can ", "I ", "help?"):
            if cancel.is_set():
                return
            await asyncio.sleep(0.03)
            yield {"type": "token", "text": token}

class StreamingTTS:
    async def stream(self, text: str, cancel: asyncio.Event):
        # Replace with Cartesia/Kokoro adapter; yields PCM chunks.
        if cancel.is_set():
            return
        await asyncio.sleep(0.01)
        yield text.encode("utf-8")

class EnergyVAD:
    def __init__(self, threshold=800):
        self.threshold = threshold

    def speech(self, pcm16: bytes) -> bool:
        if len(pcm16) < 2:
            return False
        import numpy as np
        x = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32)
        return float(np.mean(np.abs(x))) > self.threshold
