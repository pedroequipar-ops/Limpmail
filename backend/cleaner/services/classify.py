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

SUGGEST_INSTRUCTION_PROMPT = """Você vai analisar uma amostra de emails reais retirados de vários pontos da caixa de \
entrada de um usuário (que acumula anos de emails) e propor uma instrução de classificação em português.

Essa instrução será usada por outra IA para classificar automaticamente TODOS os emails da caixa em três categorias:
IMPORTANTE (fica na caixa), SPAM (move pra pasta de spam) e LIXEIRA (move pra pasta de lixeira).

Analise os padrões reais que aparecem na amostra abaixo: tipos de remetentes recorrentes, domínios de newsletter ou \
propaganda, padrões de emails transacionais (pedidos, faturas, cobranças, prazos), sinais de spam ou phishing, etc.

Para cada padrão recorrente que você notar (um mesmo remetente ou tipo de assunto aparecendo várias vezes na amostra), julgue pela ótica de uma pessoa comum recebendo isso todo dia: é o tipo de coisa que ela quer continuar recebendo regularmente — comunicação de trabalho, cobrança, prazo, algo que ela decidiu assinar e ainda usa — ou é o tipo de coisa que, insistindo em chegar toda hora, se torna incômoda e indesejada — propaganda repetitiva, newsletter que ninguém abre, notificação automática sem utilidade prática? Use esse julgamento como critério central pra decidir se aquele padrão recorrente vira IMPORTANTE, SPAM ou LIXEIRA na instrução final, não só o conteúdo isolado de cada email.

Escreva uma instrução clara, específica e prática (não genérica) que sirva de guia prático para classificar email \
por email. A instrução deve:
- Definir critérios objetivos para cada categoria.
- Citar tipos concretos de remetente/assunto observados nesta amostra como exemplo, sem inventar dados que não \
apareceram.
- Ser escrita para orientar outra IA a decidir email por email — não é uma conversa com o usuário, é a instrução \
em si.

Responda SOMENTE com o texto da instrução (sem título, sem comentário sobre o que você fez, sem marcação markdown)."""


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


def call_gemini(system_prompt, user_content, response_schema=None, thinking_level='low', timeout=30):
    if not settings.GEMINI_API_KEY:
        raise ClassificationError('GEMINI_API_KEY não configurada (.env)')

    url = settings.GEMINI_API_URL.format(model=settings.GEMINI_MODEL)
    generation_config = {
        'temperature': 0,
        'thinkingConfig': {'thinkingLevel': thinking_level},
    }
    if response_schema is not None:
        generation_config['responseMimeType'] = 'application/json'
        generation_config['responseSchema'] = response_schema

    payload = {
        'system_instruction': {'parts': [{'text': system_prompt}]},
        'contents': [{'role': 'user', 'parts': [{'text': user_content}]}],
        'generationConfig': generation_config,
    }
    try:
        resp = requests.post(
            url,
            params={'key': settings.GEMINI_API_KEY},
            json=payload,
            timeout=timeout,
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

    raw = call_gemini(system_prompt, user_content, response_schema=RESPONSE_SCHEMA, thinking_level='low')

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


def suggest_instruction(sample_items):
    """sample_items: list de dicts {from, subject, date, snippet} amostrados da caixa real.
    Retorna o texto da instrução sugerida (string), sem salvar nada."""
    user_content = json.dumps(sample_items, ensure_ascii=False)
    text = call_gemini(SUGGEST_INSTRUCTION_PROMPT, user_content, response_schema=None, thinking_level='high', timeout=60)
    return text.strip()
