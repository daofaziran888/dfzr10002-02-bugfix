"""数据分析工作台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ROUTERS
from app.services.filtering import FilterCriteria, row_matches, search_fields
from app.store import store

app = FastAPI(title="数据分析工作台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in ROUTERS:
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview(request: Request) -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。

    摘要页跟着列表跳转时会带 ``module`` 与 ``snapshot``：该模块按列表那次查询的快照
    与筛选条件统计，其余模块按实时数据展示，避免摘要和列表各按不同筛选条件。
    """
    module = str(request.query_params.get("module") or "").strip()
    if module not in store.module_names():
        return store.overview()

    token = str(request.query_params.get("snapshot") or request.query_params.get("snapshot_id") or "").strip()
    snapshot = store.get_snapshot(token) if token else store.latest_snapshot(module)
    if snapshot is None or snapshot.module != module:
        return store.overview_snapshot(module)

    criteria = FilterCriteria.from_dict(snapshot.filters)
    rows = snapshot.rows
    filtered = [row for row in rows if row_matches(row, criteria, keyword_fields=search_fields(rows))]

    payload = store.overview_snapshot(module, rows=filtered)
    return {
        **payload,
        "module": module,
        "snapshot": snapshot.token,
        "filters": criteria.to_dict(),
        "selected": {
            "name": module,
            "created": len(filtered),
            "pending": sum(1 for row in filtered if row.get("pending")),
            "abnormal": sum(1 for row in filtered if row.get("abnormal")),
        },
    }
