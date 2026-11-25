from __future__ import annotations
import json
import uuid

from fastapi import HTTPException

from app.services.common import audit, now_str

# “在途已路由” = 已完成路由裁决、但尚未封袋的件。
# 已入袋也属于未封袋（袋仍为集包中），物理上仍停在旧口门，必须一并强制回流。
IN_FLIGHT_STATUSES = ("已路由", "已入袋")


def _auto_reroute_enabled(conn) -> bool:
    row = conn.execute(
        "SELECT value FROM settings WHERE key='回流自动再路由'"
    ).fetchone()
    return bool(row) and row["value"] == "是"


def _chute_view(conn, chute_id: int | None) -> dict | None:
    if chute_id is None:
        return None
    row = conn.execute(
        "SELECT id, code, title FROM chutes WHERE id=?", (chute_id,)
    ).fetchone()
    return dict(row) if row else None


def affected_scans(conn, dest_code: str) -> list[dict]:
    """列出受改表影响的在途已路由件（已路由 / 已入袋）。"""
    rows = conn.execute(
        f"""
        SELECT * FROM scans
        WHERE dest_code=? AND status IN ({','.join('?' * len(IN_FLIGHT_STATUSES))})
        ORDER BY id
        """,
        (dest_code, *IN_FLIGHT_STATUSES),
    ).fetchall()
    return [dict(r) for r in rows]


def change_route_mapping(
    conn,
    dest_code: str,
    new_chute_id: int,
    note: str = "",
) -> dict:
    """在调用方已开启的写事务内完成一次“改路由表”。

    口径（全局唯一）：改表强制回流在途。
      * 允许改表；同一笔事务内把受影响、仍停在旧口门、尚未封袋的件标为
        “错分回流”、脱离原袋，并写 route_events + audit + 改表回执。
      * 任何一步失败 -> 整笔回滚，路由表与在途均保持原样（不出现半截拧花）。
      * 回执 payload 记录改前/改后与逐件动作，可据以重放、对账。

    返回：{回执, 是否触发回流, 受影响件, 路由}
    """
    chute = conn.execute("SELECT * FROM chutes WHERE id=?", (new_chute_id,)).fetchone()
    if not chute:
        raise HTTPException(404, "口门不存在")

    exist = conn.execute(
        "SELECT * FROM route_rules WHERE dest_code=?", (dest_code,)
    ).fetchone()
    old_chute_id = exist["chute_id"] if exist else None
    rule_id = exist["id"] if exist else None

    affected = affected_scans(conn, dest_code)

    # 1) 写路由表（先落新映射，后续回流事件以新映射为归宿）。
    if exist:
        conn.execute(
            "UPDATE route_rules SET chute_id=?, note=? WHERE id=?",
            (new_chute_id, note, rule_id),
        )
        rule_action = "改路由"
    else:
        conn.execute(
            "INSERT INTO route_rules(dest_code, chute_id, note) VALUES (?, ?, ?)",
            (dest_code, new_chute_id, note),
        )
        rule_id = conn.execute(
            "SELECT id FROM route_rules WHERE dest_code=?", (dest_code,)
        ).fetchone()["id"]
        rule_action = "新建路由"

    # 2) 强制回流受影响的在途件。按班次建回流批次（通常只有一个未封班班次）。
    auto_reroute = _auto_reroute_enabled(conn)
    by_shift: dict[int, list[dict]] = {}
    for s in affected:
        by_shift.setdefault(s["shift_id"], []).append(s)

    forced = []
    batches = []
    for shift_id, scans in by_shift.items():
        code = f"改表回流-{dest_code}-{uuid.uuid4().hex[:8]}"
        conn.execute(
            """
            INSERT INTO divert_batches(shift_id, code, status, created_at, note)
            VALUES (?, ?, '回流中', ?, ?)
            """,
            (shift_id, code, now_str(), f"改表 {dest_code} 强制回流 {len(scans)} 件"),
        )
        batch_id = conn.execute(
            "SELECT id FROM divert_batches WHERE code=?", (code,)
        ).fetchone()["id"]
        batches.append({"id": batch_id, "code": code, "shift_id": shift_id,
                        "count": len(scans)})

        for s in scans:
            old_status = s["status"]
            old_bag = s["bag_id"]
            # 错分回流：脱离原袋，并清空 chute_id——否则读路径会把“已回流件”
            # 显示成仍挂在旧口门（“表已改、在途仍挂旧口”的翻版）。
            # 旧口门历史完整保留在下面的 route_events 与回执 payload 里，可供重放。
            conn.execute(
                """
                UPDATE scans
                SET status='错分回流', bag_id=NULL, chute_id=NULL, divert_batch_id=?
                WHERE id=?
                """,
                (batch_id, s["id"]),
            )
            event_chute = s["chute_id"] if s["chute_id"] is not None else (
                old_chute_id if old_chute_id is not None else new_chute_id
            )
            conn.execute(
                """
                INSERT INTO route_events(scan_id, chute_id, action, created_at, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (s["id"], event_chute, "改表强制回流", now_str(),
                 f"{dest_code}:{chute['code']} · {old_status}→错分回流 · {code}"),
            )
            entry = {
                "scan_id": s["id"],
                "barcode": s["barcode"],
                "from_status": old_status,
                "from_chute_id": s["chute_id"],
                "from_bag_id": old_bag,
                "divert_batch_id": batch_id,
                "final_status": "错分回流",
                "final_chute_id": None,
            }
            # 臂内策略：若设置开启“回流自动再路由”，同一笔内按新映射再裁决一次。
            if auto_reroute:
                conn.execute(
                    "UPDATE scans SET status='已路由', chute_id=? WHERE id=?",
                    (new_chute_id, s["id"]),
                )
                conn.execute(
                    """
                    INSERT INTO route_events(scan_id, chute_id, action, created_at, note)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (s["id"], new_chute_id, "改表自动再路由", now_str(),
                     f"{dest_code}:{chute['code']}"),
                )
                entry["final_status"] = "已路由"
                entry["final_chute_id"] = new_chute_id
            forced.append(entry)

    at = now_str()
    receipt_payload = {
        "dest_code": dest_code,
        "old_chute": _chute_view(conn, old_chute_id),
        "new_chute": _chute_view(conn, new_chute_id),
        "auto_reroute": auto_reroute,
        "forced": forced,
        "divert_batches": batches,
        "rule_id": rule_id,
        "at": at,
    }
    conn.execute(
        """
        INSERT INTO route_change_receipts
          (dest_code, old_chute_id, new_chute_id, forced_count, created_at, payload)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (dest_code, old_chute_id, new_chute_id, len(forced), at,
         json.dumps(receipt_payload, ensure_ascii=False, sort_keys=True)),
    )
    receipt_id = conn.execute(
        "SELECT id FROM route_change_receipts ORDER BY id DESC LIMIT 1"
    ).fetchone()["id"]

    action = "改路由并强制回流" if forced else rule_action
    audit(
        conn, "路由表", rule_id, action,
        f"{dest_code}: {old_chute_id}→{new_chute_id} · 强制回流{len(forced)}件 · 回执{receipt_id}",
    )

    route = conn.execute(
        """
        SELECT r.*, c.code AS 口门码, c.title AS 口门标题
        FROM route_rules r JOIN chutes c ON c.id=r.chute_id
        WHERE r.id=?
        """,
        (rule_id,),
    ).fetchone()

    return {
        "回执编号": receipt_id,
        "是否触发回流": bool(forced),
        "强制回流件数": len(forced),
        "受影响件": forced,
        "回流批次": batches,
        "路由": dict(route),
        "回执": {
            "id": receipt_id,
            "dest_code": dest_code,
            "old_chute_id": old_chute_id,
            "new_chute_id": new_chute_id,
            "forced_count": len(forced),
            "created_at": at,
            "payload": receipt_payload,
        },
    }
