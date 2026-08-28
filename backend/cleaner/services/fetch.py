import quopri
import re
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser

from .imap_pool import ImapConnectionError

_STYLE_SCRIPT_RE = re.compile(r'<(style|script)[^>]*>.*?</\1>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')

UID_RE = re.compile(rb'UID (\d+)')


def sample_evenly(seq, n):
    """Amostra ate n itens espalhados uniformemente por toda a sequencia (nao so o inicio/fim) —
    util para pegar uma visao representativa de uma caixa que acumula varios anos de email."""
    if len(seq) <= n:
        return list(seq)
    step = len(seq) / n
    return [seq[int(i * step)] for i in range(n)]


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def search_all_uids(conn):
    typ, data = conn.uid('search', None, 'ALL')
    if typ != 'OK':
        raise ImapConnectionError('Falha ao buscar UIDs (SEARCH)')
    if not data or not data[0]:
        return []
    return [int(x) for x in data[0].split()]


def parse_uid_literal_pairs(data):
    """Extrai pares {uid: literal_bytes} de uma resposta UID FETCH com um único item de literal por mensagem."""
    pairs = {}
    for item in data:
        if isinstance(item, tuple) and len(item) == 2:
            meta, literal = item
            match = UID_RE.search(meta)
            if match:
                pairs[int(match.group(1))] = literal or b''
    return pairs


def fetch_batch_headers(conn, uids_batch):
    uid_set = ','.join(str(u) for u in uids_batch)
    typ, data = conn.uid('fetch', uid_set, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])')
    if typ != 'OK':
        raise ImapConnectionError('Falha no FETCH de headers')
    return parse_uid_literal_pairs(data)


def fetch_batch_snippets(conn, uids_batch, snippet_bytes=500):
    uid_set = ','.join(str(u) for u in uids_batch)
    typ, data = conn.uid('fetch', uid_set, f'(BODY.PEEK[TEXT]<0.{snippet_bytes}>)')
    if typ != 'OK':
        raise ImapConnectionError('Falha no FETCH de corpo')
    return parse_uid_literal_pairs(data)


def fetch_batch_message_ids(conn, uids_batch):
    uid_set = ','.join(str(u) for u in uids_batch)
    typ, data = conn.uid('fetch', uid_set, '(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])')
    if typ != 'OK':
        raise ImapConnectionError('Falha no FETCH de Message-ID')
    return parse_uid_literal_pairs(data)


def _decode_mime_words(value):
    if not value:
        return ''
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def parse_headers(raw: bytes):
    msg = BytesHeaderParser().parsebytes(raw)
    return {
        'from_addr': _decode_mime_words(msg.get('From', '')),
        'subject': _decode_mime_words(msg.get('Subject', '')),
        'date': msg.get('Date', '') or '',
        'message_id': (msg.get('Message-ID', '') or '').strip(),
    }


def extract_message_id(raw: bytes) -> str:
    msg = BytesHeaderParser().parsebytes(raw)
    return (msg.get('Message-ID', '') or '').strip()


def sender_label(from_addr):
    """Extrai um rotulo legivel do remetente pra agrupar (resumo, historico de reputacao):
    o nome de exibicao ("SHEIN" <shein@edm.shein.com> -> "SHEIN"), ou o dominio do email como
    fallback -- assim remetentes com varios subdominios de disparo (edm.shein.com,
    market.sheinmail.com) ainda agrupam sob o mesmo nome reconhecivel."""
    match = re.match(r'^"?([^"<]+?)"?\s*<', from_addr or '')
    if match and match.group(1).strip():
        return match.group(1).strip()
    match2 = re.search(r'@([\w.-]+)', from_addr or '')
    if match2:
        return match2.group(1)
    return (from_addr or '(desconhecido)')[:40]


def _cut_unclosed_style_script(text):
    # o fetch e truncado em N bytes; se um bloco <style>/<script> abrir sem fechar dentro da
    # janela, tudo dali pra frente e ruido (CSS/JS cru) — corta a partir da tag aberta.
    lowered = text.lower()
    for tag in ('style', 'script'):
        idx = lowered.rfind(f'<{tag}')
        if idx != -1 and f'</{tag}>' not in lowered[idx:]:
            text = text[:idx]
            lowered = lowered[:idx]
    return text


def clean_snippet(raw: bytes) -> str:
    """Decodifica quoted-printable (heuristica, sem depender do header real) e remove marcacao HTML/CSS,
    deixando so texto visivel -- o corpo cru costuma vir com muito ruido (tags, boilerplate de <head>,
    soft-breaks de QP) que infla o prompt sem ajudar a classificacao."""
    try:
        decoded = quopri.decodestring(raw)
    except Exception:
        decoded = raw
    text = decoded.decode('utf-8', errors='replace')
    text = _cut_unclosed_style_script(text)
    text = _STYLE_SCRIPT_RE.sub(' ', text)
    text = _TAG_RE.sub(' ', text)
    text = _WS_RE.sub(' ', text).strip()
    return text
