from typing import get_args

from pydantic import BaseModel, ValidationError

from .settings import AgentName, Command, ServerDraft, ServerSettings
from .toolsets import AgentServers, discover_tools


class SaveServer(BaseModel):
    id: str | None = None
    server: ServerDraft


def activate(ctx):
    settings = ServerSettings(ctx.data_directory / "servers.json")
    for agent in get_args(AgentName):
        ctx.register_toolset([agent], AgentServers(settings, agent))

    @ctx.expose
    async def get_servers():
        return settings.current.model_dump(mode="json")["servers"]

    @ctx.expose
    async def test_connection(data):
        try:
            tools = await discover_tools(Command.model_validate(data))
        except (ValidationError, ValueError) as error:
            return {"error": error_message(error)}
        return {"tools": [tool.model_dump() for tool in tools]}

    @ctx.expose
    async def save_server(data):
        try:
            request = SaveServer.model_validate(data)
            server = settings.save(request.server, request.id)
        except (ValidationError, ValueError) as error:
            return {"error": error_message(error)}
        return {"server": server.model_dump(mode="json")}

    @ctx.expose
    async def remove_server(server_id):
        if not isinstance(server_id, str):
            return {"error": "Invalid server ID."}
        settings.remove(server_id)
        return {}


def error_message(error: ValueError) -> str:
    if isinstance(error, ValidationError):
        return error.errors(include_input=False)[0]["msg"].removeprefix("Value error, ")
    return str(error)
