# Limpmail

Sistema local de limpeza em massa de email. Roda só em `localhost`, sem deploy, sem exposição externa. Conecta numa caixa IMAP de domínio próprio, classifica os emails em IMPORTANTE / SPAM / LIXEIRA via Groq, permite revisão visual, e só então move de fato (IMPORTANTE nunca é tocado).

## Stack

- Backend: Django + Django REST Framework, SQLite.
- Frontend: React 18 + Vite, axios, react-router-dom.
- IMAP: `imaplib` (biblioteca padrão do Python).
- IA: Groq, via `requests` cru (sem SDK).

## Setup

### Backend

```
cd backend
venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Edite `backend/.env` e preencha `GROQ_API_KEY` (as demais variáveis já têm defaults razoáveis).

```
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py runserver 127.0.0.1:8001
```

> Porta 8001 (não 8000) porque esta máquina já tinha outro projeto Django local ocupando a 8000.

### Frontend

```
cd frontend
npm install
npm run dev
```

Abre em `http://localhost:5180` (porta 5180 pelo mesmo motivo acima — 5173/5174 já estavam ocupadas por outro projeto local).

## Uso

1. **Conectar**: host/porta/email/senha da conta IMAP, "Testar conexão", conferir/ajustar as pastas de Spam e Lixeira detectadas, salvar.
2. **Instrução**: definir em linguagem natural o que considerar IMPORTANTE, SPAM ou LIXEIRA.
3. **Progresso**: "Iniciar classificação" — roda em background (fetch em lotes de 500 + classificação em lotes de 25 via Groq, respeitando rate limit). Se a página for fechada e reaberta com um job incompleto, aparece "Retomar de onde parou".
4. **Revisão**: tabela estilo inbox com filtro por categoria e opção de sobrescrever a decisão da IA por email.
5. **Aplicar**: só move de fato depois de confirmação explícita. Relocaliza cada email pelo `Message-ID` antes de mover (cobre o caso de UIDVALIDITY ter mudado) e é idempotente — pode ser rodado de novo com segurança.

## Notas de segurança

- Uso estritamente local / single-user. A senha IMAP é salva em texto puro no SQLite local (`backend/db.sqlite3`) — não versionado, não exposto pela rede.
- `GROQ_API_KEY` fica em `backend/.env`, também não versionado.
