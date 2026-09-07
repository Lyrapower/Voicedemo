from __future__ import annotations
import asyncio, json, os, sys, hashlib
from pathlib import Path
from typing import Any
from .config import Config


# Canonical provenance 接入(砥段三 item 5/6):cc 每次执行写 action + receipt,
# metadata 固定分离 transport_locality vs model_execution_locality(不折叠成单 Boolean)。
_DEMO_ROOT = Path(__file__).resolve().parents[2]  # demo/  (cc.py → harness → harness_resident → demo)
if str(_DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ROOT))


def _execution_locality(model: str) -> str:
    """Ollama model 名 → 执行地:`:cloud`/`-cloud` 后缀 = CLOUD(ollama.com 远程),否则 LOCAL。"""
    m = (model or "").lower()
    return "CLOUD" if (":cloud" in m or "-cloud" in m) else "LOCAL"


def _record_cc_provenance(job: dict[str, Any], model: str, endpoint: str,
                          prompt: str, response: str, ok: bool, status: str,
                          error: str = "") -> None:
    """记一笔 cc 执行的 action + receipt 到 canonical provenance 链。truthful:import 失败即抛。"""
    from app.harness.action_envelope import ActionEnvelope, FactualReceipt
    from app.harness import provenance
    mission_id = str(job["job_id"])
    action_id = f"cc:{mission_id}:{hashlib.sha256(prompt.encode()).hexdigest()[:8]}"
    request_hash = hashlib.sha256((prompt + "|" + model).encode()).hexdigest()[:16]
    response_hash = hashlib.sha256((response or "").encode()).hexdigest()[:16]
    ActionEnvelope(
        mission_id=mission_id, action_id=action_id,
        decision_origin="GRID_LOCAL",
        selected_resource=endpoint, operation="cc.execute",
        arguments={"goal": job["goal"], "model": model, "executor": "claude_code"},
        authorization_scope="local_write",
    ).to_dict()
    FactualReceipt(
        mission_id=mission_id, action_id=action_id,
        status=status, executed=ok,
        result=(response or "")[:2000] if ok else None,
        error=error,
        evidence_pointer=f"ollama:{model}",
        receipt_hash=response_hash,
        metadata={
            "executor_type": "claude_code",
            "transport_provider": "ollama",
            "transport_protocol": "anthropic_messages",
            "endpoint": endpoint,
            "transport_locality": "LOCAL_PROCESS",
            "selected_model": model,
            "model_execution_locality": _execution_locality(model),
            "bridge": "NONE",
            "request_hash": request_hash,
            "response_hash": response_hash,
        },
    ).to_dict()


# Claude Code 内建工具全集(deny-by-default 分母;MultiEdit/SlashCommand 已从 8-21 旧快照剔除)
CC_TOOL_UNIVERSE={"Task","Bash","BashOutput","KillShell","Glob","Grep","Read","Edit",
                  "Write","NotebookEdit","WebFetch","WebSearch","TodoWrite","Skill"}

class CCExecutor:
    def __init__(self,cfg:Config):
        self.cfg=cfg
        self.root=Path(cfg.cc.work_root)
        self.root.mkdir(parents=True,exist_ok=True)

    async def run(self,job:dict[str,Any],context_pack=None):
        if not self.cfg.cc.enabled:
            return {"ok":False,"error":"Claude Code disabled"}
        jd=self.root/job["job_id"]; jd.mkdir(parents=True,exist_ok=True)
        (jd/"TASK.md").write_text(f"# Task\n\n{job['goal']}\n",encoding="utf-8")
        context_json={
          "job_id":job["job_id"],
          "allowed_tools":job["allowed_tools"],
          "allowed_paths":job["allowed_paths"],
          "approval_mode":job["approval_mode"],
        }
        if context_pack is not None:
            context_json["context_receipt"]=context_pack.receipt()
        (jd/"CONTEXT.json").write_text(
            json.dumps(context_json,ensure_ascii=False,indent=2),encoding="utf-8"
        )
        if context_pack is not None:
            (jd/"MEMORY_CONTEXT.md").write_text(
                context_pack.to_cc_markdown(),encoding="utf-8"
            )
            (jd/"CONTEXT_RECEIPT.json").write_text(
                json.dumps(context_pack.receipt(),ensure_ascii=False,indent=2),encoding="utf-8"
            )
        prompt=("Read TASK.md and CONTEXT.json. If MEMORY_CONTEXT.md exists, read it as the "
                "canonical Grid context pack. Do only the requested task. "
                "Do not deploy. Write final result to RESULT.md. "
                "If blocked, explain the blocker in RESULT.md.")
        # v1.3 栅栏实体化:allowed_tools/allowed_paths 用 CC 自己的旗标 enforce,
        # 不再是 prompt 里的口头请求。路径栅栏 = cwd 锁 job 目录 + --add-dir 仅白名单;
        # 工具栅栏 = --allowedTools 逐项传。旗标名以本机 CC 版本为准(现场自证点):
        # 若 CC 报 unknown option,本任务按失败响亮返回,绝不静默摘栅栏重跑。
        flags: list[str] = ["-p", prompt]
        declared={str(t) for t in (job.get("allowed_tools") or [])}
        if job.get("read_only"):
            declared-={"Bash","Write","Edit"}
            if not declared:
                declared={"Read","Grep","Glob"}
        if declared:
            flags+=["--allowedTools",",".join(sorted(declared))]
            deny=sorted(CC_TOOL_UNIVERSE-declared)
            if deny:
                flags+=["--disallowedTools",",".join(deny)]
        host_add_dirs: list[Path] = []
        for p in job["allowed_paths"]:
            rp=Path(p)
            if str(p) in {".",""}:
                continue
            host_add_dirs.append(rp if rp.is_absolute() else (jd/rp).resolve())
        cc_model=getattr(self.cfg.cc,"model","")
        cc_endpoint=getattr(self.cfg.cc,"ollama_endpoint","http://127.0.0.1:11434")
        if cc_model:
            flags+=["--model",cc_model]
        if self._use_docker_sandbox():
            missing=self._sandbox_missing()
            if missing:
                return {"ok":False,"error":"BLOCKED_SANDBOX_MISSING","blocked":"sandbox_missing",
                        "detail":missing,"job_dir":str(jd),"sandbox":"docker"}
            return await self._run_docker(job,jd,flags,prompt,cc_model,cc_endpoint,host_add_dirs)
        if bool(getattr(self.cfg.cc,"sandbox_required",False)):
            return {"ok":False,"error":"BLOCKED_SANDBOX_MISSING","blocked":"sandbox_missing",
                    "detail":"sandbox_required without docker","job_dir":str(jd)}
        argv=[self.cfg.cc.binary,*flags]
        for rp in host_add_dirs:
            argv+=["--add-dir",str(rp)]
        sub_env=None
        if cc_model:
            sub_env=dict(os.environ)
            sub_env["ANTHROPIC_BASE_URL"]=cc_endpoint
            sub_env["ANTHROPIC_AUTH_TOKEN"]="ollama"
        proc=await asyncio.create_subprocess_exec(
            *argv,cwd=str(jd),env=sub_env,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        return await self._finish_proc(proc,job,jd,prompt,cc_model,cc_endpoint,sandbox=None,container=None)

    def _use_docker_sandbox(self) -> bool:
        return str(getattr(self.cfg.cc,"sandbox","") or "") == "docker"

    def _sandbox_missing(self) -> str:
        image=str(getattr(self.cfg.cc,"image","") or "")
        network=str(getattr(self.cfg.cc,"network","") or "")
        fwd=str(getattr(self.cfg.cc,"fwd","") or "")
        if not image or not network or not fwd:
            return "sandbox config incomplete"
        checks=(
            (["docker","info"],"docker unavailable"),
            (["docker","image","inspect",image],f"image missing:{image}"),
            (["docker","network","inspect",network],f"network missing:{network}"),
            (["docker","inspect",fwd],f"fwd missing:{fwd}"),
        )
        import subprocess
        for cmd, err in checks:
            try:
                r=subprocess.run(cmd,capture_output=True,timeout=8)
            except Exception:
                return err
            if r.returncode!=0:
                return err
        return ""

    async def _run_docker(self,job,jd,flags,prompt,cc_model,cc_endpoint,host_add_dirs):
        image=str(self.cfg.cc.image)
        network=str(self.cfg.cc.network)
        fwd=str(self.cfg.cc.fwd)
        name=f"grid-cc-{job['job_id']}"
        argv=["docker","run","--rm","--name",name,
              "--read-only","--network",network,
              "--cap-drop","ALL","--security-opt","no-new-privileges",
              "--pids-limit","256","--memory","2g","--cpus","2",
              "--tmpfs","/work:rw,size=512m,mode=1777",
              "-v",f"{jd}:/ws/job:ro"]
        for i, rp in enumerate(host_add_dirs):
            argv+=["-v",f"{rp}:/ws/p{i}:ro"]
            flags+=["--add-dir",f"/ws/p{i}"]
        argv+=["-e","ANTHROPIC_AUTH_TOKEN=ollama",
               "-e",f"ANTHROPIC_BASE_URL=http://{fwd}:11434",
               "-e","HOME=/work",
               "-e","PATH=/usr/local/bin:/usr/bin:/bin",
               "-e",f"HTTPS_PROXY=http://{fwd}:3128",
               "-e",f"HTTP_PROXY=http://{fwd}:3128",
               "-e",f"NO_PROXY={fwd},localhost,127.0.0.1",
               image,"claude",*flags]
        proc=await asyncio.create_subprocess_exec(
            *argv,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        return await self._finish_proc(proc,job,jd,prompt,cc_model,cc_endpoint,
                                       sandbox="docker",container=name)

    async def _finish_proc(self,proc,job,jd,prompt,cc_model,cc_endpoint,*,sandbox,container):
        try:
            out,err=await asyncio.wait_for(proc.communicate(),timeout=self.cfg.cc.timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill(); await proc.communicate()
            if cc_model:
                try: _record_cc_provenance(job, cc_model, cc_endpoint, prompt, "", False, "TIMEOUT", error="timeout")
                except Exception: pass
            return {"ok":False,"error":"Claude Code timeout","job_dir":str(jd),
                    "sandbox":sandbox,"container":container}
        except asyncio.CancelledError:
            proc.kill(); await proc.communicate()
            raise
        stderr_txt=err.decode("utf-8","replace")
        if proc.returncode!=0 and ("unknown option" in stderr_txt.lower() or "unrecognized" in stderr_txt.lower()):
            return {"ok":False,"returncode":proc.returncode,
                    "error":"CC 版本不识别权限旗标(--allowedTools/--add-dir)——栅栏无法实体化,任务未放行",
                    "stderr":stderr_txt,"job_dir":str(jd),"sandbox":sandbox,"container":container}
        rp=jd/"RESULT.md"
        result=rp.read_text(encoding="utf-8") if rp.exists() else out.decode("utf-8","replace")
        ok=proc.returncode==0
        tools={str(t) for t in (job.get("allowed_tools") or [])}
        goal=str(job.get("goal") or "")
        if ok and "Bash" not in tools and "Bash" in goal and not rp.exists():
            ok=False
        if cc_model:
            _record_cc_provenance(job, cc_model, cc_endpoint, prompt, result, ok,
                                  status="EXECUTED" if ok else ("DENIED" if "Bash" in goal and "Bash" not in tools else "FAILED"),
                                  error=stderr_txt if not ok else "")
        return {"ok":ok,"returncode":proc.returncode,
                "stdout":out.decode("utf-8","replace"),"stderr":err.decode("utf-8","replace"),
                "result":result,"job_dir":str(jd),"sandbox":sandbox,"container":container}
