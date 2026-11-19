import logging

logger = logging.getLogger(__name__)


def log_provider_event(enabled: bool, event: object) -> None:
    if enabled:
        logger.info("Provider event: %r", event)
