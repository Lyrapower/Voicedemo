"""
gateway_hook_hint_v1.py — 埋点建议(戌手工插入 local_gateway.py)

目标:route_log INSERT 时带 duration_ms + status_code

位置:local_gateway.py 里现有 route_log INSERT / UPDATE 的调用点。
      grep -n 'INSERT INTO route_log' local_gateway.py 定位。

模板(伪代码):

    import time

    async def dispatch_to_lane(lane, payload):
        t0 = time.monotonic_ns()
        status = None
        try:
            resp = await call_lane(lane, payload)
            status = getattr(resp, 'status_code', 200)
            return resp
        except asyncio.TimeoutError:
            status = -1
            raise
        except Exception:
            status = -2
            raise
        finally:
            duration_ms = (time.monotonic_ns() - t0) // 1_000_000
            # 已有 db.execute("INSERT INTO route_log ...") 的话,
            # 把 duration_ms + status_code 加到列表和 VALUES 里:
            #   INSERT INTO route_log (..., duration_ms, status_code)
            #   VALUES (..., ?, ?)
            log_route(..., duration_ms=duration_ms, status_code=status)

状态码约定:
    HTTP 2xx / 4xx / 5xx  = 数值(资源允许时透传上游 status)
    超时                  = -1
    其他异常              = -2

红线:
    - 埋点异常必须在 finally 里 swallow,不能反向影响主路径
    - 不改现有路由 / lane 调用逻辑,只在包裹层记指标
    - 不加新端口 / 依赖 / 出网

自检(埋点落地后立刻跑一次):
    在 :8501 打一次 GLM 调用(cloud_chat 或 expanded 都行),然后:
        sqlite3 gateway_log.db "
            SELECT ts, routed_to, duration_ms, status_code
            FROM route_log
            WHERE routed_to LIKE '%glm52%'
            ORDER BY ts DESC LIMIT 1;
        "
    期望:duration_ms 为正整数,status_code = 200。
    任一为 NULL = 埋点失败,不进 3 日采样,报回。
"""
