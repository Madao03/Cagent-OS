"""HTTP routes for the public roadmap page — Beta+ feature.

Stores roadmap groups + cards in a single SQLite table (`data/roadmap.db`,
WAL mode). Cards are kept as a JSON array inside each group row to avoid
multi-table JOINs — the roadmap is read-heavy and write-rare, so a single
blob read is simpler and faster.

Endpoints:
  - GET  /api/v1/roadmap        — public read-only (all groups + cards)
  - PUT  /api/v1/roadmap        — admin only, full replace
  - POST /api/v1/roadmap/init   — admin only, seed default data if table empty
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from cagent_os.interfaces.http.auth_context import require_admin

logger = logging.getLogger(__name__)

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS roadmap_groups (
    id        TEXT PRIMARY KEY,
    title     TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    cards     TEXT NOT NULL DEFAULT '[]'
);
"""


# ── Default seed data (extracted from docs/ROADMAP_v4.md) ────────────

_DEFAULT_GROUPS: list[dict[str, Any]] = [
    {
        "id": "live",
        "title": "✅ 已上线",
        "sort_order": 0,
        "cards": [
            {
                "id": "provenance",
                "title": "数字溯源",
                "desc": "每个数字可追溯到一手来源，3-pass 校验防幻觉",
                "status": "done",
                "priority": "P0",
                "eta": "",
                "children": [
                    {"title": "FactRegistry 字段级事实注册", "done": True},
                    {"title": "3-pass Checker (精确→abs→verbatim)", "done": True},
                    {"title": "P1 派生链 (公式验证 + 精度继承)", "done": True},
                ],
            },
            {
                "id": "knowledge",
                "title": "精选知识库",
                "desc": "五维分诊筛选 + 渐进式披露 + RAG 语义检索",
                "status": "done",
                "priority": "P0",
                "eta": "",
                "children": [
                    {"title": "content-triage 五维锚点评分", "done": True},
                    {"title": "read-later L1/L2/L3 渐进披露", "done": True},
                    {"title": "RAG (Embedding + Reranker)", "done": True},
                ],
            },
            {
                "id": "cross-validation",
                "title": "多源交叉验证",
                "desc": "10 个数据源交叉校验，方差 >5% 触发告警",
                "status": "done",
                "priority": "P0",
                "eta": "",
                "children": [
                    {"title": "SEC EDGAR (XBRL + 业绩新闻稿)", "done": True},
                    {"title": "FRED 21 宏观系列", "done": True},
                    {"title": "akshare A股 + 港股 + 期货", "done": True},
                    {"title": "yfinance + fin-skill 交叉验证", "done": True},
                ],
            },
            {
                "id": "memory",
                "title": "跨会话记忆",
                "desc": "热记忆注入 + 冷记忆持久化 + LLM 矛盾检测",
                "status": "done",
                "priority": "P0",
                "eta": "",
                "children": [
                    {"title": "SqliteMemoryStore (3 表 WAL)", "done": True},
                    {"title": "ContradictionDetector (LLM 语义比较)", "done": True},
                ],
            },
        ],
    },
    {
        "id": "near",
        "title": "🔨 近期",
        "sort_order": 1,
        "cards": [
            {
                "id": "feedback",
                "title": "反馈中心",
                "desc": "接收用户反馈（文字 + 截图），最小反馈闭环",
                "status": "in_progress",
                "priority": "P0",
                "eta": "",
                "children": [
                    {"title": "反馈提交页面", "done": False},
                    {"title": "后台反馈收集存储", "done": False},
                ],
            },
            {
                "id": "roadmap-page",
                "title": "路线图页面",
                "desc": "展示开发进展给用户看，公开透明",
                "status": "in_progress",
                "priority": "P0",
                "eta": "",
                "children": [
                    {"title": "路线图后端 API", "done": True},
                    {"title": "路线图前端页面", "done": False},
                ],
            },
            {
                "id": "opinion-bank",
                "title": "观点库",
                "desc": "选中回答 → 引用/存入/点赞点踩/报错，切 React 首页",
                "status": "planned",
                "priority": "P0",
                "eta": "",
                "children": [
                    {"title": "React 基建搭建", "done": False},
                    {"title": "观点存入 + 引用", "done": False},
                    {"title": "点赞点踩埋点 (8-L1)", "done": False},
                ],
            },
        ],
    },
    {
        "id": "planned",
        "title": "📋 计划中",
        "sort_order": 2,
        "cards": [
            {
                "id": "multi-agent",
                "title": "多 Agent 协作",
                "desc": "后端 Supervisor 适配到 Web 请求流，前端展示多 Agent 过程",
                "status": "planned",
                "priority": "P1",
                "eta": "",
                "children": [
                    {"title": "Supervisor Web 流式适配", "done": False},
                    {"title": "多 Agent 过程可视化", "done": False},
                ],
            },
            {
                "id": "signal-noise",
                "title": "信息流去噪",
                "desc": "真正去噪，用户只关注的信息流",
                "status": "planned",
                "priority": "P1",
                "eta": "",
                "children": [
                    {"title": "信息流工具设计", "done": False},
                ],
            },
            {
                "id": "custom-framework",
                "title": "用户自定义框架",
                "desc": "个性化注入框架 + 自带 API key / 模型",
                "status": "planned",
                "priority": "P2",
                "eta": "",
                "children": [
                    {"title": "安全存储 + 模型路由改造", "done": False},
                ],
            },
            {
                "id": "multimodal",
                "title": "多模态接入",
                "desc": "图片/文件上传 + RAG 多模态理解",
                "status": "planned",
                "priority": "P2",
                "eta": "",
                "children": [
                    {"title": "图片上传 + 描述", "done": False},
                    {"title": "文件 RAG 接入", "done": False},
                ],
            },
        ],
    },
]


# ── Pydantic schemas for PUT body ────────────────────────────────────

class CardChild(BaseModel):
    title: str
    done: bool = False


class RoadmapCard(BaseModel):
    id: str
    title: str
    desc: str = ""
    status: str = "planned"
    priority: str = ""
    eta: str = ""
    children: list[CardChild] = Field(default_factory=list)


class RoadmapGroupInput(BaseModel):
    id: str
    title: str
    sort_order: int = 0
    cards: list[RoadmapCard] = Field(default_factory=list)


class RoadmapUpdate(BaseModel):
    groups: list[RoadmapGroupInput]


# ── DB helpers ───────────────────────────────────────────────────────

def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_table(db_path: str | Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.executescript(_TABLE_DDL)
        conn.commit()
    finally:
        conn.close()


def _row_to_group(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "sort_order": row["sort_order"],
        "cards": json.loads(row["cards"]),
    }


def _count_groups(db_path: str | Path) -> int:
    conn = _connect(db_path)
    try:
        cur = conn.execute("SELECT COUNT(*) AS n FROM roadmap_groups")
        return cur.fetchone()["n"]
    finally:
        conn.close()


def _load_all_groups(db_path: str | Path) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        cur = conn.execute("SELECT * FROM roadmap_groups ORDER BY sort_order ASC, id ASC")
        return [_row_to_group(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _replace_all(db_path: str | Path, groups: list[dict[str, Any]]) -> int:
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM roadmap_groups")
        for g in groups:
            conn.execute(
                "INSERT INTO roadmap_groups (id, title, sort_order, cards) VALUES (?, ?, ?, ?)",
                (
                    g["id"],
                    g["title"],
                    g.get("sort_order", 0),
                    json.dumps(g.get("cards", []), ensure_ascii=False),
                ),
            )
        conn.commit()
        return len(groups)
    finally:
        conn.close()


# ── Router factory ───────────────────────────────────────────────────

def build_roadmap_router(db_path: str | Path) -> APIRouter:
    _ensure_table(db_path)
    router = APIRouter()

    @router.get("/api/v1/roadmap")
    def get_roadmap() -> dict:
        """Public read-only — return all groups + cards. Auto-seeds on first call."""
        groups = _load_all_groups(db_path)
        if not groups:
            count = _replace_all(db_path, _DEFAULT_GROUPS)
            logger.info("Roadmap auto-seeded with default data: %d groups", count)
            groups = _load_all_groups(db_path)
        return {"groups": groups}

    @router.put("/api/v1/roadmap")
    def put_roadmap(payload: RoadmapUpdate, request: Request) -> dict:
        """Admin only — full replace of roadmap data."""
        require_admin(request)
        groups = [g.model_dump() for g in payload.groups]
        count = _replace_all(db_path, groups)
        logger.info("Roadmap replaced by admin: %d groups", count)
        return {"status": "ok", "groups": count}

    @router.post("/api/v1/roadmap/init")
    def init_roadmap(request: Request) -> dict:
        """Admin only — seed default data if table is empty."""
        require_admin(request)
        existing = _count_groups(db_path)
        if existing > 0:
            return {"status": "skipped", "reason": "table not empty", "existing": existing}
        count = _replace_all(db_path, _DEFAULT_GROUPS)
        logger.info("Roadmap seeded with default data: %d groups", count)
        return {"status": "ok", "groups": count}

    return router
