"""路由层共用的小工具：统一解析筛选参数、组装分页结果和导出文件。

各业务模块的列表、摘要与导出都从这里走，避免同一个筛选条件在不同页面各解释一套。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.schemas import PageResult
from app.services.filtering import (
    FilterCriteria,
    FilterableService,
    criteria_from_query,
    render_csv,
)

MAX_PAGE_SIZE = 200


def _criteria(request: Request, list_fields: Sequence[str], aliases: Mapping[str, str] | None) -> FilterCriteria:
    return criteria_from_query(request.query_params, list_fields, aliases)


def _validate_paging(page: int, size: int) -> tuple[int, int]:
    if page < 1:
        raise HTTPException(status_code=400, detail="页码必须从 1 开始，请把 page 设为不小于 1 的整数")
    if size < 1:
        raise HTTPException(status_code=400, detail="每页条数必须大于 0，请把 size 设为正整数")
    if size > MAX_PAGE_SIZE:
        raise HTTPException(status_code=400, detail=f"每页最多 {MAX_PAGE_SIZE} 条，请缩小分页范围或使用导出")
    return page, size


def build_page_result(
    request: Request,
    service: FilterableService,
    list_fields: Sequence[str],
    aliases: Mapping[str, str] | None = None,
    *,
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """读取列表：筛选、排序、分页一次完成，并返回这次结果对应的快照令牌。"""
    page, size = _validate_paging(page, size)
    criteria = _criteria(request, list_fields, aliases)
    result = service.query_criteria(criteria, page=page, size=size)
    return PageResult(
        items=result.items,
        total=result.total,
        page=result.page,
        size=result.size,
        snapshot=result.snapshot,
        filters=criteria.to_dict(),
        summary=result.summary,
    )


def build_summary(
    request: Request,
    service: FilterableService,
    list_fields: Sequence[str],
    aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """筛选摘要：优先复用当前列表那张快照，保证摘要与列表看到的是同一批数据。"""
    return service.summary(request.query_params, list_fields, aliases)


def _export_headers(module: str, snapshot: str | None, total: int, label: str) -> dict[str, str]:
    filename = f"{module}-{date.today().isoformat()}.csv"
    encoded = quote(f"{label}.csv")
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{encoded}",
        "X-Total-Count": str(total),
        "Access-Control-Expose-Headers": "Content-Disposition, X-Total-Count, X-Snapshot-Id",
    }
    if snapshot:
        headers["X-Snapshot-Id"] = snapshot
    return headers


def build_export_response(
    request: Request,
    service: FilterableService,
    list_fields: Sequence[str],
    module: str,
    label: str,
    aliases: Mapping[str, str] | None = None,
) -> Response:
    """导出当前列表条件下的全量数据。

    默认输出带表头的 CSV 文件（页面新窗口打开即为下载，脚本直接请求也能拿到文件）；
    需要结构化数据时传 ``format=json`` 或 ``Accept: application/json``，返回
    ``{module, total, items, filters, snapshot}``，兼容原有读取 JSON 的调用。
    没有命中时 CSV 仍保留表头，得到一份可识别的空文件。
    """
    criteria, snapshot, rows = service.export(request.query_params, list_fields, aliases)
    total = len(rows)
    snapshot_token = snapshot.token if snapshot else None
    headers = _export_headers(module, snapshot_token, total, label)
    headers["X-Filter-Criteria"] = quote(str(criteria.to_dict()), safe="")

    wants_format = str(request.query_params.get("format") or "").strip().lower()
    accept = request.headers.get("accept", "")
    wants_json = wants_format == "json" or (wants_format == "" and "application/json" in accept)
    if wants_json:
        payload = {
            "module": module,
            "total": total,
            "items": rows,
            "filters": criteria.to_dict(),
            "snapshot": snapshot_token,
        }
        return JSONResponse(content=payload, headers=headers)

    csv_text = render_csv(rows, list_fields, with_bom=False)
    return Response(content=csv_text, media_type="text/csv; charset=utf-8", headers=headers)