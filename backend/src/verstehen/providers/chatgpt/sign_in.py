import asyncio
from typing import Literal
from uuid import uuid4

import anyio
from pydantic import BaseModel, Field
lazy from pydantic_ai.providers.openai_chatgpt import OpenAIChatGPTOAuthFlow

from verstehen.providers.accounts import Account
from verstehen.providers.chatgpt.adapter import ChatGPTAccountAdapter
from verstehen.providers.chatgpt.callback_port import CallbackPort, CallbackPortBusy


class SignInStatus(BaseModel):
    id: str
    state: Literal["pending", "connected", "failed"] = "pending"
    account: Account | None = None
    reason: str | None = None


class SignInStarted(BaseModel):
    id: str
    url: str = Field(repr=False)


class SignInBusy(Exception):
    pass


class ChatGPTSignInService:
    """Own the single loopback sign-in task and its latest safe status for Settings.
    Port 1455 admits one flow at a time; shutdown and removal cancel pending work.
    """

    def __init__(
        self,
        adapter: ChatGPTAccountAdapter,
        callback_port: CallbackPort | None = None,
    ):
        self.adapter = adapter
        self.callback_port = callback_port or CallbackPort()
        self.status: SignInStatus | None = None
        self.task: asyncio.Task[None] | None = None
        self.pending_account_id: str | None = None

    async def start(self, account_id: str | None = None) -> SignInStarted:
        try:
            self.callback_port.reserve("local")
        except CallbackPortBusy as error:
            raise SignInBusy(
                "A ChatGPT sign-in is already pending."
                if error.owner == "local"
                else "A server ChatGPT sign-in is using the sign-in port."
            ) from error
        try:
            credentials_store = self.adapter.credentials_store
            previous = credentials_store.get(account_id) if account_id else None
            credentials = previous.credentials() if previous else None
            flow = OpenAIChatGPTOAuthFlow(
                app_name="Verstehen",
                host_id=credentials_store.host_id(),
                client_id=credentials.client_id if credentials else None,
                id_token_hint=credentials.id_token if credentials else None,
            )
            params = (
                {"prompt": "consent"}
                if credentials and not credentials.plan_usage_granted
                else None
            )
            started = SignInStarted(
                id=uuid4().hex, url=flow.authorization_url(extra_params=params)
            )
            self.status = SignInStatus(id=started.id)
            self.task = asyncio.create_task(self.complete(flow, self.status))
            self.pending_account_id = account_id
        except BaseException:
            self.callback_port.release("local")
            raise
        self.task.add_done_callback(lambda _: self.callback_port.release("local"))
        await asyncio.sleep(0)
        return started

    async def complete(
        self, flow: OpenAIChatGPTOAuthFlow, status: SignInStatus
    ) -> None:
        try:
            with anyio.fail_after(300):
                credentials = await flow.exchange_code_from_callback()
            stored = self.adapter.credentials_store.sign_in(credentials)
            self.adapter.invalidate(stored.id)
            status.account = next(
                a for a in await self.adapter.accounts() if a.id == stored.id
            )
            status.state = "connected"
        except asyncio.CancelledError:
            status.state = "failed"
            status.reason = "ChatGPT sign-in was cancelled."
            raise
        except TimeoutError:
            status.state = "failed"
            status.reason = "ChatGPT sign-in timed out. Start again."
        except Exception:
            status.state = "failed"
            status.reason = "ChatGPT sign-in failed. Start again."

    def get_status(self, sign_in_id: str) -> SignInStatus | None:
        return self.status if self.status and self.status.id == sign_in_id else None

    async def remove(self, account_id: str) -> None:
        self.adapter.credentials_store.get(account_id)
        if self.pending_account_id == account_id:
            await self.close()
        self.adapter.credentials_store.remove(account_id)
        self.adapter.invalidate(account_id)

    async def close(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
