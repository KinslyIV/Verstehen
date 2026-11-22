from secrets import token_hex

from pydantic import BaseModel, ConfigDict, Field

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


class Proposition(BaseModel):
    model_config = ConfigDict(strict=True)
    id: str = Field(
        description='Local id: "p1", "p2", … — referenced by chains in this call.'
    )
    name: str = Field(
        description="A very short label — established terminology, the term the discipline itself uses, a glossary headword a textbook would print ('Will to power', 'Divine command theory'). Not a sentence, needn't be unique or self-contained: this becomes the node's global label in the graph."
    )
    statement: str = Field(
        description='One true, self-contained, world-facing core idea at full precision. Never about the learner, the teacher, or the reading: not "the learner understands X" but "X". A misconception enters as its TRUE correction.'
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Verbatim phrasings the source used for the same proposition, if any.",
    )


class SessionProposition(Proposition):
    model_config = ConfigDict(strict=True, populate_by_name=True)
    message_id: str = Field(
        alias="messageId",
        title="Messageid",
        description='The message id of the ONE passage in this stretch that most directly states or explains this proposition — copy it EXACTLY from that passage\'s "TEACHER [id]" label.',
    )


class Chain(BaseModel):
    model_config = ConfigDict(strict=True)
    premises: list[str] = Field(
        description="Premise ids used TOGETHER: they jointly entail the conclusion; independent reasons are separate chains.",
        json_schema_extra={
            "minItems": 1,
            "items": {
                "type": "string",
                "description": 'The id this premise uses — EITHER an existing graph idea id from THE GRAPH SO FAR in the prompt, verbatim ("n_…"), OR the local id of a proposition in this submission ("p1", …).',
            },
        },
    )
    conclusion: str = Field(
        description='The id this conclusion is — EITHER an existing graph idea id from THE GRAPH SO FAR in the prompt, verbatim ("n_…"), OR the local id of a proposition in this submission ("p1", …).'
    )


PROPOSITIONS_DESCRIPTION = "Only the NEW core ideas this stretch contributes — ideas the prompt's THE GRAPH SO FAR already holds are referenced by id in chains, never restated here."
CHAINS_DESCRIPTION = "Every argument this stretch makes — including arguments that join new ideas to established ones; conclusions reusable by id as premises of later chains; bare ideas (no argument) ride the propositions list alone; pass [] when none — never omit the field."


class NotesFindings(BaseModel):
    propositions: list[Proposition] = Field(description=PROPOSITIONS_DESCRIPTION)
    chains: list[Chain] = Field(description=CHAINS_DESCRIPTION)


class SessionFindings(BaseModel):
    model_config = ConfigDict(title="SessionSubmit")
    propositions: list[SessionProposition] = Field(description=PROPOSITIONS_DESCRIPTION)
    chains: list[Chain] = Field(description=CHAINS_DESCRIPTION)


type Findings = NotesFindings | SessionFindings


class Link(BaseModel):
    model_config = ConfigDict(strict=True, populate_by_name=True)
    id: str = Field(description='The proposition id from the findings ("p1", …).')
    link_to: str = Field(
        alias="linkTo",
        title="Linkto",
        description="The id of the EXISTING graph node this proposition IS — your identity verdict. EQUIVALENCE BIAS (2026-09-27): paraphrases, rewordings, and compressions of the same claim MERGE; only genuinely distinct propositions stay apart.",
    )


class AuditVerdicts(BaseModel):
    model_config = ConfigDict(title="Review")
    links: list[Link] = Field(
        description="Identity verdicts — which findings propositions ARE existing graph nodes. A proposition absent from here = create a new node. Pass [] when none — never omit the field."
    )


class EmissionStats(BaseModel):
    nodes: int = 0
    chains: int = 0
    dropped_chains: int = 0

    def add(self, other: "EmissionStats") -> None:
        self.nodes += other.nodes
        self.chains += other.chains
        self.dropped_chains += other.dropped_chains


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
    findings: Findings,
    verdicts: AuditVerdicts,
    folded_at: str,
    coverage: list[CoverageEntry] | None = None,
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
                        session_id=session_id,
                        message_id=proposition.message_id
                        if isinstance(proposition, SessionProposition)
                        else "",
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
    if coverage is None:
        ledger.checkpoints.append(
            SourceCheckpoint(session_id=session_id, folded_at=folded_at)
        )
    else:
        ledger.coverage.extend(coverage)
    return stats


async def merge_findings(
    graph_store: GraphStore,
    session_id: str,
    findings: Findings,
    verdicts: AuditVerdicts,
    folded_at: str,
    coverage: list[CoverageEntry] | None = None,
) -> EmissionStats:
    async with graph_store.transaction() as ledger:
        return merge_into(ledger, session_id, findings, verdicts, folded_at, coverage)
