import { useEffect, useState } from 'react'
import client from '../api/client.js'

const PLACEHOLDER = `Ex.: Considere IMPORTANTE emails de bancos, órgãos governamentais, clientes e qualquer pessoa se dirigindo a mim diretamente. Considere SPAM propagandas, promoções e remetentes desconhecidos em massa. Considere LIXEIRA notificações automáticas antigas, confirmações de pedidos/entregas já concluídas e newsletters que não abro há anos.`

export default function InstructionPage() {
  const [text, setText] = useState('')
  const [draft, setDraft] = useState('')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState('')

  useEffect(() => {
    client.get('/instruction').then((res) => {
      setText(res.data.text || '')
      setDraft(res.data.text || '')
    })
  }, [])

  async function handleSave() {
    setSaving(true)
    setSavedMsg('')
    try {
      const res = await client.put('/instruction', { text: draft })
      setText(res.data.text)
      setEditing(false)
      setSavedMsg('Instrução salva.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h1>Instrução de classificação</h1>
      <p className="hint">
        Este texto é enviado à IA junto com cada lote de emails para decidir entre IMPORTANTE, SPAM e LIXEIRA.
        Seja específico sobre remetentes, assuntos ou padrões que você considera de cada categoria.
      </p>

      <div className="card">
        {editing ? (
          <>
            <div className="field">
              <textarea
                rows={10}
                value={draft}
                placeholder={PLACEHOLDER}
                onChange={(e) => setDraft(e.target.value)}
              />
            </div>
            <div className="row" style={{ gap: 8 }}>
              <button onClick={handleSave} disabled={saving}>
                {saving ? 'Salvando...' : 'Salvar'}
              </button>
              <button
                className="secondary"
                onClick={() => {
                  setDraft(text)
                  setEditing(false)
                }}
              >
                Cancelar
              </button>
            </div>
          </>
        ) : (
          <>
            <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0 }}>
              {text || <span className="hint">(nenhuma instrução definida ainda)</span>}
            </pre>
            <button style={{ marginTop: 12 }} onClick={() => setEditing(true)}>
              Editar
            </button>
          </>
        )}
        {savedMsg && !editing && <div className="msg ok">{savedMsg}</div>}
      </div>
    </div>
  )
}
