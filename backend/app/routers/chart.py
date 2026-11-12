"""可视化图表配置接口：维护图表配置，覆盖提交校验、启用配置、停用配置等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.routers.common import build_export_response, build_page_result, build_summary
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.chart import ChartService

router = APIRouter(prefix="/api/chart", tags=["可视化图表配置"])

service = ChartService()

LIST_FIELDS = ["图表编号", "图表名称", "图表类型", "数据源绑定", "横轴字段", "纵轴字段", "筛选条件", "刷新间隔"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]
# 英文参数别名：code 对应编号，name 对应名称。
ALIASES = {"code": LIST_FIELDS[0], "name": LIST_FIELDS[1]}


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按编号、名称或关键字段检索"),
    status: str | None = Query(default=None, description="按状态过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按名称、关键字段与状态过滤列表；没有数据时返回空页，不报错。"""
    return build_page_result(request, service, LIST_FIELDS, ALIASES, page=page, size=size)


@router.get("/summary")
def summary(request: Request) -> dict[str, Any]:
    """筛选摘要：与当前列表同一快照、同一筛选条件。"""
    return build_summary(request, service, LIST_FIELDS, ALIASES)


@router.get("/{entry_id:int}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条图表配置明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"图表配置 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条图表配置，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="图表配置已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条图表配置执行提交校验、启用配置、停用配置；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries(request: Request) -> Any:
    """导出清单：沿用当前列表条件与快照，输出带表头的 CSV，空结果也保留表头。"""
    return build_export_response(request, service, LIST_FIELDS, "chart", "可视化图表配置清单", ALIASES)
