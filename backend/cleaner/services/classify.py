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

Um item na resposta para cada email da lista recebida, na mesma ordem, usando o campo "id" fornecido em cada email."""

RESPONSE_SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'results': {
            'type': 'ARRAY',
            'items': {
                'type': 'OBJECT',
                'properties': {
                    'id': {'type': 'INTEGER'},
                    'category': {'type': 'STRING', 'enum': list(VALID_CATEGORIES)},
                },
                'required': ['id', 'category'],
            },
        },
    },
    'required': ['results'],
}


class ClassificationError(Exception):
    pass


class RateLimiter:
    """Janela deslizante thread-safe para limitar chamadas/minuto (rede de segurança, sem
    teto de quota real conhecido para a API do Gemini no momento)."""

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


def call_gemini(system_prompt, user_content):
    if not settings.GEMINI_API_KEY:
        raise ClassificationError('GEMINI_API_KEY não configurada (.env)')

    url = settings.GEMINI_API_URL.format(model=settings.GEMINI_MODEL)
    payload = {
        'system_instruction': {'parts': [{'text': system_prompt}]},
        'contents': [{'role': 'user', 'parts': [{'text': user_content}]}],
        'generationConfig': {
            'temperature': 0,
            'responseMimeType': 'application/json',
            'thinkingConfig': {'thinkingLevel': 'low'},
            'responseSchema': RESPONSE_SCHEMA,
        },
    }
    try:
        resp = requests.post(
            url,
            params={'key': settings.GEMINI_API_KEY},
            json=payload,
            timeout=30,
        )
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
        content = data['candidates'][0]['content']['parts'][0]['text']
        return content
    except (ValueError, KeyError, IndexError) as exc:
        raise ClassificationError(f'resposta inesperada do Gemini: {exc}') from exc


def classify_batch(items, instruction_text, rate_limiter=None):
    """items: list de dicts {id, from, subject, date, snippet}. Retorna dict {id: category}."""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        instruction=instruction_text.strip() or '(nenhuma instrução definida — use bom senso)'
    )
    user_content = json.dumps(items, ensure_ascii=False)

    if rate_limiter is not None:
        rate_limiter.acquire()

    raw = call_gemini(system_prompt, user_content)

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
