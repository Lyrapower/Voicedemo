# DEV.md · CONNECT 开发隧道登记（与 EGRESS 只读权限分离）
# 拍板列为空 = 未生效。缺域名时实现与夹具可继续，live install 标 BLOCKED_DEV_APPROVAL。
# 待批（本行未填拍板，不生效）：registry.npmjs.org:443 CONNECT lane=cc_dev
# 用途：一次性隔离项目 npm ci / build / test。不得由本任务包代签日期。

| host | port | protocol | 拍板 | lanes |
|---|---|---|---|---|
| registry.npmjs.org | 443 | CONNECT | | cc_dev |
