"""A recording fake of the dbx executor interface."""


class FakeDb(object):
    def __init__(self, responder=None):
        self.statements = []  # (kind, sql, params)
        self.responder = responder or (lambda sql, params: [])
        self.commits = 0
        self.rollbacks = 0

    def query(self, sql, params=None):
        self.statements.append(("query", sql, params))
        return self.responder(sql, params)

    def execute(self, sql, params=None):
        self.statements.append(("execute", sql, params))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def sqls(self):
        return [s[1] for s in self.statements]
