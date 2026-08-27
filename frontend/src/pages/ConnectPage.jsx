import { useEffect, useState } from 'react'
import client from '../api/client.js'

const DEFAULT_FORM = { host: '', port: 993, email: '', password: '' }

const PROVIDERS = {
  custom: {
    label: 'Domínio próprio',
    host: '',
    port: 993,
    emailPlaceholder: 'voce@seudominio.com',
    hint: 'Host e porta IMAP fornecidos pela sua hospedagem (cPanel, Zimbra, etc.).',
  },
  gmail: {
    label: 'Gmail',
    host: 'imap.gmail.com',
    port: 993,
    emailPlaceholder: 'voce@gmail.com',
    hint:
      'Use uma senha de app do Google, não a senha normal da conta — o Gmail não aceita mais senha comum em IMAP. ' +
      'Gere uma em myaccount.google.com → Segurança → Senhas de app (exige verificação em duas etapas ativada).',
  },
  outlook: {
    label: 'Outlook',
    host: 'outlook.office365.com',
    port: 993,
    emailPlaceholder: 'voce@outlook.com',
    hint:
      'Use uma senha de app da Microsoft, se sua conta tiver verificação em duas etapas ativada. ' +
      'Contas corporativas (Microsoft 365) podem ter a autenticação básica por IMAP desativada pelo administrador — ' +
      'nesse caso a conexão vai falhar mesmo com a senha correta.',
  },
}

export default function ConnectPage() {
  const [provider, setProvider] = useState('custom')
  const [form, setForm] = useState(DEFAULT_FORM)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [spamFolder, setSpamFolder] = useState('')
  const [trashFolder, setTrashFolder] = useState('')
  const [allFolders, setAllFolders] = useState([])
  const [error, setError] = useState('')
  const [savedMsg, setSavedMsg] = useState('')
  const [existingAccount, setExistingAccount] = useState(null)

  useEffect(() => {
    client.get('/account').then((res) => {
      if (res.data) {
        setExistingAccount(res.data)
        setProvider(res.data.provider || 'custom')
        setForm((f) => ({ ...f, host: res.data.host, port: res.data.port, email: res.data.email }))
        setSpamFolder(res.data.spam_folder || '')
        setTrashFolder(res.data.trash_folder || '')
      }
    })
  }, [])

  function updateField(field, value) {
    setForm((f) => ({ ...f, [field]: value }))
  }

  function selectProvider(key) {
    setProvider(key)
    const preset = PROVIDERS[key]
    if (key !== 'custom') {
      setForm((f) => ({ ...f, host: preset.host, port: preset.port }))
    }
  }

  async function handleTestConnection() {
    setError('')
    setSavedMsg('')
    setTestResult(null)
    setTesting(true)
    try {
      const res = await client.post('/account/test-connection', form)
      if (res.data.ok) {
        setTestResult(res.data)
        setSpamFolder(res.data.spam_folder || '')
        setTrashFolder(res.data.trash_folder || '')
        setAllFolders(res.data.all_folders || [])
      } else {
        setError(res.data.error || 'Falha ao conectar')
      }
    } catch (err) {
      setError(err.response?.data?.error || err.message)
    } finally {
      setTesting(false)
    }
  }

  async function handleSave() {
    setError('')
    setSavedMsg('')
    setSaving(true)
    try {
      const payload = { ...form, provider, spam_folder: spamFolder, trash_folder: trashFolder }
      if (existingAccount && !form.password) {
        delete payload.password
      }
      const res = await client.post('/account', payload)
      setExistingAccount(res.data)
      setSavedMsg('Conta salva com sucesso.')
    } catch (err) {
      setError(err.response?.data?.error || err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h1>Conectar à caixa de email</h1>

      {existingAccount && (
        <div className="card">
          <p className="hint">
            Conta já configurada: <strong>{existingAccount.email}</strong> ({PROVIDERS[existingAccount.provider || 'custom'].label},{' '}
            {existingAccount.host}:{existingAccount.port}).
            Pasta de spam: <strong>{existingAccount.spam_folder || '(não definida)'}</strong>, pasta de lixeira:{' '}
            <strong>{existingAccount.trash_folder || '(não definida)'}</strong>.
          </p>
        </div>
      )}

      <div className="card">
        <div className="field">
          <label>Provedor</label>
          <div className="row" style={{ gap: 6 }}>
            {Object.entries(PROVIDERS).map(([key, p]) => (
              <button
                key={key}
                className={provider === key ? '' : 'secondary'}
                onClick={() => selectProvider(key)}
                type="button"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {provider !== 'custom' && (
          <p className="hint">{PROVIDERS[provider].hint}</p>
        )}

        {provider === 'custom' ? (
          <div className="row">
            <div className="field">
              <label>Host IMAP</label>
              <input value={form.host} onChange={(e) => updateField('host', e.target.value)} placeholder="mail.seudominio.com" />
            </div>
            <div className="field" style={{ maxWidth: 120 }}>
              <label>Porta</label>
              <input type="number" value={form.port} onChange={(e) => updateField('port', Number(e.target.value))} />
            </div>
          </div>
        ) : (
          <p className="hint">Host: <strong>{form.host}</strong>:<strong>{form.port}</strong></p>
        )}

        <div className="row">
          <div className="field">
            <label>Email</label>
            <input value={form.email} onChange={(e) => updateField('email', e.target.value)} placeholder={PROVIDERS[provider].emailPlaceholder} />
          </div>
          <div className="field">
            <label>{provider === 'custom' ? 'Senha' : 'Senha de app'}</label>
            <input
              type="password"
              value={form.password}
              onChange={(e) => updateField('password', e.target.value)}
              placeholder={existingAccount ? '(deixe em branco para manter a atual)' : ''}
            />
          </div>
        </div>

        <button onClick={handleTestConnection} disabled={testing}>
          {testing ? 'Testando...' : 'Testar conexão'}
        </button>

        {error && <div className="msg error">{error}</div>}
        {testResult && (
          <div className="msg ok">
            Conexão OK. {allFolders.length} pastas encontradas.
          </div>
        )}
      </div>

      {(testResult || existingAccount) && (
        <div className="card">
          <h1 style={{ fontSize: 15 }}>Pastas de destino</h1>
          <p className="hint">
            Detectadas automaticamente via SPECIAL-USE ou nomes comuns. Ajuste se necessário antes de salvar.
          </p>
          <div className="row">
            <div className="field">
              <label>Pasta de Spam</label>
              {allFolders.length > 0 ? (
                <select value={spamFolder} onChange={(e) => setSpamFolder(e.target.value)}>
                  <option value="">(selecione)</option>
                  {allFolders.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              ) : (
                <input value={spamFolder} onChange={(e) => setSpamFolder(e.target.value)} />
              )}
            </div>
            <div className="field">
              <label>Pasta de Lixeira</label>
              {allFolders.length > 0 ? (
                <select value={trashFolder} onChange={(e) => setTrashFolder(e.target.value)}>
                  <option value="">(selecione)</option>
                  {allFolders.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              ) : (
                <input value={trashFolder} onChange={(e) => setTrashFolder(e.target.value)} />
              )}
            </div>
          </div>

          <button onClick={handleSave} disabled={saving}>
            {saving ? 'Salvando...' : 'Salvar e continuar'}
          </button>
          {savedMsg && <div className="msg ok">{savedMsg}</div>}
        </div>
      )}
    </div>
  )
}
