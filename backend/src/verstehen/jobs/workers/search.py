from typing import Literal

import httpx2 as httpx
from pydantic import BaseModel

SearchSetting = Literal["native", "tavily", "brave"]
SearchChoice = SearchSetting | None


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str


def choose_search(
    setting: SearchSetting, provider_kind: str, keys: dict[str, str]
) -> SearchChoice:
    if setting == "native" and provider_kind == "chatgpt":
        return "native"
    if setting != "native" and keys.get(setting):
        return setting
    for engine in ("tavily", "brave"):
        if keys.get(engine):
            return engine
    return "native" if provider_kind == "chatgpt" else None


async def tavily_search(
    query: str, count: int, key: str, client: httpx.AsyncClient
) -> list[SearchHit]:
    response = await client.post(
        "https://api.tavily.com/search",
        headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
        json={"query": query, "max_results": min(count, 20)},
        timeout=30,
    )
    if not response.is_success:
        detail = response.text[:200]
        try:
            detail = response.json().get("detail", {}).get("error", detail)[:200]
        except ValueError, AttributeError, TypeError:
            pass
        raise ValueError(f"Tavily search API {response.status_code}: {detail}")
    return [
        SearchHit(
            title=row["url"] if row.get("title") is None else row["title"],
            url=row["url"],
            snippet=(row.get("content") or "").replace("\n", " ")[:500],
        )
        for row in (response.json().get("results") or [])
        if isinstance(row.get("url"), str) and row["url"]
    ]


async def brave_search(
    query: str, count: int, key: str, client: httpx.AsyncClient
) -> list[SearchHit]:
    response = await client.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": min(count, 20)},
        headers={"accept": "application/json", "x-subscription-token": key},
        timeout=30,
    )
    if not response.is_success:
        raise ValueError(
            f"Brave search API {response.status_code}: {response.text[:200]}"
        )
    return [
        SearchHit(
            title=row["url"] if row.get("title") is None else row["title"],
            url=row["url"],
            snippet=(row.get("description") or "").replace("\n", " ")[:500],
        )
        for row in ((response.json().get("web") or {}).get("results") or [])
        if isinstance(row.get("url"), str) and row["url"]
    ]
