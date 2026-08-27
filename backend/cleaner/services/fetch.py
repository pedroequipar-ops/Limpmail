import re
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser

from .imap_pool import ImapConnectionError

UID_RE = re.compile(rb'UID (\d+)')


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
