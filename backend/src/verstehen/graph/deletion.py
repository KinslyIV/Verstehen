from typing import Literal

from pydantic import BaseModel

from verstehen.store.graph import GraphLedger

DeleteMode = Literal["preserve-graph", "delete-nodes"]


class SourceDeletionStats(BaseModel):
    nodes_removed: int = 0
    chains_removed: int = 0
    coverage_removed: int = 0
    checkpoints_removed: int = 0


class NodeDeletionStats(BaseModel):
    chains_removed: int


def delete_sources_traces(
    ledger: GraphLedger, source_ids: set[str], mode: DeleteMode
) -> SourceDeletionStats:
    if mode not in ("preserve-graph", "delete-nodes"):
        raise ValueError(f"Unknown deletion mode: {mode}")
    coverage = [row for row in ledger.coverage if row.session_id not in source_ids]
    checkpoints = [
        row for row in ledger.checkpoints if row.session_id not in source_ids
    ]
    stats = SourceDeletionStats(
        coverage_removed=len(ledger.coverage) - len(coverage),
        checkpoints_removed=len(ledger.checkpoints) - len(checkpoints),
    )
    ledger.coverage, ledger.checkpoints = coverage, checkpoints
    if mode == "preserve-graph":
        return stats
    touched = {
        line.id
        for line in ledger.nodes
        if any(p.session_id in source_ids for p in line.provenance)
    }
    known = {line.id for line in ledger.nodes}
    live = {
        line.id
        for line in ledger.nodes
        if line.id not in touched
        or any(p.session_id not in source_ids for p in line.provenance)
    }
    dead = known - live
    out_nodes = []
    seen = set()
    for line in ledger.nodes:
        if line.id not in live:
            continue
        first = line.id not in seen
        seen.add(line.id)
        points = [p for p in line.provenance if p.session_id not in source_ids]
        if points == line.provenance:
            out_nodes.append(line)
        elif points:
            out_nodes.append(line.model_copy(update={"provenance": points}))
        elif first:
            out_nodes.append(line.model_copy(update={"provenance": [], "aliases": []}))
    out_chains = []
    dead_chains = set()
    for line in ledger.chains:
        points = [p for p in line.provenance if p.session_id not in source_ids]
        if (
            line.conclusion in dead
            or any(p in dead for p in line.premises)
            or (line.provenance and not points)
        ):
            dead_chains.add(line.id)
            continue
        if points != line.provenance:
            dead_chains.add(line.id)
        out_chains.append(line.model_copy(update={"provenance": points}))
    stats.nodes_removed = len(dead)
    stats.chains_removed = len(ledger.chains) - len(out_chains)
    ledger.nodes, ledger.chains = out_nodes, out_chains
    ledger.positions = {
        id: p
        for id, p in ledger.positions.items()
        if id not in dead and id not in dead_chains
    }
    return stats


def delete_node_traces(ledger: GraphLedger, node_id: str) -> NodeDeletionStats | None:
    if node_id.startswith("arg_"):
        if not any(chain.id == node_id for chain in ledger.chains):
            return None
        out = [chain for chain in ledger.chains if chain.id != node_id]
    else:
        if not any(node.id == node_id for node in ledger.nodes):
            return None
        ledger.nodes = [node for node in ledger.nodes if node.id != node_id]
        out = [
            chain
            for chain in ledger.chains
            if chain.conclusion != node_id and node_id not in chain.premises
        ]
    removed = {chain.id for chain in ledger.chains if chain not in out}
    stats = NodeDeletionStats(chains_removed=len(ledger.chains) - len(out))
    ledger.chains = out
    ledger.positions = {
        id: p
        for id, p in ledger.positions.items()
        if id != node_id and id not in removed
    }
    return stats
