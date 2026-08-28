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


class TokenRateLimiter:
    """Janela deslizante thread-safe para respeitar um orçamento de tokens/minuto (TPM).

    A Groq limita pelo tier gratuito principalmente por TPM, não por número de chamadas —
    um limitador baseado só em contagem de requisições deixa passar bursts que estouram o TPM.
    """

    def __init__(self, tpm_budget, period=60.0):
        self.tpm_budget = tpm_budget
        self.period = period
        self.usage = deque()  # cada item: [timestamp, tokens] (lista, para permitir correção por referência)
        self.lock = threading.Lock()

    def _prune(self, now):
        while self.usage and now - self.usage[0][0] > self.period:
            self.usage.popleft()

    def wait_for_capacity(self, estimated_tokens):
        """Bloqueia até haver orçamento de tokens disponível na janela e reserva `estimated_tokens`."""
        while True:
            with self.lock:
                now = time.monotonic()
                self._prune(now)
                used = sum(entry[1] for entry in self.usage)
                if used + estimated_tokens <= self.tpm_budget or not self.usage:
                    entry = [now, estimated_tokens]
                    self.usage.append(entry)
                    return entry
                sleep_for = self.period - (now - self.usage[0][0])
            time.sleep(max(sleep_for, 0.2))

    def record_actual(self, entry, actual_tokens):
        """Corrige a reserva estimada para o valor real de tokens consumidos, mantendo a contabilidade precisa."""
        with self.lock:
            entry[1] = actual_tokens


def estimate_tokens(system_prompt, user_content, num_items):
    # heurística ~4 chars/token para o prompt, mais uma folga para o JSON de resposta + reasoning (mesmo em "low").
    prompt_tokens = (len(system_prompt) + len(user_content)) // 4
    completion_estimate = 40 * max(num_items, 1)
    return prompt_tokens + completion_estimate


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
        'reasoning_effort': 'low',
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
        content = data['choices'][0]['message']['content']
        usage_tokens = (data.get('usage') or {}).get('total_tokens')
        return content, usage_tokens
    except (ValueError, KeyError, IndexError) as exc:
        raise ClassificationError(f'resposta inesperada da Groq: {exc}') from exc


def classify_batch(items, instruction_text, rate_limiter=None):
    """items: list de dicts {id, from, subject, date, snippet}. Retorna dict {id: category}."""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        instruction=instruction_text.strip() or '(nenhuma instrução definida — use bom senso)'
    )
    user_content = json.dumps(items, ensure_ascii=False)

    entry = None
    if rate_limiter is not None:
        estimated = estimate_tokens(system_prompt, user_content, len(items))
        entry = rate_limiter.wait_for_capacity(estimated)

    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_content},
    ]
    raw, usage_tokens = call_groq(messages)

    if rate_limiter is not None and entry is not None and usage_tokens:
        rate_limiter.record_actual(entry, usage_tokens)

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
