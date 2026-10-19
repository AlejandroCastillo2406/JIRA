import logging


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        import structlog
    except ImportError:
        return
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
