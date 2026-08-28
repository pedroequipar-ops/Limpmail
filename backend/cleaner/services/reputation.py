from collections import Counter

from django.db.models import F

from ..models import SenderReputation

CATEGORY_FIELD = {
    'IMPORTANTE': 'importante_count',
    'SPAN': 'span_count',
    'LIXEIRA': 'lixeira_count',
}


def get_reputation_map(account, senders):
    """senders: iteravel de rotulos (fetch.sender_label). Retorna {sender: {'importante': n, 'span': n,
    'lixeira': n}} so para os que ja tem algum historico -- remetente sem historico fica de fora,
    para o prompt nao ficar poluido com entradas zeradas."""
    rows = SenderReputation.objects.filter(account=account, sender__in=set(senders))
    result = {}
    for row in rows:
        if row.importante_count + row.span_count + row.lixeira_count > 0:
            result[row.sender] = {
                'importante': row.importante_count,
                'span': row.span_count,
                'lixeira': row.lixeira_count,
            }
    return result


def record_classifications(account, sender_categories):
    """sender_categories: iteravel de (sender_label, categoria). Incrementa o placar por remetente."""
    counts = Counter(sender_categories)
    for (sender, category), n in counts.items():
        field = CATEGORY_FIELD.get(category)
        if not field:
            continue
        obj, _ = SenderReputation.objects.get_or_create(account=account, sender=sender)
        SenderReputation.objects.filter(pk=obj.pk).update(**{field: F(field) + n})
