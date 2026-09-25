"""进水监测业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "inflow"
REQUIRED_FIELDS = ["监测编号", "采样时间", "进水流量"]
STATUS_ORDER = ["待检测", "检测中", "已记录", "已作废"]
ACTION_RULES = {"开始检测": "检测中", "确认记录": "已记录", "作废记录": "已作废"}
NEGATIVE_ACTIONS = ["作废记录"]

# 化验结果批量回填：四项化验指标必须齐备
LAB_FIELDS = ["化学需氧量", "氨氮浓度", "悬浮物", "酸碱度"]
PH_MIN, PH_MAX = 0.0, 14.0
# 进水流量按 m³/d 计，必须为正数；上限只是拦截明显的录入错误
FLOW_MIN, FLOW_MAX = 0.0, 1_000_000.0


def _clean(value: Any) -> str:
    """把提交值规范成字符串，None 与只含空白的输入都按空值处理。"""
    return str(value).strip() if value is not None else ""


def _parse_number(text: str) -> float | None:
    """解析数值；空串或无法解析时返回 None，交给上层按“不是合法数值”处理。"""
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN 不算合法数值


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

    def batch_backfill(
        self, items: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int, int]:
        """批量回填化验结果，逐条独立校验：合格的落库，不合格的只在结果里标记。

        - 任一记录校验失败都不影响批次里其他记录（允许部分失败）；
        - 校验失败的记录四项化验值一律不写库，成功时四项化验值才一起落库；
        - 返回值里成功项回传落库后的记录、失败项回传提交值与逐条原因，
          保证调用方看到的数值与批次结果、刷新后的列表完全一致。
        """
        results: list[dict[str, Any]] = []
        succeeded = failed = 0
        for item in items:
            entry_id = item.get("id")
            values = item.get("values") if isinstance(item.get("values"), dict) else {}
            submitted = {field: _clean(values.get(field)) for field in LAB_FIELDS}

            if not isinstance(entry_id, int) or isinstance(entry_id, bool):
                results.append({
                    "id": entry_id,
                    "code": None,
                    "ok": False,
                    "reason": "缺少有效的监测记录 id",
                    "values": submitted,
                    "entry": None,
                })
                failed += 1
                continue

            entry = store.find(MODULE, entry_id)
            if entry is None:
                results.append({
                    "id": entry_id,
                    "code": None,
                    "ok": False,
                    "reason": f"进水记录 {entry_id} 不存在或已归档",
                    "values": submitted,
                    "entry": None,
                })
                failed += 1
                continue

            if entry.get("labBackfilled"):
                results.append({
                    "id": entry_id,
                    "code": entry.get("监测编号"),
                    "ok": False,
                    "reason": "化验结果已回填，请勿重复提交",
                    "values": submitted,
                    "entry": None,
                })
                failed += 1
                continue

            reasons: list[str] = []
            for field in LAB_FIELDS:
                if not submitted[field]:
                    reasons.append(
                        "悬浮物为空，化验值不齐" if field == "悬浮物" else f"{field}为空"
                    )
            for field in ("化学需氧量", "氨氮浓度"):
                if submitted[field] and _parse_number(submitted[field]) is None:
                    reasons.append(f"{field}不是合法数值")
            if submitted["悬浮物"] and _parse_number(submitted["悬浮物"]) is None:
                reasons.append("悬浮物不是合法数值")
            ph = _parse_number(submitted["酸碱度"])
            if submitted["酸碱度"] and ph is None:
                reasons.append("酸碱度不是合法数值")
            elif ph is not None and not PH_MIN <= ph <= PH_MAX:
                reasons.append(f"酸碱度 {submitted['酸碱度']} 超出 0-14 合理范围")

            flow = _parse_number(_clean(entry.get("进水流量")))
            if flow is None:
                reasons.append("进水流量不是合法数值，无法据此回填")
            elif not FLOW_MIN < flow <= FLOW_MAX:
                reasons.append(
                    f"进水流量 {entry.get('进水流量')} 超出合理范围"
                    f"(大于 0 且不超过 {FLOW_MAX:.0f} m³/d)"
                )

            if reasons:
                # 不合格只标记：本记录四项化验值一律不落库
                results.append({
                    "id": entry_id,
                    "code": entry.get("监测编号"),
                    "ok": False,
                    "reason": "；".join(reasons),
                    "values": submitted,
                    "entry": None,
                })
                failed += 1
                continue

            for field in LAB_FIELDS:
                entry[field] = submitted[field]
            entry["labBackfilled"] = True
            results.append({
                "id": entry_id,
                "code": entry.get("监测编号"),
                "ok": True,
                "reason": "",
                "values": submitted,
                "entry": dict(entry),
            })
            succeeded += 1
        return results, succeeded, failed

