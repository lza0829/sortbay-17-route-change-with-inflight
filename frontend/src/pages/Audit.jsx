import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { useRefreshKey } from '../refresh'

export default function Audit() {
  const [rows, setRows] = useState([])
  const [receipts, setReceipts] = useState([])
  const [err, setErr] = useState('')
  const refreshKey = useRefreshKey()

  useEffect(() => {
    setErr('')
    Promise.all([api('/审计'), api('/改表回执')])
      .then(([a, r]) => { setRows(a); setReceipts(r) })
      .catch((e) => setErr(e.message))
  }, [refreshKey])

  return (
    <div className="panel">
      <h2>审计与改表回执</h2>
      {err && <div className="err">{err}</div>}
      <h3>改表回执（可重放）</h3>
      <table>
        <thead><tr><th>回执</th><th>目的地</th><th>旧口门</th><th>新口门</th><th>强制回流</th><th>时间</th></tr></thead>
        <tbody>
          {receipts.map((r) => (
            <tr key={r.id}>
              <td>#{r.id}</td><td>{r.dest_code}</td>
              <td>{r.payload?.old_chute?.code ?? '-'}</td>
              <td>{r.payload?.new_chute?.code ?? r.new_chute_id}</td>
              <td>{r.forced_count}</td>
              <td>{r.created_at}</td>
            </tr>
          ))}
          {receipts.length === 0 && <tr><td colSpan={6}>暂无</td></tr>}
        </tbody>
      </table>
      <h3>审计事件</h3>
      <table>
        <thead><tr><th>编号</th><th>类别</th><th>动作</th><th>备注</th><th>时间</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}><td>{r.id}</td><td>{r.kind}</td><td>{r.action}</td><td>{r.note}</td><td>{r.created_at}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
