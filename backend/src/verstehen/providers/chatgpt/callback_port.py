from typing import Literal

CallbackOwner = Literal["local", "server"]


class CallbackPortBusy(Exception):
    """Raised when loopback port 1455 is already reserved; names the current owner."""

    def __init__(self, owner: CallbackOwner):
        super().__init__(f"Port 1455 is reserved by a {owner} ChatGPT sign-in.")
        self.owner = owner


class CallbackPort:
    """One in-process reservation of loopback port 1455, shared by local and server sign-in."""

    def __init__(self) -> None:
        self.owner: CallbackOwner | None = None

    def reserve(self, owner: CallbackOwner) -> None:
        if self.owner is not None:
            raise CallbackPortBusy(self.owner)
        self.owner = owner

    def release(self, owner: CallbackOwner) -> None:
        if self.owner == owner:
            self.owner = None
