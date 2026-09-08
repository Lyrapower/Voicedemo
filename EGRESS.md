# EGRESS.md · 出网登记表(bind-before-register 同款:未登记一律拒)

| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |
|---|---|---|---|---|---|---|---|
| efts.sec.gov | EDGAR 全文检索 | yes | none | 10 | attested | 2026-09-07 | research,rwa,deep,full |
| data.sec.gov | EDGAR 提交 JSON(需 User-Agent 含邮箱:SEC_UA) | yes | SEC_UA | 10 | attested | 2026-09-07 | research,rwa,deep,full |
| export.arxiv.org | arXiv API | yes | none | 20 | issuer_claim | 2026-09-07 | research,deep,full |
| www.grants.gov | grants.gov 检索 | yes | none | 20 | attested | 2026-09-07 | scout |
| api.sam.gov | SAM.gov 机会 | yes | SAM_API_KEY | 10 | attested | 2026-09-07 | scout |
| api.github.com | GitHub API | yes | GITHUB_TOKEN | 30 | issuer_claim | 2026-09-07 | maintainer,research |
| api.grants.gov | grants.gov Search2 + fetchOpportunity JSON POST | yes | none | 20 | attested | 2026-09-08 | scout |
| * | 开放网研究读取 | yes | none | 30 | unverified | 2026-09-07 | research,deep,full,cc,scout |
| html.duckduckgo.com | 搜索 HTML | yes | none | 20 | unverified | 2026-09-07 | research,deep,full,cc,scout |
| lite.duckduckgo.com | 搜索备用 Lite | yes | none | 20 | unverified | 2026-09-07 | research,deep,full,cc,scout |
| *.alchemy.com | ETH JSON-RPC (third_party; cap witnesses_agree) | yes | ETH_RPC_URL | 30 | witnesses_agree | 2026-08-26 | rwa |
| *.quiknode.pro | ETH JSON-RPC 2 (third_party; cap witnesses_agree) | yes | ETH_RPC_URL_2 | 30 | witnesses_agree | 2026-08-26 | rwa |
| *.ankr.com | BSC JSON-RPC (third_party; cap witnesses_agree; second optional) | yes | BSC_RPC_URL | 30 | witnesses_agree | 2026-08-26 | rwa |

拍板列为空 = 未生效(fetch 一律拒)。Lyra 在拍板列填日期即生效。grade 按 rwa v7 阶梯;lanes 空 = 所有 lane。
开放网 `*` + DDG 两行：Lyra 2026-09-07 拍板（WEB_FETCH_V3）。精确域名优先；该行 lane 不含调用方则不掉到 `*`。
RPC 三家为既有授权端点最小登记(RWA CHAIN CONNECT v1 · G6);reader 仍走 urllib eth_call,不新建 web.fetch。未列 vendor → 停。

