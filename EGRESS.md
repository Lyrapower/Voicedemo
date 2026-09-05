# EGRESS.md · 出网登记表(bind-before-register 同款:未登记一律拒)

| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |
|---|---|---|---|---|---|---|---|
| efts.sec.gov | EDGAR 全文检索 | yes | none | 10 | attested | | research,rwa |
| data.sec.gov | EDGAR 提交 JSON(需 User-Agent 含邮箱:SEC_UA) | yes | SEC_UA | 10 | attested | | research,rwa |
| export.arxiv.org | arXiv API | yes | none | 20 | issuer_claim | | research |
| www.grants.gov | grants.gov 检索 | yes | none | 20 | attested | | scout |
| api.sam.gov | SAM.gov 机会 | yes | SAM_API_KEY | 10 | attested | | scout |
| api.github.com | GitHub API | yes | GITHUB_TOKEN | 30 | issuer_claim | | maintainer,research |

拍板列为空 = 未生效(fetch 一律拒)。Lyra 在拍板列填日期即生效。grade 按 rwa v7 阶梯;lanes 空 = 所有 lane。

