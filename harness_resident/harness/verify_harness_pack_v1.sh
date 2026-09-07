#!/usr/bin/env bash
# verify_harness_pack_v1.sh · harness 四件自证(2026-09-02,砥):GatewayClient v2 / 契约探针+tool_log+等级 / web.fetch / EGRESS 模板
set -u; cd "$(dirname "$0")"; OUT="VERIFY_HARNESS_PACK_$(date +%Y-%m-%d_%H%M).md"; FAIL=0
log(){ printf '%s\n' "$*" >> "$OUT"; }
run(){ local name=$1 exp=$2; shift 2; local o; o=$("$@" 2>&1); local rc=$?
  if [ "$rc" -eq "$exp" ]; then st=PASS; else st=FAIL; FAIL=1; fi
  echo "[$st] $name (exit=$rc)"; log "## [$st] $name"; log "cmd: $*"; log "exit=$rc expect=$exp"; log '```'; log "$o"; log '```'; log ""; }
: > "$OUT"; log "# harness 四件自证 · $(date '+%F %T %Z') · $(hostname) · $(python3 -V 2>&1)"; log ""
run "1 GatewayClient v2.1(11 条,stub 8501)"       0 python3 harness_gateway_client_v2_1.py selftest
run "2 契约:探针/tool_log/等级(13 条)"          0 python3 harness_contract_v1.py selftest
run "3 web.fetch v3 runtime (24 条)"           0 python3 -c "
import pathlib, shutil, subprocess, sys, tempfile
src=pathlib.Path('web_fetch_v3.py').resolve(); tes=pathlib.Path('test_web_fetch.py').resolve()
td=pathlib.Path(tempfile.mkdtemp()); shutil.copy(src, td/'web_fetch_v3.py'); shutil.copy(tes, td/'test_web_fetch.py')
raise SystemExit(subprocess.call([sys.executable, str(td/'web_fetch_v3.py'), 'selftest']))"
run "4 EGRESS.md 模板可解析且默认全未生效"        0 python3 -c "
import web_fetch_v3 as W, tempfile, os
p=os.path.join(tempfile.mkdtemp(),'EGRESS.md'); open(p,'w').write(W.EGRESS_TEMPLATE)
r=W.load_egress(p); rows=r.get('rows') or {}; print('生效行', len(rows), 'star', bool(r.get('star'))); assert len(rows)==0 and not r.get('star')"
if [ "$FAIL" -eq 0 ]; then echo "ALL PASS → $OUT"; log "# ALL PASS"; exit 0; else echo "FAIL → $OUT"; log "# FAIL"; exit 1; fi
