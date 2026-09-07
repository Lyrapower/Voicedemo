# Web Fetch v3 · 扩大覆盖

**状态：NOT YET ACCEPTED（公网/现场）；本地真实 HTTPS smoke / E2E 已通过。**

## 改了什么

| 范围 | v2 | v3 |
|---|---|---|
| 搜索 | DDG HTML 第一页 | 最多 5 页（默认 3），跟随返回的 next 参数；不足/失败尝试 DDG Lite |
| 多问题覆盖 | 每次一个 query | `search_many` 最多 8 个查询，交错合并、URL 去重 |
| 可扩展搜索源 | 单 DDG | 可配置 SearXNG JSON，启用后优先使用；仍通过 EGRESS |
| 正文类型 | UTF-8 + 正则剥标签 | HTML、JSON、XML/RSS/Atom、文本编码、gzip、文本型 PDF |
| 后续材料 | 只有正文 | HTML 的 title 和最多 100 个 HTTPS 链接；`fetch_many` 最多 50 URL、最多 8 并发 |
| 长正文 | 默认 6,000 字符 | 默认 12,000，保留 max_chars / 环境变量，显式截断 |
| 域名范围 | 精确域名或全网 `*` | 增加显式 `*.example.org` 子域规则；精确规则优先 |

v2 的搜索正则把 snippet 设为可选，实际经常在标题处就完成匹配；v3 改为 HTMLParser，支持属性换序、额外 class、嵌套标签及 Lite 的摘要单元格。

模板的开放网 lanes 补入 `scout`。**没有修改任何现场 EGRESS**，模板拍板列仍为空；已有 `*` 行是否获准、实际调用 lane 是否在其中，仍决定能否出网。具体域名的 lane 禁止不会掉到 `*` 重试。

## 怎么接

保留原文件备份，用包内 `web_fetch_v2.py` 替换原模块即可继续用原 import 名称。它与 `web_fetch_v3.py` 内容相同，都是单文件实现；不要再把老 v2 内容复制回来。`fetch` / `search` 的原参数继续可用。

```python
import web_fetch_v3 as web   # 或原 import web_fetch_v2

found = web.search_many(
    ["tokenized treasury issuer disclosure", "代币化国债 储备 披露"],
    "research", n=20, max_pages=3, egress_path="EGRESS.md",
)
receipts = web.fetch_many(
    [r["url"] for r in found["results"]],
    "research", workers=4, egress_path="EGRESS.md", max_chars=16000,
)

# 定向搜索：把域名限制加入查询；最终结果是否符合仍需核对。
results = web.search("tokenization", "research", domains=["sec.gov"], n=12)
```

SearXNG 可通过 `WEB_FETCH_SEARXNG_URL=https://your-public-search-host/search` 或 `searxng_url=` 配置。该实例须启用 JSON，并在你的 EGRESS 中获准；不随机挑公共实例、不自动安装服务。GET 参数为 `q`、`format=json`、`pageno`，对应 [SearXNG 官方 Search API](https://docs.searxng.org/dev/search_api.html)。未配置时仅使用 DDG HTML/Lite。

基础抓取/搜索只用 Python 标准库。PDF 可选依赖 `pypdf`；未装返回 `PDF_DEPENDENCY_MISSING`。测试额外需要 `cryptography`、`reportlab`、`pypdf`。

```bash
python web_fetch_v3.py selftest
# 在已有授权登记表和实际网络上复核；不改登记表。
python probe.py --egress /absolute/path/EGRESS.md --lane research
```

## 范围扩大时一并修的漏洞

- **DNS 重绑定**：验证所有解析地址，固定连接这些 IP；TLS/SNI 验证原域名。混有内网 IP 整次拒绝。禁代理环境自动接管连接。
- **统一网络路径**：search 和 fetch 共用鉴权、跳转检查、字节上限、限速、日志；搜索不再绕过这些步骤。
- **每跳重查**：限制三跳，每跳重新按登记表生成请求头；跨域不会带走上个域名的 token。
- **回执脱敏**：正文、标题、链接、请求 URL、跳转记录均处理已登记鉴权值，常见 key/token 查询字段隐藏。
- **正文边界**：压缩前/解压后均受 MAX_BYTES 限制；XML 禁 DTD/实体；PDF 子进程 8 秒上限，支持平台上施加 CPU/地址空间限制，最多 40 页。不执行 JavaScript。
- **旧旁路**：原 opener 测试注入保留并标记 `test_transport`；仅传 `_private_check=False` 不能关闭生产 DNS 检查。注入 opener 自行跟随跳转会被拒绝。该注入接口只供可信 Python 测试调用，不应从远端 tool 参数暴露。
- 日志落盘失败在回执显示 `audit_warning=tool_log_failed`，不再只静默吞掉。

## 实际验证

`runtime_tests.txt`：24 项运行测试通过。测试启动了真实本地 HTTPS server，真实 TLS 握手、证书主机名验证、GET、响应读取、跳转、解析、PDF 子进程和批量执行。仅 DNS 与 TCP 目的地在 fixture 中被替换，使“已验证公网地址”连接到本地服务；没有用假的 fetch 返回值代替主路径。

覆盖：搜索 next 翻页/摘要/挑战备用/聚合后抓取 E2E，PDF/JSON/RSS/编码/gzip，SSRF 地址与尾点域名、混合 DNS、禁止二次域名解析、证书不匹配、跨域 auth、超大响应/压缩炸弹/XML 实体、速率、失败脱敏、审计失败、未拍板模板与旧注入旁路。

`public_probe.json` / `network_diagnostics.json`：未注入网络的实际公网尝试。三个域名均报 `Temporary failure in name resolution`，因此**外部搜索页当前布局、公开 next 请求是否被接受、反爬状态、实际 SearXNG 实例与现场 harness 尚未验收**。测试页是合成 fixture，不标作抓回的现网页。

## 明确的剩余边界

- DDG HTML/Lite 共用一个搜索源；备用页不等于独立搜索证据。搜索页可能要求验证码，返回 `SEARCH_CHALLENGE` 并尝试备用，绝不绕过挑战。
- SearXNG 的覆盖取决于你实例启用的引擎。此公共网抓取器维持 HTTPS:443/公网约束，本地 HTTP SearXNG 应走独立内网工具；本包不为它开 SSRF 豁免。
- PDF 没有 OCR；扫描件返回 `PDF_OCR_REQUIRED`。JS 动态站、登录页和付费墙没有浏览器执行或会话能力。
- `grade` 是登记表的分级，回执增加 `grade_basis=egress_registration`；不是内容真伪验证。搜索结果恒 `unverified`，发现的链接没有预先验来源，抓取时才重新过表。
- 限速是单进程、每注册规则/目标域名的滚动分钟上限；不宣称跨进程共享配额。触发返回 `RATE_LIMITED`，不自动无限等待。
- 网络超时不保证 OS DNS 调用自身可被中断。PDF 解析在子进程里限时/限资源，非操作系统级完全隔离沙盒。
- 批量大小、页数、字符和字节上限用于控制一次工作量；增加结果数不保证引擎实际返回那么多。失败/不足都在 `attempts` 和 `PARTIAL` 中体现。
