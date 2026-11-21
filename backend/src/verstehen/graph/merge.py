from secrets import token_hex

from pydantic import BaseModel, Field

from verstehen.graph.model import chain_key
from verstehen.store.graph import (
    CoverageEntry,
    GraphChain,
    GraphLedger,
    GraphNode,
    GraphStore,
    ProvenancePoint,
    SourceCheckpoint,
    timestamp,
)


class ExtractedProposition(BaseModel):
    id: str
    name: str
    statement: str
    aliases: list[str] = Field(default_factory=list)
    message_id: str | None = None


class ExtractedChain(BaseModel):
    premises: list[str]
    conclusion: str


class SessionFindings(BaseModel):
    propositions: list[ExtractedProposition]
    chains: list[ExtractedChain]


class IdentityLink(BaseModel):
    id: str
    link_to: str


class AuditVerdicts(BaseModel):
    links: list[IdentityLink]


class MergeSource(BaseModel):
    folded_at: str
    coverage: list[CoverageEntry] | None = None


class EmissionStats(BaseModel):
    nodes: int = 0
    chains: int = 0
    dropped_chains: int = 0


def simplify_chains(lines: list[GraphChain]) -> list[GraphChain]:
    groups: dict[str, GraphChain] = {}
    premises_of: dict[str, list[str]] = {}
    for line in lines:
        groups.setdefault(chain_key(line), line)
        premises_of.setdefault(line.conclusion, []).extend(line.premises)
    memo: dict[str, set[str]] = {}

    def ancestry(id: str, visiting: set[str]) -> set[str]:
        if id in memo:
            return memo[id]
        if id in visiting:
            return set()
        visiting.add(id)
        out: set[str] = set()
        for premise in premises_of.get(id, []):
            out.add(premise)
            out.update(ancestry(premise, visiting))
        visiting.remove(id)
        memo[id] = out
        return out

    conclusions: dict[str, list[GraphChain]] = {}
    for line in groups.values():
        conclusions.setdefault(line.conclusion, []).append(line)
    dropped: set[str] = set()
    for candidates in conclusions.values():
        kept: list[GraphChain] = []
        for candidate in sorted(
            candidates, key=lambda c: (len(c.premises), c.created_at, chain_key(c))
        ):
            redundant = False
            for other in kept:
                covered = set(other.premises)
                if covered <= set(candidate.premises):
                    redundant = True
                    break
                for premise in other.premises:
                    covered.update(ancestry(premise, set()))
                if set(candidate.premises) <= covered:
                    redundant = True
                    break
            if redundant:
                dropped.add(chain_key(candidate))
            else:
                kept.append(candidate)
    return [line for line in lines if chain_key(line) not in dropped]


def merge_into(
    ledger: GraphLedger,
    session_id: str,
    findings: SessionFindings,
    verdicts: AuditVerdicts,
    source: MergeSource,
) -> EmissionStats:
    stats = EmissionStats()
    existing = {node.id for node in ledger.nodes}
    mapping: dict[str, str] = {}
    links = {link.id: link.link_to for link in verdicts.links}
    now = timestamp()
    for proposition in findings.propositions:
        if proposition.id in mapping:
            continue
        target = links.get(proposition.id)
        if target not in existing:
            target = "n_" + token_hex(6)
            stats.nodes += 1
            existing.add(target)
        ledger.nodes.append(
            GraphNode(
                id=target,
                name=proposition.name,
                statement=proposition.statement,
                aliases=list(proposition.aliases),
                created_at=now,
                provenance=[
                    ProvenancePoint(
                        session_id=session_id, message_id=proposition.message_id or ""
                    )
                ],
            )
        )
        mapping[proposition.id] = target
    ids = {chain_key(line): line.id for line in reversed(ledger.chains)}
    asserted = {
        chain_key(line)
        for line in ledger.chains
        if any(p.session_id == session_id for p in line.provenance)
    }

    def resolve(endpoint: str) -> str | None:
        return mapping.get(endpoint, endpoint if endpoint in existing else None)

    for chain in findings.chains:
        conclusion = resolve(chain.conclusion)
        if conclusion is None:
            continue
        premises = list(
            dict.fromkeys(
                p
                for endpoint in chain.premises
                if (p := resolve(endpoint)) is not None and p != conclusion
            )
        )
        if not premises:
            continue
        line = GraphChain(
            id="arg_" + token_hex(6),
            premises=premises,
            conclusion=conclusion,
            created_at=now,
            provenance=[ProvenancePoint(session_id=session_id)],
        )
        key = chain_key(line)
        if key in asserted:
            continue
        line.id = ids.setdefault(key, line.id)
        ledger.chains.append(line)
        asserted.add(key)
        stats.chains += 1
    kept = simplify_chains(ledger.chains)
    stats.dropped_chains = len(ledger.chains) - len(kept)
    ledger.chains = kept
    if source.coverage is None:
        ledger.checkpoints.append(
            SourceCheckpoint(session_id=session_id, folded_at=source.folded_at)
        )
    else:
        ledger.coverage.extend(source.coverage)
    return stats


async def merge_findings(
    graph_store: GraphStore,
    session_id: str,
    findings: SessionFindings,
    verdicts: AuditVerdicts,
    source: MergeSource,
) -> EmissionStats:
    async with graph_store.transaction() as ledger:
        return merge_into(ledger, session_id, findings, verdicts, source)
