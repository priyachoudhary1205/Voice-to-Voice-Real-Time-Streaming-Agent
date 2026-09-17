import asyncio
from .state import AgentState
from .providers import StreamingSTT, StreamingLLM, StreamingTTS, EnergyVAD

class VoiceAgent:
    def __init__(self, send_audio):
        self.state = AgentState.IDLE
        self.send_audio = send_audio
        self.vad = EnergyVAD()
        self.stt = StreamingSTT()
        self.llm = StreamingLLM()
        self.tts = StreamingTTS()
        self.cancel = asyncio.Event()
        self.audio_buffer = bytearray()
        self.output_task = None

    async def on_audio(self, chunk: bytes):
        speaking = self.vad.speech(chunk)
        if self.state == AgentState.SPEAKING and speaking:
            await self.interrupt()
        self.audio_buffer.extend(chunk)
        self.state = AgentState.LISTENING

    async def end_turn(self):
        if not self.audio_buffer:
            return
        pcm = bytes(self.audio_buffer)
        self.audio_buffer.clear()
        self.cancel = asyncio.Event()
        self.state = AgentState.THINKING
        text = await self.stt.finalize(pcm)
        self.output_task = asyncio.create_task(self._respond(text))

    async def interrupt(self):
        self.cancel.set()
        self.state = AgentState.INTERRUPTED
        if self.output_task:
            self.output_task.cancel()
        # Transport adapter should additionally flush jitter/audio buffers.
        await self.send_audio(b"")

    async def _respond(self, text):
        try:
            sentence = ""
            async for event in self.llm.stream(text, self.cancel):
                if self.cancel.is_set():
                    return
                if event["type"] == "function_call":
                    # Execute asynchronously and continue streaming in production.
                    continue
                sentence += event["text"]
                if event["text"].endswith((" ", ".", "?", "!")) and sentence.strip():
                    self.state = AgentState.SPEAKING
                    async for audio in self.tts.stream(sentence, self.cancel):
                        if self.cancel.is_set():
                            return
                        await self.send_audio(audio)
                    sentence = ""
            if sentence and not self.cancel.is_set():
                async for audio in self.tts.stream(sentence, self.cancel):
                    await self.send_audio(audio)
        except asyncio.CancelledError:
            pass
        finally:
            if not self.cancel.is_set():
                self.state = AgentState.IDLE
