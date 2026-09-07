from __future__ import annotations
import asyncio, json, os, sys, hashlib, shutil
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
        jd=jd.resolve()
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
            if job.get("read_only"):
                deny=[t for t in deny if t!="Bash"]
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

    def _docker_bin(self) -> str:
        return os.environ.get("DOCKER_BIN") or shutil.which("docker") or "/usr/local/bin/docker"

    def _sandbox_dir(self) -> Path:
        return Path(__file__).resolve().parents[1] / "sandbox"

    def _sandbox_missing(self) -> str:
        image=str(getattr(self.cfg.cc,"image","") or "")
        broker_image=str(getattr(self.cfg.cc,"broker_image","") or "python:3.13-slim")
        if not image:
            return "sandbox config incomplete"
        sd=self._sandbox_dir()
        for rel in ("model_broker.py","model_relay.js","cc_boot.sh"):
            if not (sd/rel).is_file():
                return f"sandbox file missing:{rel}"
        docker=self._docker_bin()
        import subprocess
        checks=(
            ([docker,"info"],"docker unavailable"),
            ([docker,"image","inspect",image],f"image missing:{image}"),
            ([docker,"image","inspect",broker_image],f"image missing:{broker_image}"),
        )
        for cmd, err in checks:
            try:
                r=subprocess.run(cmd,capture_output=True,timeout=8)
            except Exception:
                return err
            if r.returncode!=0:
                return err
        missing_net=self._ensure_broker_net()
        if missing_net:
            return missing_net
        return ""

    def _ensure_broker_net(self) -> str:
        import subprocess
        docker=self._docker_bin()
        net=str(getattr(self.cfg.cc,"broker_net","") or "grid-cc-broker-net")
        r=subprocess.run([docker,"network","inspect",net],capture_output=True,timeout=8)
        if r.returncode==0:
            return ""
        c=subprocess.run(
            [docker,"network","create","--driver","bridge",net],
            capture_output=True,timeout=15,text=True)
        if c.returncode!=0:
            return f"broker net missing:{net}"
        return ""

    def _d(self, args: list[str], timeout: int = 30, check: bool = True, text: bool = True):
        import subprocess
        r=subprocess.run([self._docker_bin(),*args],capture_output=True,timeout=timeout,text=text)
        if check and r.returncode!=0:
            err=(r.stderr or r.stdout or "").strip()[:400]
            raise RuntimeError(err or f"docker {' '.join(args[:4])} failed")
        return r

    def _names(self, job_id: str) -> dict[str,str]:
        safe="".join(c if c.isalnum() or c in "-_" else "-" for c in job_id)[:80]
        return {
            "cc": f"grid-cc-{safe}",
            "broker": f"grid-cc-broker-{safe}",
            "work": f"grid-cc-work-{safe}",
            "bridge": f"grid-cc-bridge-{safe}",
        }

    def _chown_vol(self, volume: str) -> None:
        broker_image=str(getattr(self.cfg.cc,"broker_image","") or "python:3.13-slim")
        self._d(["run","--rm","--user","0",
                 "-v",f"{volume}:/bridge",
                 "--entrypoint","python3",broker_image,
                 "-c","import os; os.chown('/bridge',1001,1001); os.chmod('/bridge',0o750)"],
                timeout=30)

    def _start_broker(self, names: dict[str,str], model: str) -> None:
        sd=self._sandbox_dir()
        broker_image=str(getattr(self.cfg.cc,"broker_image","") or "python:3.13-slim")
        net=str(getattr(self.cfg.cc,"broker_net","") or "grid-cc-broker-net")
        self._d(["rm","-f",names["broker"]], check=False)
        argv=["run","-d","--name",names["broker"],
              "--network",net,
              "--add-host","host.docker.internal:host-gateway",
              "--user","1001:1001",
              "--read-only","--tmpfs","/tmp:rw,mode=1777",
              "--cap-drop","ALL","--security-opt","no-new-privileges",
              "--pids-limit","64","--memory","256m","--cpus","0.5",
              "-v",f"{names['bridge']}:/bridge",
              "-v",f"{sd/'model_broker.py'}:/opt/grid/model_broker.py:ro",
              "--entrypoint","python3",
              broker_image,
              "/opt/grid/model_broker.py",
              "--sock","/bridge/model.sock",
              "--upstream","host.docker.internal:11434",
              "--model",model or ""]
        self._d(argv, timeout=30)
        for _ in range(40):
            r=self._d(["exec",names["broker"],"python3","-c",
                       "import os,sys; sys.exit(0 if os.path.exists('/bridge/ready') else 1)"],
                      check=False, timeout=8)
            if r.returncode==0:
                return
            import time as _t; _t.sleep(0.1)
        raise RuntimeError("broker sock not ready")

    def _cleanup_job(self, names: dict[str,str], *, remove_volumes: bool) -> None:
        self._d(["rm","-f",names["cc"],names["broker"]], check=False)
        if remove_volumes:
            self._d(["volume","rm","-f",names["work"],names["bridge"]], check=False)

    def _inspect_cc(self, name: str) -> dict[str,str]:
        fmt="{{.HostConfig.NetworkMode}}|{{.HostConfig.Privileged}}|{{.HostConfig.ReadonlyRootfs}}|{{.Config.User}}|{{json .HostConfig.PortBindings}}|{{json .HostConfig.CapAdd}}"
        r=self._d(["inspect","-f",fmt,name], timeout=8)
        net,priv,ro,user,ports,caps=(r.stdout or "").strip().split("|",5)
        return {"network":net,"privileged":priv,"readonly":ro,"user":user,"ports":ports,"caps":caps}

    async def _run_docker(self,job,jd,flags,prompt,cc_model,cc_endpoint,host_add_dirs):
        names=self._names(job["job_id"])
        image=str(self.cfg.cc.image)
        sd=self._sandbox_dir()
        collected=False
        try:
            self._d(["volume","create",names["work"]], check=False)
            self._d(["volume","create",names["bridge"]], check=False)
            self._chown_vol(names["work"])
            self._chown_vol(names["bridge"])
            self._start_broker(names, cc_model)
            self._d(["rm","-f",names["cc"]], check=False)
            argv=["create","--name",names["cc"],
                  "--network","none",
                  "--user","1001:1001",
                  "--read-only",
                  "--tmpfs","/tmp:rw,exec,mode=1777",
                  "--cap-drop","ALL","--security-opt","no-new-privileges",
                  "--pids-limit","256","--memory","2g","--cpus","2",
                  "-v",f"{names['work']}:/work",
                  "-v",f"{names['bridge']}:/bridge:ro",
                  "-v",f"{jd}:/ws/job:ro",
                  "-v",f"{sd/'cc_boot.sh'}:/opt/grid/cc_boot.sh:ro",
                  "-v",f"{sd/'model_relay.js'}:/opt/grid/model_relay.js:ro",
                  "-e","ANTHROPIC_AUTH_TOKEN=ollama",
                  "-e","ANTHROPIC_API_KEY=ollama",
                  "-e","ANTHROPIC_BASE_URL=http://127.0.0.1:11434",
                  "-e","HOME=/work",
                  "-e","PATH=/usr/local/bin:/usr/bin:/bin",
                  "-e","MODEL_SOCK=/bridge/model.sock"]
            add_flags=list(flags)
            for i, rp in enumerate(host_add_dirs):
                argv+=["-v",f"{rp}:/ws/p{i}:ro"]
                add_flags+=["--add-dir",f"/ws/p{i}"]
            argv+=["--entrypoint","/bin/sh",image,"/opt/grid/cc_boot.sh","claude",*add_flags]
            self._d(argv, timeout=30)
            info=self._inspect_cc(names["cc"])
            if info["network"]!="none" or info["privileged"].lower()=="true" or info["ports"] not in {"map[]","{}"}:
                raise RuntimeError(f"cc inspect rejected {info}")
            self._d(["start",names["cc"]], timeout=15)
            wait=await asyncio.to_thread(self._d, ["wait",names["cc"]], self.cfg.cc.timeout_seconds+5, False)
            raw_rc=(wait.stdout or "").strip()
            if wait.returncode!=0 or not raw_rc:
                self._d(["kill",names["cc"]], check=False)
                if cc_model:
                    try: _record_cc_provenance(job, cc_model, cc_endpoint, prompt, "", False, "TIMEOUT", error="timeout")
                    except Exception: pass
                return {"ok":False,"error":"Claude Code timeout","job_dir":str(jd),
                        "sandbox":"docker","container":names["cc"]}
            rc=int(raw_rc.splitlines()[-1])
            logs=self._d(["logs",names["cc"]], timeout=30, check=False)
            stdout=(logs.stdout or "")
            stderr=(logs.stderr or "")
            collected=True
            class _P:
                returncode=rc
                async def communicate(self):
                    return stdout.encode(), stderr.encode()
                def kill(self):
                    pass
            return await self._finish_proc(_P(),job,jd,prompt,cc_model,cc_endpoint,
                                           sandbox="docker",container=names["cc"])
        except Exception as e:
            return {"ok":False,"error":"BLOCKED_SANDBOX_MISSING","blocked":"sandbox_missing",
                    "detail":str(e)[:400],"job_dir":str(jd),"sandbox":"docker",
                    "container":names["cc"]}
        finally:
            try:
                self._cleanup_job(names, remove_volumes=collected)
            except Exception:
                pass

    def run_isolation_diag(self, targets: list[str], tag: str = "iso") -> dict:
        """Supervisor-owned probe: --network none, no cc tools, no Write/Edit."""
        names=self._names(f"iso-{tag}")
        broker_image=str(getattr(self.cfg.cc,"broker_image","") or "python:3.13-slim")
        sd=self._sandbox_dir()
        self._d(["rm","-f",names["cc"]], check=False)
        argv=["run","--rm","--name",names["cc"],
              "--network","none",
              "--user","1001:1001",
              "--read-only","--tmpfs","/tmp:rw,mode=1777",
              "--cap-drop","ALL","--security-opt","no-new-privileges",
              "--pids-limit","32","--memory","64m",
              "-v",f"{sd/'isolate_diag.py'}:/opt/grid/isolate_diag.py:ro",
              "-e",f"ISOLATE_TARGETS={','.join(targets)}",
              "--entrypoint","python3",
              broker_image,"/opt/grid/isolate_diag.py"]
        r=self._d(argv, timeout=30, check=False)
        return {"ok":r.returncode==0,"returncode":r.returncode,
                "stdout":r.stdout or "","stderr":r.stderr or "",
                "container":names["cc"]}

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
