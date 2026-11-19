import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

logger = logging.getLogger(__name__)
OBJECT = TypeAdapter(dict[str, JsonValue])


async def control_response(
    process: asyncio.subprocess.Process, request_id: str, request: dict[str, str]
) -> dict[str, JsonValue]:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(
        (
            json.dumps(
                {
                    "type": "control_request",
                    "request_id": request_id,
                    "request": request,
                }
            )
            + "\n"
        ).encode()
    )
    await process.stdin.drain()
    while line := await process.stdout.readline():
        message = OBJECT.validate_json(line)
        if message.get("type") != "control_response":
            continue
        response = OBJECT.validate_python(message.get("response"))
        if response.get("request_id") != request_id:
            continue
        if response.get("subtype") != "success":
            raise ValueError("Claude Code context control request failed.")
        return OBJECT.validate_python(response.get("response", {}))
    return {}


async def context_window(path: Path, model: str) -> int | None:
    """Ask the CLI for local summary metadata, without submitting a model prompt."""
    with tempfile.TemporaryDirectory(prefix="verstehen-claude-context-") as directory:
        process = None
        try:
            async with asyncio.timeout(5):
                process = await asyncio.create_subprocess_exec(
                    str(path),
                    "-p",
                    "--input-format",
                    "stream-json",
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "--model",
                    model,
                    "--tools",
                    "",
                    "--max-turns",
                    "1",
                    "--system-prompt",
                    "",
                    "--setting-sources",
                    "",
                    "--strict-mcp-config",
                    "--mcp-config",
                    '{"mcpServers":{}}',
                    "--disable-slash-commands",
                    "--no-session-persistence",
                    "--permission-prompts",
                    "none",
                    cwd=directory,
                    env={
                        **os.environ,
                        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
                    },
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await control_response(process, "initialize", {"subtype": "initialize"})
                summary = await control_response(
                    process,
                    "context",
                    {
                        "subtype": "get_context_usage",
                        "detail": "summary",
                    },
                )
                tokens = summary.get("maxTokens")
                return tokens if type(tokens) is int and tokens > 0 else None
        except OSError, ValueError, TimeoutError:
            logger.debug("Claude Code context summary unavailable", exc_info=True)
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
    return None
