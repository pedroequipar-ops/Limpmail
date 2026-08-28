import { useEffect, useRef, useState } from 'react'
import client from '../api/client.js'

export default function ApplyPage() {
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [counts, setCounts] = useState(null)
  const [applyInfo, setApplyInfo] = useState(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const intervalRef = useRef(null)

  useEffect(() => {
    client.get('/jobs/current').then((res) => {
      if (res.data?.job) {
        setJobId(res.data.job.id)
        setJobStatus(res.data.job.status)
        setCounts(res.data.counts)
      }
    })
  }, [])

  useEffect(() => {
    if (!jobId) return
    fetchApplyStatus()
    intervalRef.current = setInterval(fetchApplyStatus, 2500)
    return () => clearInterval(intervalRef.current)
  }, [jobId])

  async function fetchApplyStatus() {
    try {
      const res = await client.get(`/jobs/${jobId}/apply-status`)
      setApplyInfo(res.data)
    } catch (err) {
      setError(err.response?.data?.error || err.message)
    }
  }

  async function handleApply() {
    const toMove = (counts?.SPAN || 0) + (counts?.LIXEIRA || 0)
    const confirmed = window.confirm(
      `Isso vai mover ${toMove} emails (SPAN + LIXEIRA) de verdade na sua caixa. IMPORTANTE não é tocado. Confirmar?`
    )
    if (!confirmed) return

    setStarting(true)
    setError('')
    try {
      await client.post(`/jobs/${jobId}/apply`)
      await fetchApplyStatus()
    } catch (err) {
      setError(err.response?.data?.error || err.message)
    } finally {
      setStarting(false)
    }
  }

  if (!jobId) {
    return (
      <div>
        <h1>Aplicar</h1>
        <p className="hint">Nenhum job encontrado. Inicie a classificação na tela de Progresso.</p>
      </div>
    )
  }

  if (jobStatus !== 'reviewing' && jobStatus !== 'completed') {
    return (
      <div>
        <h1>Aplicar</h1>
        <p className="hint">A classificação ainda não terminou. Acompanhe em Progresso antes de aplicar.</p>
      </div>
    )
  }

  const running = applyInfo?.running
  const c = applyInfo?.counts

  return (
    <div>
      <h1>Aplicar movimentação</h1>
      <p className="hint">
        Move SPAN para a pasta de spam e LIXEIRA para a pasta de lixeira. IMPORTANTE nunca é tocado.
        A operação é idempotente: pode ser rodada de novo com segurança.
      </p>

      <div className="card">
        <div className="stats">
          <div className="stat">
            <div className="value">{counts?.SPAN ?? '—'}</div>
            <div className="label">A mover para Span</div>
          </div>
          <div className="stat">
            <div className="value">{counts?.LIXEIRA ?? '—'}</div>
            <div className="label">A mover para Lixeira</div>
          </div>
          <div className="stat">
            <div className="value">{counts?.IMPORTANTE ?? '—'}</div>
            <div className="label">Importante (intocado)</div>
          </div>
        </div>

        <button onClick={handleApply} disabled={starting || running}>
          {running ? 'Aplicando...' : starting ? 'Iniciando...' : 'Aplicar agora'}
        </button>
        {error && <div className="msg error">{error}</div>}
        {!error && applyInfo?.job?.error_message && (
          <div className="msg error">Falha na última tentativa: {applyInfo.job.error_message}</div>
        )}
      </div>

      {c && (
        <div className="card">
          <h1 style={{ fontSize: 15 }}>Progresso da aplicação</h1>
          <div className="stats">
            <div className="stat">
              <div className="value">{c.applied}</div>
              <div className="label">Aplicados / já movidos</div>
            </div>
            <div className="stat">
              <div className="value">{c.pending}</div>
              <div className="label">Pendentes</div>
            </div>
            <div className="stat">
              <div className="value">{c.failed}</div>
              <div className="label">Falhas</div>
            </div>
          </div>
          {applyInfo.job.status === 'completed' && c.pending === 0 && (
            <div className="msg ok">Aplicação concluída.</div>
          )}
        </div>
      )}
    </div>
  )
}
