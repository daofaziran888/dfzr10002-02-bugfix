"""指标口径管理接口：维护业务指标，覆盖提交审批、发布指标、废弃指标等动作。

筛选口径统一由 ``app.services.filtering`` 提供：``keyword`` 会同时检索编号、名称与公式，
也可以按 ``指标名称``、``口径版本``、``status`` 等列名逐项过滤；列表、摘要与导出共用同一张
数据快照，导出前先登记 ``/export`` 路由，避免被 ``/{entry_id}`` 详情入口截住。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.routers.common import build_export_response, build_page_result, build_summary
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.indicator import IndicatorService

router = APIRouter(prefix="/api/indicator", tags=["指标口径管理"])

service = IndicatorService()

LIST_FIELDS = ["指标编号", "指标名称", "计算公式", "统计粒度", "时间范围", "筛选条件", "数据来源", "口径版本"]
STATUSES = ["草稿", "待审批", "已发布", "已废弃"]
# 英文与中文参数别名：既兼容按编号检索，也支持按名称、公式、版本检索。
ALIASES = {
    "code": "指标编号",
    "指标代码": "指标编号",
    "name": "指标名称",
    "业务指标名称": "指标名称",
    "名称": "指标名称",
    "formula": "计算公式",
    "公式": "计算公式",
    "version": "口径版本",
    "指标口径版本": "口径版本",
    "口径版本号": "口径版本",
}


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按指标编号、指标名称或计算公式检索"),
    status: str | None = Query(default=None, description="草稿、待审批、已发布、已废弃"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按指标名称、计算公式、编号与状态过滤指标口径管理列表；没有数据时返回空页，不报错。"""
    return build_page_result(request, service, LIST_FIELDS, ALIASES, page=page, size=size)


@router.get("/summary")
def summary(request: Request) -> dict[str, Any]:
    """筛选摘要：与当前列表同一快照、同一筛选条件，状态计数不会各算各的。"""
    return build_summary(request, service, LIST_FIELDS, ALIASES)


@router.get("/export")
def export_entries(request: Request) -> Any:
    """导出指标口径管理清单：沿用当前列表条件与快照，输出带表头的 CSV，空结果也保留表头。"""
    return build_export_response(request, service, LIST_FIELDS, "indicator", "指标口径管理清单", ALIASES)


@router.get("/{entry_id:int}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条业务指标明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"业务指标 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条业务指标，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="业务指标已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条业务指标执行提交审批、发布指标、废弃指标；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
