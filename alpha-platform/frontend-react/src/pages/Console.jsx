import React, { useEffect, useState } from 'react'
import { useStream } from '../ws.js'

const RAIL = [['data_crypto', '加密'], ['data_equity', '美股'], ['watchlist', '名单'], ['factor', '因子'], ['grid_store', 'BFS'], ['worker', '循环']]
const fmt = (v, d = 2) => v == null ? '—' : Number(v).toFixed(d)
const pct = (v, d = 2) => v == null ? '—' : (v * 100).toFixed(d) + '%'
const age = s => s == null ? '' : s < 90 ? s + 's' : s < 5400 ? Math.round(s / 60) + 'm' : Math.round(s / 3600) + 'h'
const FKEYS = [['ret_5m', 'RET 5M'], ['rvol', 'RVOL'], ['ret_30m', 'RET 30M'], ['vol_1m', 'VOL 1M'], ['range_pos', 'RANGE']]
const AETHER_TRADING = 'http://127.0.0.1:8501/app/aether.html#trading'

const heat = (v, signed = true) => {
  if (v == null) return {}
  const a = Math.min(0.55, Math.abs(v) * (signed ? 55 : 1.4))
  const c = !signed ? `rgba(232,180,90,${a})` : v >= 0 ? `rgba(74,222,128,${a})` : `rgba(248,113,113,${a})`
  return { background: c }
}

function bfsHitCount(b, w) {
  return (b?.windows?.[w]?.rows || []).length
}

function statusLineForWindow(audit, b, w, decN) {
  const aw = audit?.windows?.[w] || {}
  if (aw.quarantine) {
    return `${w}: 本轮查证中 · 不作数 · scan #${aw.scan_event_id ?? '?'} → 详见决策面`
  }
  const cand = aw.candidates ?? bfsHitCount(b, w)
  const filt = aw.filtered || []
  const dec = w === 'AM' ? (aw.decisions ?? decN ?? 0) : (aw.decisions ?? 0)
  if (!cand && !filt.length) return null
  if (filt.length) {
    const reasons = [...new Set(filt.map(f => f.reason))].join(' · ')
    return `${w}: ${cand} 候选 · ${filt.length} 被滤除(${reasons}) · ${dec} 决策 → 详见决策面`
  }
  return `${w}: ${cand} 候选 · ${dec} 决策 → 详见决策面`
}

function DataAgeBadge({ meta, faceReadTs }) {
  if (!meta) return null
  const storeAge = meta.store_age_s
  const period = meta.heat_face_period_s || meta.face_period_s || meta.heat_refresh_s || meta.refresh_s || 60
  const level = meta.age_level || (storeAge != null && storeAge > period * 2 ? 'amber' : 'ok')
  const amber = level === 'amber'
  const readAgo = faceReadTs ? Math.max(0, Math.round(Date.now() / 1000 - faceReadTs)) : null
  return (
    <div className="dim" style={{
      fontSize: 11, marginBottom: 10, padding: '6px 10px',
      border: `1px solid ${amber ? 'rgba(232,180,90,.55)' : 'rgba(155,158,208,.25)'}`,
      borderRadius: 8,
      background: amber ? 'rgba(232,180,90,.08)' : 'transparent',
      color: amber ? '#E8B45A' : undefined,
    }} title="仪表宪法:来源+时间戳;超本面周期×2 琥珀">
      数据龄 · store写 {age(storeAge) || '—'} · 本面读 {readAgo != null ? readAgo + 's' : '—'}
      · 周期 {period}s{amber ? ' · 琥珀(>2×)' : ''}
    </div>
  )
}

export default function Console() {
  const snap = useStream()
  const [sortKey, setSortKey] = useState('ret_5m')
  const [faceReadTs, setFaceReadTs] = useState(null)
  useEffect(() => {
    if (snap) setFaceReadTs(Math.floor(Date.now() / 1000))
  }, [snap])
  if (!snap) return <div className="glass dim">连接流…</div>
  const h = snap.health.components, d = snap.decisions, p = snap.pulse, b = snap.bfs || d.bfs
  const audit = d.audit || {}
  const quarantine = d.quarantine || {}
  const wl = p.watchlist || []
  const meta = p.meta || {}
  const heatTickLeft = meta.heat_next_tick_in_s ?? meta.next_tick_in_s
  const scanTickLeft = meta.scan_next_tick_in_s
  const envN = wl.length
  const rank = sym => { const i = wl.indexOf(sym); return i >= 0 ? i : 9999 }
  const breadth = p.equity.length
    ? p.equity.filter(e => (e.factors?.ret_5m || 0) > 0).length + '/' + p.equity.length : '—'
  const amHits = bfsHitCount(b, 'AM')
  const pmHits = bfsHitCount(b, 'PM')
  const decN = d.rows.length
  const amLine = statusLineForWindow(audit, b, 'AM', decN)
  const pmLine = statusLineForWindow(audit, b, 'PM', 0)
  const headerContract = d.header_contract || {}
  const showIsoBadge = headerContract.am_isolation_badge || (quarantine.active && amHits > 0)
  const filteredRows = []
  for (const w of ['AM', 'PM']) {
    const aw = audit?.windows?.[w] || {}
    const eventId = aw.scan_event_id ?? b?.windows?.[w]?.event_id
    if (aw.filtered?.length) {
      for (const f of aw.filtered) {
        const row = (b?.windows?.[w]?.rows || []).find(r => (r.sym || r.symbol) === f.symbol) || {}
        filteredRows.push({ window: w, symbol: f.symbol, score: row.score, reason: f.reason, scan_id: eventId })
      }
    } else if (aw.quarantine || quarantine.active) {
      for (const row of (b?.windows?.[w]?.rows || [])) {
        filteredRows.push({
          window: w,
          symbol: row.sym || row.symbol,
          score: row.score,
          reason: 'missing bid/ask · quarantine',
          scan_id: eventId,
        })
      }
    }
  }
  const gateRank = e => {
    const g = e.factors?.rvol_gate
    if (g == null) return 1
    if (g >= 0.5) return 0
    if (g >= 0) return 2
    return 1
  }
  const equitySorted = sortKey === 'watchlist'
    ? [...p.equity].sort((a, b) => rank(a.symbol) - rank(b.symbol))
    : sortKey === 'ret_5m'
      ? [...p.equity].sort((a, b) => {
          const gr = gateRank(a) - gateRank(b)
          if (gr) return gr
          const av = a.factors?.ret_5m, bv = b.factors?.ret_5m
          if (av == null && bv == null) return rank(a.symbol) - rank(b.symbol)
          if (av == null) return 1
          if (bv == null) return -1
          return bv - av
        })
      : [...p.equity].sort((a, b) => ((b.factors?.[sortKey] ?? -1e9) - (a.factors?.[sortKey] ?? -1e9)))
  const scanCand = p.scan_candidates || []
  return (<>
    <DataAgeBadge meta={meta} faceReadTs={faceReadTs} />
    <div className="stats">
      <div className="stat"><span className="k">BFS AM</span><b>{amHits ? amHits + ' 命中' : '未扫'}{showIsoBadge ? <span className="badge-iso">隔离中</span> : null}</b></div>
      <div className="stat"><span className="k">BFS PM</span><b>{pmHits ? pmHits + ' 命中' : '未扫'}</b></div>
      <div className="stat"><span className="k">今日决策</span><b className="gold">{decN || (amHits + pmHits ? '0' : '—')}</b></div>
      <div className="stat"><span className="k">5M 宽度</span><b>{breadth}</b></div>
      <div className="stat"><span className="k">BTC</span><b className="num">${fmt(p.crypto.find(c => c.symbol.startsWith('BTC'))?.price, 0)}</b></div>
      <div className="stat"><span className="k">下轮热力</span><b className="num">{heatTickLeft != null ? `T-${heatTickLeft}s` : '—'}</b></div>
      <div className="stat"><span className="k">下轮扫描</span><b className="num">{scanTickLeft != null ? `T-${scanTickLeft}s` : '—'}</b></div>
    </div>
    <div className="glass rail">
      {RAIL.map(([k, label]) => {
        const c = h[k] || { status: 'skipped' }
        return <div key={k} className={'node ' + c.status}>
          <div className="k">{label}</div>
          <div><span className="dot" />{c.status} <span className="dim" style={{ fontSize: 10 }}>{age(c.age_s)}</span></div>
          {k === 'watchlist' && c.detail ? <div className="dim" style={{ fontSize: 9, marginTop: 4, lineHeight: 1.35 }}>{c.detail}</div> : null}
        </div>
      })}
    </div>
    <section>
      <h2>BFS 原始行 · 即时</h2>
      <div className="dim" style={{ fontSize: 11, lineHeight: 1.55, marginBottom: 8 }}>
        原始 scan 行即时显示(不经 worker tick)。决策/热力挂下轮 tick 倒计时。
        {heatTickLeft != null ? <span className="gold"> · 下轮热力 T-{heatTickLeft}s</span> : null}
        {scanTickLeft != null ? <span className="dim"> · 下轮扫描 T-{scanTickLeft}s</span> : null}
      </div>
      {quarantine.active ? (
        <div className="status-banner">{quarantine.banner || '本轮查证中 · 不作数'}</div>
      ) : null}
      <div className="dim" style={{ fontSize: 11, lineHeight: 1.55 }}>
        {amLine ? <div>{amLine}</div> : null}
        {pmLine ? <div>{pmLine}</div> : null}
        {!amLine && !pmLine ? <div>等待 BFS 窗口(09:45 / 15:35 ET)——信号只来自内核,不自造。</div> : null}
        <div style={{ marginTop: 6 }}>
          <a href={AETHER_TRADING} style={{ color: '#9AE6B4' }}>8501 · Aether TRADING 决策面</a>
          {scanTickLeft != null ? <span style={{ marginLeft: 8 }}>决策面 · 下轮扫描 T-{scanTickLeft}s</span> : null}
        </div>
      </div>
    </section>
    <details className="glass" style={{ marginBottom: 12, padding: '8px 12px' }}>
      <summary style={{ cursor: 'pointer', fontSize: 12 }}>机房 · 滤除明细</summary>
      {filteredRows.length ? (
        <table style={{ width: '100%', fontSize: 11, marginTop: 8 }}>
          <thead><tr><th>窗</th><th>标的</th><th>score</th><th>滤除原因</th><th>scan</th></tr></thead>
          <tbody>
            {filteredRows.map((r, i) => (
              <tr key={i}>
                <td>{r.window}</td>
                <td className="gold">{r.symbol}</td>
                <td className="num">{fmt(r.score, 1)}</td>
                <td>{r.reason}</td>
                <td className="dim">#{r.scan_id ?? '?'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="dim" style={{ fontSize: 11, marginTop: 8 }}>无滤除行（或本轮已隔离不作数）</div>
      )}
    </details>
    <section className="glass">
      <h2>因子热力 · RET 5M（quote 快照，近 300s）· 观察面 = env 9 + 席 8 · 量能门 RVOL≥1.5 · heat({envN})
        {heatTickLeft != null ? <span className="dim" style={{ fontWeight: 400, marginLeft: 8 }}>下轮热力 T-{heatTickLeft}s</span> : null}
      </h2>
      <div className="heat-scroll">
        <table><thead><tr><th onClick={() => setSortKey('watchlist')} style={{ cursor: 'pointer' }}
          className={sortKey === 'watchlist' ? 'gold' : ''}>标的{sortKey === 'watchlist' ? ' ▾' : ''}</th>
          <th>来源</th>
          <th>最新</th>{FKEYS.map(([k, l]) =>
          <th key={k} onClick={() => setSortKey(k)} style={{ cursor: 'pointer' }}
            className={sortKey === k ? 'gold' : ''}>{l}{sortKey === k ? ' ▾' : ''}</th>)}</tr></thead>
          <tbody>
            {equitySorted.map(e => <tr key={e.symbol} className={e.stale ? 'stale-row' : ''} title={e.stale ? (e.crosscheck?.detail || 'stale') : undefined}>
              <td className="gold" style={{ fontWeight: 600 }}>{e.symbol}{e.bfs ? <span className="chipCALL" style={{ marginLeft: 6, fontSize: 9 }}>BFS</span> : null}{e.stale ? <span style={{ marginLeft: 6, fontSize: 9, color: '#E8B45A' }}>STALE</span> : null}</td>
              <td className="dim" style={{ fontSize: 10 }}>{e.source || 'watchlist'}</td>
              <td className="num">${fmt(e.last)}</td>
              {FKEYS.map(([k]) => {
                const v = e.factors?.[k]; const signed = k !== 'range_pos' && k !== 'vol_1m'
                const fail = (e.factors?.rvol_gate != null && e.factors.rvol_gate >= 0 && e.factors.rvol_gate < 0.5)
                const gray = fail && (k === 'ret_5m' || k === 'rvol')
                const shown = k === 'rvol' ? fmt(v, 1) : (k.startsWith('ret') || k === 'vol_1m' ? pct(v) : fmt(v, 2))
                return <td key={k} className="num" style={{ ...heat(k === 'rvol' ? null : v, signed), opacity: gray ? 0.45 : undefined }}>{shown}</td>
              })}
            </tr>)}
            {p.crypto.map(t => <tr key={t.symbol}>
              <td className="gold" style={{ fontWeight: 600 }}>{t.symbol}</td>
              <td className="dim" style={{ fontSize: 10 }}>—</td>
              <td className="num">${fmt(t.price)}</td>
              <td colSpan="4" className="dim">bid {fmt(t.extra?.bid)} · ask {fmt(t.extra?.ask)} · vol {fmt(Number(t.extra?.volume), 0)}</td>
            </tr>)}
          </tbody></table>
      </div>
    </section>
    <details className="glass" style={{ marginTop: 12, padding: '8px 12px' }}>
      <summary style={{ cursor: 'pointer', fontSize: 12 }}>
        涨榜未进席({scanCand.length})
      </summary>
      {scanCand.length ? (
        <table style={{ width: '100%', fontSize: 11, marginTop: 8 }}>
          <thead><tr><th>标的</th><th>来源</th><th>score</th><th>last_on</th></tr></thead>
          <tbody>
            {scanCand.map((r, i) => (
              <tr key={i}>
                <td className="gold">{r.symbol}</td>
                <td>{r.label || r.source || 'movers'}</td>
                <td className="num">{fmt(r.score, 2)}</td>
                <td className="dim">{r.last_on || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="dim" style={{ fontSize: 11, marginTop: 8 }}>无超额扫描候选</div>
      )}
    </details>
  </>)
}
