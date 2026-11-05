"""拓扑判定：数据库元数据标签 + 结构比对（underlying net 签名）。

Owner: sources topology teammate. Public API (frozen in docs/DESIGN.md §6b):

    verify(structure, expected: str) -> dict
        -> {"ok": bool, "evidence": "metadata"|"verified"|"curated"|"mismatch"|"unknown",
            "detail": str, "signature": {...}, "reference": {...}}

    describe(structure) -> dict
    underlying_net(structure) -> dict

判定顺序（诚实性要求，见 DESIGN §5）：

1. **metadata**：显式传入 ``record`` 且数据库元数据标注 == expected；或者结构的
   化学式/原子数/晶胞参数与 CoRE MOF 2024 ASR 的某条 labeled 记录完全一致。
2. **verified**：按结构本身计算 underlying net（金属节点 + 经有机 linker 连接的
   周期图，保留平移向量 = LQG 商图），再与同拓扑参考结构（默认取 CoRE ASR 里
   该拓扑的典型计算就绪 CIF）比较不变量：金属节点配位数分布、配位序列（2–8 层）、
   环大小分布（4–8 元环，按每节点归一化）。全部一致才返回 verified。
3. **mismatch**：元数据或结构签名明确冲突。
4. **unknown**：无金属节点（主族/纯有机体系）、无法获得参考签名、或解析失败。
   这一档绝不返回 True —— 不清楚就是不清楚。

所有比较用的都是**数值不变量**，没有任何"按名字/按 zif-8 硬编码返回 True"的逻辑。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

__all__ = [
    "verify",
    "identify",
    "describe",
    "underlying_net",
    "is_metal_symbol",
    "signature",
    "signature_base",
    "available_reference_nets",
    "load_reference",
    "write_net_reference",
]

# ---------------------------------------------------------------------------
# 元素 / 成键判据
# ---------------------------------------------------------------------------
#: d/f 区 + 碱金属/碱土金属视为可能的金属节点；p 区主族元素（Al/Si/...）不算金属，
#: 这样纯主族/无金属体系会走 unknown 降级而不是硬编造拓扑。
METAL_BLOCKS = frozenset({"d", "f"})
METAL_EXTRA = frozenset({"Li", "Na", "K", "Rb", "Cs", "Be", "Mg", "Ca", "Sr", "Ba"})

_NEIGHBOR_CUTOFF = 3.2  # Å，覆盖 Zr-O(2.1–2.4)、Zn-N(2.0)、Cd-N(2.3) 等
_BOND_FACTOR = 1.25     # d <= (r_i + r_j) * factor，抑制芳香环上的次近邻假键
_RING_SIZES = (4, 5, 6, 7, 8)
_COORD_DEPTH = 8
_CS_MAX_STATES = 8000      # 每个起点的配位序列 BFS 状态上限（防止稠密 net 爆炸）
_RING_PATH_CAP = 20000     # 每个（环大小, 起点）的 DFS 访问上限
_RING_BUDGET = 150000      # 一次环统计的总访问上限

#: 落盘参考签名目录（随包分发：cifkit/data/nets/<net>.json + <net>-reference.cif）
NETS_DATA_DIR = Path(__file__).resolve().parent / "data" / "nets"
REFERENCE_SCHEMA = "cifkit/net-signature/v1"
_SIGNATURE_VERSION = "topology-v2-sbu"


def _element(sym: str):
    from pymatgen.core import Element

    return Element(sym)


def is_metal_symbol(sym: str) -> bool:
    """Return True if ``sym`` is treated as a potential MOF metal node."""
    try:
        el = _element(str(sym).strip())
    except Exception:  # noqa: BLE001 - unknown label
        return False
    if el.block in METAL_BLOCKS:
        return True
    return el.symbol in METAL_EXTRA


def _site_symbol(site) -> str:
    try:
        elems = site.species.elements
        if elems:
            return elems[0].symbol
    except Exception:  # noqa: BLE001
        pass
    return str(site.species_string)


def _atomic_radius(sym: str) -> float:
    try:
        radius = _element(sym).atomic_radius
    except Exception:  # noqa: BLE001
        radius = None
    return float(radius) if radius else 1.0


# ---------------------------------------------------------------------------
# 周期成键图
# ---------------------------------------------------------------------------
def _bond_graph(structure) -> tuple[dict[int, list[tuple[int, tuple[int, int, int]]]], list[str], list[str]]:
    """Build the periodic bond graph.

    Returns ``(adjacency, elements, warnings)`` where every adjacency entry is
    ``(neighbor_index, offset)`` and the neighbor's position is
    ``structure[neighbor_index].frac_coords + offset`` (in lattice units).
    """
    warnings: list[str] = []
    elements = [_site_symbol(s) for s in structure]
    adjacency: dict[int, list[tuple[int, tuple[int, int, int]]]] = defaultdict(list)
    try:
        centers, points, offsets, distances = structure.get_neighbor_list(_NEIGHBOR_CUTOFF)
    except Exception as exc:  # noqa: BLE001 - degenerate cells etc.
        return adjacency, elements, [f"邻居表构建失败：{type(exc).__name__}: {exc}"]
    radii: dict[str, float] = {}
    for i, j, off, dist in zip(centers, points, offsets, distances):
        ei, ej = elements[int(i)], elements[int(j)]
        ri = radii.get(ei)
        if ri is None:
            ri = radii[ei] = _atomic_radius(ei)
        rj = radii.get(ej)
        if rj is None:
            rj = radii[ej] = _atomic_radius(ej)
        if float(dist) <= (ri + rj) * _BOND_FACTOR:
            adjacency[int(i)].append((int(j), (int(off[0]), int(off[1]), int(off[2]))))
    return adjacency, elements, warnings


# ---------------------------------------------------------------------------
# underlying net（LQG：节点 + 经 linker 的连接 + 平移向量）
# ---------------------------------------------------------------------------
def _nonmetal_components(adjacency, elements, metal_set) -> list[dict[str, Any]]:
    """去掉金属后的非金属连通分量 = 有机 linker 分子或无机桥连单元。

    对每个分量沿成键图传播平移量（整数组），得到"分量根 frame"下的金属配位点
    ``(metal_index, translation)``；跨晶胞边界的分子也能正确还原。
    """
    visited: set[int] = set()
    components: list[dict[str, Any]] = []
    for start in range(len(elements)):
        if start in metal_set or start in visited:
            continue
        atoms: list[int] = []
        queue = deque([start])
        visited.add(start)
        while queue:
            atom = queue.popleft()
            atoms.append(atom)
            for nb, _off in adjacency.get(atom, ()):
                if nb in metal_set or nb in visited:
                    continue
                visited.add(nb)
                queue.append(nb)
        shifts: dict[int, tuple[int, int, int]] = {atoms[0]: (0, 0, 0)}
        queue = deque([atoms[0]])
        consistent = True
        while queue:
            atom = queue.popleft()
            base = shifts[atom]
            for nb, off in adjacency.get(atom, ()):
                if nb in metal_set:
                    continue
                shifted = (base[0] + off[0], base[1] + off[1], base[2] + off[2])
                if nb in shifts:
                    if shifts[nb] != shifted:
                        consistent = False
                else:
                    shifts[nb] = shifted
                    queue.append(nb)
        attachments: set[tuple[int, tuple[int, int, int]]] = set()
        if consistent:
            for atom in atoms:
                base = shifts[atom]
                for nb, off in adjacency.get(atom, ()):
                    if nb in metal_set:
                        # metal 在该分量 frame 下的整数平移：neighbor image shift = off + atom_shift
                        attachments.add((int(nb), (off[0] + base[0], off[1] + base[1], off[2] + base[2])))
        components.append(
            {
                "atoms": atoms,
                "consistent": consistent,
                "has_carbon": any(elements[atom] == "C" for atom in atoms),
                "attachments": attachments,
            }
        )
    return components


def _build_net_impl(structure, *, sbu: bool = True):
    """Return ``(net, reason)``; ``net`` is None when no metal node exists.

    ``sbu=True``：Round2 v2 实现，含 **SBU/金属簇收缩** ——
    * 金属–金属直接键、以及无碳无机桥连单元（μ-O/μ-OH/μ-F/μ-Cl…，连到 ≥2 个金属）
      把相关金属并成同一个 net 节点（如 MOF-5 的 Zn4O、UiO-66 的 Zr6O4(OH)4、
      HKUST-1 的 Cu2 paddlewheel）；
    * 含碳的有机 linker 仍作为连接边，边两端是"金属簇节点"；
    * 孤立金属簇不算节点；平移量（LQG shift）按各节点内部金属的整数平移传播计算。

    ``sbu=False``：Round1 v1 表示（每个金属原子一个节点，所有非金属分量都当 linker），
    用于 SBU 收缩后没有任何有机 linker 连接的无机/离子体系回退。
    """
    adjacency, elements, warnings = _bond_graph(structure)
    metals = [i for i, sym in enumerate(elements) if is_metal_symbol(sym)]
    if not metals:
        return None, {
            "reason": "未识别到金属节点（主族元素/无金属体系），本工具不做拓扑断言",
            "warnings": warnings,
        }
    metal_set = set(metals)
    components = _nonmetal_components(adjacency, elements, metal_set)

    # ------------------------------------------------------------------
    # 1) 金属簇（SBU）划分：union-find（v1 模式下每个金属单独一个节点）
    # ------------------------------------------------------------------
    parent: dict[int, int] = {m: m for m in metals}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_a] = root_b

    if sbu:
        for metal in metals:
            for nb, _off in adjacency.get(metal, ()):
                if nb in metal_set and nb != metal:
                    union(metal, nb)
        for comp in components:
            if not comp["consistent"] or comp["has_carbon"]:
                continue
            attached_metals = {metal for metal, _t in comp["attachments"]}
            if len(attached_metals) >= 2:
                ordered = sorted(attached_metals)
                for metal in ordered[1:]:
                    union(ordered[0], metal)

    raw_groups: dict[int, list[int]] = defaultdict(list)
    for metal in metals:
        raw_groups[find(metal)].append(metal)
    # rep = 最小原子编号，保证索引确定性
    cluster_members = {min(members): sorted(members) for members in raw_groups.values()}

    # ------------------------------------------------------------------
    # 2) 簇内整数平移量：通过金属–金属键 / 无机桥连分量传播
    # ------------------------------------------------------------------
    cluster_of: dict[int, int] = {}
    shift_of: dict[int, tuple[int, int, int]] = {}
    if sbu:
        relations: dict[int, list[tuple[int, tuple[int, int, int]]]] = defaultdict(list)
        for metal in metals:
            for nb, off in adjacency.get(metal, ()):
                if nb in metal_set and nb != metal:
                    relations[metal].append((int(nb), (int(off[0]), int(off[1]), int(off[2]))))
        for comp in components:
            if not comp["consistent"] or comp["has_carbon"]:
                continue
            attachments = sorted(comp["attachments"])
            if len(attachments) < 2:
                continue
            (m0, t0) = attachments[0]
            for metal, t in attachments[1:]:
                delta = (t[0] - t0[0], t[1] - t0[1], t[2] - t0[2])
                relations[m0].append((metal, delta))
                relations[metal].append((m0, (-delta[0], -delta[1], -delta[2])))

        for rep, members in cluster_members.items():
            member_set = set(members)
            assigned: dict[int, tuple[int, int, int]] = {rep: (0, 0, 0)}
            queue = deque([rep])
            ok = True
            while queue:
                atom = queue.popleft()
                base = assigned[atom]
                for nb, delta in relations.get(atom, ()):
                    if nb not in member_set:
                        continue
                    shifted = (base[0] + delta[0], base[1] + delta[1], base[2] + delta[2])
                    if nb in assigned:
                        if assigned[nb] != shifted:
                            ok = False
                    else:
                        assigned[nb] = shifted
                        queue.append(nb)
            if not ok or len(assigned) != len(members):
                warnings.append(f"金属簇内部平移不一致，退回逐金属节点：{members}")
                for metal in members:
                    cluster_of[metal] = metal
                    shift_of[metal] = (0, 0, 0)
            else:
                for metal in members:
                    cluster_of[metal] = rep
                    shift_of[metal] = assigned.get(metal, (0, 0, 0))
    else:
        for metal in metals:
            cluster_of[metal] = metal
            shift_of[metal] = (0, 0, 0)

    members_by_cluster: dict[int, list[int]] = defaultdict(list)
    for metal in metals:
        members_by_cluster[cluster_of[metal]].append(metal)

    frac = np.asarray([site.frac_coords for site in structure], dtype=float)
    nodes_by_id: dict[int, dict[str, Any]] = {}
    for rep in sorted(members_by_cluster):
        members = sorted(members_by_cluster[rep])
        positions = [frac[metal] + np.asarray(shift_of[metal], dtype=float) for metal in members]
        center = np.mean(positions, axis=0)
        symbols = {elements[metal] for metal in members}
        nodes_by_id[rep] = {
            "index": int(rep),
            "element": symbols.pop() if len(symbols) == 1 else "+".join(sorted(symbols)),
            "frac": [float(x) for x in np.round(center, 6)],
            "members": members,
            "size": len(members),
        }

    # ------------------------------------------------------------------
    # 3) 含碳有机 linker → 连接不同金属簇节点的边（LQG shift）
    # ------------------------------------------------------------------
    edges: dict[int, list[tuple[int, tuple[int, int, int]]]] = defaultdict(list)
    linkers: list[dict[str, Any]] = []
    n_linkers = 0
    for comp in components:
        if not comp["consistent"]:
            warnings.append(f"跳过非分子性（周期/聚合物）有机组分：{len(comp['atoms'])} 个原子")
            continue
        if sbu and not comp["has_carbon"]:
            # 无碳无机桥已用于簇收缩；端基（只连 1 个金属）忽略
            continue
        sites: set[tuple[int, tuple[int, int, int]]] = set()
        for metal, t in comp["attachments"]:
            cluster = cluster_of[metal]
            s = shift_of[metal]
            sites.add((int(cluster), (t[0] - s[0], t[1] - s[1], t[2] - s[2])))
        if len(sites) < 2:
            continue
        n_linkers += 1
        linkers.append({"atoms": sorted(comp["atoms"]), "n_attachment_sites": len(sites)})
        ordered_sites = sorted(sites)
        for x in range(len(ordered_sites)):
            for y in range(x + 1, len(ordered_sites)):
                (c1, t1), (c2, t2) = ordered_sites[x], ordered_sites[y]
                shift = (t2[0] - t1[0], t2[1] - t1[1], t2[2] - t1[2])
                edges[c1].append((c2, shift))
                edges[c2].append((c1, (-shift[0], -shift[1], -shift[2])))

    # ------------------------------------------------------------------
    # 4) 无连接节点（孔道里的孤立离子/孤立簇）排除出 net
    # ------------------------------------------------------------------
    connected = [cluster for cluster in nodes_by_id if edges.get(cluster)]
    isolated = len(nodes_by_id) - len(connected)
    if isolated:
        warnings.append(f"{isolated} 个金属节点（簇）没有通过有机 linker 连接，已排除出 net")

    nodes = [nodes_by_id[cluster] for cluster in sorted(connected)]
    centers = {node["index"]: np.asarray(node["frac"], dtype=float) for node in nodes}
    edge_list: list[dict[str, Any]] = []
    lattice = structure.lattice
    for cluster in sorted(connected):
        for nb, shift in edges.get(cluster, ()):
            if nb not in centers:
                continue
            delta = centers[nb] + np.asarray(shift, dtype=float) - centers[cluster]
            length = float(np.linalg.norm(lattice.get_cartesian_coords(delta)))
            edge_list.append(
                {"i": int(cluster), "j": int(nb), "shift": [int(s) for s in shift], "length": round(length, 3)}
            )

    net = {
        "nodes": nodes,
        "edges": edge_list,
        "linkers": linkers,
        "n_nodes": len(nodes),
        "n_edges": len(edge_list) // 2,
        "n_linkers": n_linkers,
        "warnings": warnings,
        "sbu_contraction": bool(sbu),
    }
    return net, None


def _build_net(structure):
    """net 构建入口：优先 SBU 收缩表示；无机/离子体系退回逐金属节点表示。"""
    net, reason = _build_net_impl(structure, sbu=True)
    if net is None:
        return None, reason
    if net["n_edges"] == 0:
        fallback, _fallback_reason = _build_net_impl(structure, sbu=False)
        if fallback is not None and fallback["n_edges"] > 0:
            fallback["warnings"].append(
                "SBU 收缩后没有有机 linker 连接（离子/无机体系？），退回逐金属节点表示"
            )
            return fallback, None
    return net, None


def underlying_net(structure) -> dict:
    """金属节点 + 经有机 linker 连接的周期图（节点、边、平移、linker 摘要）。

    返回 dict 总是包含 ``nodes/edges/linkers/n_nodes/n_edges/n_linkers/warnings``；
    无金属体系时列表为空、``warnings`` 里写明原因（不抛异常）。
    """
    net, reason = _build_net(structure)
    if net is None:
        return {
            "nodes": [],
            "edges": [],
            "linkers": [],
            "n_nodes": 0,
            "n_edges": 0,
            "n_linkers": 0,
            "warnings": reason.get("warnings", []) + [reason.get("reason", "")],
        }
    return net


def _edges_by_node(net: dict) -> dict[int, list[tuple[int, tuple[int, int, int]]]]:
    edges: dict[int, list[tuple[int, tuple[int, int, int]]]] = defaultdict(list)
    for edge in net["edges"]:
        edges[edge["i"]].append((edge["j"], tuple(edge["shift"])))
    return edges


# ---------------------------------------------------------------------------
# 结构不变量
# ---------------------------------------------------------------------------
def _coordination_sequence(edges, metals, depth: int = _COORD_DEPTH, max_states: int = _CS_MAX_STATES):
    rows: list[list[int]] = []
    truncated = False
    for metal in metals:
        start = (metal, (0, 0, 0))
        seen = {start}
        frontier = {start}
        row: list[int] = []
        for _ in range(depth):
            nxt: set[tuple[int, tuple[int, int, int]]] = set()
            for node, shift in frontier:
                for nb, off in edges.get(node, ()):
                    state = (nb, (shift[0] + off[0], shift[1] + off[1], shift[2] + off[2]))
                    if state not in seen:
                        seen.add(state)
                        nxt.add(state)
            row.append(len(nxt))
            frontier = nxt
            if len(seen) > max_states:
                truncated = True
                break
        rows.append(row)
    if not rows:
        return [], False
    width = min(len(r) for r in rows)
    mean = [float(np.mean([row[k] for row in rows])) for k in range(width)]
    return [round(v, 3) for v in mean], truncated


def _canonical_cycle(cycle: list[tuple[int, tuple[int, int, int]]]):
    n = len(cycle)
    idxs = [int(c[0]) for c in cycle]
    shifts = [tuple(int(x) for x in c[1]) for c in cycle]
    best = None
    for direction in (1, -1):
        for start in range(n):
            seq = []
            for k in range(n):
                pos = (start + direction * k) % n
                rel = tuple(shifts[pos][t] - shifts[start][t] for t in range(3))
                seq.append((idxs[pos], rel))
            tup = tuple(seq)
            if best is None or tup < best:
                best = tup
    return best


def _ring_stats(
    edges,
    metals,
    sizes=_RING_SIZES,
    *,
    max_paths: int = _RING_PATH_CAP,
    budget: int = _RING_BUDGET,
):
    """统计每个金属节点参与的各元环数量（周期环，平移矢量和为 0）。

    高配位/稠密 net 上环枚举会爆炸，所以有 DFS 访问上限；一旦触顶就把该环大小标
    ``truncated=True``（调用方据此降级为 unknown，不会拿不完整签名冒充 verified）。
    """
    out: dict[str, dict[str, Any]] = {}
    n = len(metals)
    total_visits = 0
    for size in sizes:
        found: set = set()
        truncated = False
        for start_metal in metals:
            if total_visits >= budget:
                truncated = True
                break
            start = (start_metal, (0, 0, 0))
            path = [start]
            path_set = {start}
            visits = 0

            def dfs(state) -> None:  # noqa: ANN001 - nested recursion
                nonlocal visits, total_visits, truncated
                visits += 1
                total_visits += 1
                if visits > max_paths or total_visits > budget:
                    truncated = True
                    return
                if len(path) == size:
                    for nb, off in edges.get(state[0], ()):
                        nxt = (nb, (state[1][0] + off[0], state[1][1] + off[1], state[1][2] + off[2]))
                        if nxt == start:
                            found.add(_canonical_cycle(path))
                    return
                for nb, off in edges.get(state[0], ()):
                    nxt = (nb, (state[1][0] + off[0], state[1][1] + off[1], state[1][2] + off[2]))
                    if nxt in path_set:
                        continue
                    path.append(nxt)
                    path_set.add(nxt)
                    dfs(nxt)
                    path.pop()
                    path_set.remove(nxt)

            dfs(start)
        # 每个环会被环上 size 个节点各数一次 → 先得到每晶胞环数，再按节点归一化
        rings_per_cell = len(found) / size if found else 0.0
        out[str(size)] = {
            "per_cell": round(rings_per_cell, 4),
            "per_node": round(rings_per_cell / n, 6) if n else 0.0,
            "truncated": bool(truncated),
        }
        if truncated:
            break
    return out


def signature_base(net: dict) -> dict | None:
    """便宜的签名部分：配位数分布 + 配位序列 + linker 比例（不做环枚举）。"""
    metals = [node["index"] for node in net["nodes"]]
    if not metals:
        return None
    edges = _edges_by_node(net)
    coordination = Counter(len(edges.get(m, ())) for m in metals)
    n = len(metals)
    cs, truncated = _coordination_sequence(edges, metals)
    return {
        "coordination_numbers": {str(k): round(v / n, 6) for k, v in sorted(coordination.items())},
        "coordination_sequence": cs,
        "coordination_sequence_truncated": bool(truncated),
        "n_metal_nodes": n,
        "n_edges": int(net.get("n_edges", 0)),
        "n_linkers": int(net.get("n_linkers", 0)),
        "linkers_per_metal": round(net.get("n_edges", 0) / n, 6) if n else 0.0,
    }


def signature(net: dict) -> dict | None:
    """由 underlying net 计算完整不变量签名（含环分布）；无节点返回 None。"""
    base = signature_base(net)
    if base is None:
        return None
    metals = [node["index"] for node in net["nodes"]]
    edges = _edges_by_node(net)
    rings = _ring_stats(edges, metals)
    rings_truncated = any(item.get("truncated") for item in rings.values())
    base.update(
        {
            "ring_sizes": [int(s) for s in _RING_SIZES],
            "rings_per_node": rings,
            "rings_truncated": bool(rings_truncated),
        }
    )
    return base


def describe(structure) -> dict:
    """人类可读的结构 + net 摘要（含完整 signature），不抛异常。"""
    info: dict[str, Any] = {
        "formula": structure.composition.formula,
        "natoms": len(structure),
        "lattice": {
            "abc": [round(float(x), 4) for x in structure.lattice.abc],
            "angles": [round(float(x), 4) for x in structure.lattice.angles],
        },
        "metals": [],
        "signature": None,
        "warnings": [],
    }
    net = underlying_net(structure)
    info["warnings"] = list(net.get("warnings", []))
    info["metals"] = sorted({node["element"] for node in net["nodes"]})
    info["net"] = {
        "n_nodes": net["n_nodes"],
        "n_edges": net["n_edges"],
        "n_linkers": net["n_linkers"],
    }
    info["signature"] = signature(net)
    return info


# ---------------------------------------------------------------------------
# 落盘参考签名（cifkit/data/nets/<net>.json + <net>-reference.cif）
# ---------------------------------------------------------------------------
#: 落盘参考的进程内缓存（key = 小写 net code）
_BUNDLED_CACHE: dict[str, dict | None] = {}


def _normalize_net(net: str) -> str:
    return str(net or "").strip().lower()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def available_reference_nets() -> list[str]:
    """已落盘的参考 net code 列表（如 ``["bcu","dia","fcu","pcu","sod","tbo"]``）。"""
    if not NETS_DATA_DIR.is_dir():
        return []
    return sorted(path.stem for path in NETS_DATA_DIR.glob("*.json"))


def load_reference(net: str) -> dict | None:
    """加载落盘参考签名；未落盘/损坏返回 None。

    返回 dict 与 ``verify`` 的 ``reference`` 字段同形状，并额外带
    ``bundled=True`` / ``reference_json`` / ``cif_path``（便于溯源审计）。
    """
    key = _normalize_net(net)
    if key in _BUNDLED_CACHE:
        return _BUNDLED_CACHE[key]
    path = NETS_DATA_DIR / f"{key}.json"
    reference: dict | None = None
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            signature_payload = payload.get("signature")
            if payload.get("schema") == REFERENCE_SCHEMA and isinstance(signature_payload, dict):
                source = payload.get("source") or {}
                cif_name = payload.get("cif")
                reference = {
                    "source": source.get("record_id") or f"bundled:{key}",
                    "record_id": source.get("record_id"),
                    "topology": payload.get("net", key),
                    "topology_evidence": "metadata",
                    "doi": source.get("doi"),
                    "refcode": source.get("refcode"),
                    "coreid": source.get("coreid"),
                    "bundled": True,
                    "signature_version": payload.get("signature_version"),
                    "reference_json": str(path),
                    "cif_path": str(NETS_DATA_DIR / cif_name) if cif_name else None,
                    "signature": signature_payload,
                }
        except Exception:  # noqa: BLE001 - 损坏的参考 JSON 当作缺失
            reference = None
    _BUNDLED_CACHE[key] = reference
    return reference


def write_net_reference(
    net: str,
    structure,
    *,
    record_id: str,
    cif_bytes: bytes | None = None,
    cif_filename: str | None = None,
    refcode: str | None = None,
    coreid: str | None = None,
    doi: str | None = None,
    natoms: int | None = None,
    formula: str | None = None,
    spacegroup: str | None = None,
    selection_reason: str = "",
    generator_command: str | None = None,
    outdir: str | Path | None = None,
) -> Path:
    """把某一 net 的参考签名（可选连同参考 CIF）落盘到 ``cifkit/data/nets/``。

    生成侧使用（需要 pymatgen 结构；运行时不依赖本函数）。记录来源 record_id /
    refcode / DOI / 原子数 / 空间群、生成时间与生成命令，便于审计。
    """
    net_key = _normalize_net(net)
    info = underlying_net(structure)
    signature_payload = signature(info)
    if signature_payload is None:
        raise ValueError(f"结构 {record_id!r} 没有可用的金属节点网络，不能生成 {net_key} 参考签名")
    out = Path(outdir) if outdir is not None else NETS_DATA_DIR
    out.mkdir(parents=True, exist_ok=True)
    cif_name = cif_filename or f"{net_key}-reference.cif"
    cif_sha = None
    if cif_bytes is not None:
        target = out / cif_name
        target.write_bytes(cif_bytes)
        cif_sha = hashlib.sha256(cif_bytes).hexdigest()
    payload = {
        "schema": REFERENCE_SCHEMA,
        "net": net_key,
        "signature_version": _SIGNATURE_VERSION,
        "source": {
            "record_id": record_id,
            "refcode": refcode,
            "coreid": coreid,
            "doi": doi,
            "natoms": natoms if natoms is not None else len(structure),
            "formula": formula if formula is not None else structure.composition.formula,
            "spacegroup": spacegroup,
        },
        "cif": cif_name if cif_bytes is not None else None,
        "cif_sha256": cif_sha,
        "signature": signature_payload,
        "net_summary": {
            "n_nodes": info["n_nodes"],
            "n_edges": info["n_edges"],
            "n_linkers": info["n_linkers"],
            "sbu_contraction": info.get("sbu_contraction", False),
            "warnings": info["warnings"],
        },
        "generated_at": _now(),
        "generated_by": {
            "algorithm": _SIGNATURE_VERSION,
            "command": generator_command or "<未记录>",
        },
        "selection_reason": selection_reason,
    }
    json_path = out / f"{net_key}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _BUNDLED_CACHE.pop(net_key, None)
    return json_path


#: 落盘参考的选取来源（生成侧元数据；运行时不读取 CoRE zip）。
#: 每条记录都要求：CoRE 2024 ASR 的 topology(AllNodes)==net 且为 computation-ready。
BUNDLED_REFERENCE_SOURCES: dict[str, dict[str, str]] = {
    "sod": {
        "zip_path": "SI/CR/ASR/2015[Zn][sod]3[ASR]1.cif",
        "reason": (
            "ZIF-8（Zn(2-甲基咪唑)2，RCSR sod，CoRE ASR 计算就绪、H 完整，138 原子）；"
            "用于核实 NCR 原始缺氢 ZIF-8 的 sod 拓扑"
        ),
    },
    "pcu": {
        "zip_path": "SI/CR/ASR/2007[Zn][pcu]3[ASR]3.cif",
        "reason": (
            "Zn4O(BDC)3 = MOF-5（Zn8 H24 C48 O26 = 2×MOF-5，topology(AllNodes)=pcu）；"
            "任务建议的 2015[Zn][pcu]3[ASR]2 经核查不是 MOF-5：它是多齿 PAH 配体 + Zn4 簇"
            "（AllNodes 标注 scn），按 ditopic-linker 简化会得到 30 配位假 net，故不采用"
        ),
    },
    "dia": {
        "zip_path": "SI/CR/ASR/2017[Ni][dia]3[ASR]3.cif",
        "reason": (
            "Ni 基 dia 拓扑 MOF（54 原子，小体系）；contract 后 4 配位、配位序列与环分布完整，"
            "适合作为 dia 参考指纹"
        ),
    },
    "fcu": {
        "zip_path": "SI/CR/ASR/2015[Zr][fcu]3[ASR]1.cif",
        "reason": (
            "UiO-66（Zr6O4(OH)4(BDC)6，Zr6 H28 C48 O32，114 原子，topology(AllNodes)=fcu）；"
            "SBU 收缩后 12 配位 fcu 节点"
        ),
    },
    "tbo": {
        "zip_path": "SI/CR/ASR/2020[Cu][tbo]3[ASR]1.cif",
        "reason": (
            "HKUST-1（Cu3(BTC)2，Cu12 H24 C72 O48 = 4×HKUST-1，topology(AllNodes)=tbo）；"
            "Cu2 paddlewheel 收缩后 8 配位金属 net"
        ),
    },
    "bcu": {
        "zip_path": "SI/CR/ASR/2018[Zr][bcu]3[ASR]1.cif",
        "reason": (
            "Zr6 基 bcu MOF（Zr6 H16 C24 O24，topology(AllNodes)=bcu）；SBU 收缩后 8 配位，"
            "配位序列与 tbo/pcu 可区分"
        ),
    },
}


def _spacegroup_from_cif_bytes(data: bytes) -> str | None:
    head = data[:4096].decode("utf-8", "replace")
    match = re.search(r"_symmetry_space_group_name_H-M\s+['\"]?([^'\"\n]+)", head) or re.search(
        r"_space_group_name_H-M_alt\s+['\"]?([^'\"\n]+)", head
    )
    return match.group(1).strip() if match else None


def regenerate_bundled_references(
    *, outdir: str | Path | None = None, nets: list[str] | None = None
) -> list[str]:
    """从 CoRE MOF 2024 本地缓存重建 ``cifkit/data/nets/*.json``（**生成侧工具**）。

    运行时不依赖本函数；它需要 pymatgen + CoRE zip 缓存。生成命令（可复现）::

        python -c "from cifkit.topology import regenerate_bundled_references as r; print(r())"

    返回写出的 JSON 路径列表。
    """
    from cifkit.sources import core_mof

    wanted = [_normalize_net(net) for net in nets] if nets else list(BUNDLED_REFERENCE_SOURCES)
    index = core_mof.load_index()
    outputs: list[str] = []
    for net in wanted:
        spec = BUNDLED_REFERENCE_SOURCES.get(net)
        if spec is None:
            raise KeyError(f"没有 {net!r} 的落盘参考来源配置（BUNDLED_REFERENCE_SOURCES）")
        member = spec["zip_path"]
        data = core_mof.read_cif_bytes(member)
        structure = core_mof.structure_from_cif_bytes(data, label=member)
        entry = index["entries"].get(member, {})
        path = write_net_reference(
            net,
            structure,
            record_id=f"core-mof:{member}",
            cif_bytes=data,
            refcode=entry.get("refcode"),
            coreid=entry.get("coreid"),
            doi=entry.get("doi"),
            natoms=len(structure),
            formula=structure.composition.formula,
            spacegroup=_spacegroup_from_cif_bytes(data),
            selection_reason=spec["reason"],
            generator_command=(
                "python -c \"from cifkit.topology import regenerate_bundled_references as r; print(r())\""
            ),
            outdir=outdir,
        )
        outputs.append(str(path))
    return outputs


# ---------------------------------------------------------------------------
# 参考结构 + 元数据指纹（与 CoRE MOF 2024 缓存解耦：缺失时优雅降级）
# ---------------------------------------------------------------------------
_REFERENCE_CACHE: dict[str, dict | None] = {}


def _reference_from_object(reference) -> dict | None:
    if reference is None:
        return None
    if isinstance(reference, dict):
        if isinstance(reference.get("signature"), dict):
            return {
                "source": reference.get("source", "provided"),
                "record_id": reference.get("record_id"),
                "topology": reference.get("topology"),
                "signature": reference["signature"],
            }
        return None
    if hasattr(reference, "lattice") and hasattr(reference, "sites"):
        structure = reference
    else:
        path = Path(str(reference)).expanduser()
        if not path.is_file():
            return None
        from pymatgen.core import Structure

        structure = Structure.from_file(str(path))
    sig = signature(underlying_net(structure))
    if sig is None:
        return None
    return {
        "source": "reference structure",
        "record_id": str(reference),
        "topology": None,
        "signature": sig,
    }


def _resolve_reference(expected: str, reference=None) -> dict | None:
    provided = _reference_from_object(reference)
    if provided is not None:
        provided.setdefault("topology", expected)
        return provided
    if expected in _REFERENCE_CACHE:
        return _REFERENCE_CACHE[expected]
    # 优先用随包落盘的参考签名（离线、无需 CoRE zip）
    bundled = load_reference(expected)
    if bundled is not None:
        _REFERENCE_CACHE[expected] = bundled
        return bundled
    resolved = None
    try:
        from cifkit.sources import core_mof

        for cand in core_mof.reference_candidates(expected):
            try:
                structure = core_mof.load_structure(cand["zip_path"])
            except Exception:  # noqa: BLE001 - try next candidate
                continue
            sig = signature(underlying_net(structure))
            if sig is None:
                continue
            resolved = {
                "source": f"CoRE MOF 2024 CR/ASR 元数据（topology(AllNodes)=={expected}）",
                "record_id": cand.get("record_id"),
                "zip_path": cand.get("zip_path"),
                "topology": expected,
                "topology_evidence": "metadata",
                "doi": cand.get("doi"),
                "signature": sig,
            }
            break
    except Exception:  # noqa: BLE001 - no cache / no network => unresolved
        resolved = None
    _REFERENCE_CACHE[expected] = resolved
    return resolved


def _core_metadata_fingerprint(structure) -> dict | None:
    """与 CoRE ASR labeled 记录做化学式/原子数/晶胞参数指纹匹配（唯一且无冲突时）。"""
    try:
        from cifkit.sources import core_mof

        return core_mof.find_metadata_record(structure)
    except Exception:  # noqa: BLE001 - cache absent or parse issue
        return None


def _result(ok: bool, evidence: str, detail: str, sig: dict | None, reference: dict | None) -> dict:
    return {
        "ok": bool(ok),
        "evidence": evidence,
        "detail": detail,
        "signature": sig,
        "reference": reference,
    }


def _sig_summary(sig: dict | None) -> str:
    if not sig:
        return "签名不可用"
    cn = ", ".join(f"{k}-配位×{v:.2f}" for k, v in sig.get("coordination_numbers", {}).items())
    cs = ", ".join(f"{v:g}" for v in sig.get("coordination_sequence", []))
    rings_map = sig.get("rings_per_node") or {}
    rings = ", ".join(
        f"{k}元环/节点={v['per_node']:.3f}"
        for k, v in rings_map.items()
        if isinstance(v, dict) and v.get("per_node", 0) > 0
    )
    tail = f"；环分布[{rings or '无4-8元环'}]"
    if not rings_map:
        tail = "；环分布[未计算]"
    return f"配位数[{cn}]；配位序列[2-8层: {cs}]{tail}"


def _compare_base(sig: dict, ref_sig: dict) -> tuple[bool, list[str], list[str]]:
    """比较"便宜"部分：配位数分布、配位序列（2-8 层）、linker/金属比。"""
    issues: list[str] = []
    notes: list[str] = []

    # 1) 配位数分布
    cn_a, cn_b = sig["coordination_numbers"], ref_sig["coordination_numbers"]
    for key in sorted(set(cn_a) | set(cn_b)):
        a, b = cn_a.get(key, 0.0), cn_b.get(key, 0.0)
        if abs(a - b) > 1e-6:
            issues.append(f"金属配位数 {key} 的节点占比不同（目标 {a:.3f} vs 参考 {b:.3f}）")

    # 2) 配位序列（2-8 层）
    cs_a, cs_b = sig["coordination_sequence"], ref_sig["coordination_sequence"]
    depth = min(len(cs_a), len(cs_b))
    if depth == 0:
        issues.append("配位序列为空")
    for k in range(depth):
        a, b = cs_a[k], cs_b[k]
        tol = max(0.05, 0.005 * max(abs(a), abs(b), 1.0))
        if abs(a - b) > tol:
            issues.append(f"配位序列第 {k + 2} 层不同（目标 {a:.2f} vs 参考 {b:.2f}）")
    if len(cs_a) != len(cs_b):
        notes.append(f"配位序列深度不同（目标 {len(cs_a)} 层 vs 参考 {len(cs_b)} 层），比较了前 {depth} 层")

    # 3) linker/metal 比例（顺手的一致性检查）
    a, b = sig.get("linkers_per_metal", 0.0), ref_sig.get("linkers_per_metal", 0.0)
    if abs(a - b) > 1e-6:
        issues.append(f"linker/金属比不同（目标 {a:.3f} vs 参考 {b:.3f}）")

    return (not issues), issues, notes


def _compare_rings(sig: dict, ref_sig: dict) -> tuple[bool, list[str]]:
    """比较环大小分布（按节点归一化，消除原胞/常规胞倍数差异）。"""
    issues: list[str] = []
    rings_a = sig["rings_per_node"]
    rings_b = ref_sig["rings_per_node"]
    for size in sorted(set(rings_a) | set(rings_b), key=int):
        a = rings_a.get(size, {}).get("per_node", 0.0)
        b = rings_b.get(size, {}).get("per_node", 0.0)
        if abs(a - b) > 5e-3:
            issues.append(f"{size} 元环（每节点）不同（目标 {a:.4f} vs 参考 {b:.4f}）")
    return (not issues), issues


# ---------------------------------------------------------------------------
# 公开入口
# ---------------------------------------------------------------------------
#: verify 结果的进程内缓存：sources 检索时已核实过的结构，pipeline 的
#: verify-topology 步骤再核实一次时直接命中，避免重复解析/环统计。
_VERIFY_CACHE: dict[tuple, dict] = {}
_VERIFY_CACHE_MAX = 96


def clear_cache() -> None:
    """Drop the in-process verify/reference/落盘参考 caches (tests, long-running workers)."""
    _VERIFY_CACHE.clear()
    _REFERENCE_CACHE.clear()
    _BUNDLED_CACHE.clear()


def _structure_cache_key(structure, expected: str):
    try:
        composition = tuple(
            sorted(
                (str(element), round(float(amount), 6))
                for element, amount in structure.composition.as_dict().items()
            )
        )
        lattice = tuple(round(float(x), 3) for x in structure.lattice.abc) + tuple(
            round(float(x), 2) for x in structure.lattice.angles
        )
        # 化学式 + 晶胞可能相同而原子排布不同（多晶型），所以再加一个坐标指纹
        coords = structure.frac_coords
        payload = ";".join(
            f"{_site_symbol(site)}:{coords[i][0]:.4f},{coords[i][1]:.4f},{coords[i][2]:.4f}"
            for i, site in enumerate(structure)
        )
        digest = hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()[:16]
        return (expected, composition, len(structure), lattice, digest)
    except Exception:  # noqa: BLE001 - caching is best-effort only
        return None


def verify(structure, expected: str, *, record=None, reference=None) -> dict:
    """核实 ``structure`` 的拓扑是否为 ``expected``（RCSR code，如 ``sod``）。

    参数
    ----
    structure : pymatgen Structure
    expected : str
        期望拓扑（RCSR 小写 code）。
    record : StructureRecord, optional
        若提供且其数据库元数据标注与 expected 一致，可直接按 metadata 证据返回。
    reference : Structure | str | Path | dict, optional
        显式参考结构/参考签名；缺省时自动从 CoRE MOF 2024 CR/ASR 元数据里找该
        拓扑的典型计算就绪结构。

    返回 dict（见模块 docstring）。``ok and evidence == "verified"`` 才表示
    "结构比对通过"；证据等级绝不混用。
    """
    expected = str(expected or "").strip().lower()
    use_cache = record is None and reference is None
    cache_key = _structure_cache_key(structure, expected) if use_cache else None
    if cache_key is not None and cache_key in _VERIFY_CACHE:
        return copy.deepcopy(_VERIFY_CACHE[cache_key])
    result = _verify_impl(structure, expected, record=record, reference=reference)
    if cache_key is not None:
        if len(_VERIFY_CACHE) >= _VERIFY_CACHE_MAX:
            _VERIFY_CACHE.clear()
        _VERIFY_CACHE[cache_key] = copy.deepcopy(result)
    return result


def _metadata_only_signature(base_getter) -> dict | None:
    """Metadata 证据路径的签名：只含便宜的配位数/配位序列，不枚举环。"""
    base = base_getter()
    if base is None:
        return None
    return {
        **base,
        "ring_sizes": [int(s) for s in _RING_SIZES],
        "rings_per_node": {},
        "rings_truncated": False,
        "rings_note": "元数据证据路径，未计算环统计（metadata 证据不依赖环分布）",
    }


def _verify_impl(structure, expected: str, *, record=None, reference=None) -> dict:
    expected = str(expected or "").strip().lower()
    if not expected:
        return _result(False, "unknown", "未给出期望拓扑（expected 为空）", None, None)

    state: dict[str, Any] = {"net": None, "base": None, "warnings": []}

    def ensure_base() -> dict | None:
        if state["base"] is not None:
            return state["base"]
        try:
            net = underlying_net(structure)
        except Exception as exc:  # noqa: BLE001 - never crash the pipeline
            state["warnings"].append(f"underlying net 构建失败：{type(exc).__name__}: {exc}")
            return None
        state["net"] = net
        state["warnings"].extend(net.get("warnings", []))
        state["base"] = signature_base(net)
        return state["base"]

    def full_signature() -> dict | None:
        base = ensure_base()
        if base is None:
            return None
        net = state["net"]
        sig = dict(base)
        rings = _ring_stats(_edges_by_node(net), [node["index"] for node in net["nodes"]])
        sig.update(
            {
                "ring_sizes": [int(s) for s in _RING_SIZES],
                "rings_per_node": rings,
                "rings_truncated": any(item.get("truncated") for item in rings.values()),
            }
        )
        return sig

    # --- 1) 显式 record 的数据库元数据 -------------------------------------
    if record is not None:
        rec_topo = str(getattr(record, "topology", "") or "").strip().lower()
        rec_ev = str(getattr(record, "topology_evidence", "") or "unknown").strip().lower()
        if rec_topo == expected and rec_ev in ("metadata", "verified"):
            ref = {
                "source": "record metadata",
                "record_id": getattr(record, "record_id", None),
                "topology": rec_topo,
                "topology_evidence": rec_ev,
                "doi": getattr(record, "doi", None),
            }
            return _result(
                True,
                "metadata",
                f"record {getattr(record, 'record_id', '?')} 的数据库元数据标注为 {expected}"
                f"（证据等级 {rec_ev}），未做结构比对",
                _metadata_only_signature(ensure_base),
                ref,
            )
        if rec_topo and rec_topo != expected and rec_ev == "metadata":
            return _result(
                False,
                "mismatch",
                f"record 元数据标注为 {rec_topo}，与期望 {expected} 不符",
                _metadata_only_signature(ensure_base),
                {"source": "record metadata", "topology": rec_topo, "record_id": getattr(record, "record_id", None)},
            )

    # --- 2) CoRE ASR 元数据指纹（结构 == 某条 labeled 记录时） -------------
    # 放在结构比对之前：指纹匹配很便宜，而稠密 net 的环统计很贵；明显对不上时
    # 不应把时间花在环枚举上。
    fingerprint = _core_metadata_fingerprint(structure)
    if fingerprint is not None:
        meta_topo = str(fingerprint.get("topology") or "").strip().lower()
        base = ensure_base()
        sig: dict | None = None
        if base is not None:
            # metadata 证据不依赖环分布，跳过昂贵的环统计（结构可能很稠密）
            sig = {
                **base,
                "ring_sizes": [int(s) for s in _RING_SIZES],
                "rings_per_node": {},
                "rings_truncated": False,
                "rings_note": "元数据指纹命中，未计算环统计（metadata 证据不依赖环分布）",
            }
        if meta_topo == expected:
            return _result(
                True,
                "metadata",
                f"结构与 CoRE MOF 2024 ASR 记录 {fingerprint.get('records')} 的化学式/原子数/晶胞一致，"
                f"该记录元数据标注 topology={meta_topo}",
                sig,
                {"source": "CoRE MOF 2024 ASR metadata fingerprint", **fingerprint},
            )
        if meta_topo:
            return _result(
                False,
                "mismatch",
                f"结构与 CoRE MOF 2024 ASR 记录 {fingerprint.get('records')} 完全一致，"
                f"但其元数据标注为 {meta_topo}，不是 {expected}",
                sig,
                {"source": "CoRE MOF 2024 ASR metadata fingerprint", **fingerprint},
            )

    # --- 3) 结构比对 --------------------------------------------------------
    base = ensure_base()
    if base is None:
        detail = "结构中没有可用的金属节点网络（主族元素/无金属/孤立离子），无法做拓扑比对"
        extra = [w for w in state["warnings"] if w]
        if extra:
            detail += "；" + "；".join(extra[:3])
        return _result(False, "unknown", detail, None, None)

    reference_info = _resolve_reference(expected, reference)
    if reference_info is None or not reference_info.get("signature"):
        return _result(
            False,
            "unknown",
            f"无法获得拓扑 {expected} 的参考净签名（CoRE 缓存不可用且未传入 reference），"
            "按诚实性要求不能声称 verified",
            dict(base),
            None,
        )
    ref_sig = reference_info["signature"]
    ref_label = reference_info.get("record_id") or reference_info.get("source")
    if ref_sig.get("coordination_sequence_truncated"):
        return _result(
            False,
            "unknown",
            f"参考结构 {ref_label} 的配位序列签名不完整（触及安全上限），不能作为 verified 依据",
            dict(base),
            reference_info,
        )

    # 3a) 先比便宜的：配位数分布 + 配位序列 2–8 层 + linker/金属比
    base_ok, base_issues, notes = _compare_base(base, ref_sig)
    if not base_ok:
        sig = {
            **base,
            "ring_sizes": [int(s) for s in _RING_SIZES],
            "rings_per_node": {},
            "rings_truncated": False,
            "rings_note": "配位数/配位序列已不匹配，未继续计算环统计",
        }
        detail = f"结构比对不匹配（参考 {ref_label}）：" + "；".join(base_issues[:8])
        detail += f"。目标签名：{_sig_summary(sig)}；参考签名：{_sig_summary(ref_sig)}"
        return _result(False, "mismatch", detail, sig, reference_info)

    # 3b) 便宜的都对上了，再做环大小分布（预算受限）
    sig = full_signature() or dict(base)
    if sig.get("coordination_sequence_truncated"):
        return _result(
            False,
            "unknown",
            "配位序列触及安全上限（结构过于稠密），签名不完整，不能以 verified 结论返回",
            sig,
            reference_info,
        )
    rings_incomplete = bool(sig.get("rings_truncated") or ref_sig.get("rings_truncated"))
    if rings_incomplete:
        # 高配位 net（fcu/tbo/bcu/pcu 等）环枚举必然触顶；此时按"配位数+配位序列+
        # linker/金属比"这三个数值不变量判定，并在 detail/verified_on 里诚实说明。
        detail = (
            f"与参考 {ref_label} 的 underlying net 一致：{_sig_summary(sig)}；"
            "环统计在至少一侧触及安全上限（高配位 net），本次 verified 依据=配位数+配位序列+linker/金属比"
        )
        if notes:
            detail += "；" + "；".join(notes)
        result = _result(True, "verified", detail, sig, reference_info)
        result["verified_on"] = ["coordination_numbers", "coordination_sequence", "linkers_per_metal"]
        return result

    rings_ok, ring_issues = _compare_rings(sig, ref_sig)
    if rings_ok:
        detail = f"与参考 {ref_label} 的 underlying net 签名一致：{_sig_summary(sig)}"
        if notes:
            detail += "；" + "；".join(notes)
        result = _result(True, "verified", detail, sig, reference_info)
        result["verified_on"] = ["coordination_numbers", "coordination_sequence", "linkers_per_metal", "rings_per_node"]
        return result

    detail = f"结构比对不匹配（参考 {ref_label}）：" + "；".join(ring_issues[:8])
    detail += f"。目标签名：{_sig_summary(sig)}；参考签名：{_sig_summary(ref_sig)}"
    return _result(False, "mismatch", detail, sig, reference_info)


def identify(structure, nets=None) -> dict:
    """在落盘参考签名里找出 ``structure`` 最匹配的拓扑 net。

    返回 dict::

        {"ok": bool, "net": str|None, "best_net": str|None,
         "evidence": "verified"|"mismatch"|"unknown",
         "detail": str, "signature": {...}|None,
         "candidates": [{"net","base_ok","rings_ok","issues","record_id","doi"}...],
         "reference": {...}|None}

    判定顺序与 ``verify`` 一致：先比配位数分布 + 2–8 层配位序列 + linker/金属比；
    环统计在参考/目标任一侧不完整（高配位 net 的正常情况）时跳过环比较并在 detail
    说明；多个 net 同时匹配或都不匹配时返回 ``ok=False, evidence="unknown"``（诚实）。
    """
    names = available_reference_nets()
    if nets:
        wanted = {_normalize_net(n) for n in nets}
        names = [name for name in names if name in wanted]
    refs: dict[str, dict] = {}
    for name in names:
        reference = load_reference(name)
        if reference and isinstance(reference.get("signature"), dict):
            refs[name] = reference
    result: dict[str, Any] = {
        "ok": False,
        "net": None,
        "best_net": None,
        "evidence": "unknown",
        "detail": "",
        "signature": None,
        "candidates": [],
        "reference": None,
    }
    if not refs:
        result["detail"] = "没有可用的落盘参考签名（cifkit/data/nets/<net>.json 为空）"
        return result
    try:
        netinfo = underlying_net(structure)
        base = signature_base(netinfo)
    except Exception as exc:  # noqa: BLE001 - never crash
        result["detail"] = f"underlying net 构建失败：{type(exc).__name__}: {exc}"
        return result
    if base is None:
        result["detail"] = "结构中没有可用的金属节点网络（主族/无金属/孤立离子），无法判定拓扑（unknown）"
        return result

    candidates: list[dict[str, Any]] = []
    base_matches: list[tuple[str, dict, dict]] = []
    for name in sorted(refs):
        reference = refs[name]
        ref_sig = reference["signature"]
        ok, issues, notes = _compare_base(base, ref_sig)
        item = {
            "net": name,
            "base_ok": bool(ok),
            "rings_ok": None,
            "issues": issues[:6],
            "notes": notes[:3],
            "record_id": reference.get("record_id"),
            "doi": reference.get("doi"),
        }
        candidates.append(item)
        if ok:
            base_matches.append((name, reference, item))

    if not base_matches:
        closest = min(candidates, key=lambda item: (len(item["issues"]), item["net"]))
        result["candidates"] = candidates
        result["signature"] = base
        result["detail"] = (
            f"未匹配任何落盘 net 参考（已检查 {sorted(refs)}）；最接近 {closest['net']}"
            f"（记录 {closest['record_id']}），差异："
            + ("；".join(closest["issues"][:4]) or "配位数/配位序列差异")
        )
        return result

    # 只有需要环比较时才计算完整签名（环统计对高配位 net 很贵）
    need_full = any(
        not (reference["signature"].get("rings_truncated") or reference["signature"].get("coordination_sequence_truncated"))
        for _name, reference, _item in base_matches
    )
    full = None
    if need_full:
        try:
            full = signature(netinfo)
        except Exception:  # noqa: BLE001 - fall back to base comparison
            full = None

    verified: list[tuple[str, dict, dict]] = []
    for name, reference, item in base_matches:
        ref_sig = reference["signature"]
        can_compare_rings = (
            full is not None
            and not full.get("rings_truncated")
            and not full.get("coordination_sequence_truncated")
            and not ref_sig.get("rings_truncated")
            and not ref_sig.get("coordination_sequence_truncated")
        )
        if can_compare_rings:
            rings_ok, ring_issues = _compare_rings(full, ref_sig)
            item["rings_ok"] = bool(rings_ok)
            if not rings_ok:
                item["issues"] = item["issues"] + ring_issues
                continue
        verified.append((name, reference, item))

    result["candidates"] = candidates
    result["signature"] = full or base
    if len(verified) == 1:
        name, reference, item = verified[0]
        basis = "配位数+配位序列+linker/金属比"
        basis += "+环分布" if item.get("rings_ok") else "（环统计在参考/目标侧不完整，未参与判定）"
        result.update(
            {
                "ok": True,
                "net": name,
                "best_net": name,
                "evidence": "verified",
                "detail": (
                    f"最佳匹配 net={name}（参考记录 {reference.get('record_id')}，DOI {reference.get('doi')}）；"
                    f"判定依据：{basis}"
                ),
                "reference": reference,
            }
        )
        return result
    if not verified:
        result["detail"] = (
            "配位数/配位序列匹配但环分布不一致，无法确认拓扑："
            + "；".join(issue for _n, _r, item in base_matches for issue in item["issues"][:2])
        )
        return result
    matched = [name for name, _reference, _item in verified]
    result["detail"] = f"多个 net 的签名同时匹配（{matched}），无法唯一判定（unknown）"
    return result
