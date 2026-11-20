from verstehen.graph.model import derive_view, get_graph
from verstehen.graph.render_settings import finite_number
from verstehen.store.graph import GraphLedger, Position


def commit_positions(ledger: GraphLedger, raw: object) -> dict[str, Position]:
    if not isinstance(raw, dict):
        return {}
    known = {node.id for node in derive_view(get_graph(ledger)).nodes}
    positions = {}
    for id, value in raw.items():
        if id not in known or not isinstance(value, dict):
            continue
        x, y = value.get("x"), value.get("y")
        if finite_number(x) and finite_number(y):
            positions[id] = Position(x=min(max(x, -1e6), 1e6), y=min(max(y, -1e6), 1e6))
    if positions:
        ledger.positions = positions
    return positions
