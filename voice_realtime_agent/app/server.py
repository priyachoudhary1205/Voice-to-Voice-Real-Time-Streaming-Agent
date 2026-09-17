from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn
from .agent import VoiceAgent

app = FastAPI(title="Interruptible Voice Agent")

@app.get("/")
async def home():
    return HTMLResponse("<h3>Voice Agent running</h3><p>Connect a WebSocket client to /ws</p>")

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()

    async def send_audio(data: bytes):
        await websocket.send_bytes(data)

    agent = VoiceAgent(send_audio)
    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"] is not None:
                await agent.on_audio(message["bytes"])
            elif message.get("text") == "END_TURN":
                await agent.end_turn()
    except WebSocketDisconnect:
        await agent.interrupt()

if __name__ == "__main__":
    uvicorn.run("app.server:app", host="0.0.0.0", port=8000, reload=True)
