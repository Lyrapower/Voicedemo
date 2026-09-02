const $=s=>document.querySelector(s);
const state={
  cfg:JSON.parse(localStorage.getItem("grid_cfg")||"null")||{
    mode:"local",baseUrl:location.origin,deviceId:"grid-mac",token:""
  },
  sessions:[],active:null,lastSeq:Number(localStorage.getItem("grid_last_seq")||0),
  ws:null,retry:1000,live:{}
};

function esc(s){return (s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]))}
function age(ts){if(!ts)return"no heartbeat";let x=Math.max(0,Date.now()/1000-ts);return x<60?`${Math.round(x)}s ago`:`${Math.round(x/60)}m ago`}
function statusClass(s){return ["running","waiting_approval","blocked"].includes(s)?s:""}

async function localFetch(path,opts={}){
  const auth=state.cfg.token?{"authorization":`Bearer ${state.cfg.token}`}:{};
  const r=await fetch(state.cfg.baseUrl.replace(/\/$/,"")+path,{
    ...opts,headers:{"content-type":"application/json",...auth,...(opts.headers||{})}
  });
  if(!r.ok)throw new Error(`${r.status} ${await r.text()}`); return r.json();
}
async function rpc(payload){
  const r=await fetch(state.cfg.baseUrl.replace(/\/$/,"")+"/rpc",{
    method:"POST",
    headers:{"content-type":"application/json","authorization":`Bearer ${state.cfg.token}`},
    body:JSON.stringify({device_id:state.cfg.deviceId,payload})
  });
  if(!r.ok)throw new Error(`${r.status} ${await r.text()}`); return r.json();
}

async function createSessionRemote(agent_id,channel,title){
  if(state.cfg.mode==="local") return await localFetch("/sessions",{method:"POST",body:JSON.stringify({agent_id,channel,title})});
  const x=await rpc({type:"create_session",agent_id,channel,title}); return x.session;
}
async function listSessions(){
  if(state.cfg.mode==="local") return await localFetch("/sessions");
  const x=await rpc({type:"list_sessions"}); return x.sessions||[];
}
async function getSession(id){
  if(state.cfg.mode==="local") return await localFetch(`/sessions/${id}`);
  const x=await rpc({type:"get_session",session_id:id});
  return {...x.session,messages:x.messages||[]};
}
async function contextPreview(id){
  if(state.cfg.mode==="local") return await localFetch(`/sessions/${id}/context-preview`);
  const x=await rpc({type:"context_preview",session_id:id}); return {receipt:x.receipt};
}
async function sendMessage(id,text){
  if(state.cfg.mode==="local") return await localFetch(`/sessions/${id}/message`,{
    method:"POST",body:JSON.stringify({text,spawn_job:true})
  });
  return await rpc({type:"session_message",session_id:id,text});
}
async function control(id,action){
  if(state.cfg.mode==="local") return await localFetch(`/sessions/${id}/${action}`,{
    method:"POST",body:JSON.stringify({note:"mobile"})
  });
  return await rpc({type:"control",session_id:id,action,note:"mobile"});
}
async function replay(){
  let ev=[];
  if(state.cfg.mode==="local") ev=await localFetch(`/events?after_seq=${state.lastSeq}&limit=1000`);
  else { const x=await rpc({type:"events_after",after_seq:state.lastSeq,limit:1000}); ev=x.events||[]; }
  for(const e of ev) ingest(e,false);
  if(ev.length) await refresh();
}

function ingest(e,refreshNow=true){
  if(e.seq && Number(e.seq)<=state.lastSeq) return;
  if(e.seq){
    state.lastSeq=Math.max(state.lastSeq,Number(e.seq));
    localStorage.setItem("grid_last_seq",String(state.lastSeq));
  }
  if(e.kind==="agent_delta" && e.session_id){
    state.live[e.session_id]=(state.live[e.session_id]||"")+(e.payload?.text||"");
    if(state.active===e.session_id) renderLiveDelta();
    return;
  }
  if((e.kind==="job_done"||e.kind==="job_failed"||e.kind==="job_exception") && e.session_id){
    delete state.live[e.session_id];
  }
  if(refreshNow) refresh();
}

function renderSessions(){
  const box=$("#sessionList");
  const pri={waiting_approval:0,blocked:1,running:2,stale:3,interrupted:4,idle:5,done:6,failed:7,cancelled:8};
  state.sessions.sort((a,b)=>(pri[a.state]??9)-(pri[b.state]??9)||b.updated_at-a.updated_at);
  box.innerHTML=state.sessions.map(s=>`
    <article class="card" data-id="${esc(s.session_id)}">
      <div class="cardTop">
        <div class="agent">${esc(s.title||s.agent_id)}</div>
        <span class="badge ${statusClass(s.state)}">${esc(s.state)}</span>
      </div>
      <div class="meta">${esc(s.agent_id)} · ${esc(s.channel)} · ${age(s.last_heartbeat)}</div>
      <div class="job">${s.active_job_id?`Active: ${esc(s.active_job_id)}`:"Idle"}${s.waiting_for?` · waiting: ${esc(s.waiting_for)}`:""}</div>
    </article>`).join("")||`<div class="card">No sessions yet.</div>`;
  box.querySelectorAll(".card[data-id]").forEach(el=>el.onclick=()=>openThread(el.dataset.id));
}

async function refresh(){
  try{
    state.sessions=await listSessions();
    renderSessions();
    if(state.active){
      const d=await getSession(state.active);
      renderThread(d);
    }
  }catch(e){setPresence(false,String(e))}
}

function renderLiveDelta(){
  if(!state.active)return;
  let el=document.querySelector("#liveDelta");
  const text=state.live[state.active]||"";
  if(!text){if(el)el.remove();return}
  if(!el){
    el=document.createElement("div");el.id="liveDelta";el.className="msg assistant";
    $("#messages").appendChild(el);
  }
  el.textContent=text+" ▌";
  window.scrollTo(0,document.body.scrollHeight);
}

function renderThread(d){
  $("#threadTitle").textContent=d.title||d.agent_id;
  $("#threadMeta").textContent=`${d.state} · ${d.agent_id} · ${age(d.last_heartbeat)}`;
  $("#messages").innerHTML=(d.messages||[]).map(m=>
    `<div class="msg ${esc(m.role)}">${esc(m.content)}</div>`).join("");
  renderLiveDelta();
  $("#messages").scrollTop=$("#messages").scrollHeight;
}

async function openThread(id){
  state.active=id;
  $("#sessionList").classList.add("hidden"); $("#thread").classList.remove("hidden");
  renderThread(await getSession(id));
}
function closeThread(){state.active=null;$("#thread").classList.add("hidden");$("#sessionList").classList.remove("hidden")}

function setPresence(on,detail=""){
  const p=$("#presence"); p.className=`presence ${on?"online":"offline"}`;
  p.textContent=`● ${on?"ONLINE":"OFFLINE"}${detail?` · ${detail}`:""}`;
}

function connectWS(){
  if(state.ws)try{state.ws.close()}catch{}
  const base=state.cfg.baseUrl.replace(/^http/,"ws").replace(/\/$/,"");
  const url=state.cfg.mode==="local"
    ?`${base}/ws/events?after_seq=${state.lastSeq}${state.cfg.token?`&token=${encodeURIComponent(state.cfg.token)}`:""}`
    :`${base}/ws/client`;
  const ws=new WebSocket(url); state.ws=ws;
  ws.onopen=()=>{
    state.retry=1000; setPresence(true);
    if(state.cfg.mode==="relay")ws.send(JSON.stringify({
      token:state.cfg.token,device_id:state.cfg.deviceId
    }));
    else ws.send(JSON.stringify({type:"resume",after_seq:state.lastSeq}));
  };
  ws.onmessage=e=>{
    try{
      const x=JSON.parse(e.data);
      if(x.type==="agent_presence"){setPresence(!!x.online);return}
      if(x.type==="client_ready"){setPresence(!!x.online); replay();return}
      if(x.type==="heartbeat"||x.type==="pong"){setPresence(true);return}
      if(x.type==="event") ingest(x.event);
      else if(x.seq) ingest(x);
    }catch{}
  };
  ws.onclose=()=>{
    setPresence(false,"reconnecting");
    setTimeout(connectWS,state.retry);
    state.retry=Math.min(15000,state.retry*1.7);
  };
  ws.onerror=()=>ws.close();
}

$("#messageForm").onsubmit=async e=>{
  e.preventDefault();
  const input=$("#messageInput"),text=input.value.trim(); if(!text||!state.active)return;
  input.value="";
  try{await sendMessage(state.active,text);await refresh()}
  catch(err){alert(String(err))}
};
$("#backBtn").onclick=closeThread;
$("#contextBtn").onclick=async()=>{
  if(!state.active)return;
  try{
    const x=await contextPreview(state.active);
    $("#contextReceipt").textContent=JSON.stringify(x.receipt||x,null,2);
    $("#contextDialog").showModal();
  }catch(err){alert(String(err))}
};

document.querySelectorAll(".controls button").forEach(b=>b.onclick=async()=>{
  if(!state.active)return;
  try{await control(state.active,b.dataset.action);await refresh()}catch(e){alert(String(e))}
});
$("#newBtn").onclick=()=>$("#newSession").showModal();
$("#createSessionBtn").onclick=async e=>{
  e.preventDefault();
  try{
    const s=await createSessionRemote($("#newAgent").value,$("#newChannel").value.trim()||"grid",
                                      $("#newTitle").value.trim());
    $("#newSession").close(); await refresh(); await openThread(s.session_id);
  }catch(err){alert(String(err))}
};
$("#settingsBtn").onclick=()=>{
  $("#mode").value=state.cfg.mode;$("#baseUrl").value=state.cfg.baseUrl;
  $("#deviceId").value=state.cfg.deviceId;$("#token").value=state.cfg.token;
  $("#settings").showModal();
};
$("#saveSettings").onclick=e=>{
  e.preventDefault();
  state.cfg={mode:$("#mode").value,baseUrl:$("#baseUrl").value.trim()||location.origin,
             deviceId:$("#deviceId").value.trim()||"grid-mac",token:$("#token").value};
  localStorage.setItem("grid_cfg",JSON.stringify(state.cfg));
  $("#settings").close(); connectWS(); refresh();
};

if("serviceWorker"in navigator)navigator.serviceWorker.register("/mobile/sw.js").catch(()=>{});
refresh().then(()=>replay()).finally(connectWS);
setInterval(()=>{if(state.ws?.readyState===1)state.ws.send(JSON.stringify({type:"ping"}))},20000);
