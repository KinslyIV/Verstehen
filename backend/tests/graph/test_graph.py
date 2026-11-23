import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.graph.candidates import (
    CandidateRequest,
    PropositionCandidateSearch,
    proposition_candidate_batch,
    words,
)
from verstehen.graph.costs import graph_cost_summary
from verstehen.graph.deletion import delete_node_traces, delete_sources_traces
from verstehen.graph.merge import (
    AuditVerdicts,
    Chain,
    Link,
    NotesFindings,
    Proposition,
    SessionFindings,
    SessionProposition,
    merge_findings,
    simplify_chains,
)
from verstehen.graph.model import derive_view, get_graph
from verstehen.graph.organization import (
    OrganizationAction,
    apply_organization_action,
    can_move_folder,
    parse_organization_action,
    place_imported_source,
    register_import,
    validate_organization,
)
from verstehen.graph.positions import commit_positions
from verstehen.graph.render_settings import (
    GraphRenderSettings,
    sanitize_render_settings,
)
from verstehen.graph.snapshot import (
    format_graph_propositions,
    format_graph_sessions,
    graph_session_index,
    graph_snapshot,
)
from verstehen.store.database import open_database
from verstehen.store.graph import (
    CoverageEntry,
    GraphChain,
    GraphLedger,
    GraphNode,
    GraphStore,
    NotesSource,
    Position,
    ProvenancePoint,
    SourceCheckpoint,
    SourceOrganization,
)
from verstehen.store.migrate import migrate
from verstehen.store.sessions import Session, SessionsStore
from verstehen.store.usage import UsageRecord, UsageStore

NOW = "2026-11-20T00:00:00+00:00"


def node(id: str, source: str = "s1", **values) -> GraphNode:
    return GraphNode(
        id=id,
        name=values.pop("name", id),
        statement=values.pop("statement", id),
        provenance=[ProvenancePoint(session_id=source)],
        created_at=NOW,
        **values,
    )


def chain(
    id: str, premises: list[str], conclusion: str, source: str = "s1"
) -> GraphChain:
    return GraphChain(
        id=id,
        premises=premises,
        conclusion=conclusion,
        provenance=[ProvenancePoint(session_id=source)],
        created_at=NOW,
    )


def findings() -> SessionFindings:
    return SessionFindings(
        propositions=[
            SessionProposition(
                id="p1", name="A", statement="A is true", message_id="m1"
            ),
            SessionProposition(
                id="p2", name="B", statement="B follows", message_id="m2"
            ),
        ],
        chains=[Chain(premises=["p1"], conclusion="p2")],
    )


def test_first_row_defines_identity_and_later_rows_add_aliases_and_provenance():
    first = node("n_a", aliases=["first"])
    link = node(
        "n_a", "s2", name="new name", statement="second", aliases=["first", "third", ""]
    )
    ledger = GraphLedger(nodes=[first, link, link])
    merged = get_graph(ledger).nodes[0]
    assert (merged.name, merged.statement, merged.created_at) == ("n_a", "n_a", NOW)
    assert merged.aliases == ["first", "second", "third"]
    assert [p.session_id for p in merged.provenance] == ["s1", "s2"]
    assert first.aliases == ["first"]


def test_chain_assertions_merge_by_sorted_premises_and_keep_first_identity():
    a = chain("arg_a", ["n_a", "n_b"], "n_c")
    b = chain("arg_b", ["n_b", "n_a"], "n_c", "s2")
    result = get_graph(GraphLedger(chains=[a, b, b])).chains
    assert len(result) == 1
    assert result[0].id == "arg_a"
    assert result[0].premises == ["n_a", "n_b"]
    assert [p.session_id for p in result[0].provenance] == ["s1", "s2"]


def test_view_derives_direct_edges_implications_and_drops_dangling_chains():
    ledger = GraphLedger(
        nodes=[node(id) for id in ("a", "b", "c")],
        chains=[
            chain("arg_a", ["a"], "b"),
            chain("arg_b", ["a", "b"], "c"),
            chain("arg_dead", ["missing"], "a"),
        ],
    )
    view = derive_view(get_graph(ledger))
    assert [n.id for n in view.nodes] == ["a", "b", "c", "arg_b"]
    assert view.nodes[-1].statement == "a, b → c"
    assert [(e.from_, e.to) for e in view.edges] == [
        ("a", "b"),
        ("a", "arg_b"),
        ("b", "arg_b"),
        ("arg_b", "c"),
    ]
    assert [(e.from_, e.to) for e in view.logical_edges] == [
        ("a", "b"),
        ("a", "c"),
        ("b", "c"),
    ]


def test_simplification_removes_supersets_and_ancestry_covered_arguments():
    lines = [
        chain("arg_x", ["a", "b"], "x"),
        chain("arg_y", ["x", "c"], "y"),
        chain("arg_redundant", ["a", "b", "c"], "y"),
        chain("arg_superset", ["a", "b", "d"], "x"),
        chain("arg_independent", ["z"], "x"),
    ]
    assert [c.id for c in simplify_chains(lines)] == [
        "arg_x",
        "arg_y",
        "arg_independent",
    ]


def test_simplification_is_cycle_safe_and_drops_every_assertion_of_a_redundant_key():
    lines = [
        chain("arg_a", ["a"], "b"),
        chain("arg_b", ["b"], "a"),
        chain("arg_c", ["a", "x"], "b"),
        chain("arg_c", ["x", "a"], "b", "s2"),
    ]
    assert [c.id for c in simplify_chains(lines)] == ["arg_a", "arg_b"]


def test_snapshot_clusters_by_birth_and_counts_only_propositions_for_hulls():
    ledger = GraphLedger(
        nodes=[node(id) for id in ("a", "b", "c")] + [node("d", "s2"), node("e", "s2")],
        chains=[chain("arg_a", ["a", "b"], "c"), chain("arg_b", ["d", "e"], "a", "s2")],
    )
    snapshot = graph_snapshot(ledger, [Session(id="s1", title="First")])
    assert [(c.id, c.label, c.members) for c in snapshot.clusters] == [
        ("s1", "First", ["a", "arg_a", "b", "c"])
    ]
    assert snapshot.node_sessions["a"] == ["s1"]
    assert "d" not in snapshot.node_sessions


def test_snapshot_source_lookup_live_session_wins_last_duplicate_wins_empty_path_is_present():
    ledger = GraphLedger(
        nodes=[
            node("a", "same"),
            node("b", "file"),
            node("c", "empty"),
            node("d", "missing"),
        ],
        sources=[
            NotesSource(id=id, file_path=path, imported_at=NOW)
            for id, path in [
                ("same", "wrong.md"),
                ("file", "old.md"),
                ("file", "new.md"),
                ("empty", ""),
            ]
        ],
    )
    snapshot = graph_snapshot(ledger, [Session(id="same", title="Live")])
    assert snapshot.sessions == {"same": "Live"}
    assert snapshot.file_sources == {"file": "new.md", "empty": ""}
    assert snapshot.node_sessions == {"a": ["same"], "b": ["file"], "c": ["empty"]}
    ledger.sources[-2].file_path = "changed.md"
    assert graph_snapshot(ledger, []).file_sources["file"] == "changed.md"


def test_session_readers_count_births_and_include_missing_sources():
    ledger = GraphLedger(
        nodes=[node("b"), node("a"), node("b", "s2"), node("c", "missing")]
    )
    entries = graph_session_index(ledger, [Session(id="s1", title="Live")])
    assert [(e.id, e.propositions, e.kind) for e in entries] == [
        ("s1", 2, "chat"),
        ("missing", 1, "file"),
    ]


def test_merge_commits_nodes_chains_and_coverage_together_and_emits_after_commit(
    tmp_path: Path,
):
    async def run():
        events = []
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            store = GraphStore(database, events.append)
            coverage = CoverageEntry(session_id="s1", fp="fp", tokens=42, folded_at=NOW)
            stats = await merge_findings(
                store,
                "s1",
                findings(),
                AuditVerdicts(links=[]),
                NOW,
                [coverage],
            )
            ledger = await store.read()
            assert stats.nodes == 2 and stats.chains == 1
            assert len(ledger.nodes) == 2 and len(ledger.chains) == 1
            assert ledger.coverage == [coverage] and ledger.checkpoints == []
            assert ledger.nodes[0].provenance[0].message_id == "m1"
            assert events == [ledger.revision] == [1]
            async with store.transaction():
                pass
            assert events == [1]

    asyncio.run(run())


def test_failed_coverage_write_rolls_back_every_graph_write_and_event(tmp_path: Path):
    async def run():
        events = []
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            store = GraphStore(database, events.append)
            async with database.transaction() as connection:
                await connection.execute(
                    "CREATE TRIGGER fail_coverage BEFORE INSERT ON graph_coverage BEGIN SELECT RAISE(ABORT, 'coverage failed'); END"
                )
            with pytest.raises(Exception, match="coverage failed"):
                await merge_findings(
                    store,
                    "s1",
                    findings(),
                    AuditVerdicts(links=[]),
                    NOW,
                    [CoverageEntry(session_id="s1", fp="fp", tokens=1, folded_at=NOW)],
                )
            assert await store.read() == GraphLedger()
            assert events == []

    asyncio.run(run())


def test_merge_links_aliases_resolves_digest_endpoints_and_checkpoints_notes(
    tmp_path: Path,
):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            store = GraphStore(database)
            async with store.transaction() as ledger:
                ledger.nodes = [node("n_known")]
            proposed = NotesFindings(
                propositions=[
                    Proposition(id="p", name="alias", statement="rewording"),
                    Proposition(id="p", name="ignored", statement="ignored"),
                ],
                chains=[Chain(premises=["p", "p", "missing"], conclusion="n_known")],
            )
            stats = await merge_findings(
                store,
                "src_notes",
                proposed,
                AuditVerdicts(links=[Link(id="p", link_to="n_known")]),
                NOW,
            )
            ledger = await store.read()
            assert stats.nodes == 0 and stats.chains == 0
            assert get_graph(ledger).nodes[0].aliases == ["rewording"]
            assert ledger.checkpoints == [
                SourceCheckpoint(session_id="src_notes", folded_at=NOW)
            ]
            proposed.propositions[0].id = "p2"
            proposed.propositions = proposed.propositions[:1]
            proposed.chains = [Chain(premises=["n_known"], conclusion="p2")]
            stats = await merge_findings(
                store,
                "src_notes",
                proposed,
                AuditVerdicts(links=[Link(id="p2", link_to="n_gone")]),
                NOW,
            )
            assert stats.nodes == 1 and stats.chains == 1

    asyncio.run(run())


def test_bm25_ranks_aliases_separately_and_pages_with_hints():
    nodes = [
        node(
            f"n_{i}",
            statement="quantum physics",
            aliases=["wave particle", *[f"unrelated {j}" for j in range(20)]],
        )
        for i in range(7)
    ]
    search = PropositionCandidateSearch(nodes)
    proposition = Proposition(id="p", name="", statement="wave")
    first = proposition_candidate_batch(
        search, [proposition], [CandidateRequest(id="p")]
    )
    assert first.matches[0].candidate_ids == [f"n_{i}" for i in range(5)]
    assert first.matches[0].next_offset == 5
    assert first.candidates[0].matched_aliases == ["wave particle"]
    second = proposition_candidate_batch(
        search, [proposition], [CandidateRequest(id="p", offset=5)]
    )
    assert second.matches[0].candidate_ids == ["n_5", "n_6"]
    assert second.matches[0].next_offset is None
    unrelated = Proposition(id="p", name="", statement="banana")
    assert not proposition_candidate_batch(
        search, [unrelated], [CandidateRequest(id="p")]
    ).candidates
    assert (
        len(
            proposition_candidate_batch(
                search, [unrelated], [CandidateRequest(id="p", hints=["quantum"])]
            ).candidates
        )
        == 5
    )
    assert words("ＴＨＥ not α₂ gravity") == ["not", "α2", "gravity"]


@pytest.mark.parametrize(
    "requests, message",
    [
        ([CandidateRequest(id="bad")], "Unknown proposition"),
        ([CandidateRequest(id="p"), CandidateRequest(id="p")], "Repeated proposition"),
        ([CandidateRequest(id="p", offset=-1)], "nonnegative safe integer"),
    ],
)
def test_candidate_batch_rejects_invalid_requests(requests, message):
    with pytest.raises(ValueError, match=message):
        proposition_candidate_batch(
            PropositionCandidateSearch([]),
            [Proposition(id="p", name="", statement="")],
            requests,
        )


@pytest.mark.parametrize("mode", ["preserve-graph", "delete-nodes"])
def test_source_deletion_keeps_shared_identity_and_foreign_knowledge(mode):
    ledger = GraphLedger(
        nodes=[
            node("a", aliases=["birth alias"]),
            node("a", "s2", statement="foreign alias"),
            node("b"),
            node("c", "s2"),
        ],
        chains=[chain("arg_shared", ["a"], "c", "s2"), chain("arg_dead", ["b"], "c")],
        coverage=[CoverageEntry(session_id="s1", fp="fp", tokens=1, folded_at=NOW)],
        checkpoints=[SourceCheckpoint(session_id="s1", folded_at=NOW)],
        positions={
            id: Position(x=1, y=2) for id in ("a", "b", "arg_dead", "arg_shared")
        },
    )
    before = ledger.model_copy(deep=True)
    stats = delete_sources_traces(ledger, {"s1"}, mode)
    assert stats.coverage_removed == stats.checkpoints_removed == 1
    if mode == "preserve-graph":
        assert ledger.nodes == before.nodes and ledger.chains == before.chains
    else:
        assert [n.id for n in ledger.nodes] == ["a", "a", "c"]
        assert ledger.nodes[0].statement == "a" and ledger.nodes[0].aliases == []
        merged = get_graph(ledger).nodes[0]
        assert merged.aliases == ["foreign alias"]
        assert merged.provenance == [ProvenancePoint(session_id="s2")]
        assert [c.id for c in ledger.chains] == ["arg_shared"]
        assert set(ledger.positions) == {"a", "arg_shared"}
        assert stats.nodes_removed == stats.chains_removed == 1
    assert delete_sources_traces(ledger, {"s1"}, mode).nodes_removed == 0


def test_source_deletion_leaves_unrelated_legacy_rows_and_positions():
    legacy = node("legacy").model_copy(update={"provenance": []})
    ledger = GraphLedger(
        nodes=[legacy, node("dead")],
        chains=[
            chain("arg_foreign", ["missing"], "legacy").model_copy(
                update={"provenance": []}
            )
        ],
        positions={"foreign": Position(x=1, y=2)},
    )
    delete_sources_traces(ledger, {"s1"}, "delete-nodes")
    assert ledger.nodes == [legacy]
    assert len(ledger.chains) == 1 and "foreign" in ledger.positions


@pytest.mark.parametrize(
    "id, remaining", [("a", ["b", "c"]), ("arg_a", ["a", "b", "c"])]
)
def test_node_and_argument_deletion_remove_only_their_traces(id, remaining):
    ledger = GraphLedger(
        nodes=[node("a"), node("b"), node("c")],
        chains=[chain("arg_a", ["a", "b"], "c")],
        positions={"arg_a": Position(x=1, y=2), "a": Position(x=1, y=2)},
    )
    result = delete_node_traces(ledger, id)
    assert result is not None and result.chains_removed == 1
    assert [n.id for n in ledger.nodes] == remaining
    assert "arg_a" not in ledger.positions
    assert delete_node_traces(ledger, id) is None


def test_organization_moves_refuse_cycles_and_nonempty_folder_deletion():
    state = SourceOrganization()
    parent = apply_organization_action(
        state, OrganizationAction(action="create-folder", name="Parent"), set()
    )
    child = apply_organization_action(
        state,
        OrganizationAction(action="create-folder", name="Child", parent_id=parent),
        set(),
    )
    assert parent and child
    assert not can_move_folder(state, parent, child)
    with pytest.raises(ValueError, match="descendants"):
        apply_organization_action(
            state,
            OrganizationAction(
                action="move", kind="folder", id=parent, parent_id=child
            ),
            set(),
        )
    with pytest.raises(ValueError, match="Only empty folders"):
        apply_organization_action(
            state, OrganizationAction(action="delete-folder", id=parent), set()
        )
    apply_organization_action(
        state,
        OrganizationAction(action="move", kind="source", id="source", parent_id=child),
        {"source"},
    )
    with pytest.raises(ValueError, match="Only empty folders"):
        apply_organization_action(
            state, OrganizationAction(action="delete-folder", id=child), {"source"}
        )
    validate_organization(state)


def test_import_placement_reuses_moved_folders_and_preserves_renames():
    state = SourceOrganization()
    place_imported_source(state, "src_a", "course/topic/a.md")
    topic = state.folders[-1]
    topic.name, topic.parent_id = "Renamed", None
    place_imported_source(state, "src_b", "course/topic/b.md")
    assert len(state.folders) == 2
    assert state.placements["src_b"].folder_id == topic.id
    state.placements["src_a"].name = "My notes"
    place_imported_source(state, "src_a", "elsewhere/a.md")
    assert state.placements["src_a"].name == "My notes"
    ledger = GraphLedger(organization=state)
    assert register_import(ledger, "course/topic/a.md") == register_import(
        ledger, "course/topic/a.md"
    )


@pytest.mark.parametrize(
    "raw, message",
    [
        ({}, "Unknown source"),
        ({"action": "move", "id": "x", "kind": "source"}, "Invalid parent"),
        ({"action": "create-folder", "name": "  ", "parent_id": None}, "Name must"),
    ],
)
def test_organization_parser_rejects_malformed_actions(raw, message):
    with pytest.raises(ValueError, match=message):
        parse_organization_action(raw)


def test_positions_keep_known_propositions_and_implications_clamp_finite_values_and_do_not_settle():
    ledger = GraphLedger(
        nodes=[node("a"), node("b"), node("c")],
        chains=[chain("arg_a", ["a", "b"], "c")],
    )
    positions = commit_positions(
        ledger,
        {
            "a": {"x": 1e9, "y": -1e9},
            "arg_a": {"x": 1, "y": 2},
            "b": {"x": float("nan"), "y": 0},
            "c": {"x": True, "y": 1},
            "unknown": {"x": 0, "y": 0},
        },
    )
    assert positions == {"a": Position(x=1e6, y=-1e6), "arg_a": Position(x=1, y=2)}
    assert commit_positions(ledger, {}) == {}
    assert ledger.positions == positions


def test_render_settings_reset_legacy_sizes_snap_ladders_tie_low_and_clamp_physics():
    settings = sanitize_render_settings(
        {
            "node_size": 99,
            "edge_width": 1.25,
            "regions": {"bitmap": 999, "blur": 999, "enabled": False},
            "physics": {
                "charge_strength": 0,
                "depth_mode": "invalid",
                "velocity_decay": 0,
            },
        }
    )
    assert settings.node_size == 2 and settings.edge_width == 1
    assert settings.regions.bitmap == 512 and settings.regions.blur == 120
    assert not settings.regions.enabled
    assert (
        settings.physics.charge_strength == -120
        and settings.physics.velocity_decay == 0.18
    )
    assert settings.physics.depth_mode == "off"
    assert (
        sanitize_render_settings({"size_units": "world", "node_size": 99}).node_size
        == 12
    )
    assert (
        sanitize_render_settings({"node_size": True, "regions": None, "physics": []})
        == GraphRenderSettings()
    )


def usage(role: str, source: str, account: str, id: str = "request") -> UsageRecord:
    return UsageRecord(
        request_id=id,
        session_id=source,
        role=role,
        account=account,
        model="unknown",
        input_tokens=10,
        output_tokens=5,
        cache_read_tokens=2,
        cache_write_tokens=3,
        reasoning_tokens=1,
    )


def test_cost_totals_include_only_graph_roles_and_separate_subscription_from_unpriced():
    summary = graph_cost_summary(
        [
            usage("extractor", "s1", "claude_code"),
            usage("auditor", "s1", "chatgpt:uuid"),
            usage("extractor", "src_a", "unknown"),
            usage("teacher", "s1", "unknown"),
        ],
        {"s1": "Session"},
    )
    assert summary.tokens["input_tokens"] == 30
    assert summary.subscription_runs == 2 and summary.unpriced_runs == 1
    assert summary.plan_cost_label == "CLI + ChatGPT"
    assert summary.total_dollars == 0
    assert summary.stages["extraction"].runs == 2 and summary.stages["audit"].runs == 1
    assert summary.sources[0].title == "Session"


def test_notes_usage_survives_without_a_session_and_session_usage_still_cascades(
    tmp_path: Path,
):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            sessions = SessionsStore(database)
            session = await sessions.create("Session")
            store = UsageStore(database)
            await store.append(usage("extractor", "src_notes", "chatgpt:uuid", "notes"))
            await store.append(usage("extractor", session.id, "claude_code", "chat"))
            await sessions.delete(session.id)
            assert [u.request_id for u in await store.list_graph()] == ["notes"]

    asyncio.run(run())


def test_graph_routes_persist_organization_settings_positions_and_errors(
    tmp_path: Path,
):
    with TestClient(
        create_app(Settings(tmp_path)), headers={"host": "localhost"}
    ) as client:
        assert client.get("/api/graph").json()["revision"] == 0
        assert client.get("/api/graph/render-settings").json() is None
        settings = client.put(
            "/api/graph/render-settings", json={"size_units": "world", "node_size": 999}
        ).json()
        assert settings["node_size"] == 12
        assert client.get("/api/graph/render-settings").json() == settings
        assert client.put(
            "/api/graph/positions", json={"unknown": {"x": 1, "y": 2}}
        ).json() == {"positions": {}, "revision": None}
        assert client.put("/api/graph/positions", content="broken").status_code == 400
        result = client.post(
            "/api/graph/sources",
            json={"action": "create-folder", "name": "Folder", "parent_id": None},
        )
        assert result.status_code == 200
        assert result.json()["created_folder_id"].startswith("folder_")
        assert (
            client.post(
                "/api/graph/sources",
                json={
                    "action": "move",
                    "kind": "folder",
                    "id": result.json()["created_folder_id"],
                    "parent_id": result.json()["created_folder_id"],
                },
            ).status_code
            == 400
        )
        assert client.post("/api/graph/sources", content="x" * 65537).status_code == 400
        assert client.delete("/api/graph/nodes/n_missing").json() == {
            "error": "No such node",
            "code": "not_found",
        }
        assert (
            client.request(
                "DELETE",
                "/api/graph/sources",
                json={"source_ids": [], "folder_ids": [], "delete_sessions": False},
            ).status_code
            == 400
        )
        assert client.get("/api/graph/costs").json()["tokens"]["input_tokens"] == 0


@pytest.mark.parametrize("delete_sessions", [False, True])
def test_source_route_removes_graph_contributions_and_only_selected_conversations(
    tmp_path: Path, delete_sessions: bool
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:

        async def seed():
            sessions_store = SessionsStore(app.state.database)
            session = await sessions_store.create("Original")
            other = await sessions_store.create("Other")
            async with app.state.graph_service.graph_store.transaction() as ledger:
                ledger.nodes = [
                    node("n_shared", session.id, aliases=["birth alias"]),
                    node("n_shared", other.id, statement="shared"),
                    node("n_only", session.id),
                ]
            return session.id, other.id

        assert client.portal is not None
        session_id, other_id = client.portal.call(seed)
        rename = client.post(
            "/api/graph/sources",
            json={"action": "rename-source", "id": session_id, "name": "Renamed"},
        )
        assert rename.status_code == 200
        revision = client.get("/api/graph").json()["revision"]
        assert rename.json()["revision"] == revision
        assert client.get("/api/graph").json()["sessions"][session_id] == "Renamed"
        result = client.request(
            "DELETE",
            "/api/graph/sources",
            json={
                "source_ids": [session_id],
                "folder_ids": [],
                "delete_sessions": delete_sessions,
            },
        )
        assert result.status_code == 200
        snapshot = client.get("/api/graph").json()
        assert [n["id"] for n in snapshot["propositions"]] == ["n_shared"]
        assert snapshot["propositions"][0]["statement"] == "n_shared"
        assert snapshot["node_sessions"] == {"n_shared": [other_id]}
        assert client.get(f"/api/sessions/{session_id}").status_code == (
            404 if delete_sessions else 200
        )
        assert client.get(f"/api/sessions/{other_id}").status_code == 200


def test_deletion_routes_refuse_while_extraction_is_registered(tmp_path: Path):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:

        async def seed():
            async with app.state.graph_service.graph_store.transaction() as ledger:
                ledger.nodes = [node("n_a")]

            async def waiting():
                await asyncio.Event().wait()

            app.state.extraction_service.launch("s1", waiting)

        assert client.portal is not None
        client.portal.call(seed)
        assert client.delete("/api/graph/nodes/n_a").status_code == 409
        assert (
            client.request(
                "DELETE",
                "/api/graph/sources",
                json={"source_ids": ["s1"], "folder_ids": [], "delete_sessions": False},
            ).status_code
            == 409
        )
        assert len(client.get("/api/graph").json()["propositions"]) == 1


def test_graph_store_round_trip_preserves_assertion_identity_and_organization(
    tmp_path: Path,
):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            store = GraphStore(database)
            async with store.transaction() as ledger:
                ledger.nodes = [
                    node("a"),
                    node("a", "s2", statement="alias"),
                    node("b"),
                ]
                ledger.chains = [
                    chain("arg_a", ["a"], "b"),
                    chain("arg_a", ["a"], "b", "s2"),
                ]
                ledger.sources = [
                    NotesSource(
                        id="src_a", file_path="folder/notes.md", imported_at=NOW
                    )
                ]
                place_imported_source(ledger.organization, "src_a", "folder/notes.md")
                ledger.positions = {"a": Position(x=1, y=2)}
            saved = await store.read()
            assert get_graph(saved) == get_graph(ledger)
            assert saved.organization == ledger.organization
            assert saved.positions == ledger.positions
            assert graph_snapshot(saved, []).file_sources == {}

    asyncio.run(run())


def test_notes_source_deletion_removes_usage_and_placement_in_the_graph_transaction(
    tmp_path: Path,
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:

        async def seed():
            async with app.state.graph_service.graph_store.transaction() as ledger:
                ledger.nodes = [node("n_notes", "src_notes")]
                ledger.sources = [
                    NotesSource(
                        id="src_notes", file_path="folder/notes.md", imported_at=NOW
                    )
                ]
                place_imported_source(
                    ledger.organization, "src_notes", "folder/notes.md"
                )
            await UsageStore(app.state.database).append(
                usage("extractor", "src_notes", "chatgpt:uuid")
            )

        assert client.portal is not None
        client.portal.call(seed)
        assert client.get("/api/graph/costs").json()["subscription_runs"] == 1
        response = client.request(
            "DELETE",
            "/api/graph/sources",
            json={
                "source_ids": ["src_notes"],
                "folder_ids": [],
                "delete_sessions": False,
            },
        )
        assert response.status_code == 200
        assert response.json()["sources"] == []
        assert response.json()["organization"]["placements"] == {}
        assert client.get("/api/graph/costs").json()["subscription_runs"] == 0
        assert client.get("/api/graph").json()["propositions"] == []


def test_source_deletion_blocks_new_extractions_until_finished(
    tmp_path: Path,
):
    from verstehen.graph.errors import GraphRefused
    from verstehen.graph.merge import EmissionStats

    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:
        launched_during_delete = []

        async def noop():
            return EmissionStats()

        async def seed():
            async with app.state.graph_service.graph_store.transaction() as ledger:
                ledger.nodes = [node("n_a")]
            blocker = asyncio.Event()

            async def wait():
                await blocker.wait()
                return EmissionStats()

            task = app.state.extraction_service.launch("s2", wait)
            return blocker, task

        assert client.portal is not None
        blocker, task = client.portal.call(seed)
        refused = client.request(
            "DELETE",
            "/api/graph/sources",
            json={"source_ids": ["s1"], "folder_ids": [], "delete_sessions": False},
        )
        assert refused.status_code == 409
        assert client.get("/api/graph").json()["propositions"][0]["id"] == "n_a"

        async def finish_blocker():
            blocker.set()
            await task

        client.portal.call(finish_blocker)

        original_delete = app.state.graph_service.graph_store.transaction

        def probe_launch():
            with pytest.raises(GraphRefused) as err:
                app.state.extraction_service.launch("s2", noop)
            launched_during_delete.append((err.value.status, err.value.code))
            return original_delete()

        app.state.graph_service.graph_store.transaction = probe_launch
        response = client.request(
            "DELETE",
            "/api/graph/sources",
            json={"source_ids": ["s1"], "folder_ids": [], "delete_sessions": False},
        )
        assert response.status_code == 200
        assert launched_during_delete == [(409, "graph_deleting")]
        assert app.state.extraction_service.graph_deletions == 0
        assert client.get("/api/graph").json()["propositions"] == []


def test_graph_formatters_separate_prober_and_auditor_views():
    assert "The knowledge graph is empty" in format_graph_sessions(GraphLedger(), [])
    assert 'No propositions born in session "missing"' in format_graph_propositions(
        GraphLedger(), "missing"
    )

    session = Session(id="s1", title="Live")
    ledger = GraphLedger(
        nodes=[
            node("n_2", "s1", name="Beta", statement="Secret beta statement"),
            node("n_1", "s1", name="Alpha", statement="Secret alpha statement"),
            node("n_2", "s2", name="Linked", statement="Linked beta statement"),
        ]
    )

    prober_sessions = format_graph_sessions(ledger, [session], auditor=False)
    assert "most recent first:" in prober_sessions
    assert "born " in prober_sessions and "last active " in prober_sessions

    auditor_sessions = format_graph_sessions(ledger, [session], auditor=True)
    assert "1 session(s):\n" in auditor_sessions
    assert "born " not in auditor_sessions

    prober_props = format_graph_propositions(ledger, "s1", auditor=False)
    assert "covered in this session:" in prober_props
    assert prober_props.splitlines()[1:] == ["- Alpha", "- Beta"]
    assert "Secret alpha statement" not in prober_props

    auditor_props = format_graph_propositions(ledger, "s1", auditor=True)
    assert "born in this session:" in auditor_props
    assert auditor_props.splitlines()[1:] == [
        "- n_1 :: Alpha",
        "  statement: Secret alpha statement",
        "- n_2 :: Beta",
        "  statement: Secret beta statement",
    ]
    assert 'No propositions born in session "s2"' in format_graph_propositions(
        ledger, "s2", auditor=True
    )
