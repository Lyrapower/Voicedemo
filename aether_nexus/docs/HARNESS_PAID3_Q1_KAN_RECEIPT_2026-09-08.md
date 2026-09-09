# 衔拍3 §① 真跑 回执

模型 id: glm-5.2
窗口压缩: 否

---

## 结果: failed

| 项 | 值 |
|----|----|
| MID | M-ce9664e9e99a |
| status | failed |
| close_reason | INCOMPLETE |
| hops_used | 30 / 30 |
| model_resolved (每跳) | glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 · glm-5.2 |
| findings | 5 |
| grants.gov URL | 5/5 |
| deadline 列 | 5/5 |
| title 列 | 5/5 |
| event_id 列 | 5/5 |
| abandoned | 5 |

## findings (runner-built)

| # | opp_id | Title | Agency | Deadline | kind | eligibility | URL | event_id | Reason |
|---|--------|-------|--------|----------|------|-------------|-----|----------|--------|
| 1 | 358004 | Cybersecurity Innovation for Cyberinfrastructure | U.S. National Science Foundation | 01/20/2027 |  | unknown | https://www.grants.gov/search-results-detail/358004 | J-c48bbfbd3ba4 | mission goal "AI/data/energy/broadband cyberinfrastructure infrastructure" 与标题 "Cybersecurity Innovation for Cyberinfrastructure" 直接对应 cyberinfrastructure infrastructure；eligibility=unknown（待 runner 用 |
| 2 | 363268 | Unlocking Dataset Value for AI-Enabled Scientific Discovery (AI Datasets) | U.S. National Science Foundation | 11/04/2026 |  | unknown | https://www.grants.gov/search-results-detail/363268 | J-c48bbfbd3ba4 | mission goal 含 "AI/data"，标题 "Unlocking Dataset Value for AI-Enabled Scientific Discovery (AI Datasets)" 直接对应 AI/data；eligibility=unknown（待 runner 验证）。 |
| 3 | 363481 | U.S. National Science Foundation State and Regional Artificial Intelligence Infrastructure Hubs: | U.S. National Science Foundation | 11/04/2026 |  | unknown | https://www.grants.gov/search-results-detail/363481 | J-c48bbfbd3ba4 | mission goal 含 "AI ... infrastructure"，标题 "NSF State and Regional Artificial Intelligence Infrastructure Hubs" 直接对应 AI infrastructure；eligibility=unknown（待 runner 验证）。 |
| 4 | 362843 | Tribal Broadband Connectivity Program | DOC NIST ERA | 11/17/2026 |  | unknown | https://www.grants.gov/search-results-detail/362843 | J-afe52e74442a | mission goal "broadband cyberinfrastructure infrastructure" 与标题 "Tribal Broadband Connectivity Program" 直接对应 broadband infrastructure；eligibility=unknown（catalog 行未携带 eligibility 文本，待 runner 经 grants. |
| 5 | 357725 | EPSCoR Research Infrastructure Improvement Program: EPSCoR Collaborations for Optimizing Research Ecosystems | U.S. National Science Foundation | 07/20/2027 |  | unknown | https://www.grants.gov/search-results-detail/357725 | J-e6bedac55017 | 标题 "EPSCoR Research Infrastructure Improvement Program: EPSCoR Collaborations for Optimizing Research Ecosystems" 直接对应 mission goal "cyberinfrastructure infrastructure"；eligibility=unknown（catalog 行未携 |

## abandoned

| opp_id | reason | title | deadline | status |
|--------|--------|-------|----------|--------|
| 346815 | missing_field | FY 2025 EDA Public Works and Economic Adjustment Assistance Programs | unknown | posted |
| 363302 | deadline_lt_14d | Advancing Oil and Natural Gas Production and Delivery | 09/22/2026 | posted |
| 359648 | reason_not_citing | Resource-Related Research Projects for Development of Models and Related Materials for Studying Human Health and Diseases (R24 Clinical Trials Not Allowed) | 09/28/2028 | posted |
| 348923 | missing_field | Fiscal Year (FY) 2022-2026 Advanced Digital Construction Management Systems (ADCMS) | unknown | posted |
| 360651 | deadline_lt_14d | CHIPS Research and Development Office (CRDO) Broad Agency Announcement (BAA) | 09/15/2026 | posted |

---

## 勘说明（程序生成抬头，不手填）

本回执表头 findings/URL/deadline/title/event_id 均由 `render_findings_receipt()` 从 findings 行计数。
① 重跑 `M-ce9664e9e99a`：worker=deep 钉死，lineage 30 跳 model_resolved=glm-5.2。过滤后 n=5 < 10，30 跳满 → close_reason=INCOMPLETE，未放宽。

本跑 grants.detail 已调用，但当时解析读了 data 顶层而非 `data.synopsis.applicantTypes` / `responseDateStr`，故 eligibility 列仍为 catalog 的 unknown。解析已在同包补到 synopsis（单测 37/37 仍过）。未再重跑、不放宽 n。

单测处决案：
- (a) 缺 title → 不进 findings，lineage ABANDONED missing_field
- (b) 2076-08-19 → rolling 计入；2025-06-01 已过 → deadline_lt_14d 不计
- (c) eligibility 只含 Public and State controlled institutions of higher education → ineligible 不计

---

## 附：上一跑 M-62e650baa763 回评点名的 #6 #7 #9 #10

### worker HIT reason 原文

**#6 opp 347679** (hop2 J-f75cd8979331)
```
opp 347679: HIT — NSF "Infrastructure Capacity for Biological Research" directly funds biological-research infrastructure capacity, in-scope for data cyberinfrastructure.
```

**#7 opp 357725** (hop3 J-cadba173f481)
```
opp 357725: HIT — "EPSCoR Research Infrastructure Improvement Program: EPSCoR Collaborations for Optimizing Research Ecosystems"(25-523,NSF,deadline 07/20/2027)直接资助研究基础设施能力建设,落在 cyberinfrastructure / data infrastructure 范围内。
```

**#9 opp 363302** (hop3 J-cadba173f481)
```
opp 363302: HIT — "Advancing Oil and Natural Gas Production and Delivery"(DE-FOA-0003634,DOE,deadline 09/22/2026)属能源基础设施/能源数据基础设施范畴,在 mission 范围内。
```

**#10 opp 280970** (hop6 J-87b736bc5ada)
```
opp 280970: HIT — DOE Infrastructure Work Scope Development RFI is DOE energy-infrastructure scope, directly matching the energy-infrastructure mission lane.
```

### #9 #10 catalog row 原文（title 并非空）

上一跑回执表 #9 #10 title 显示空/"—"，是 DOSSIER.md `[:3000]` 截断，不是 catalog 缺 title。

**#9 363302** (J-cadba173f481 tool_search catalog_rows)
```
{"opportunity_id": "363302", "title": "Advancing Oil and Natural Gas Production and Delivery", "publisher": "National Energy Technology Laboratory", "deadline": "09/22/2026", "human_url": "", "status": "posted", "summary": "{'opportunityId': 363302, ...}"}
```
本跑同一 opp 以 deadline 09/22/2026（距 2026-09-08 < 14d）→ ABANDONED deadline_lt_14d。

**#10 280970** (J-87b736bc5ada tool_search catalog_rows)
```
{"opportunity_id": "280970", "title": "RFI - DOE Infrastructure Work Scope Development", "publisher": "Idaho Field Office", "deadline": "unknown", "human_url": "", "status": "posted", "summary": "{'opportunityId': 280970, ...}"}
```
title 有值；deadline=unknown。按本包规则应 ABANDONED missing_field，不进 findings。

—— 戌
