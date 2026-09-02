from __future__ import annotations
from .db import Store

class ControlPlane:
    def __init__(self,store:Store,supervisor):
        self.store=store
        self.supervisor=supervisor

    def message(self,session_id:str,text:str):
        msg=self.store.append_message(session_id,"user",text)
        self.store.append_stream_event(session_id=session_id,job_id=None,kind="control_message",
                                       payload={"text":text})
        return msg

    async def pause(self,session_id): return await self.supervisor.pause_session(session_id)
    async def resume(self,session_id): return await self.supervisor.resume_session(session_id)
    async def cancel(self,session_id): return await self.supervisor.cancel_session(session_id)
    async def approve(self,session_id,note="approved"): return await self.supervisor.approve_session(session_id,note)
    async def reject(self,session_id,note="rejected"): return await self.supervisor.reject_session(session_id,note)
