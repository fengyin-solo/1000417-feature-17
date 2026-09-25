"""进水监测业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import math
from typing import Any

from app.store import store

MODULE = "inflow"
REQUIRED_FIELDS = ["监测编号", "采样时间", "进水流量"]
STATUS_ORDER = ["待检测", "检测中", "已记录", "已作废"]
ACTION_RULES = {"开始检测": "检测中", "确认记录": "已记录", "作废记录": "已作废"}
NEGATIVE_ACTIONS = ["作废记录"]

LAB_FIELDS = ["化学需氧量", "氨氮浓度", "悬浮物", "酸碱度"]
PH_MIN, PH_MAX = 0.0, 14.0
FLOW_MIN, FLOW_MAX = 0.0, 100000.0


def _parse_number(raw: Any) -> float | None:
    """把提交值解析成浮点数；空串、布尔值、非数值都按无效处理。"""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class InflowService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("监测编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"进水记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于进水监测可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"进水记录已{action}"

    def backfill_lab_results(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """批量回填化验结果：逐条校验，合格的落库，不合格的只标记原因，允许部分成功。"""
        results = [self._backfill_one(item) for item in items]
        succeeded = sum(1 for item in results if item["ok"])
        failed = len(results) - succeeded
        if failed == 0:
            ok, message = True, f"批量回填完成，{succeeded} 条化验结果已写入"
        elif succeeded == 0:
            ok, message = False, f"批量回填未写入任何记录，{failed} 条均未通过校验"
        else:
            ok, message = False, f"批量回填部分成功：{succeeded} 条已写入，{failed} 条未通过校验"
        return {
            "ok": ok,
            "message": message,
            "total": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }

    def _backfill_one(self, item: dict[str, Any]) -> dict[str, Any]:
        entry_id = item.get("entry_id")
        values = item.get("values") or {}

        def fail(message: str) -> dict[str, Any]:
            return {"entry_id": entry_id, "ok": False, "message": message, "entry": None}

        if entry_id is None:
            return fail("缺少进水记录 ID，无法定位待回填记录")
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return fail(f"进水记录 {entry_id} 不存在或已归档")
        if entry.get("lab_filled"):
            return fail(f"进水记录 {entry_id} 已回填过化验结果，重复回填不予落库")
        suspended = values.get("悬浮物")
        if suspended is None or not str(suspended).strip():
            return fail("悬浮物为空，需补测悬浮物后再回填")
        ph = _parse_number(values.get("酸碱度"))
        if ph is None or not math.isfinite(ph):
            return fail(f"酸碱度「{values.get('酸碱度')}」不是有效数值，需在 {PH_MIN:g}~{PH_MAX:g} 之间")
        if not PH_MIN <= ph <= PH_MAX:
            return fail(f"酸碱度 {ph:g} 超出合理范围 {PH_MIN:g}~{PH_MAX:g}，已标记不落库")
        flow = _parse_number(entry.get("进水流量"))
        if flow is None or not math.isfinite(flow) or flow <= FLOW_MIN or flow > FLOW_MAX:
            return fail(f"进水流量「{entry.get('进水流量')}」不合理，需为大于 {FLOW_MIN:g} 且不超过 {FLOW_MAX:g} 的数值，已标记不落库")
        for field in LAB_FIELDS:
            if field in values:
                entry[field] = values[field]
        entry["酸碱度"] = ph
        entry["lab_filled"] = True
        return {"entry_id": entry_id, "ok": True, "message": "化验结果已回填", "entry": dict(entry)}
