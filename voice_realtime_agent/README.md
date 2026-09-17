# Voice-to-Voice Real-Time Streaming Agent

Production-oriented reference implementation for a full-duplex voice pipeline with interruptibility.

## Features
- WebSocket PCM16 audio transport (adapter-friendly for WebRTC/LiveKit)
- Silero-compatible VAD abstraction
- Barge-in state machine
- Cancellation of active LLM/TTS work
- Output-buffer clearing on interruption
- Streaming STT/LLM/TTS interfaces
- Function-call event handling without blocking the audio pipeline

## Run
```bash
pip install -r requirements.txt
python -m app.server
```

Open `http://localhost:8000`.

## Architecture
Audio In -> VAD -> STT -> LLM -> TTS -> Audio Out
                     ^         |
                     |         +-> function calls
Barge-in cancels downstream generation and clears output buffers.

The included providers are mock implementations so the project runs without API keys.
Replace providers with Deepgram/Whisper, an LLM provider, and Cartesia/Kokoro.
