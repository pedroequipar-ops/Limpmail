import imaplib
import re


class ImapConnectionError(Exception):
    pass


LIST_RE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.+)$')

COMMON_SPAM_NAMES = [
    'Junk', 'INBOX.Junk', 'Spam', 'INBOX.Spam', 'Junk E-mail', 'INBOX.Junk E-mail',
    'Junk Email', 'INBOX.Junk Email',  # Outlook / Office365
]
COMMON_TRASH_NAMES = ['Trash', 'INBOX.Trash', 'Deleted Items', 'INBOX.Deleted Items', 'Deleted Messages']


def connect(host, port, email, password, timeout=20):
    """Abre e autentica uma conexão IMAP. Levanta ImapConnectionError em qualquer falha."""
    try:
        port = int(port)
        if port == 993:
            conn = imaplib.IMAP4_SSL(host, port, timeout=timeout)
        else:
            conn = imaplib.IMAP4(host, port, timeout=timeout)
            try:
                conn.starttls()
            except Exception:
                pass
        conn.login(email, password)
        return conn
    except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
        raise ImapConnectionError(str(exc)) from exc


def _decode_name(raw_name: bytes) -> str:
    name = raw_name.decode('utf-8', errors='replace').strip()
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1]
    return name


def list_folders(conn):
    typ, data = conn.list()
    if typ != 'OK':
        raise ImapConnectionError('Falha ao listar pastas (LIST)')
    folders = []
    for line in data:
        if not line:
            continue
        match = LIST_RE.match(line)
        if not match:
            continue
        flags = match.group('flags').decode('utf-8', errors='replace')
        name = _decode_name(match.group('name'))
        folders.append({'name': name, 'flags': flags})
    return folders


def discover_special_folders(conn):
    """Descobre pasta de spam/lixeira via flag SPECIAL-USE, com fallback a nomes comuns."""
    folders = list_folders(conn)
    names = [f['name'] for f in folders]

    spam = next((f['name'] for f in folders if '\\Junk' in f['flags']), None)
    trash = next((f['name'] for f in folders if '\\Trash' in f['flags']), None)

    if not spam:
        spam = next((n for n in COMMON_SPAM_NAMES if n in names), None)
    if not trash:
        trash = next((n for n in COMMON_TRASH_NAMES if n in names), None)

    return {'spam_folder': spam, 'trash_folder': trash, 'all_folders': names}


def supports_move(conn):
    typ, data = conn.capability()
    if typ != 'OK' or not data:
        return False
    caps = data[0].decode('utf-8', errors='replace').upper()
    return 'MOVE' in caps.split()


def select_inbox(conn, readonly=False):
    typ, data = conn.select('INBOX', readonly=readonly)
    if typ != 'OK':
        raise ImapConnectionError('Falha ao abrir INBOX')
    uid_validity = None
    name, values = conn.response('UIDVALIDITY')
    if values and values[0]:
        try:
            uid_validity = int(values[0])
        except (TypeError, ValueError):
            uid_validity = None
    return uid_validity
