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
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["verify", "describe", "underlying_net", "is_metal_symbol", "signature"]

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
def _build_net(structure):
    """Return ``(net, reason)``; ``net`` is None when no metal node exists."""
    adjacency, elements, warnings = _bond_graph(structure)
    metals = [i for i, sym in enumerate(elements) if is_metal_symbol(sym)]
    if not metals:
        return None, {
            "reason": "未识别到金属节点（主族元素/无金属体系），本工具不做拓扑断言",
            "warnings": warnings,
        }
    metal_set = set(metals)

    # 1) 去掉金属后，有机/阴离子部分按周期成键图取连通分量 = linker 分子
    visited: set[int] = set()
    components: list[list[int]] = []
    for start in range(len(elements)):
        if start in metal_set or start in visited:
            continue
        comp: list[int] = []
        queue = deque([start])
        visited.add(start)
        while queue:
            atom = queue.popleft()
            comp.append(atom)
            for nb, _off in adjacency.get(atom, ()):
                if nb in metal_set or nb in visited:
                    continue
                visited.add(nb)
                queue.append(nb)
        components.append(comp)

    # 2) 对每个 linker 分子传播平移量，把分子摆回同一个物理位置块；
    #    这样跨晶胞边界的 linker 也能得到正确的金属-金属相对平移 (LQG 的 shift)。
    edges: dict[int, list[tuple[int, tuple[int, int, int]]]] = defaultdict(list)
    linkers: list[dict[str, Any]] = []
    n_linkers = 0
    for comp in components:
        shifts: dict[int, tuple[int, int, int]] = {comp[0]: (0, 0, 0)}
        queue = deque([comp[0]])
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
        if not consistent:
            warnings.append(f"跳过非分子性（周期/聚合物）有机组分：{len(comp)} 个原子")
            continue

        attachments: set[tuple[int, tuple[int, int, int]]] = set()
        for atom in comp:
            base = shifts[atom]
            for nb, off in adjacency.get(atom, ()):
                if nb in metal_set:
                    attachments.add((nb, (off[0] - base[0], off[1] - base[1], off[2] - base[2])))
        if len(attachments) < 2:
            # 单齿配体 / 端基：不构成 net 的边
            continue

        n_linkers += 1
        linkers.append({"atoms": sorted(comp), "n_attachment_sites": len(attachments)})
        ordered = sorted(attachments)
        for x in range(len(ordered)):
            for y in range(x + 1, len(ordered)):
                (m1, t1), (m2, t2) = ordered[x], ordered[y]
                shift = (t2[0] - t1[0], t2[1] - t1[1], t2[2] - t1[2])
                edges[m1].append((m2, shift))
                edges[m2].append((m1, (-shift[0], -shift[1], -shift[2])))

    # 3) 无连接的金属（孔道里的孤立离子）不作为 net 节点
    connected = [m for m in metals if edges.get(m)]
    isolated = len(metals) - len(connected)
    if isolated:
        warnings.append(f"{isolated} 个金属原子没有通过 linker 连接，已排除出 net")

    nodes = [
        {
            "index": int(m),
            "element": elements[m],
            "frac": [float(x) for x in np.round(structure[m].frac_coords, 6)],
        }
        for m in connected
    ]
    edge_list: list[dict[str, Any]] = []
    lattice = structure.lattice
    frac = np.asarray([site.frac_coords for site in structure], dtype=float)
    for m in connected:
        for nb, shift in edges.get(m, ()):
            delta = frac[nb] + np.asarray(shift, dtype=float) - frac[m]
            length = float(np.linalg.norm(lattice.get_cartesian_coords(delta)))
            edge_list.append({"i": int(m), "j": int(nb), "shift": [int(s) for s in shift], "length": round(length, 3)})

    net = {
        "nodes": nodes,
        "edges": edge_list,
        "linkers": linkers,
        "n_nodes": len(nodes),
        "n_edges": len(edge_list) // 2,
        "n_linkers": n_linkers,
        "warnings": warnings,
    }
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
    """Drop the in-process verify/reference caches (tests, long-running workers)."""
    _VERIFY_CACHE.clear()
    _REFERENCE_CACHE.clear()


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
    if ref_sig.get("coordination_sequence_truncated") or ref_sig.get("rings_truncated"):
        return _result(
            False,
            "unknown",
            f"参考结构 {ref_label} 自身的签名不完整（配位序列/环统计触及安全上限），不能作为 verified 依据",
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

    # 3b) 便宜的都对上了，再做环大小分布（预算受限，触顶则诚实降级）
    sig = full_signature() or dict(base)
    if sig.get("coordination_sequence_truncated") or sig.get("rings_truncated"):
        return _result(
            False,
            "unknown",
            "配位序列/环统计触及安全上限（结构过于稠密），签名不完整，不能以 verified 结论返回",
            sig,
            reference_info,
        )
    rings_ok, ring_issues = _compare_rings(sig, ref_sig)
    if rings_ok:
        detail = f"与参考 {ref_label} 的 underlying net 签名一致：{_sig_summary(sig)}"
        if notes:
            detail += "；" + "；".join(notes)
        return _result(True, "verified", detail, sig, reference_info)

    detail = f"结构比对不匹配（参考 {ref_label}）：" + "；".join(ring_issues[:8])
    detail += f"。目标签名：{_sig_summary(sig)}；参考签名：{_sig_summary(ref_sig)}"
    return _result(False, "mismatch", detail, sig, reference_info)
