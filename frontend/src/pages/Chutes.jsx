import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { bump, useRefreshKey } from '../refresh'

export default function Chutes() {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const refreshKey = useRefreshKey()
  const load = () => { setErr(''); api('/口门').then(setRows).catch((e) => setErr(e.message)) }
  useEffect(() => { load() }, [refreshKey])
  const toggle = async (id, 状态) => {
    try { await api(`/口门/${id}/开闭?状态=${encodeURIComponent(状态)}`, { method: 'POST' }); bump(); load() }
    catch (e) { setErr(e.message) }
  }
  return (
    <div className="panel">
      <h2>口门</h2>
      {err && <div className="err">{err}</div>}
      <table>
        <thead><tr><th>口门码</th><th>标题</th><th>状态</th><th>软容量</th><th>在口件数</th><th>操作</th></tr></thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td>{c.code}</td><td>{c.title}</td><td>{c.status}</td><td>{c.soft_cap}</td><td>{c.在口件数}</td>
              <td>
                <button type="button" onClick={() => toggle(c.id, '口门开')}>开</button>{' '}
                <button type="button" className="secondary" onClick={() => toggle(c.id, '口门闭')}>闭</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
