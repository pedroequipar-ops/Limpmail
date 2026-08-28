import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import client from '../api/client.js'

const STATUS_LABELS = {
  discovering: 'Descobrindo pastas',
  fetching: 'Buscando emails na caixa',
  classifying: 'Classificando com IA',
  reviewing: 'Pronto para revisão',
  applying: 'Aplicando movimentação',
  completed: 'Concluído',
}

export default function DashboardPage() {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState('')
  const intervalRef = useRef(null)

  async function fetchStatus() {
    try {
      const res = await client.get('/jobs/current')
      setStatus(res.data)
      if (!res.data) setCancelling(false)
    } catch (err) {
      setError(err.response?.data?.error || err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStatus()
    intervalRef.current = setInterval(fetchStatus, 2500)
    return () => clearInterval(intervalRef.current)
  }, [])

  async function handleStart() {
    setStarting(true)
    setError('')
    try {
      await client.post('/jobs')
      await fetchStatus()
    } catch (err) {
      setError(err.response?.data?.error || err.message)
    } finally {
      setStarting(false)
    }
  }

  async function handleResume() {
    if (!status?.job?.id) return
    setStarting(true)
    setError('')
    try {
      await client.post(`/jobs/${status.job.id}/resume`)
      await fetchStatus()
    } catch (err) {
      setError(err.response?.data?.error || err.message)
    } finally {
      setStarting(false)
    }
  }

  async function handleReset() {
    if (!status?.job?.id) return
    const confirmed = window.confirm(
      'Isso apaga todo o progresso desta classificação (emails já buscados e já classificados) e deixa pronto pra começar do zero. A conta e a instrução salvas não são afetadas. Confirmar?'
    )
    if (!confirmed) return

    setResetting(true)
    setError('')
    try {
      const res = await client.post(`/jobs/${status.job.id}/reset`)
      if (res.data.pending) {
        setCancelling(true)
      } else if (res.data.ok) {
        setStatus(null)
      } else {
        setError(res.data.error || 'Não foi possível zerar agora')
      }
    } catch (err) {
      setError(err.response?.data?.error || err.message)
    } finally {
      setResetting(false)
    }
  }

  if (loading) return <div className="hint">Carregando...</div>

  if (!status) {
    return (
      <div>
        <h1>Progresso</h1>
        <div className="card">
          <p className="hint">Nenhuma classificação iniciada ainda.</p>
          <button onClick={handleStart} disabled={starting}>
            {starting ? 'Iniciando...' : 'Iniciar classificação'}
          </button>
          {error && <div className="msg error">{error}</div>}
        </div>
      </div>
    )
  }

  const job = status.job
  const total = job.total_uids || 0
  const fetchedPct = total ? Math.min(100, (status.fetched / total) * 100) : 0
  const classifiedPct = status.fetched ? Math.min(100, (status.classify_done / status.fetched) * 100) : 0
  const isStuck = !status.running && job.status !== 'reviewing' && job.status !== 'completed'

  return (
    <div>
      <h1>Progresso</h1>

      <div className="card">
        <div className="toolbar">
          <div>
            <strong>{STATUS_LABELS[job.status] || job.status}</strong>
            {status.running && <span className="hint"> — rodando em background...</span>}
          </div>
          <div className="row" style={{ gap: 8 }}>
            {isStuck && (
              <button onClick={handleResume} disabled={starting}>
                {starting ? 'Retomando...' : 'Retomar de onde parou'}
              </button>
            )}
            <button className="danger" onClick={handleReset} disabled={resetting || cancelling}>
              {resetting ? 'Zerando...' : cancelling ? 'Cancelando...' : 'Zerar e recomeçar'}
            </button>
          </div>
        </div>

        {job.error_message && <div className="msg error">Erro: {job.error_message}</div>}
        {error && <div className="msg error">{error}</div>}
        {cancelling && <div className="hint">Cancelamento solicitado — aguarde, a tela atualiza sozinha assim que parar.</div>}

        <div style={{ marginBottom: 14 }}>
          <div className="hint" style={{ marginBottom: 4 }}>
            Busca na caixa: {status.fetched} / {total || '?'}
          </div>
          <div className="progress-bar">
            <div className="progress-bar-fill" style={{ width: `${fetchedPct}%` }} />
          </div>
        </div>

        <div>
          <div className="hint" style={{ marginBottom: 4 }}>
            Classificação: {status.classify_done} / {status.fetched} (pendentes: {status.classify_pending}, falhas: {status.classify_failed})
          </div>
          <div className="progress-bar">
            <div className="progress-bar-fill" style={{ width: `${classifiedPct}%` }} />
          </div>
        </div>
      </div>

      <div className="stats">
        <div className="stat">
          <div className="value">{status.counts.IMPORTANTE}</div>
          <div className="label">Importante</div>
        </div>
        <div className="stat">
          <div className="value">{status.counts.SPAM}</div>
          <div className="label">Spam</div>
        </div>
        <div className="stat">
          <div className="value">{status.counts.LIXEIRA}</div>
          <div className="label">Lixeira</div>
        </div>
      </div>

      {job.status === 'reviewing' || job.status === 'completed' ? (
        <div className="card">
          <p className="hint">Classificação concluída. Revise antes de aplicar.</p>
          <Link to="/revisao"><button>Ir para revisão</button></Link>
        </div>
      ) : null}
    </div>
  )
}
