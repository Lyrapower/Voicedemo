import { useEffect, useRef, useState } from 'react'

export function apiPrefix() {
  return location.pathname.startsWith('/alpha') ? '/alpha' : ''
}

function useRemote() {
  return location.hostname.endsWith('.ts.net') || /iPhone|iPad/i.test(navigator.userAgent || '')
}

// 单一 ws,自动重连;snapshot 状态化,job_events 增量回调
// A3: poll 兜底不再只限 ts.net/手机——桌面 WS 断连时也会卡「连接流…」。
// 改为：WS 为主，watchdog 监控 lastMsg；WS 超过 5s 无消息则触发一次 poll 兜底。
export function useStream(onJobEvents) {
  const [snap, setSnap] = useState(null)
  const cb = useRef(onJobEvents)
  cb.current = onJobEvents
  const remote = useRemote()
  useEffect(() => {
    let ws, pollTimer, reconnectTimer, alive = true
    let lastMsg = Date.now()
    const apply = m => {
      setSnap(m)
      if (m.job_events?.length && cb.current) cb.current(m.job_events)
    }
    const poll = async () => {
      const p = apiPrefix()
      try {
        const [health, pulse, decisions, bfs] = await Promise.all([
          fetch(p + '/api/health').then(r => r.json()),
          fetch(p + '/api/pulse').then(r => r.json()),
          fetch(p + '/api/decisions').then(r => r.json()),
          fetch(p + '/api/bfs').then(r => r.json()),
        ])
        if (alive) apply({ type: 'snapshot', health, pulse, decisions, bfs, job_events: [] })
      } catch { /* next tick */ }
    }
    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss://' : 'ws://'
      ws = new WebSocket(proto + location.host + apiPrefix() + '/ws/stream')
      ws.onmessage = e => {
        lastMsg = Date.now()
        const m = JSON.parse(e.data)
        if (m.type === 'snapshot') apply(m)
        else if (m.type === 'error') apply({ type: 'snapshot', error: m.reason, health: {}, pulse: {}, decisions: [], bfs: {}, job_events: [] })
      }
      ws.onclose = () => { if (alive) reconnectTimer = setTimeout(connect, 2000) }
    }
    // ts.net / 手机：并行轮询（WS 经 Serve 易挂死）
    if (remote) {
      poll()
      pollTimer = setInterval(poll, 2000)
    } else {
      // A3: 桌面 watchdog——WS 健康 5s 内有消息则不轮询；断连/慢则 poll 兜底
      pollTimer = setInterval(() => {
        if (!alive) return
        if (Date.now() - lastMsg > 5000) poll()
      }, 2000)
    }
    connect()
    return () => {
      alive = false
      clearInterval(pollTimer)
      clearTimeout(reconnectTimer)
      ws && ws.close()
    }
  }, [remote])
  return snap
}
