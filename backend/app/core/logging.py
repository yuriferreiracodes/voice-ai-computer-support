import logging


class _SidFilter(logging.Filter):
    """Every record gets a `sid` (short session id) so call logs can be followed."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "sid"):
            record.sid = "-"
        return True


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_SidFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [sid=%(sid)s] %(name)s: %(message)s"))
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)
