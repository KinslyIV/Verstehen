import re

TITLE_MAX_CHARS = 72


def title_from_prompt(prompt: str) -> str:
    """Use LearnHarness's word-boundary cut, with the chat creation fallback."""
    one_line = re.sub(r"\s+", " ", prompt).strip()
    if not one_line:
        return "Untitled session"
    encoded = one_line.encode("utf-16-le", errors="surrogatepass")
    if len(encoded) <= TITLE_MAX_CHARS * 2:
        return one_line
    prefix = encoded[: TITLE_MAX_CHARS * 2].decode("utf-16-le", errors="surrogatepass")
    cut = prefix.rfind(" ")
    return (prefix if cut < 0 else prefix[:cut]) + "…"
