import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_ai import Tool
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.tools import ToolReturn

from verstehen.store.settings import SettingsStore
from verstehen.teaching.files.access import SourceAccess
from verstehen.teaching.files.read import read_source
from verstehen.teaching.files.search import find_sources, grep_sources, list_sources
from verstehen.teaching.tool_schema import TeachingToolSchema

READ_DESCRIPTION = "Read the contents of a file. Supports text files and images (jpg, png, gif, webp, bmp). Images are sent as attachments. For text files, output is truncated to 2000 lines or 50.0KB (whichever is hit first). Use offset/limit for large files. When you need the full file, continue with offset until complete. File access settings and protected-location denials apply; use ls without a path to discover allowed folders when restricted."
LS_DESCRIPTION = "List directory contents, or list the allowed folder paths when restriction is enabled and no path is supplied. Inspect a listed folder by supplying its path. Returns entries sorted alphabetically, with '/' suffix for directories. Includes dotfiles. Output is truncated to 500 entries or 50.0KB (whichever is hit first)."
FIND_DESCRIPTION = "Search for files by glob pattern. Returns paths relative to an explicit search directory, or absolute paths when searching the allowed folders by default. Use ls without a path to discover allowed roots. Ignores node_modules, .git, and Library directories, and skips known sensitive locations (including agent transcripts, credential stores and browser profiles), plus .env/.env.* files. Output is truncated to 1000 total results or 50.0KB (whichever is hit first)."
GREP_DESCRIPTION = "Search file contents for a pattern. Returns matching lines with file paths and line numbers; default searches of allowed folders use absolute paths. Use ls without a path to discover allowed roots. Ignores node_modules, .git, and Library directories, and skips known sensitive locations (e.g. ~/.ssh, ~/.aws, ~/.claude, browser profiles and LearnHarness credential stores), plus .env/.env.* files. Output is truncated to 100 matches or 50.0KB (whichever is hit first). Long lines are truncated to 500 chars."


def file_tools(
    settings_store: SettingsStore, data_dir: Path, *, accepts_images: bool
) -> tuple[Tool[None], ...]:
    async def run[Result](
        tool: str, operation: Callable[[SourceAccess], Result]
    ) -> Result:
        try:
            settings = await settings_store.read_file_access()

            def execute() -> Result:
                return operation(SourceAccess(settings, data_dir, Path.home()))

            return await asyncio.wait_for(asyncio.to_thread(execute), timeout=30)
        except TimeoutError as error:
            raise ToolFailed(
                f'Tool "{tool}" timed out after 30s — the result was discarded'
            ) from error
        except (OSError, ValueError) as error:
            raise ToolFailed(str(error)) from error

    async def read(
        path: Annotated[
            str,
            Field(
                min_length=1,
                description="Path to the file to read (relative or absolute)",
            ),
        ],
        offset: Annotated[
            int,
            Field(
                ge=1,
                strict=True,
                description="Line number to start reading from (1-indexed)",
            ),
        ] = 1,
        limit: Annotated[
            int, Field(ge=1, strict=True, description="Maximum number of lines to read")
        ] = 0,
    ) -> ToolReturn[str]:
        return await run(
            "read",
            lambda access: read_source(
                access.resolve(path), offset, limit or None, data_dir, accepts_images
            ),
        )

    async def ls(
        path: Annotated[
            str,
            Field(
                description="Directory to list. Default: home when unrestricted, the allowed folder paths when restricted. Explicit relative paths are home-relative."
            ),
        ] = "",
        limit: Annotated[
            int,
            Field(
                strict=True,
                description="Maximum number of entries to return (default: 500)",
            ),
        ] = 500,
    ) -> ToolReturn[str]:
        text = await run("ls", lambda access: list_sources(access, path, limit))
        return ToolReturn(text, metadata=text)

    async def find(
        pattern: Annotated[
            str,
            Field(
                min_length=1,
                description="Glob pattern, e.g. '*.ts', '**/*.json', or 'src/**/*.spec.ts'; matched relative to each search root",
            ),
        ],
        path: Annotated[
            str,
            Field(
                description="Directory to search. Default: home when unrestricted, all allowed folders when restricted. Explicit relative paths are home-relative."
            ),
        ] = "",
        limit: Annotated[
            int,
            Field(
                strict=True,
                description="Maximum total results across all roots (default: 1000)",
            ),
        ] = 1000,
    ) -> ToolReturn[str]:
        text = await run(
            "find", lambda access: find_sources(access, path, pattern, limit)
        )
        return ToolReturn(text, metadata=text)

    async def grep(
        pattern: Annotated[
            str,
            Field(min_length=1, description="Search pattern (regex or literal string)"),
        ],
        path: Annotated[
            str,
            Field(
                description="Directory or file to search. Default: home when unrestricted, all allowed folders when restricted. Explicit relative paths are home-relative."
            ),
        ] = "",
        glob: Annotated[
            str,
            Field(
                description="Filter files by glob pattern, e.g. '*.ts' or '**/*.spec.ts'"
            ),
        ] = "",
        ignore_case: Annotated[
            bool,
            Field(
                strict=True,
                alias="ignoreCase",
                description="Case-insensitive search (default: false)",
            ),
        ] = False,
        literal: Annotated[
            bool,
            Field(
                strict=True,
                description="Treat pattern as literal string instead of regex (default: false)",
            ),
        ] = False,
        context: Annotated[
            int,
            Field(
                ge=0,
                strict=True,
                description="Number of lines to show before and after each match (default: 0)",
            ),
        ] = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                strict=True,
                description="Maximum number of matches to return (default: 100)",
            ),
        ] = 100,
    ) -> ToolReturn[str]:
        text = await run(
            "grep",
            lambda access: grep_sources(
                access, path, pattern, glob, ignore_case, literal, context, limit
            ),
        )
        return ToolReturn(text, metadata=text)

    return (
        Tool(read, description=READ_DESCRIPTION, schema_generator=TeachingToolSchema),
        Tool(ls, description=LS_DESCRIPTION, schema_generator=TeachingToolSchema),
        Tool(find, description=FIND_DESCRIPTION, schema_generator=TeachingToolSchema),
        Tool(grep, description=GREP_DESCRIPTION, schema_generator=TeachingToolSchema),
    )
