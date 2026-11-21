import math
import unicodedata
from collections import Counter
from collections.abc import Sequence

import regex
from pydantic import BaseModel, ConfigDict, Field

from verstehen.graph.merge import Proposition
from verstehen.store.graph import GraphNode

STOP_WORDS = set(
    "a an the and or of to in on at by for from with as is are was were be been being it its this that these those which who whose their them they we our you your can could may might must will would should has have had does do did such than then when where each every any all also into through".split()
)
CANDIDATE_PAGE_SIZE = 5


def words(text: str) -> list[str]:
    return [
        word
        for word in regex.findall(
            r"[\p{L}\p{N}]+", unicodedata.normalize("NFKC", text).lower()
        )
        if word not in STOP_WORDS
    ]


class CandidateRequest(BaseModel):
    id: str
    hints: list[str] = Field(default_factory=list)
    offset: int = Field(default=0, strict=True)


class CandidateMatch(BaseModel):
    proposition_id: str
    candidate_ids: list[str]
    next_offset: int | None


class CandidateNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    name: str
    statement: str
    matched_aliases: list[str] = Field(alias="matchedAliases")
    sessions: list[str]


class CandidateBatch(BaseModel):
    matches: list[CandidateMatch]
    candidates: list[CandidateNode]


class PropositionCandidateSearch:
    """Keep one immutable BM25 index for an audit, scoring each phrasing separately."""

    def __init__(self, nodes: list[GraphNode]):
        self.nodes = [node.model_copy(deep=True) for node in nodes]
        self.texts: list[list[tuple[Counter[str], int, str | None]]] = []
        self.frequency: Counter[str] = Counter()
        total_length = text_count = 0
        for node in self.nodes:
            texts = []
            node_terms: set[str] = set()
            for alias in [
                None,
                *dict.fromkeys(a for a in node.aliases if a != node.statement),
            ]:
                tokens = words(
                    node.name + " " + (node.statement if alias is None else alias)
                )
                texts.append((Counter(tokens), len(tokens), alias))
                node_terms.update(tokens)
                total_length += len(tokens)
                text_count += 1
            self.texts.append(texts)
            self.frequency.update(node_terms)
        self.average_length = (
            total_length / text_count if text_count and total_length else 1
        )

    def search(
        self, proposition: Proposition, hints: list[str]
    ) -> list[tuple[GraphNode, float, str | None]]:
        query = set(
            words(
                " ".join(
                    [
                        proposition.name,
                        proposition.statement,
                        *proposition.aliases,
                        *hints,
                    ]
                )
            )
        )
        hits = []
        for node, texts in zip(self.nodes, self.texts):
            best_score = 0
            matched_alias = None
            for terms, length, alias in texts:
                score = 0
                for term in query:
                    tf = terms[term]
                    if tf:
                        df = self.frequency[term]
                        idf = math.log(1 + (len(self.nodes) - df + 0.5) / (df + 0.5))
                        score += (
                            idf
                            * tf
                            * 2.2
                            / (tf + 1.2 * (0.25 + 0.75 * length / self.average_length))
                        )
                if score > best_score:
                    best_score = score
                    matched_alias = (
                        alias if alias and query.intersection(words(alias)) else None
                    )
            if best_score > 0:
                hits.append((node, best_score, matched_alias))
        return sorted(hits, key=lambda hit: (-hit[1], hit[0].id))


def proposition_candidate_batch(
    search: PropositionCandidateSearch,
    propositions: Sequence[Proposition],
    requests: list[CandidateRequest],
) -> CandidateBatch:
    by_id: dict[str, Proposition] = {}
    for proposition in propositions:
        by_id.setdefault(proposition.id, proposition)
    seen = set()
    for request in requests:
        if request.id not in by_id:
            raise ValueError(
                f'Unknown proposition id "{request.id}". Use an id from the proposed findings.'
            )
        if request.id in seen:
            raise ValueError(
                f'Repeated proposition id "{request.id}". Combine its hints in one request.'
            )
        if request.offset < 0 or request.offset > 2**53 - 1:
            raise ValueError("offset must be a nonnegative safe integer.")
        seen.add(request.id)
    matches = []
    candidates: dict[str, CandidateNode] = {}
    for request in requests:
        hits = search.search(by_id[request.id], request.hints)
        page = hits[request.offset : request.offset + CANDIDATE_PAGE_SIZE]
        for node, _, alias in page:
            candidate = candidates.setdefault(
                node.id,
                CandidateNode(
                    id=node.id,
                    name=node.name,
                    statement=node.statement,
                    matched_aliases=[],
                    sessions=list(dict.fromkeys(p.session_id for p in node.provenance)),
                ),
            )
            if alias and alias not in candidate.matched_aliases:
                candidate.matched_aliases.append(alias)
        has_more = request.offset + len(page) < len(hits)
        matches.append(
            CandidateMatch(
                proposition_id=request.id,
                candidate_ids=[node.id for node, _, _ in page],
                next_offset=request.offset + len(page) if has_more else None,
            )
        )
    return CandidateBatch(matches=matches, candidates=list(candidates.values()))
