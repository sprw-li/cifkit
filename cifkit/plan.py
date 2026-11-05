"""Turn a TaskSpec into an ordered list of pipeline steps.

Pure planning: no I/O, no network. ``pipeline.py`` executes the plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cifkit.types import TaskSpec


@dataclass
class Step:
    name: str
    func: str  # pipeline function key
    params: dict[str, Any] = field(default_factory=dict)
    optional: bool = False
    description: str = ""


def build_plan(spec: TaskSpec) -> list[Step]:
    steps: list[Step] = [Step("resolve", "resolve", description="按拓扑/名称/id 检索并下载结构")]

    if spec.topology:
        steps.append(
            Step(
                "verify-topology",
                "verify_topology",
                params={"expected": spec.topology},
                description="核实结构拓扑与请求一致（元数据/结构比对）",
            )
        )

    repair_params = {
        "add_hydrogen": spec.repair_h,
        "resolve_disorder": spec.repair_disorder,
        "remove_close_contacts": spec.remove_close_contacts,
    }
    if any(repair_params.values()):
        steps.append(Step("repair", "repair", params=repair_params, description="补氢/无序/近邻修复"))
    else:
        steps.append(Step("repair", "repair", params=repair_params, optional=True, description="结构体检（不修改）"))

    if spec.extract_cluster:
        steps.append(
            Step("cluster", "extract_cluster", params={"mode": spec.cluster_mode}, description="提取金属簇/SBU")
        )
    else:
        steps.append(Step("standardize", "standardize", description="标准胞/去重复"))

    if spec.supercell:
        steps.append(
            Step("supercell", "supercell", params={"reps": spec.supercell}, description="扩展超胞")
        )

    if spec.surface:
        steps.append(
            Step(
                "surface",
                "surface",
                params={"hkl": spec.surface, "slab_thickness": spec.slab_thickness, "vacuum": spec.vacuum},
                description="切 (hkl) 表面",
            )
        )

    if spec.vacuum is not None:
        steps.append(Step("vacuum", "vacuum", params={"vacuum": spec.vacuum}, description="设置/校核真空层"))

    steps.append(Step("export", "export", params={"formats": spec.output_formats}, description="导出计算化学格式"))
    steps.append(Step("validate", "validate", description="结构校验"))
    steps.append(Step("render", "render", optional=True, description="预览图"))
    steps.append(Step("manifest", "manifest", description="写 manifest / 入库"))
    return steps


def describe_plan(steps: list[Step]) -> str:
    lines = ["## 执行计划"]
    for i, s in enumerate(steps, 1):
        suffix = "（可选）" if s.optional else ""
        lines.append(f"{i}. {s.name}：{s.description}{suffix}")
    return "\n".join(lines)
