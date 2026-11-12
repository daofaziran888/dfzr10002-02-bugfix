"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

列表和导出需要看到同一份数据。这里的做法是在列表查询时给当前模块拍一张快照，
导出优先按快照取数；快照之后的登记、状态流转不会反过来影响已经展示的列表。
"""
from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from app.seed import SEED_ROWS

MAX_SNAPSHOTS = 128


@dataclass
class Snapshot:
    """一次列表查询对应的数据快照。"""

    token: str
    module: str
    rows: list[dict[str, Any]]
    filters: dict[str, str] = field(default_factory=dict)
    page: int = 1
    size: int = 20
    total: int = 0


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._snapshots: OrderedDict[str, Snapshot] = OrderedDict()
        self._latest_snapshots: dict[str, str] = {}
        self._lock = threading.RLock()

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def snapshot(
        self,
        module: str,
        *,
        filters: dict[str, str] | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Snapshot:
        """给当前模块拍快照，并记住它是该模块最近一次列表查询。"""
        token = uuid.uuid4().hex
        with self._lock:
            snapshot = Snapshot(
                token=token,
                module=module,
                rows=[dict(row) for row in self.rows(module)],
                filters=dict(filters or {}),
                page=page,
                size=size,
            )
            self._snapshots[token] = snapshot
            self._latest_snapshots[module] = token
            while len(self._snapshots) > MAX_SNAPSHOTS:
                old_token, old_snapshot = self._snapshots.popitem(last=False)
                if self._latest_snapshots.get(old_snapshot.module) == old_token:
                    self._latest_snapshots.pop(old_snapshot.module, None)
        return snapshot

    def get_snapshot(self, token: str | None) -> Snapshot | None:
        if not token:
            return None
        with self._lock:
            snapshot = self._snapshots.get(token)
            if snapshot is not None:
                self._snapshots.move_to_end(token)
            return snapshot

    def latest_snapshot(self, module: str) -> Snapshot | None:
        with self._lock:
            token = self._latest_snapshots.get(module)
            return self._snapshots.get(token) if token else None

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        """运营概览：按模块汇总当前数据。"""
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            modules.append(self._module_card(name, self.rows(name)))
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}

    def overview_snapshot(self, module: str, rows: list[dict[str, Any]] | None = None) -> dict[str, object]:
        """按给定行（通常是列表快照过滤后的行）汇总单个模块，供筛选摘要页与列表同步。

        ``rows`` 为空时取该模块最近一次列表快照，没有快照则用实时数据；
        其余模块仍按实时数据展示。
        """
        if rows is None:
            snapshot = self.latest_snapshot(module)
            rows = snapshot.rows if snapshot is not None else self.rows(module)
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            modules.append(self._module_card(name, rows if name == module else self.rows(name)))
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}

    @staticmethod
    def _module_card(name: str, rows: list[dict[str, Any]]) -> dict[str, object]:
        return {
            "name": name,
            "created": len(rows),
            "pending": sum(1 for row in rows if row.get("pending")),
            "abnormal": sum(1 for row in rows if row.get("abnormal")),
        }


store = Store()
