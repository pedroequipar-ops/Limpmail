import json
import threading
import time
from collections import deque

import requests
from django.conf import settings

VALID_CATEGORIES = ('IMPORTANTE', 'SPAM', 'LIXEIRA')

SYSTEM_PROMPT_TEMPLATE = """Você é um classificador de emails. Use a instrução abaixo, definida pelo usuário, para decidir a categoria de cada email.

Instrução do usuário:
{instruction}

Categorias possíveis (use exatamente estas strings): IMPORTANTE, SPAM, LIXEIRA.
- IMPORTANTE: emails relevantes que devem permanecer intocados.
- SPAM: propaganda, phishing, golpes, emails não solicitados.
- LIXEIRA: emails que não são spam mas não têm mais utilidade (notificações antigas, confirmações expiradas, newsletters que o usuário não lê mais, etc.).

Responda SOMENTE com um JSON no formato exato:
{{"results": [{{"id": <int>, "category": "IMPORTANTE"}}, ...]}}

Um item para cada email da lista recebida, na mesma ordem, usando o campo "id" fornecido em cada email."""


class ClassificationError(Exception):
    pass


class RateLimiter:
    """Janela deslizante simples e thread-safe para limitar chamadas/minuto."""

    def __init__(self, max_calls, period=60.0):
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()
        self.lock = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0] > self.period:
                    self.calls.popleft()
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return
                sleep_for = self.period - (now - self.calls[0])
            time.sleep(max(sleep_for, 0.05))


def call_groq(messages):
    if not settings.GROQ_API_KEY:
        raise ClassificationError('GROQ_API_KEY não configurada (.env)')

    headers = {
        'Authorization': f'Bearer {settings.GROQ_API_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': settings.GROQ_MODEL,
        'messages': messages,
        'temperature': 0,
        'response_format': {'type': 'json_object'},
    }
    try:
        resp = requests.post(settings.GROQ_API_URL, headers=headers, json=payload, timeout=60)
    except requests.RequestException as exc:
        raise ClassificationError(f'network_error: {exc}') from exc

    if resp.status_code == 429:
        raise ClassificationError(f'rate_limited: {resp.text[:200]}')
    if resp.status_code >= 500:
        raise ClassificationError(f'server_error_{resp.status_code}: {resp.text[:200]}')
    if resp.status_code != 200:
        raise ClassificationError(f'http_{resp.status_code}: {resp.text[:200]}')

    try:
        data = resp.json()
        return data['choices'][0]['message']['content']
    except (ValueError, KeyError, IndexError) as exc:
        raise ClassificationError(f'resposta inesperada da Groq: {exc}') from exc


def classify_batch(items, instruction_text):
    """items: list de dicts {id, from, subject, date, snippet}. Retorna dict {id: category}."""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        instruction=instruction_text.strip() or '(nenhuma instrução definida — use bom senso)'
    )
    user_content = json.dumps(items, ensure_ascii=False)
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_content},
    ]
    raw = call_groq(messages)

    try:
        parsed = json.loads(raw)
        results = parsed['results']
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ClassificationError(f'invalid_json: {exc}') from exc

    out = {}
    for r in results:
        try:
            idx = int(r['id'])
            cat = str(r['category']).upper().strip()
        except (KeyError, ValueError, TypeError):
            continue
        if cat in VALID_CATEGORIES:
            out[idx] = cat
    return out
