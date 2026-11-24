from django.apps import AppConfig
from django.db.backends.signals import connection_created


def register_sqlite_search(sender, connection, **kwargs):
    if connection.vendor == 'sqlite':
        connection.connection.create_function(
            'UNICODE_CONTAINS', 2,
            lambda text, query: None if text is None or query is None else int(str(query).casefold() in str(text).casefold()),
            deterministic=True,
        )


class PracticeConfig(AppConfig):
    name = 'practice'
    verbose_name = 'Учебная практика'

    def ready(self):
        from . import lookups  # Register the portable Cyrillic search lookup.
        connection_created.connect(register_sqlite_search, dispatch_uid='practice.unicode_search')
