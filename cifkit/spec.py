"""Natural-language request parsing: Chinese/English sentence -> TaskSpec.

The parser is intentionally declarative (regex slot table). It never invents a
structure; anything it cannot parse is reported in ``spec.notes`` so the agent
can ask a targeted question instead of guessing silently.
"""
from __future__ import annotations

import re
from pathlib import Path

from cifkit.types import TaskSpec

# Common RCSR 3-letter nets. Used only to *recognise* a code in free text.
KNOWN_NETS = {
    "sod", "pcu", "dia", "fcu", "bcu", "tbo", "hms", "qtz", "cag", "lta",
    "nbo", "acs", "bto", "rna", "rht", "she", "srs", "pts", "mog", "tfa",
    "ana", "abw", "bea", "cha", "fau", "lta", "mfi", "mor", "zni", "neb",
    "zni", "tfy", "dmc", "mmm", "mmm", "rtl", "scu", "tfy", "wse", "zst",
}

KNOWN_MOFS = [
    "zif-8", "zif-67", "zif-4", "zif-7", "zif-90",
    "mof-5", "mof-74", "mof-177", "mof-199", "mof-801",
    "hkust-1", "cu-btc", "uio-66", "uio-67", "uio-68",
    "mil-101", "mil-100", "mil-53", "mil-125", "pcn-222", "nu-1000",
    "mof-1", "irmof-1", "irmof-3", "irmof-8", "irmof-16",
]

_FORMAT_MAP = {
    "vasp": ["vasp", "poscar", "contcar", "vasp.poscar"],
    "cif": ["cif", "crystallographic information file"],
    "xyz": ["xyz", "extxyz", "ovito"],
    "lammps": ["lammps", "lammps-data", "lammps.data"],
    "qe": ["qe", "quantum espresso", "espresso", "pwscf"],
    "cp2k": ["cp2k"],
    "xsf": ["xsf", "xcrysden"],
    "gaussian": ["gaussian", "gjf", "g16"],
    "orca": ["orca", "orca.inp"],
    "abacus": ["abacus"],
}

# NOTE: ``\b`` is unusable here because Python's Unicode ``\w`` includes CJK,
# so "…sod的…" has no word boundary after "sod". Use explicit ASCII lookarounds.
_TOPO_CTX = re.compile(
    r"(?:rcsr|拓扑|topology|net)\s*(?:为|是|:|：|=|＝|叫做|叫)?\s*([a-z]{3})(?![a-z])",
    re.IGNORECASE,
)
_TOPO_VERB = re.compile(
    r"(?:rcsr\s*为|rcsr\s*是|拓扑为|拓扑是|topology\s*(?:is|=|:))\s*([a-z]{3})(?![a-z])",
    re.IGNORECASE,
)
_NET_CODE = re.compile(r"(?<![a-z])([a-z]{3})(?![a-z])", re.IGNORECASE)

_SUPERCELL = re.compile(
    r"(?:(\d+)\s*[x×X*]\s*(\d+)\s*[x×X*]\s*(\d+)|(?:超胞|supercell)\s*(?:为|是)?\s*(\d+)\s*[x×X*]\s*(\d+)\s*[x×X*]\s*(\d+))"
)
_SURFACE = re.compile(
    r"(?:沿|沿着|切|cleave|surface)?\s*[(（]\s*(\d)\s*[,，\s]?\s*(\d)\s*[,，\s]?\s*(\d)\s*[)）]\s*(?:面|晶面|surface|plane)?"
)
_SURFACE_BARE = re.compile(r"沿\s*(\d)(\d)(\d)\s*面")
_VACUUM = re.compile(
    r"(?:(\d+(?:\.\d+)?)\s*(?:å|Å|a|A|埃|angstrom|ang)?\s*(?:的)?\s*(?:真空层|真空|vacuum)"
    r"|(?:真空层|真空|vacuum)\s*(?:为|是|:|：)?\s*(\d+(?:\.\d+)?)\s*(?:å|Å|a|A|埃|angstrom|ang)?)",
    re.IGNORECASE,
)
_THICKNESS = re.compile(
    r"(?:厚度|thickness|slab thickness)\s*(?:为|是|:|：)?\s*(\d+(?:\.\d+)?)\s*(?:å|Å|a|A|埃|angstrom|ang)?",
    re.IGNORECASE,
)
_H_REPAIR = re.compile(
    r"(补(?:充)?氢|加氢|补\s*h|加\s*h\b|hydrogenat|add\s+(?:hydrogen|h\b)|missing\s+h|缺氢)",
    re.IGNORECASE,
)
_DISORDER = re.compile(
    r"(统计原子|占位|无序|多位置|部分占据|partial\s+occupancy|disorder|disordered|statistical)",
    re.IGNORECASE,
)
_CONTACTS = re.compile(
    r"(距离过近|原子过近|过近|原子重叠|重叠原子|overlap|close\s+contact|too\s+close)",
    re.IGNORECASE,
)
_CLUSTER = re.compile(
    r"(核心金属簇|金属簇|金属核|metal\s+cluster|metal\s+core|\bsbu\b|二级构筑单元|构筑单元|簇)",
    re.IGNORECASE,
)
_DOWNLOAD = re.compile(r"(下载|获取|抓取|拉取|download|fetch|检索|查找|找一?个?典型案例?)", re.IGNORECASE)
_TYPICAL = re.compile(r"(典型|经典|代表性|typical|canonical|classic|最常见)", re.IGNORECASE)
_SOURCE_PATTERNS = [
    ("core-mof", re.compile(r"(core[-\s]?mof|core\s+mof)", re.IGNORECASE)),
    ("cod", re.compile(r"(crystallography open database|\bcod\b|晶体学开放数据库)", re.IGNORECASE)),
    ("materials-project", re.compile(r"(materials project|\bmp\b\s*数据库)", re.IGNORECASE)),
    ("qmof", re.compile(r"\bqmof\b", re.IGNORECASE)),
    ("local", re.compile(r"(本地文件|local file|这个文件|该文件|附件)", re.IGNORECASE)),
]


def _extract_formats(text: str) -> list[str]:
    low = text.lower()
    found: list[str] = []
    for fmt, aliases in _FORMAT_MAP.items():
        if any(a in low for a in aliases):
            found.append(fmt)
    return found


def _looks_like_path(token: str) -> bool:
    return token.lower().endswith(".cif") or "\\" in token or "/" in token


def parse_request(text: str, outdir: Path | str | None = None) -> TaskSpec:
    spec = TaskSpec(query=text.strip(), raw_text=text)
    low = text.lower()

    # --- topology -------------------------------------------------------
    m = _TOPO_VERB.search(text) or _TOPO_CTX.search(text)
    if m:
        spec.topology = m.group(1).lower()
    else:
        for code_m in _NET_CODE.finditer(low):
            code = code_m.group(1).lower()
            if code in KNOWN_NETS:
                spec.topology = code
                break

    # --- named structure -------------------------------------------------
    for name in sorted(KNOWN_MOFS, key=len, reverse=True):
        if name in low:
            spec.structure_name = name.upper()
            break

    # --- explicit identifiers / local path --------------------------------
    m = re.search(r"\b(?:cod[:\s]*)?(\d{7})\b", text)
    if m:
        spec.structure_id = m.group(1)
        spec.source = "cod"
    m = re.search(r"([A-Za-z]:\\[^\s，。；;]+\.cif|[^\s，。；;]+\.cif)", text)
    if m:
        spec.structure_id = m.group(1)
        spec.source = "local"

    # --- source ----------------------------------------------------------
    if spec.source == "auto":
        for source, pat in _SOURCE_PATTERNS:
            if pat.search(text):
                spec.source = source
                break

    # --- repair intents ---------------------------------------------------
    spec.repair_h = bool(_H_REPAIR.search(text))
    spec.repair_disorder = bool(_DISORDER.search(text)) or spec.repair_h
    spec.remove_close_contacts = bool(_CONTACTS.search(text)) or spec.repair_h
    if _CLUSTER.search(text):
        spec.extract_cluster = True

    # --- geometry ---------------------------------------------------------
    m = _SUPERCELL.search(text)
    if m:
        groups = [g for g in m.groups() if g is not None]
        spec.supercell = tuple(int(g) for g in groups)  # type: ignore[arg-type]

    m = _SURFACE.search(text)
    if m and tuple(int(g) for g in m.groups()) != (0, 0, 0):
        spec.surface = tuple(int(g) for g in m.groups())  # type: ignore[arg-type]
    else:
        m = _SURFACE_BARE.search(text)
        if m:
            spec.surface = tuple(int(g) for g in m.groups())  # type: ignore[arg-type]

    m = _VACUUM.search(text)
    if m:
        spec.vacuum = float(m.group(1) or m.group(2))

    m = _THICKNESS.search(text)
    if m:
        spec.slab_thickness = float(m.group(1))

    # --- outputs -----------------------------------------------------------
    formats = _extract_formats(text)
    if formats:
        spec.output_formats = formats
    elif re.search(r"(导出|输出|转成|转为|export|convert)", text):
        spec.output_formats = ["vasp", "cif", "xyz"]
        spec.assumptions.append("未指定导出格式，按默认 VASP/CIF/XYZ 导出（计算化学常用）")
    else:
        spec.output_formats = ["cif"]

    if outdir is not None:
        spec.outdir = Path(outdir)

    # --- "does the user actually want a download?" -------------------------
    if spec.structure_id is None and (spec.topology or spec.structure_name) and not _DOWNLOAD.search(text):
        spec.notes.append("未出现下载动词，按“按拓扑/名称检索数据库”处理")

    # --- missing slots / assumptions ---------------------------------------
    if spec.surface and spec.vacuum is None:
        spec.vacuum = 15.0
        spec.assumptions.append("切面但未给真空层厚度，默认 15 Å")
    if spec.vacuum is not None and spec.surface is None:
        spec.notes.append("给了真空层但没给切面：沿 c 轴加真空")
    if spec.surface and spec.slab_thickness is None:
        spec.slab_thickness = 15.0
        spec.assumptions.append("未指定 slab 厚度，默认 15 Å")
    if spec.topology is None and spec.structure_name is None and spec.structure_id is None:
        spec.notes.append("没有识别到拓扑/结构名/结构 id：需要用户补充要什么结构")

    return spec


def describe_spec(spec: TaskSpec) -> str:
    lines: list[str] = []
    lines.append("## 解析结果")
    lines.append(f"- 查询：{spec.query}")
    lines.append(f"- 数据源：{spec.source}")
    if spec.topology:
        lines.append(f"- 拓扑（RCSR）：{spec.topology}")
    if spec.structure_name:
        lines.append(f"- 结构名：{spec.structure_name}")
    if spec.structure_id:
        lines.append(f"- 结构 id：{spec.structure_id}")
    if spec.repair_h:
        lines.append("- 修复：补氢（碳上）")
    if spec.repair_disorder:
        lines.append("- 修复：无序/占位原子")
    if spec.remove_close_contacts:
        lines.append("- 修复：过近原子")
    if spec.extract_cluster:
        lines.append(f"- 提取：{spec.cluster_mode}")
    if spec.supercell:
        lines.append(f"- 超胞：{spec.supercell[0]}x{spec.supercell[1]}x{spec.supercell[2]}")
    if spec.surface:
        lines.append("- 切面：({}{}{})".format(*spec.surface))
    if spec.vacuum is not None:
        lines.append(f"- 真空层：{spec.vacuum} Å")
    if spec.output_formats:
        lines.append("- 导出格式：" + ", ".join(spec.output_formats))
    if spec.notes:
        lines.append("- 备注：" + "；".join(spec.notes))
    if spec.assumptions:
        lines.append("- 默认假设：" + "；".join(spec.assumptions))
    return "\n".join(lines)
