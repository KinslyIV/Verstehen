from dataclasses import dataclass


@dataclass
class Refused:
    status: int
    reason: dict[str, object]
