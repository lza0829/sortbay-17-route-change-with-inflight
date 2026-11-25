from __future__ import annotations
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import db, rows_to_list, row_to_dict
from app.services.routing import affected_scans, change_route_mapping

router = APIRouter(tags=["路由表"])


class RouteIn(BaseModel):
    目的地码: str = Field(min_length=1)
    口门编号: int
    备注: str = ""


@router.get("/路由表")
def list_routes():
    with db() as conn:
        return rows_to_list(conn.execute(
            """
            SELECT r.*, c.code AS 口门码, c.title AS 口门标题
            FROM route_rules r JOIN chutes c ON c.id=r.chute_id
            ORDER BY r.dest_code
            """
        ).fetchall())


@router.get("/路由表/影响")
def preview_impact(目的地码: str):
    """改表前预览：若现在改这个目的地，会强制回流哪些在途已路由件。"""
    with db() as conn:
        rows = affected_scans(conn, 目的地码)
        rule = conn.execute(
            "SELECT * FROM route_rules WHERE dest_code=?", (目的地码,)
        ).fetchone()
        return {
            "目的地码": 目的地码,
            "当前路由": row_to_dict(rule),
            "受影响件数": len(rows),
            "受影响件": rows,
        }


@router.post("/路由表")
def upsert_route(body: RouteIn):
    # 口径：改表强制回流在途。整笔在一个 BEGIN IMMEDIATE 事务内完成，
    # 与封袋/入袋/路由裁决严格串行；失败整体回滚，路由表与在途都不变。
    with db(write=True) as conn:
        result = change_route_mapping(conn, body.目的地码, body.口门编号, body.备注)
        return result


@router.get("/改表回执")
def list_receipts(limit: int = 100):
    with db() as conn:
        rows = rows_to_list(conn.execute(
            "SELECT * FROM route_change_receipts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall())
        for r in rows:
            try:
                r["payload"] = json.loads(r["payload"])
            except Exception:
                pass
        return rows


@router.get("/改表回执/{receipt_id}")
def get_receipt(receipt_id: int):
    with db() as conn:
        r = row_to_dict(conn.execute(
            "SELECT * FROM route_change_receipts WHERE id=?", (receipt_id,)
        ).fetchone())
        if not r:
            raise HTTPException(404, "回执不存在")
        try:
            r["payload"] = json.loads(r["payload"])
        except Exception:
            pass
        return r
