import logging
import sys
from typing import Any


class APIKeyRedactingFilter(logging.Filter):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self._secret = secret or ""

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secret:
            return True
        if isinstance(record.msg, str) and self._secret in record.msg:
            record.msg = record.msg.replace(self._secret, "***")
        if record.args:
            args: tuple[Any, ...]
            if isinstance(record.args, dict):
                args = tuple(record.args.values())
            else:
                args = record.args  # type: ignore[assignment]
            new_args = tuple(
                a.replace(self._secret, "***") if isinstance(a, str) else a for a in args
            )
            if new_args != args:
                record.args = new_args  # type: ignore[assignment]
        return True


def configure(api_key: str | None = None, level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    if api_key:
        handler.addFilter(APIKeyRedactingFilter(api_key))
    root.addHandler(handler)
