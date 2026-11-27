import os
import re
import tempfile
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

AgentName = Literal["prober", "teacher", "practice", "chat"]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    args: list[str]
    env: dict[str, str]

    @model_validator(mode="after")
    def validate_command(self) -> "Command":
        if not self.command.strip():
            raise ValueError("Enter an executable name or path.")
        if any(
            "\0" in value for value in (self.command, *self.args, *self.env.values())
        ):
            raise ValueError("Command, arguments, and environment cannot contain NUL.")
        if any(not key or "=" in key or "\0" in key for key in self.env):
            raise ValueError("Enter valid environment variable names.")
        return self


class ToolInfo(BaseModel):
    name: str
    description: str = ""


class ServerDraft(Command):
    name: str
    tools: list[ToolInfo]
    selections: dict[AgentName, list[str]]

    @model_validator(mode="after")
    def validate_selections(self) -> "ServerDraft":
        if not self.name.strip():
            raise ValueError("Enter a server name.")
        discovered = {tool.name for tool in self.tools}
        if any(set(names) - discovered for names in self.selections.values()):
            raise ValueError("Choose tools from the server's tool list.")
        return self


class Server(ServerDraft):
    id: str


class Settings(BaseModel):
    servers: dict[str, Server] = Field(default_factory=dict)


class ServerSettings:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.current = Settings.model_validate_json(path.read_bytes())
        except FileNotFoundError:
            self.current = Settings()

    def save(self, draft: ServerDraft, server_id: str | None) -> Server:
        servers = self.current.servers.copy()
        if server_id is None:
            slug = re.sub(r"[^a-z0-9]+", "_", draft.name.lower()).strip("_")[:16]
            server_id = f"{slug or 'server'}_{uuid4().hex[:10]}"
        elif server_id not in servers:
            raise ValueError(
                "This server was removed. Reopen settings to reload the list."
            )
        server = Server(id=server_id, **draft.model_dump())
        servers[server_id] = server
        self.write(Settings(servers=servers))
        return server

    def remove(self, server_id: str) -> None:
        servers = self.current.servers.copy()
        if servers.pop(server_id, None) is not None:
            self.write(Settings(servers=servers))

    def write(self, settings: Settings) -> None:
        descriptor, name = tempfile.mkstemp(
            dir=self.path.parent, prefix=".mcp-servers-"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(settings.model_dump_json(indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)
        self.current = settings
