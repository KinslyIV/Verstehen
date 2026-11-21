class GraphRefused(Exception):
    def __init__(self, error: str, status: int = 400, code: str | None = None):
        super().__init__(error)
        self.status = status
        self.code = code
