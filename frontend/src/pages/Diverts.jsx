import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { bump, useRefreshKey } from '../refresh'

export default function Diverts() {
  const [batches, setBatches] = useState([])
  const [scans, setScans] = useState([])
  const [scanId, setScanId] = useState('')
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const refreshKey = useRefreshKey()

  const load = async () => {
    setErr('')
    setBatches(await api('/回流批次'))
    const s = await api('/扫描')
    setScans(s.filter((x) => x.status === '已路由' || x.status === '已入袋'))
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [refreshKey])

  const create = async () => {
    setErr(''); setMsg('')
    try {
      await api('/回流批次', { method: 'POST', body: JSON.stringify({ 扫描编号: Number(scanId) }) })
      setMsg('已建回流批次'); bump(); load()
    } catch (e) { setErr(e.message) }
  }
  return (
    <div className="panel">
      <h2>错分回流</h2>
      {msg && <div className="msg">{msg}</div>}
      {err && <div className="err">{err}</div>}
      <p className="muted">改表强制回流会在此生成“改表回流-…”批次；批次与回执可在审计页追溯。</p>
      <div className="row">
        <label>扫描
          <select value={scanId} onChange={(e) => setScanId(e.target.value)}>
            <option value="">选择</option>
            {scans.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.barcode} · {s.status}</option>)}
          </select>
        </label>
        <button type="button" onClick={create}>建回流批次</button>
      </div>
      <table>
        <thead><tr><th>编号</th><th>批次码</th><th>状态</th><th>时间</th></tr></thead>
        <tbody>
          {batches.map((b) => (
            <tr key={b.id}><td>{b.id}</td><td>{b.code}</td><td>{b.status}</td><td>{b.created_at}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
