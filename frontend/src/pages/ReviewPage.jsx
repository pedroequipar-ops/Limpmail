import { useEffect, useState } from 'react'
import client from '../api/client.js'
import CategoryBadge from '../components/CategoryBadge.jsx'

const CATEGORIES = ['IMPORTANTE', 'SPAN', 'LIXEIRA']

export default function ReviewPage() {
  const [jobId, setJobId] = useState(null)
  const [counts, setCounts] = useState(null)
  const [category, setCategory] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState({ results: [], total: 0, page_size: 100 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    client.get('/jobs/current').then((res) => {
      if (res.data?.job) {
        setJobId(res.data.job.id)
        setCounts(res.data.counts)
      }
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    if (!jobId) return
    loadEmails()
  }, [jobId, category, page])

  async function loadEmails() {
    setLoading(true)
    setError('')
    try {
      const params = { page }
      if (category) params.category = category
      const res = await client.get(`/jobs/${jobId}/emails`, { params })
      setData(res.data)
    } catch (err) {
      setError(err.response?.data?.error || err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleOverride(emailId, newCategory) {
    const value = newCategory === '' ? null : newCategory
    setData((d) => ({
      ...d,
      results: d.results.map((r) => (r.id === emailId ? { ...r, user_override: value, final_category: value || r.ai_category } : r)),
    }))
    try {
      await client.patch(`/emails/${emailId}`, { user_override: value })
    } catch (err) {
      setError(err.response?.data?.error || err.message)
    }
  }

  function changeCategory(cat) {
    setCategory(cat)
    setPage(1)
  }

  if (!jobId && !loading) {
    return (
      <div>
        <h1>Revisão</h1>
        <p className="hint">Nenhum job encontrado. Inicie a classificação na tela de Progresso.</p>
      </div>
    )
  }

  const totalPages = Math.max(1, Math.ceil((data.total || 0) / (data.page_size || 100)))

  return (
    <div>
      <h1>Revisão</h1>

      {counts && (
        <div className="stats">
          <div className="stat">
            <div className="value">{counts.IMPORTANTE}</div>
            <div className="label">Importante</div>
          </div>
          <div className="stat">
            <div className="value">{counts.SPAN}</div>
            <div className="label">Span</div>
          </div>
          <div className="stat">
            <div className="value">{counts.LIXEIRA}</div>
            <div className="label">Lixeira</div>
          </div>
        </div>
      )}

      <div className="toolbar">
        <div className="row" style={{ gap: 6 }}>
          <button className={category === '' ? '' : 'secondary'} onClick={() => changeCategory('')}>Todos</button>
          {CATEGORIES.map((c) => (
            <button key={c} className={category === c ? '' : 'secondary'} onClick={() => changeCategory(c)}>
              {c}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="msg error">{error}</div>}

      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>Remetente</th>
              <th>Assunto</th>
              <th>Trecho</th>
              <th>Data</th>
              <th>Categoria</th>
              <th>Sobrescrever</th>
            </tr>
          </thead>
          <tbody>
            {data.results.map((r) => (
              <tr key={r.id}>
                <td>{r.from_addr}</td>
                <td>{r.subject}</td>
                <td className="snippet">{r.snippet}</td>
                <td>{r.date}</td>
                <td><CategoryBadge category={r.final_category} /></td>
                <td>
                  <select value={r.user_override || ''} onChange={(e) => handleOverride(r.id, e.target.value)}>
                    <option value="">(manter IA: {r.ai_category || '—'})</option>
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
            {!loading && data.results.length === 0 && (
              <tr><td colSpan={6} className="hint">Nenhum email nesta categoria.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="pagination">
        <button className="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Anterior</button>
        <span>Página {page} de {totalPages} ({data.total} emails)</span>
        <button className="secondary" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Próxima</button>
      </div>
    </div>
  )
}
