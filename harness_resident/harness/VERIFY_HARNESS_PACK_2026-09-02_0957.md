# harness 四件自证 · 2026-09-02 09:57:16 PDT · CiCideMacBook-Air.local · Python 3.13.12

## [PASS] 1 GatewayClient v2.1(11 条,stub 8501)
cmd: python3 harness_gateway_client_v2_1.py selftest
exit=0 expect=0
```
SELFTEST PASS 11/11(cloud 路 /task/cloud_chat · 本地 model id 走 /v1/chat/completions · demo/aster 拒 · sealed 默认 · extract_text · usage · 封读透传 · 非流式 · 400/403 抛错 · 空 content 不算通)
```

## [PASS] 2 契约:探针/tool_log/等级(13 条)
cmd: python3 harness_contract_v1.py selftest
exit=0 expect=0
```
SELFTEST PASS 13/13(等级只降不升 · 探针通/断/未起/超时并发 · lane 过滤 · 缓存 · 实况行 · 注册表派生 · tool_log · trace 列表 · mission 串)
```

## [PASS] 3 web.fetch + EGRESS 解析(13 条)
cmd: python3 web_fetch_v1.py selftest
exit=0 expect=0
```
SELFTEST PASS 13/13(登记表解析 · 去标签 · lane/未登记/无等级/未拍板/http 五种 DENIED · 截断 · 5xx · 鉴权缺/泄 · signal_filter · tool_log)
```

## [PASS] 4 EGRESS.md 模板可解析且默认全未生效
cmd: python3 -c 
import web_fetch_v1 as W, tempfile, os
p=os.path.join(tempfile.mkdtemp(),'EGRESS.md'); open(p,'w').write(W.EGRESS_TEMPLATE)
r=W.load_egress(p); print('生效行', len(r)); assert len(r)==0
exit=0 expect=0
```
生效行 0
```

# ALL PASS
