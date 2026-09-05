import React, { useCallback, useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import { useStream, apiPrefix } from '../ws.js'

const PALETTE = ['#E8B45A', '#4ADE80', '#7DD3FC', '#F87171', '#C4B5FD', '#F9A8D4']
const REPLAY_KINDS = new Set(['point', 'curve_done', 'symbol_skip', 'no_data', 'done', 'error'])
const REVIEW_KINDS = new Set(['review_start', 'metrics_done', 'grid_explain', 'proposal_ready', 'failed', 'fix_applied'])

function MetricTable({ metrics }) {
  if (!metrics || !Object.keys(metrics).length) return null
  const rows = Object.entries(metrics).filter(([k]) => !['computed_by', 'computed_at', 'data_window'].includes(k))
  return (
    <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', marginTop: 8 }}>
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <td style={{ color: '#8A94A6', padding: '4px 8px 4px 0' }}>{k}</td>
            <td className="num">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function Alpha() {
  const [idea, setIdea] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [drafts, setDrafts] = useState([])
  const [proposals, setProposals] = useState([])
  const [reviewJob, setReviewJob] = useState(null)
  const [replayJob, setReplayJob] = useState(null)
  const [replayBusy, setReplayBusy] = useState(false)
  const [replayErr, setReplayErr] = useState('')
  const reviewRef = useRef(null)
  const replayRef = useRef(null)
  const [log, setLog] = useState([])
  const [results, setResults] = useState({})
  const chartRef = useRef(null)
  const seriesRef = useRef({})
  const elRef = useRef(null)

  const refresh = useCallback(async () => {
    const [d, q] = await Promise.all([
      fetch(apiPrefix() + '/api/factory/drafts').then(r => r.json()),
      fetch(apiPrefix() + '/api/factory/queue').then(r => r.json()),
    ])
    setDrafts(d.drafts || [])
    setProposals(q.proposals || [])
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  useEffect(() => {
    const chart = createChart(elRef.current, {
      height: 240, layout: { background: { color: 'transparent' }, textColor: '#8A94A6',
        fontFamily: '"IBM Plex Mono", monospace', fontSize: 11 },
      grid: { vertLines: { color: 'rgba(30,38,52,.6)' }, horzLines: { color: 'rgba(30,38,52,.6)' } },
      rightPriceScale: { borderColor: '#1E2634' },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#1E2634' },
    })
    chartRef.current = chart
    const ro = new ResizeObserver(() => chart.applyOptions({ width: elRef.current.clientWidth }))
    ro.observe(elRef.current)
    return () => { ro.disconnect(); chart.remove() }
  }, [])

  useStream(events => {
    for (const e of events) {
      const isReplay = replayRef.current && e.job_id === replayRef.current
      const isReview = reviewRef.current && e.job_id === reviewRef.current
      if (!isReplay && !isReview) continue

      if (isReplay && e.kind === 'point') {
        const sym = e.payload.symbol
        if (!seriesRef.current[sym]) {
          const i = Object.keys(seriesRef.current).length
          seriesRef.current[sym] = chartRef.current.addLineSeries({
            color: PALETTE[i % PALETTE.length], lineWidth: 2, title: sym,
          })
        }
        seriesRef.current[sym].update({ time: e.payload.ts, value: e.payload.equity })
      }

      if (REPLAY_KINDS.has(e.kind) && isReplay) {
        setLog(l => [...l.slice(-24), e])
        if (e.kind === 'curve_done') setResults(r => ({ ...r, [e.payload.symbol]: e.payload.final_equity }))
        setReplayJob(j => ({ id: e.job_id, pct: e.pct }))
        if (['done', 'error', 'no_data'].includes(e.kind)) {
          setReplayBusy(false)
          replayRef.current = null
        }
      }

      if (REVIEW_KINDS.has(e.kind) && isReview) {
        setLog(l => [...l.slice(-24), e])
        setReviewJob(j => ({ id: e.job_id, pct: e.pct }))
        if (['proposal_ready', 'failed', 'fix_applied', 'error'].includes(e.kind)) {
          reviewRef.current = null
          void refresh()
        }
      }
    }
  })

  const propose = async () => {
    const text = idea.trim()
    if (!text || busy) return
    setBusy(true)
    setMsg('已提交 · Grid 分析中（约 1–3 分钟，槽满则秒退）…')
    try {
      const r = await fetch(apiPrefix() + '/api/factory/propose', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idea: text, budget_hint: 'std' }),
      })
      let d = {}
      try { d = await r.json() } catch { d = {} }
      if (!r.ok) {
        const detail = d.detail
        const err = typeof detail === 'string' ? detail
          : detail?.message || detail?.error || JSON.stringify(detail || d)
        if (r.status === 429 || String(err).includes('槽满'))
          throw new Error('8501 推理槽满 · 等 30s 再点')
        if (r.status === 502) {
          const hint = String(err || '')
          if (/signer key missing|GRID_FACTORY_SIGNER|cleanroom/i.test(hint))
            throw new Error('Grid factory 签链钥未挂载 · 检查 GRID_FACTORY_SIGNER_KEY / cleanroom')
          if (/ConnectError|ECONNREFUSED|unreachable|Name or service/i.test(hint))
            throw new Error('Grid factory 不可达 · 确认 8501 /factory/task 在跑')
          throw new Error(hint ? `Grid factory: ${hint}` : 'Grid factory 502')
        }
        throw new Error(err || `propose failed (${r.status})`)
      }
      const route = d.route || 'extended'
      setMsg(`提案 draft #${d.draft_id} · route ${route}`)
      setIdea('')
      await refresh()
    } catch (e) {
      setMsg(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  const review = async (draftId) => {
    const r = await fetch(apiPrefix() + `/api/factory/review/${draftId}`, { method: 'POST' })
    const d = await r.json()
    reviewRef.current = d.job_id
    setReviewJob({ id: d.job_id, pct: 0 })
    setLog([])
  }

  const decide = async (proposalId, decision) => {
    await fetch(apiPrefix() + '/api/factory/decide', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proposal_id: proposalId, decision }),
    })
    await refresh()
  }

  const pollReplay = async (jobId) => {
    for (let i = 0; i < 90; i++) {
      await new Promise(res => setTimeout(res, 2000))
      const r = await fetch(apiPrefix() + `/api/jobs/${jobId}`)
      if (!r.ok) continue
      const st = await r.json()
      if (!st.found) continue
      setReplayJob({ id: jobId, pct: st.pct || 0 })
      if (st.pct >= 100 || st.status === 'error') {
        setReplayBusy(false)
        replayRef.current = null
        return
      }
    }
    setReplayBusy(false)
    setReplayErr('回放超时 · 看事件流或重试')
  }

  const startReplay = async () => {
    if (replayBusy) return
    setReplayErr('')
    setReplayBusy(true)
    Object.values(seriesRef.current).forEach(s => chartRef.current.removeSeries(s))
    seriesRef.current = {}
    setLog([])
    setResults({})
    setReplayJob({ id: null, pct: 0 })
    try {
      const r = await fetch(apiPrefix() + '/api/jobs/factor_replay', { method: 'POST' })
      const d = await r.json()
      if (!r.ok || !d.job_id) throw new Error(d.detail || `replay failed (${r.status})`)
      replayRef.current = d.job_id
      setReplayJob({ id: d.job_id, pct: 0 })
      void pollReplay(d.job_id)
    } catch (e) {
      setReplayErr(String(e.message || e))
      setReplayBusy(false)
      replayRef.current = null
    }
  }

  return (<>
    <section className="glass">
      <h2>因子工坊 · Grid</h2>
      <p className="dim" style={{ fontSize: 12, lineHeight: 1.5 }}>
        提案/解读走 <code>8501/factory/task</code> · Router 调度 · IC/IR 由 worker 确定性计算
      </p>
      <textarea
        value={idea}
        onChange={e => setIdea(e.target.value)}
        placeholder="描述因子想法,例如:5分钟动量反转,universe=动态 watchlist…"
        rows={3}
        style={{ width: '100%', marginTop: 8, fontSize: 14 }}
      />
      <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <button onClick={propose} disabled={busy || !idea.trim()}>{busy ? '生成中…' : '生成因子'}</button>
        {msg && <span className="dim" style={{ fontSize: 12, color: /槽满|失败|不可达|签链|502|Grid factory/i.test(msg) ? '#F87171' : undefined }}>{msg}</span>}
      </div>
    </section>

    <section className="glass">
      <h2>草稿库</h2>
      {!drafts.length && <div className="dim">尚无 draft — 上方输入想法后点「生成因子」。</div>}
      {drafts.map(d => (
        <div key={d.id} className="evt" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 6 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span className="chip">{d.status}</span>
            <b>{d.name}</b>
            <span className="dim">#{d.id} · route {d.route || '—'}{d.test ? ' · test' : ''}</span>
            {(d.status === 'draft' || d.status === 'failed') &&
              <button style={{ marginLeft: 'auto' }} onClick={() => review(d.id)} disabled={reviewJob && reviewJob.pct < 100}>评审</button>}
          </div>
          {d.hypothesis && <div className="dim" style={{ fontSize: 12 }}>{d.hypothesis}</div>}
        </div>
      ))}
    </section>

    <section className="glass">
      <h2>审批队列 · 因子提案</h2>
      {!proposals.length && <div className="dim">评审通过后 proposal 出现在此。</div>}
      {proposals.map(p => (
        <div key={p.proposal_id} className="evt" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 8, borderLeft: '2px solid rgba(232,180,90,.4)', paddingLeft: 12 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <span className="chip">{p.card_type || 'factor'}</span>
            <span className="chip">{p.status}</span>
            <b>{p.name}</b>
          </div>
          <MetricTable metrics={p.metrics} />
          {p.grid_explain &&
            <details>
              <summary className="dim" style={{ cursor: 'pointer' }}>Grid 解读</summary>
              <div style={{ fontSize: 12, marginTop: 6, whiteSpace: 'pre-wrap' }}>{p.grid_explain}</div>
            </details>}
          {p.hypothesis &&
            <details>
              <summary className="dim" style={{ cursor: 'pointer' }}>展开依据 · 假设</summary>
              <div style={{ fontSize: 12, marginTop: 6 }}>{p.hypothesis}</div>
            </details>}
          {p.status === 'pending' &&
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={() => decide(p.proposal_id, 'approve')}>Approve</button>
              <button onClick={() => decide(p.proposal_id, 'reject')}>Reject</button>
            </div>}
        </div>
      ))}
    </section>

    <section className="glass">
      <h2>因子回放 · 动量 v0(管道验证)</h2>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', margin: '10px 0', flexWrap: 'wrap' }}>
        <button onClick={startReplay} disabled={replayBusy}>{replayBusy ? '回放中…' : '启动回放'}</button>
        <div className="bar rail-glow" style={{ flex: 1, minWidth: 120 }}><i style={{ width: (replayJob?.pct || 0) + '%' }} /></div>
        <span className="num gold">{replayJob ? (replayJob.pct >= 100 ? '100%' : replayJob.pct.toFixed(1) + '%') : '—'}</span>
      </div>
      {replayErr && <div className="dim" style={{ color: '#F87171', fontSize: 12, marginBottom: 8 }}>{replayErr}</div>}
      <div ref={elRef} />
    </section>

    <section className="glass">
      <h2>事件流</h2>
      {log.length ? log.map((e, i) => <div key={e.id || i} className="evt">
        <span className={'chip ' + e.kind}>{e.kind}</span>
        <span className="dim" style={{ fontSize: 11 }}>{JSON.stringify(e.payload).slice(0, 120)}</span>
      </div>) : <div className="dim">评审/回放事件在此出现。</div>}
    </section>
  </>)
}
