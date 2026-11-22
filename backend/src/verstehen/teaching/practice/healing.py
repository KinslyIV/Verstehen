import json
from collections.abc import Mapping, Sequence
from typing import Protocol

from verstehen.teaching.questions.validation import strip_model_value_debris

_MISSING = object()


class GraphNodeTarget(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...


def _try_parse_json(raw: str) -> object:
    try:
        return json.loads(raw)
    except ValueError:
        return _MISSING


def _literals_of(prop: Mapping[str, object]) -> list[object]:
    literals: list[object] = []
    if isinstance(any_of := prop.get("anyOf"), list):
        for member in any_of:
            if isinstance(member, Mapping):
                literals.extend(_literals_of(member))
    if isinstance(enum_values := prop.get("enum"), list):
        literals.extend(enum_values)
    if "const" in prop:
        literals.append(prop["const"])
    return literals


def _accepts_type(prop: Mapping[str, object], expected: str) -> bool:
    if prop.get("type") == expected:
        return True
    if isinstance(any_of := prop.get("anyOf"), list):
        return any(
            isinstance(member, Mapping) and member.get("type") == expected
            for member in any_of
        )
    return False


def heal_encoded_arguments(args: object, schema: Mapping[str, object]) -> object:
    """Heal JSON-encoded string arguments for literals, null, booleans, numbers, and arrays."""
    if not isinstance(args, dict):
        return args
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return args
    healed: dict[str, object] | None = None
    for key, prop in properties.items():
        if not isinstance(prop, Mapping):
            continue
        raw = args.get(key)
        if not isinstance(raw, str):
            continue
        parsed = _try_parse_json(raw)
        fixed: object = _MISSING
        literals = _literals_of(prop)
        if literals:
            if raw in literals:
                continue
            if parsed is not _MISSING and parsed in literals:
                fixed = parsed
        if fixed is _MISSING and _accepts_type(prop, "null") and parsed is None:
            fixed = None
        if (
            fixed is _MISSING
            and _accepts_type(prop, "boolean")
            and isinstance(parsed, bool)
        ):
            fixed = parsed
        if (
            fixed is _MISSING
            and (_accepts_type(prop, "number") or _accepts_type(prop, "integer"))
            and isinstance(parsed, (int, float))
            and not isinstance(parsed, bool)
        ):
            fixed = parsed
        if (
            fixed is _MISSING
            and _accepts_type(prop, "array")
            and isinstance(parsed, list)
        ):
            fixed = parsed
        if fixed is not _MISSING:
            if healed is None:
                healed = dict(args)
            healed[key] = fixed
    return healed if healed is not None else args


def resolve_target_id(
    target: str, nodes: Sequence[GraphNodeTarget | Mapping[str, str]]
) -> str | None:
    """Resolve a target string to a canonical proposition id by exact id, then case-insensitive name."""
    cleaned = strip_model_value_debris(target)
    if not cleaned:
        return None
    for node in nodes:
        node_id = node["id"] if isinstance(node, Mapping) else node.id
        if node_id == cleaned:
            return cleaned
    lower = cleaned.lower()
    for node in nodes:
        node_id = node["id"] if isinstance(node, Mapping) else node.id
        node_name = node["name"] if isinstance(node, Mapping) else node.name
        if strip_model_value_debris(node_name).lower() == lower:
            return node_id
    return None


__all__ = [
    "GraphNodeTarget",
    "heal_encoded_arguments",
    "resolve_target_id",
    "strip_model_value_debris",
]
