from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _enable_wal(sender, connection, **kwargs):
    if connection.vendor == 'sqlite':
        cursor = connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL;')
        cursor.execute('PRAGMA busy_timeout=30000;')


class CleanerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cleaner'

    def ready(self):
        connection_created.connect(_enable_wal)
