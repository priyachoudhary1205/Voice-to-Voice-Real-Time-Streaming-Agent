# Voice-to-Voice Real-Time Streaming Agent

**A full-duplex, interruptible voice agent: streaming STT → LLM → TTS over a single WebSocket, with true barge-in.**

<p>
<img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue">
<img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.110%2B-009688">
<img alt="Transport" src="https://img.shields.io/badge/transport-WebSocket%20PCM16-4b32c3">
<img alt="Providers" src="https://img.shields.io/badge/providers-pluggable-informational">
</p>

---

## The problem this solves

Most "voice AI" demos are half-duplex walkie-talkies: you speak, you wait, the bot speaks its entire reply, and only then will it listen again. Talk over it and it keeps going. Real conversation doesn't work like that — humans interrupt, and the other party *stops within a couple hundred milliseconds*.

Getting that right is not a model problem, it's a **concurrency and cancellation** problem. When the user barges in, four things must happen almost at once:

1. detect speech while the agent is still talking,
2. cancel LLM generation mid-stream,
3. cancel TTS synthesis mid-sentence,
4. **flush audio already queued downstream** — otherwise the agent keeps talking out of the buffer for seconds after it has "stopped."

Step 4 is the one that's usually missed, and it's the one users actually notice. This repository is a clean reference implementation of the whole path.

---

## Architecture

```
  mic ──PCM16──► WebSocket ──► VAD ──► STT ──► LLM ──► TTS ──► WebSocket ──► speaker
                                │                │       │
                                │                └───────┴──► function-call events
                                │                              (non-blocking)
                                │
                                └──► barge-in detected while SPEAKING
                                     → set cancel event
                                     → cancel the response task
                                     → flush output buffer
```

The design principle: **one cancellation token, checked at every await boundary.** `asyncio.Event` is passed down into the LLM stream and the TTS stream, and every loop re-checks it after each yield. There is no point in the pipeline where an in-flight generation can outlive the interruption that killed it.

### Turn state machine

```
IDLE ──speech──► LISTENING ──END_TURN──► THINKING ──first audio──► SPEAKING
  ▲                                                                   │
  │                                                          user speaks
  │                                                                   ▼
  └──────────────── cancel + flush ◄───────────────────────── INTERRUPTED
```

States live in `app/state.py` as a `str`-valued enum, so they serialize straight onto the wire for client-side UI ("listening…", "thinking…") without a mapping layer.

---

## What's implemented

| Capability | Where | Notes |
|---|---|---|
| WebSocket transport, binary PCM16 in / out | `app/server.py` | Adapter-shaped for WebRTC or LiveKit |
| Voice activity detection | `app/providers.py` | Energy-based; Silero-compatible interface |
| Barge-in detection during agent speech | `app/agent.py` | VAD fires while state is `SPEAKING` |
| Cooperative cancellation of LLM + TTS | `app/agent.py` | Shared `asyncio.Event`, checked per chunk |
| Output-buffer flush on interrupt | `app/agent.py` | Prevents "ghost audio" after barge-in |
| Sentence-boundary chunked TTS | `app/agent.py` | Synthesis starts before the LLM finishes |
| Function-call events in the token stream | `app/agent.py` | Routed without stalling audio |
| Turn state machine | `app/state.py` | 5 states, serializable |
| Streaming provider interfaces | `app/providers.py` | Mock implementations, see below |

### On the mock providers

`StreamingSTT`, `StreamingLLM`, and `StreamingTTS` ship as **working mocks** so the project clones, installs, and runs end-to-end with zero API keys and zero GPU. That's deliberate: the interesting engineering here is the orchestration layer, and it's testable in isolation when the providers are deterministic and free.

They are interfaces, not stubs to be worked around — swapping in real vendors means implementing the same three async signatures:

```python
class StreamingSTT:
    async def finalize(self, pcm: bytes) -> str: ...

class StreamingLLM:
    async def stream(self, text: str, cancel: asyncio.Event): ...   # yields {"type", "text"}

class StreamingTTS:
    async def stream(self, text: str, cancel: asyncio.Event): ...   # yields PCM bytes
```

Suggested real backends: **Deepgram** or **Whisper** streaming for STT, any token-streaming LLM API, **Cartesia** or **Kokoro** for low-latency TTS. Nothing in `agent.py` changes.

---

## Latency design

Time-to-first-audio is dominated by serialization, not raw model speed. Two choices in `_respond()` attack it:

**Sentence-boundary flushing.** Rather than waiting for the full completion, tokens accumulate until a boundary character arrives, then that fragment goes straight to TTS:

```python
sentence += event["text"]
if event["text"].endswith((" ", ".", "?", "!")) and sentence.strip():
    self.state = AgentState.SPEAKING
    async for audio in self.tts.stream(sentence, self.cancel):
        await self.send_audio(audio)
```

The agent starts speaking while the LLM is still generating. Perceived latency becomes *first sentence*, not *full response*.

**Cancellation at every boundary.** Both the LLM loop and the TTS loop check `cancel.is_set()` after each yield, and `interrupt()` additionally cancels the asyncio task outright. Belt and braces — cooperative checks handle the clean case, task cancellation handles a provider blocked inside a slow network read.

---

## Quickstart

```bash
git clone https://github.com/<you>/voice-realtime-agent.git
cd voice-realtime-agent
pip install -r requirements.txt
python -m app.server
```

Server comes up on `http://localhost:8000`. Connect a WebSocket client to `ws://localhost:8000/ws`.

### Wire protocol

| Direction | Frame | Meaning |
|---|---|---|
| client → server | binary | PCM16 audio chunk from the mic |
| client → server | text `END_TURN` | user finished speaking; begin responding |
| server → client | binary | PCM16 audio chunk to play |
| server → client | empty binary frame | **flush signal** — clear your playback buffer immediately |

The empty-frame flush is what makes barge-in feel instant on the client side. A client that ignores it will keep playing stale audio no matter how fast the server cancels.

Minimal client:

```python
import asyncio, websockets

async def main():
    async with websockets.connect("ws://localhost:8000/ws") as ws:
        await ws.send(pcm16_chunk)      # bytes from the microphone
        await ws.send("END_TURN")
        async for frame in ws:
            if frame == b"":
                playback_buffer.clear()  # barge-in: drop everything queued
            else:
                playback_buffer.write(frame)

asyncio.run(main())
```

---

## Layout

```
voice_realtime_agent/
├── app/
│   ├── server.py      FastAPI app, WebSocket endpoint, frame routing
│   ├── agent.py       VoiceAgent: turn handling, barge-in, cancellation
│   ├── state.py       AgentState enum
│   └── providers.py   VAD + streaming STT/LLM/TTS interfaces (mocked)
└── requirements.txt
```

Three dependencies: FastAPI, uvicorn, numpy. That's the whole install.

---

## Roadmap

- [ ] **WebRTC / LiveKit transport adapter** — jitter buffering, packet loss concealment, NAT traversal for real networks
- [ ] **Silero VAD** — swap the energy threshold for a neural VAD; the energy detector will false-trigger on background noise
- [ ] **Real provider adapters** — Deepgram STT, streaming LLM, Cartesia TTS behind the existing interfaces
- [ ] **Echo cancellation** — currently the agent's own output can trip its VAD in a speakerphone setup; needs AEC or a reference-signal gate
- [ ] **Partial-transcript handling** — act on interim STT results rather than waiting for `END_TURN`
- [ ] **Async function-call execution** — run tool calls concurrently and splice results back into the stream instead of skipping them
- [ ] **Latency instrumentation** — per-stage timing (VAD → STT → first token → first audio) exported to Prometheus

## License

MIT
