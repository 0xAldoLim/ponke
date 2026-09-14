import logging

import structlog


def configure_logging():
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    # These libraries may include token-bearing URLs or query strings in their logs.
    for name in ("httpx", "httpcore", "telegram", "openai", "sqlalchemy", "uvicorn.access"):
        logging.getLogger(name).disabled = True
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
    )
