"""cifkit — CIF 处理工作台。

一条管线：选型下载 → 修复（补氢/无序/近邻）→ 几何（超胞/切面/真空/簇）→ 导出 → 校验入库。
"""

__version__ = "0.1.0"

from cifkit.types import (  # noqa: F401
    CheckResult,
    FetchedStructure,
    RepairReport,
    RunResult,
    SourceQuery,
    StepResult,
    StructureRecord,
    TaskSpec,
    ValidationReport,
)
