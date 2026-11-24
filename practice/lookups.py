from django.db.models import CharField, Lookup, TextField


@CharField.register_lookup
@TextField.register_lookup
class UnicodeContains(Lookup):
    """Literal case-insensitive search, including Cyrillic in SQLite."""
    lookup_name = 'unicode_contains'

    def as_sqlite(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f'UNICODE_CONTAINS({lhs}, {rhs})', [*lhs_params, *rhs_params]

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f'POSITION(LOWER({rhs}) IN LOWER({lhs})) > 0', [*rhs_params, *lhs_params]
