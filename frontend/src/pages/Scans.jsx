import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { bump, useRefreshKey } from '../refresh'

export default function Scans() {
  const [rows, setRows] = useState([])
  const [chutes, setChutes] = useState([])
  const [barcode, setBarcode] = useState('')
  const [dest, setDest] = useState('110')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const refreshKey = useRefreshKey()

  const load = async () => {
    setErr('')
    setRows(await api('/扫描'))
    setChutes(await api('/口门'))
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [refreshKey])

  const chuteCode = (id) => chutes.find((c) => c.id === id)?.code || (id || '-')

  const create = async () => {
    setErr(''); setMsg('')
    try {
      await api('/扫描', { method: 'POST', body: JSON.stringify({ 条码: barcode, 目的地码: dest }) })
      setMsg('过机装载成功'); setBarcode(''); bump(); load()
    } catch (e) { setErr(e.message) }
  }
  const routeOne = async (id) => {
    setErr(''); setMsg('')
    try {
      await api(`/扫描/${id}/路由`, { method: 'POST' })
      setMsg('路由成功'); bump(); load()
    } catch (e) { setErr(e.message) }
  }
  return (
    <div className="panel">
      <h2>过机扫描</h2>
      <div className="row">
        <label>条码<input value={barcode} onChange={(e) => setBarcode(e.target.value)} /></label>
        <label>目的地码<input value={dest} onChange={(e) => setDest(e.target.value)} /></label>
        <button type="button" onClick={create}>装载扫描</button>
      </div>
      {msg && <div className="msg">{msg}</div>}
      {err && <div className="err">{err}</div>}
      <table>
        <thead><tr><th>编号</th><th>条码</th><th>目的地</th><th>状态</th><th>口门</th><th>操作</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.id}</td><td>{r.barcode}</td><td>{r.dest_code}</td><td>{r.status}</td>
              <td>{r.chute_id ? chuteCode(r.chute_id) : '-'}</td>
              <td>{(r.status === '待路由' || r.status === '错分回流') && <button type="button" onClick={() => routeOne(r.id)}>路由</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
