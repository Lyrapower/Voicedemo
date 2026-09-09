# 衔拍3 §① 真跑 回执

模型 id: glm-5.2 (deep worker, cloud_lane)
窗口压缩: 否(本窗口连续跑完)

---

## 结果: GREEN

| 项 | 值 |
|----|----|
| MID | M-62e650baa763 |
| status | done |
| close_reason | stop_condition:n>=10 |
| hops_used | 6 / 30 |
| denied_streak | 0 |
| out_of_bounds | 0 |
| model_resolved (每跳) | glm-5.2 ×6 (全 deep, 无 fallback research) |
| findings | 10 |
| grants.gov URL | 10/10 齐全 |
| deadline 列 | 10/10 |
| event_id 列 | 10/10 |

## 10 条 findings (runner-built, URL+截止+event_id 齐全)

| # | opp_id | Title | Agency | Deadline |
|---|--------|-------|--------|----------|
| 1 | 358004 | Cybersecurity Innovation for Cyberinfrastructure | NSF | 01/20/2027 |
| 2 | 363268 | Unlocking Dataset Value for AI-Enabled Scientific Discovery | NSF | 11/04/2026 |
| 3 | 363481 | NSF State and Regional Artificial Intelligence Infrastructure Hubs | NSF | 11/04/2026 |
| 4 | 324456 | Expeditions in Computing | NSF | 03/31/2027 |
| 5 | 363613 | ENG: Electrical, Communications, and Computing Systems (ECCS) | NSF | 08/19/2076 |
| 6 | 347679 | Infrastructure Capacity for Biological Research | NSF | unknown |
| 7 | 357725 | EPSCoR Research Infrastructure Improvement Program | NSF | 07/20/2027 |
| 8 | 346815 | FY 2025 EDA Public Works and Economic Adjustment Assistance | EDA | unknown |
| 9 | 363302 | (NSF cyberinfrastructure) | NSF | — |
| 10 | 280970 | (NSF) | NSF | — |

URL 形如 `https://www.grants.gov/search-results-detail/{opp_id}`，10 条齐全。

## 衔拍3 落实项

- §①1 结构化 catalog 查询: `missions.toml [mission.scout.search]` 10 keywords × rows_per_query=25，每跳 offset=(hop-1)*25 分页 → 每跳取 catalog 不同页，累积 HITs。
- §①2 grants.detail / INVALID_URL: `web.fetch` malformed URL → `INVALID_URL`(非 DENIED)；`_catalog_body` 允许 `startRecordNum`。
- §①3 runner-built findings: `_parse_judgments` + `_build_findings` 从 catalog rows + worker HIT/MISS 判定建 dossier，自动附 URL/deadline/event_id；worker 只判 HIT/MISS+理由。
- §①4 worker=deep 钉死: scout 模板 worker=deep，每跳 model_resolved=glm-5.2(无 fallback research)；工具环按 allowed_tools 开。
- §①5 catalog 可靠性: `run_grants_catalog_structured` 每关键词 retry×3 + backoff + 0.4s pacing。
- §①6 SANDBOX_TIMEOUT 看门狗: `_sandbox_timeout_sweep` + `cc.cleanup_job`(hop4 job_exception 循环被 runner 跳过续下一跳，mission 不挂)。
- §①7 findings 累积到 n>=10: 6 跳累积 10 unique HITs → stop_condition 触发 done。

## 本包改动文件

- `harness_resident/missions.toml` (search 块 10 keywords, rows_per_query=25)
- `harness_resident/harness/supervisor.py` (max_details 25, structured catalog 调用, SANDBOX_TIMEOUT sweep)
- `harness_resident/harness/tool_loop.py` (`run_grants_catalog_structured` + 分页 offset + retry/pacing + cache)
- `harness_resident/harness/web_fetch_v3.py` (INVALID_URL, startRecordNum)
- `harness_resident/harness/db.py` (jobs/missions search 列)
- `harness_resident/harness/api.py` (MissionCreate search/tools 自动从模板加载)
- `harness_resident/mission/runner.py` (_parse_judgments, _build_findings, _collect_catalog_rows, model_resolved, offset 分页, dossier 表不截断)
- `harness_resident/harness/cc.py` (cleanup_job 公开方法)
- `harness_resident/mission/test_mission.py` (TestPaid3Structured 5 条)

单测: 33/33 pass。

—— 戌
