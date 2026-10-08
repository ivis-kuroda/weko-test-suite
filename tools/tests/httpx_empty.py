"""An empty filename that httpx still announces as `filename=""` (as the hub's executor does)."""


class EmptyFilename(str):
    def __bool__(self) -> bool:
        return True
