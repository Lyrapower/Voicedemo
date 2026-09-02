from __future__ import annotations
import asyncio, json, os
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

app=FastAPI(title="Grid Thin Relay")
agents:dict[str,WebSocket]={}
clients:dict[str,set[WebSocket]]={}
waiters:dict[str,asyncio.Future]={}

MOBILE=Path(__file__).resolve().parent/"mobile"
if MOBILE.exists():
    app.mount("/mobile",StaticFiles(directory=str(MOBILE),html=True),name="mobile")

@app.get("/")
async def root():
    if (MOBILE/"index.html").exists():
        return FileResponse(MOBILE/"index.html")
    return {"name":"Grid Thin Relay"}

def required_token():
    return os.getenv("GRID_RELAY_TOKEN","")

def check_token(auth):
    required=required_token()
    if required and auth!=f"Bearer {required}":
        raise HTTPException(401,"unauthorized")

async def broadcast(device_id:str,payload:dict):
    dead=[]
    for ws in list(clients.get(device_id,set())):
        try: await ws.send_json(payload)
        except Exception: dead.append(ws)
    for ws in dead:
        clients.get(device_id,set()).discard(ws)

@app.websocket("/ws/agent")
async def agent_ws(ws:WebSocket):
    required=required_token()
    if required and ws.headers.get("authorization")!=f"Bearer {required}":
        await ws.close(code=4401); return
    await ws.accept()
    device_id=None
    try:
        hello=json.loads(await ws.receive_text())
        if hello.get("type")!="hello":
            await ws.close(code=4400); return
        device_id=hello["device_id"]; agents[device_id]=ws
        await broadcast(device_id,{"type":"agent_presence","online":True,"device_id":device_id})
        async for raw in ws.iter_text():
            msg=json.loads(raw)
            if msg.get("type")=="event":
                await broadcast(device_id,msg)
                continue
            rid=msg.get("request_id")
            if rid and rid in waiters:
                fut=waiters.pop(rid)
                if not fut.done(): fut.set_result(msg)
    except WebSocketDisconnect:
        pass
    finally:
        if device_id and agents.get(device_id) is ws:
            agents.pop(device_id,None)
            await broadcast(device_id,{"type":"agent_presence","online":False,"device_id":device_id})

@app.websocket("/ws/client")
async def client_ws(ws:WebSocket):
    await ws.accept()
    device_id=None
    try:
        auth=await asyncio.wait_for(ws.receive_json(),timeout=10)
        token=auth.get("token","")
        if required_token() and token!=required_token():
            await ws.close(code=4401); return
        device_id=auth.get("device_id")
        if not device_id:
            await ws.close(code=4400); return
        clients.setdefault(device_id,set()).add(ws)
        await ws.send_json({"type":"client_ready","device_id":device_id,"online":device_id in agents})
        while True:
            msg=await ws.receive_json()
            if msg.get("type")=="ping":
                await ws.send_json({"type":"pong","online":device_id in agents})
    except (WebSocketDisconnect,asyncio.TimeoutError):
        pass
    finally:
        if device_id:
            clients.get(device_id,set()).discard(ws)

class RelayRequest(BaseModel):
    device_id:str
    payload:dict
    timeout_seconds:int=30

@app.post("/rpc")
async def rpc(body:RelayRequest,authorization:str|None=Header(default=None)):
    check_token(authorization)
    ws=agents.get(body.device_id)
    if not ws: raise HTTPException(503,"device offline")
    rid=os.urandom(8).hex()
    fut=asyncio.get_running_loop().create_future()
    waiters[rid]=fut
    await ws.send_text(json.dumps({**body.payload,"request_id":rid}))
    try: return await asyncio.wait_for(fut,timeout=body.timeout_seconds)
    except asyncio.TimeoutError:
        waiters.pop(rid,None)
        raise HTTPException(504,"agent timeout")

@app.get("/presence/{device_id}")
async def presence(device_id:str,authorization:str|None=Header(default=None)):
    check_token(authorization)
    return {"device_id":device_id,"online":device_id in agents,
            "clients":len(clients.get(device_id,set()))}

if __name__=="__main__":
    uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","8080")))
