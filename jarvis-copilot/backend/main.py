from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from ai_engine import generate_suggestion

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active connections and their context
connections = {}


@app.get("/")
async def health():
    return {"status": "ok", "service": "jarvis-copilot"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_id = id(websocket)
    connections[client_id] = {"ws": websocket, "context": []}

    try:
        while True:
            data = await websocket.receive_json()

            if data.get("type") == "transcript":
                # Add to context
                connections[client_id]["context"].append(data)

                # Only process investor speech
                if data.get("speaker") == "investor":
                    suggestion = await generate_suggestion(
                        data.get("text", ""),
                        connections[client_id]["context"],
                    )

                    if suggestion:
                        await websocket.send_json(suggestion)

    except WebSocketDisconnect:
        if client_id in connections:
            del connections[client_id]

