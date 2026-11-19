import asyncio
import logging
import re

from pydantic_ai import Agent

from verstehen.providers.policy import ProviderPolicy
from verstehen.providers.resolve import ResolverService
from verstehen.providers.usage import UsageModel
from verstehen.session.events import Notification, Notifications
from verstehen.store.sessions import SessionsStore
from verstehen.store.usage import UsageStore

logger = logging.getLogger(__name__)
TITLE_PROMPT = (
    "Write a title for a learning session that starts with the learner's message below.\n"
    'Use at most 6 words. Name the topic, not the request ("Photosynthesis basics",\n'
    'not "Help me understand photosynthesis"). Reply with the title only: no quotes,\n'
    "no trailing punctuation.\n\nLearner's message:\n"
)

TITLE_MAX_CHARS = 72


def title_from_prompt(prompt: str) -> str:
    """Use LearnHarness's pure word-boundary title cut."""
    one_line = re.sub(r"\s+", " ", prompt).strip()
    encoded = one_line.encode("utf-16-le", errors="surrogatepass")
    if len(encoded) <= TITLE_MAX_CHARS * 2:
        return one_line
    prefix = encoded[: TITLE_MAX_CHARS * 2].decode("utf-16-le", errors="surrogatepass")
    cut = prefix.rfind(" ")
    return (prefix if cut < 0 else prefix[:cut]) + "…"


class TitleService:
    """Own one-shot title tasks started alongside the first accepted learner turn.
    Successful titles overwrite the current name; failure leaves the current name untouched.
    """

    def __init__(
        self,
        resolver_service: ResolverService,
        provider_policy: ProviderPolicy,
        usage_store: UsageStore,
        sessions_store: SessionsStore,
        notifications: Notifications,
        provider_events: bool = False,
    ):
        self.resolver_service = resolver_service
        self.provider_policy = provider_policy
        self.usage_store = usage_store
        self.sessions_store = sessions_store
        self.notifications = notifications
        self.provider_events = provider_events
        self.tasks: set[asyncio.Task[None]] = set()

    def start(self, session_id: str, first_message: str) -> None:
        task = asyncio.create_task(self.generate(session_id, first_message))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def generate(self, session_id: str, first_message: str) -> None:
        try:
            resolved = await self.resolver_service.resolve("title")
            if not await self.provider_policy.admit("foreground", resolved.account):
                raise PermissionError("Provider policy does not allow title generation")
            model = UsageModel(
                resolved, self.usage_store, session_id, "title", self.provider_events
            )
            result = await Agent(
                model, retries=0, model_settings=resolved.settings
            ).run(TITLE_PROMPT + first_message)
            title = clean_title(result.output)
            if await self.sessions_store.rename(session_id, title):
                self.notifications.publish(
                    Notification(type="chats-changed", session_id=session_id)
                )
        except Exception:
            logger.exception(
                "Title generation failed for session %s; no retry", session_id
            )

    async def close(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def clean_title(reply: str) -> str:
    title = re.sub(r"\s+", " ", reply).strip().strip("\"'“”‘’").strip()
    if not title:
        raise ValueError("The title model returned an empty title")
    return title_from_prompt(title)
