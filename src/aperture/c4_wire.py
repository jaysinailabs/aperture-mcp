"""C4 wire adapter: 实现层 DeltaResult → 补齐 methodology C4_DeltaResult required 的 wire。

aperture 的 `DeltaResult` 是 methodology `C4_DeltaResult` 的**实现层子集**（仅
status / reason / provider_family / profile? / state_kind / anchor_violations / event_id?）。
`DeltaResult.to_dict()` 输出该紧凑原生形态、不强求合法 C4。

本 adapter 把原生形态转成满足 **C4_DeltaResult required 集**的 wire——补齐本实现暂未承载的
多视角 required 字段（`delta` / `anchor_reaffirmations` / `per_view_findings` /
`cross_view_conflicts`）以空载占位。多视角语义（delta 内容、真实 per_view_findings、
impact_radius、suggested_actions）维持 deferred——当前实现暂不承载多视角语义。
"""

from __future__ import annotations

from typing import Any

from aperture.core import DeltaResult

#: The required field set of the C4 DeltaResult wire schema.
C4_DELTA_RESULT_REQUIRED = (
    "status",
    "delta",
    "anchor_violations",
    "anchor_reaffirmations",
    "per_view_findings",
    "cross_view_conflicts",
)


def as_c4_delta_result(result: DeltaResult) -> dict[str, Any]:
    """把实现层 ``DeltaResult`` 转成补齐 C4_DeltaResult required 字段的 wire 形态。

    在原生 ``to_dict()`` 基础上补齐 C4 required 中本实现未承载的多视角字段（空载占位），
    使输出的 key 集 ⊇ C4_DeltaResult required；新增的 5 个可选字段（reason /
    provider_family / profile / state_kind / event_id）由原生形态原样带出（已收入当前适配 schema）。
    """
    wire = result.to_dict()
    wire.setdefault("delta", {})
    wire.setdefault("anchor_reaffirmations", [])
    wire.setdefault("per_view_findings", [])
    wire.setdefault("cross_view_conflicts", [])
    return wire
