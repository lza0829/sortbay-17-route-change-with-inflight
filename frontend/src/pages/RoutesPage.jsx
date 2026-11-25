import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { bump, useRefreshKey } from '../refresh'

export default function RoutesPage() {
  const [rows, setRows] = useState([])
  const [chutes, setChutes] = useState([])
  const [dest, setDest] = useState('')
  const [chuteId, setChuteId] = useState('')
  const [impact, setImpact] = useState(null)
  const [result, setResult] = useState(null)
  const [err, setErr] = useState('')
  const refreshKey = useRefreshKey()

  const load = async () => {
    setRows(await api('/路由表'))
    const cs = await api('/口门')
    setChutes(cs)
    if (!chuteId && cs[0]) setChuteId(String(cs[0].id))
  }

  useEffect(() => {
    setErr('')
    load().catch((e) => setErr(e.message))
  }, [refreshKey])

  // 改表前预览：若现在改这个目的地，会强制回流哪些在途已路由件。
  const preview = async (code) => {
    setResult(null)
    if (!code) { setImpact(null); return }
    try { setImpact(await api(`/路由表/影响?目的地码=${encodeURIComponent(code)}`)) }
    catch (e) { setErr(e.message) }
  }

  const save = async () => {
    setErr(''); setResult(null)
    try {
      const r = await api('/路由表', {
        method: 'POST',
        body: JSON.stringify({ 目的地码: dest, 口门编号: Number(chuteId) }),
      })
      setResult(r)
      setDest(''); setImpact(null)
      bump()          // 触发总览/口门/封袋/扫描册/回流等页同刷
      load()
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className="panel">
      <h2>路由表</h2>
      {err && <div className="err">{err}</div>}
      <p className="muted">
        改表口径：有已路由未封袋件时，允许改表并在同一笔内把受影响件强制回流（可审计、可重放）；
        失败则整笔回滚，路由表与在途都不变。
      </p>
      <div className="row">
        <label>目的地码
          <input value={dest} onChange={(e) => { setDest(e.target.value); preview(e.target.value) }} />
        </label>
        <label>口门
          <select value={chuteId} onChange={(e) => setChuteId(e.target.value)}>
            {chutes.map((c) => <option key={c.id} value={c.id}>{c.code} {c.title}</option>)}
          </select>
        </label>
        <button type="button" onClick={save}>写入路由</button>
      </div>

      {impact && (
        <div className="panel" style={{ background: '#eef1f4', margin: '0.6rem 0' }}>
          <strong>改表影响预览</strong>
          <span className="muted"> · {impact.受影响件数} 件已路由未封袋将被强制回流</span>
          {impact.受影响件数 > 0 && (
            <table>
              <thead><tr><th>编号</th><th>条码</th><th>状态</th><th>当前口门</th></tr></thead>
              <tbody>
                {impact.受影响件.map((s) => (
                  <tr key={s.id}><td>{s.id}</td><td>{s.barcode}</td><td>{s.status}</td><td>{s.chute_id || '-'}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {result && (
        <div className={result.是否触发回流 ? 'msg' : 'muted'}>
          {result.是否触发回流
            ? `改表成功：已强制回流 ${result.强制回流件数} 件，回执 #${result.回执编号}`
            : '改表成功：无在途已路由件，未触发回流'}
        </div>
      )}

      <table>
        <thead><tr><th>目的地码</th><th>口门</th><th>备注</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}><td>{r.dest_code}</td><td>{r.口门码}</td><td>{r.note}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
