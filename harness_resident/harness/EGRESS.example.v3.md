# EGRESS.md: approval cells intentionally empty; edit your existing registry explicitly.
| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |
|---|---|---|---|---|---|---|---|
| * | 开放网研究读取 | yes | none | 30 | unverified | | research,deep,full,cc,scout |
| html.duckduckgo.com | 搜索 HTML | yes | none | 20 | unverified | | research,deep,full,cc,scout |
| lite.duckduckgo.com | 搜索备用 Lite | yes | none | 20 | unverified | | research,deep,full,cc,scout |
| data.sec.gov | SEC JSON | yes | SEC_UA | 10 | attested | | research,rwa,deep,full |
| export.arxiv.org | arXiv feed | yes | none | 20 | issuer_claim | | research,deep,full |
# 可用 *.example.org 显式授权其子域；不包含 example.org 本身。
[deny]
