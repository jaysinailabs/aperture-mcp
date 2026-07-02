"""Aperture TopologyProvider — read-only structural diagnosis (cut vertices / bridge nodes).

Frozen form: project a directed, labelled decision network onto an undirected
simple graph (the structural-connectivity edge subset) and surface articulation /
cut-vertex candidates for inspection via Tarjan's algorithm.

Diagnosis only: the result is a bare ``NodeRef`` list with no
severity, impact, priority, ranking, or suggested disposition. Whether to split,
refactor, revoke, or accept a single point is the decision-maker's call. The output
order is canonical for determinism only and carries no priority semantics. This is a
read-only audit entry: it never writes back to the graph, never touches anchor
lifecycle, and never enters a model compute path. Minimal v0.1; not empirically validated.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any

from aperture.core import DeltaStatus

NodeRef = str


class EdgeLabel(StrEnum):
    """Standard decision-network edge labels (methodology C.1), lowercase on wire."""

    DEPENDS_ON = "depends_on"
    REFERS_TO = "refers_to"
    EXTENDS = "extends"
    AGGREGATES = "aggregates"
    REVOKES = "revokes"
    CONTRADICTS = "contradicts"
    TEMPORAL = "temporal"


# Structural-connectivity edge subset included in the undirected projection.
# Custom (non-standard) labels and contradicts/temporal are excluded.
_STRUCTURAL_LABELS: frozenset[str] = frozenset(
    {
        EdgeLabel.DEPENDS_ON.value,
        EdgeLabel.REFERS_TO.value,
        EdgeLabel.EXTENDS.value,
        EdgeLabel.AGGREGATES.value,
        EdgeLabel.REVOKES.value,
    }
)


@dataclass(frozen=True, slots=True)
class Edge:
    """A directed, labelled edge. ``label`` is a free string so custom labels are expressible."""

    src: NodeRef
    dst: NodeRef
    label: str


@dataclass(frozen=True, slots=True)
class DecisionGraph:
    """Read-only directed labelled multigraph input container."""

    nodes: frozenset[NodeRef]
    edges: tuple[Edge, ...]

    @classmethod
    def from_edges(
        cls, edges: tuple[Edge, ...], nodes: frozenset[NodeRef] | None = None
    ) -> DecisionGraph:
        if nodes is None:
            derived: set[NodeRef] = set()
            for e in edges:
                derived.add(e.src)
                derived.add(e.dst)
            nodes = frozenset(derived)
        return cls(nodes=nodes, edges=edges)


@dataclass(frozen=True, slots=True)
class TopologyResult:
    """Bare cut-vertex result. Contains only status + node references —
    no severity, impact, priority, ranking, or suggested disposition fields."""

    status: DeltaStatus
    cut_vertices: tuple[NodeRef, ...] = ()
    reason: str = ""
    supported_metrics: frozenset[str] = frozenset({"cut_vertices"})

    def __post_init__(self) -> None:
        if self.status is not DeltaStatus.OK and not self.reason.strip():
            raise ValueError("non-ok TopologyResult.status requires a non-empty reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "cut_vertices": list(self.cut_vertices),
            "reason": self.reason,
            "supported_metrics": sorted(self.supported_metrics),
        }


def project_to_undirected(graph: DecisionGraph) -> dict[NodeRef, set[NodeRef]]:
    """Project the directed labelled graph onto an undirected simple graph.

    Includes only structural-connectivity labels; excludes contradicts / temporal and any
    custom label; drops self-loops; collapses multi-edges (set adjacency). Isolated nodes
    are kept (as empty adjacency) so they count as their own component.
    """
    adjacency: dict[NodeRef, set[NodeRef]] = {n: set() for n in graph.nodes}
    for e in graph.edges:
        adjacency.setdefault(e.src, set())
        adjacency.setdefault(e.dst, set())
        if e.label not in _STRUCTURAL_LABELS or e.src == e.dst:
            continue
        adjacency[e.src].add(e.dst)
        adjacency[e.dst].add(e.src)
    return adjacency


def find_cut_vertices(adjacency: dict[NodeRef, set[NodeRef]]) -> set[NodeRef]:
    """Articulation points of an undirected graph via iterative Tarjan (O(V+E)).

    Iterative (explicit stack) to avoid Python recursion limits on deep decision chains.
    """
    visited: set[NodeRef] = set()
    disc: dict[NodeRef, int] = {}
    low: dict[NodeRef, int] = {}
    parent: dict[NodeRef, NodeRef | None] = {}
    cut: set[NodeRef] = set()
    timer = 0

    for start in adjacency:
        if start in visited:
            continue
        root_children = 0
        visited.add(start)
        disc[start] = low[start] = timer
        timer += 1
        parent[start] = None
        stack: list[tuple[NodeRef, Iterator[NodeRef]]] = [(start, iter(adjacency[start]))]
        while stack:
            node, neighbors = stack[-1]
            advanced = False
            for nxt in neighbors:
                if nxt not in visited:
                    parent[nxt] = node
                    visited.add(nxt)
                    disc[nxt] = low[nxt] = timer
                    timer += 1
                    if node == start:
                        root_children += 1
                    stack.append((nxt, iter(adjacency[nxt])))
                    advanced = True
                    break
                if nxt != parent[node]:
                    low[node] = min(low[node], disc[nxt])
            if not advanced:
                stack.pop()
                if stack:
                    p = stack[-1][0]
                    low[p] = min(low[p], low[node])
                    if parent[p] is not None and low[node] >= disc[p]:
                        cut.add(p)
        if root_children >= 2:
            cut.add(start)
    return cut


class TopologyProvider:
    """Surfaces structural cut-vertex candidates for inspection (diagnosis only)."""

    supports_topology_metrics: frozenset[str] = frozenset({"cut_vertices"})

    def analyze(self, graph: DecisionGraph) -> TopologyResult:
        """Surface cut-vertex candidates of the structural undirected projection.

        Degenerate graphs (empty / single node / no cut vertex) return status ok with an
        empty list — a normal result, not a failure. Surfaces candidates for inspection;
        it does not rank, score, or prescribe a disposition.
        """
        adjacency = project_to_undirected(graph)
        cut = find_cut_vertices(adjacency)
        return TopologyResult(status=DeltaStatus.OK, cut_vertices=tuple(sorted(cut)))

    def metric(self, name: str, graph: DecisionGraph) -> TopologyResult:
        """Dispatch by metric name. Unsupported metrics return provider_unavailable + reason.

        The unsupported metric name is never written into a result value (it stays a status).
        """
        if name not in self.supports_topology_metrics:
            return TopologyResult(
                status=DeltaStatus.PROVIDER_UNAVAILABLE,
                reason=f"metric not supported in v0.1: {name}",
            )
        return self.analyze(graph)


def _result_field_names() -> frozenset[str]:
    """Field names of TopologyResult — used by tests to assert the bare-result invariant holds."""
    return frozenset(f.name for f in fields(TopologyResult))
