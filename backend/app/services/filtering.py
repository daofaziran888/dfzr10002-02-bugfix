"""跨模块共用的筛选契约：把查询参数收敛成一套条件，列表、摘要与导出都按它取数。

约定：
- ``keyword`` 做包含匹配，默认检索前三个业务字段（编号、名称、第三列），
  因此原有的“按编号检索”依旧可用，也能按名称或公式片段检索；
- 也可以直接按列名（如 ``指标名称``、``口径版本``）传筛选条件，列名条件之间按“且”组合；
- ``status`` / ``状态`` 精确匹配状态字段；
- 结果按业务编号排序，保证列表、摘要与导出、以及多次打开之间行序一致。
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from app.store import Snapshot, store

INTERNAL_KEYS = {"id", "status", "pending", "abnormal"}
STATUS_ALIASES = ("status", "状态")
KEYWORD_ALIASES = ("keyword", "关键词")
IGNORED_PARAMS = {"page", "size", "snapshot", "snapshot_id", "format"}
DEFAULT_SEARCH_DEPTH = 3


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _norm(value: Any) -> str:
    return _text(value).casefold()


@dataclass(frozen=True)
class FilterCriteria:
    """一次查询使用的筛选条件。"""

    keyword: str | None = None
    status: str | None = None
    fields: Mapping[str, str] = field(default_factory=dict)

    def has_filters(self) -> bool:
        return bool(_text(self.keyword) or _text(self.status) or any(_text(v) for v in self.fields.values()))

    def to_dict(self) -> dict[str, str]:
        payload: dict[str, str] = {}
        if _text(self.keyword):
            payload["keyword"] = _text(self.keyword)
        if _text(self.status):
            payload["status"] = _text(self.status)
        for column, value in self.fields.items():
            if _text(value):
                payload[column] = _text(value)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, str]) -> "FilterCriteria":
        status = ""
        keyword = ""
        fields: dict[str, str] = {}
        for key, value in payload.items():
            if key in KEYWORD_ALIASES:
                keyword = _text(value)
            elif key in STATUS_ALIASES:
                status = _text(value)
            elif key not in IGNORED_PARAMS:
                fields[key] = _text(value)
        return cls(keyword=keyword or None, status=status or None, fields=fields)


def build_criteria(
    *,
    keyword: str | None = None,
    status: str | None = None,
    fields: Mapping[str, str] | None = None,
) -> FilterCriteria:
    cleaned_fields = {column: _text(value) for column, value in (fields or {}).items() if _text(value)}
    return FilterCriteria(keyword=_text(keyword) or None, status=_text(status) or None, fields=cleaned_fields)


def criteria_from_query(
    query_params: Mapping[str, str],
    list_fields: Sequence[str],
    aliases: Mapping[str, str] | None = None,
) -> FilterCriteria:
    """从查询参数里提取筛选条件。

    直接使用列名的条件（如 ``指标名称=月度活跃客户``）优先；英文别名（如 ``name``）
    在没有同名中文列时生效。未知参数会被忽略，不会让列表意外变成空表。
    """
    alias_map = dict(aliases or {})
    keyword = ""
    status = ""
    columns: dict[str, str] = {}

    for key, value in query_params.items():
        if key in IGNORED_PARAMS:
            continue
        if key in KEYWORD_ALIASES:
            keyword = _text(value)
            continue
        if key in STATUS_ALIASES:
            status = _text(value)
            continue
        target = key if key in list_fields else alias_map.get(key)
        if target in list_fields:
            columns[target] = _text(value)

    return build_criteria(keyword=keyword, status=status, fields=columns)


def business_columns(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """业务字段顺序：仓库里的行按列登记，内部字段（id/status 等）不参与展示与检索。"""
    for row in rows:
        return [key for key in row if key not in INTERNAL_KEYS]
    return []


def search_fields(rows: Iterable[Mapping[str, Any]], depth: int = DEFAULT_SEARCH_DEPTH) -> list[str]:
    return business_columns(rows)[:depth]


def id_field(rows: Iterable[Mapping[str, Any]]) -> str:
    columns = business_columns(rows)
    return columns[0] if columns else "id"


def row_matches(
    row: Mapping[str, Any],
    criteria: FilterCriteria,
    *,
    keyword_fields: Sequence[str] = (),
) -> bool:
    if criteria.keyword:
        needle = _norm(criteria.keyword)
        columns = keyword_fields or [key for key in row if key not in INTERNAL_KEYS]
        if not any(needle in _norm(row.get(column)) for column in columns):
            return False
    for column, expected in criteria.fields.items():
        if _text(expected) and _norm(expected) not in _norm(row.get(column)):
            return False
    if criteria.status and _text(row.get("status")) != _text(criteria.status):
        return False
    return True


def sort_rows(rows: Sequence[Mapping[str, Any]], code_field: str) -> list[dict[str, Any]]:
    """按业务编号排序，编号相同时用内部自增 id 兜底，保证次序稳定。"""

    def key(row: Mapping[str, Any]) -> tuple[str, int]:
        try:
            internal_id = int(row.get("id", 0) or 0)
        except (TypeError, ValueError):
            internal_id = 0
        return (_norm(row.get(code_field)), internal_id)

    return sorted((dict(row) for row in rows), key=key)


def summarize(rows: Sequence[Mapping[str, Any]], statuses: Sequence[str]) -> dict[str, Any]:
    counts: dict[str, int] = {status: 0 for status in statuses}
    for row in rows:
        status = _text(row.get("status"))
        if status:
            counts[status] = counts.get(status, 0) + 1
    return {"total": len(rows), "status_counts": counts}


@dataclass
class QueryResult:
    """一次列表查询的结果，附加快照令牌供导出与摘要复用。"""

    items: list[dict[str, Any]]
    total: int
    page: int
    size: int
    snapshot: str
    summary: dict[str, Any]
    all_rows: list[dict[str, Any]]


def _filter_snapshot(snapshot: Snapshot, criteria: FilterCriteria) -> list[dict[str, Any]]:
    rows = snapshot.rows
    keyword_fields = search_fields(rows)
    filtered = [row for row in rows if row_matches(row, criteria, keyword_fields=keyword_fields)]
    return sort_rows(filtered, id_field(rows))


def query_entries(
    module: str,
    criteria: FilterCriteria,
    *,
    statuses: Sequence[str] = (),
    page: int = 1,
    size: int = 20,
) -> QueryResult:
    """在模块快照上过滤、排序并分页；总数、摘要与导出都来自这张快照。"""
    snapshot = store.snapshot(module, filters=criteria.to_dict(), page=page, size=size)
    ordered = _filter_snapshot(snapshot, criteria)
    total = len(ordered)
    safe_page = max(int(page or 1), 1)
    safe_size = max(int(size or 0), 1)
    start = (safe_page - 1) * safe_size
    items = ordered[start:start + safe_size]
    snapshot.total = total
    return QueryResult(
        items=items,
        total=total,
        page=safe_page,
        size=safe_size,
        snapshot=snapshot.token,
        summary=summarize(ordered, statuses),
        all_rows=ordered,
    )


def _pick_snapshot(
    module: str,
    query_params: Mapping[str, str],
    list_fields: Sequence[str],
    aliases: Mapping[str, str] | None,
) -> tuple[FilterCriteria, Snapshot]:
    """确定摘要请求该用哪张快照、哪套条件。

    优先级：
    1. 显式带上 ``snapshot`` 令牌 —— 严格按列表快照记录的条件，冲突参数不生效；
    2. 请求条件与最近一次列表条件一致 —— 复用同一张快照，新增记录不会让总数对不上；
    3. 请求带有新的筛选条件 —— 立即拍一张新快照，摘要与列表仍基于同一次数据；
    4. 没有任何筛选参数 —— 沿用最近一次列表快照，否则对全量数据拍快照。
    """
    token = _text(query_params.get("snapshot")) or _text(query_params.get("snapshot_id"))
    if token:
        snapshot = store.get_snapshot(token)
        if snapshot is not None and snapshot.module == module:
            return FilterCriteria.from_dict(snapshot.filters), snapshot

    explicit = criteria_from_query(query_params, list_fields, aliases)
    latest = store.latest_snapshot(module)
    if latest is not None:
        latest_criteria = FilterCriteria.from_dict(latest.filters)
        if explicit.to_dict() == latest_criteria.to_dict():
            return latest_criteria, latest

    if explicit.has_filters():
        return explicit, store.snapshot(module, filters=explicit.to_dict())

    if latest is not None:
        return FilterCriteria.from_dict(latest.filters), latest

    return explicit, store.snapshot(module, filters={})


def resolve_export_criteria(
    module: str,
    query_params: Mapping[str, str],
    list_fields: Sequence[str],
    aliases: Mapping[str, str] | None = None,
) -> tuple[FilterCriteria, Snapshot]:
    """确定导出使用的条件与数据快照。

    导出必须和页面上的列表一致：
    - 带上列表返回的 ``snapshot`` 令牌时，严格按快照记录的列表条件取数，URL 上冲突
      的参数不生效（当前列表条件优先）；
    - 没带令牌时沿用最近一次列表查询的快照与条件，URL 上带着的旧筛选参数不生效，
      列表之后新增的记录也不会让文件行数与页面合计对不上；
    - 服务端还没有任何列表快照时，才按显式传入的参数拍一张新快照。
    """
    token = _text(query_params.get("snapshot")) or _text(query_params.get("snapshot_id"))
    if token:
        snapshot = store.get_snapshot(token)
        if snapshot is not None and snapshot.module == module:
            return FilterCriteria.from_dict(snapshot.filters), snapshot

    latest = store.latest_snapshot(module)
    if latest is not None:
        return FilterCriteria.from_dict(latest.filters), latest

    explicit = criteria_from_query(query_params, list_fields, aliases)
    return explicit, store.snapshot(module, filters=explicit.to_dict())


def summary_for(
    module: str,
    *,
    statuses: Sequence[str] = (),
    query_params: Mapping[str, str] | None = None,
    list_fields: Sequence[str] = (),
    aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """返回与当前列表同一快照、同一筛选条件的摘要。

    摘要页跟着列表走：带上列表令牌时严格按列表条件；没有令牌时按当前参数取数，
    与列表共用同一套筛选契约，不会各按不同过滤条件。
    """
    params = query_params or {}
    criteria, snapshot = _pick_snapshot(module, params, list_fields, aliases)
    filtered = _filter_snapshot(snapshot, criteria)
    return {
        "module": module,
        "snapshot": snapshot.token,
        "filters": criteria.to_dict(),
        **summarize(filtered, statuses),
    }


def export_rows(
    module: str,
    *,
    query_params: Mapping[str, str],
    list_fields: Sequence[str],
    aliases: Mapping[str, str] | None = None,
) -> tuple[FilterCriteria, Snapshot, list[dict[str, Any]]]:
    criteria, snapshot = resolve_export_criteria(module, query_params, list_fields, aliases)
    rows = _filter_snapshot(snapshot, criteria)
    return criteria, snapshot, rows


def render_csv(rows: Sequence[Mapping[str, Any]], columns: Sequence[str], *, with_bom: bool = False) -> str:
    """把行渲染成带表头的 CSV；没有命中时仍保留表头，得到一份空文件。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(columns))
    for row in rows:
        writer.writerow(["" if row.get(column) is None else row.get(column) for column in columns])
    content = buffer.getvalue()
    return "﻿" + content if with_bom else content


class FilterableService:
    """各业务模块共用的列表 / 摘要 / 导出实现。

    子类只需要声明模块名与状态序列，筛选、排序和快照口径都从这里来，
    避免列表、另一个页面的摘要和导出各按一套过滤条件。
    """

    module: str = ""
    statuses: Sequence[str] = ()

    def query(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        filters: Mapping[str, str] | None = None,
        page: int = 1,
        size: int = 20,
    ) -> QueryResult:
        criteria = build_criteria(keyword=keyword, status=status, fields=filters)
        return self.query_criteria(criteria, page=page, size=size)

    def query_criteria(self, criteria: FilterCriteria, *, page: int = 1, size: int = 20) -> QueryResult:
        return query_entries(self.module, criteria, statuses=self.statuses, page=page, size=size)

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        filters: Mapping[str, str] | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        result = self.query(keyword=keyword, status=status, filters=filters, page=page, size=size)
        return result.items, result.total

    def summary(
        self,
        query_params: Mapping[str, str],
        list_fields: Sequence[str],
        aliases: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return summary_for(
            self.module,
            statuses=self.statuses,
            query_params=query_params,
            list_fields=list_fields,
            aliases=aliases,
        )

    def export(
        self,
        query_params: Mapping[str, str],
        list_fields: Sequence[str],
        aliases: Mapping[str, str] | None = None,
    ) -> tuple[FilterCriteria, Snapshot, list[dict[str, Any]]]:
        return export_rows(
            self.module,
            query_params=query_params,
            list_fields=list_fields,
            aliases=aliases,
        )
