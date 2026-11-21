from typing import Annotated

from fastapi import APIRouter, Depends, Request

from verstehen.providers.claude_code.adapter import ClaudeCodeAccountAdapter
from verstehen.providers.claude_code.binary import BinaryStatus

router = APIRouter(prefix="/api/accounts/claude-code")


def get_adapter(request: Request) -> ClaudeCodeAccountAdapter:
    return request.app.state.claude_code_adapter


AdapterDependency = Annotated[ClaudeCodeAccountAdapter, Depends(get_adapter)]


@router.get("", response_model=BinaryStatus)
async def get_status(adapter: AdapterDependency) -> BinaryStatus:
    return await adapter.status()
