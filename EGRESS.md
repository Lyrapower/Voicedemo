# EGRESS.md · 出网登记表(bind-before-register 同款:未登记一律拒)

| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |
|---|---|---|---|---|---|---|---|
| efts.sec.gov | EDGAR 全文检索 | yes | none | 10 | attested | | research,rwa |
| data.sec.gov | EDGAR 提交 JSON(需 User-Agent 含邮箱:SEC_UA) | yes | SEC_UA | 10 | attested | | research,rwa |
| export.arxiv.org | arXiv API | yes | none | 20 | issuer_claim | | research |
| www.grants.gov | grants.gov 检索 | yes | none | 20 | attested | | scout |
| api.sam.gov | SAM.gov 机会 | yes | SAM_API_KEY | 10 | attested | | scout |
| api.github.com | GitHub API | yes | GITHUB_TOKEN | 30 | issuer_claim | | maintainer,research |
| *.alchemy.com | ETH JSON-RPC (third_party; cap witnesses_agree) | yes | ETH_RPC_URL | 30 | witnesses_agree | 2026-08-26 | rwa |
| *.quiknode.pro | ETH JSON-RPC 2 (third_party; cap witnesses_agree) | yes | ETH_RPC_URL_2 | 30 | witnesses_agree | 2026-08-26 | rwa |
| *.ankr.com | BSC JSON-RPC (third_party; cap witnesses_agree; second optional) | yes | BSC_RPC_URL | 30 | witnesses_agree | 2026-08-26 | rwa |

拍板列为空 = 未生效(fetch 一律拒)。Lyra 在拍板列填日期即生效。grade 按 rwa v7 阶梯;lanes 空 = 所有 lane。
RPC 三家为既有授权端点最小登记(RWA CHAIN CONNECT v1 · G6);reader 仍走 urllib eth_call,不新建 web.fetch。未列 vendor → 停。

