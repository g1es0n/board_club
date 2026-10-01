import json
from datetime import date

import logging
log = logging.getLogger("board_club.sessions")

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import staff_db, staff_user
from ..db import execute, fetch_all, fetch_one, paginate, transaction
from ..schemas import AttendanceIn, PlayerRef, RescheduleIn, ScoresIn, SessionIn

router = APIRouter(prefix="/api/sessions", tags=["Партии"])

SESSION_SELECT = """
    SELECT s.id, s.starts_at, s.ends_at, s.status,
           s.game_id, g.title AS game, g.min_players, g.max_players,
           s.table_id, t.number AS table_number, t.capacity, t.description AS table_description,
           s.host_id, st.full_name AS host,
           (SELECT COUNT(*) FROM session_player sp WHERE sp.session_id = s.id) AS players_count
      FROM session s
      JOIN game g        ON g.id = s.game_id
      JOIN game_table t  ON t.id = s.table_id
      JOIN staff st      ON st.id = s.host_id"""


@router.get("")
def list_sessions(
    status: str | None = Query(None, pattern="^(planned|active|finished|cancelled)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db=Depends(staff_db),
):
    where, params = [], []
    if status:
        where.append("s.status = %s")
        params.append(status)
    if date_from:
        where.append("s.starts_at >= %s")
        params.append(date_from)
    if date_to:
        where.append("s.starts_at < DATE_ADD(%s, INTERVAL 1 DAY)")
        params.append(date_to)
    return paginate(db, SESSION_SELECT, where, params, "starts_at DESC", page, size)


@router.get("/{session_id}")
def get_session(session_id: int, db=Depends(staff_db)):
    session = fetch_one(db, SESSION_SELECT + " WHERE s.id = %s", [session_id])
    if not session:
        raise HTTPException(404, "Партия не найдена")

    try:
        players = fetch_all(db, """
            SELECT p.id AS player_id, p.nickname, p.name, p.rating,
                   sp.score, sp.place, sp.rating_delta, sp.attended
              FROM session_player sp JOIN player p ON p.id = sp.player_id
             WHERE sp.session_id = %s
             ORDER BY sp.place IS NULL, sp.place, p.nickname""", [session_id])
    except Exception as e:
        log.exception("get_session(%s): не удалось получить участников: %s", session_id, e)
        players = []

    session["players"] = players if isinstance(players, list) else []
    return session


@router.post("", status_code=201)
def create_session(data: SessionIn, user: dict = Depends(staff_user), db=Depends(staff_db)):
    row = fetch_one(db, "CALL sp_create_session(%s, %s, %s, %s, %s, %s)", [
        data.game_id, data.table_id, user["id"], data.starts_at, data.ends_at, json.dumps(data.player_ids),
    ])
    return get_session(row["id"], db)


@router.put("/{session_id}")
def reschedule_session(session_id: int, data: RescheduleIn, db=Depends(staff_db)):
    session = fetch_one(db, "SELECT id, status FROM session WHERE id = %s", [session_id])
    if not session:
        raise HTTPException(404, "Партия не найдена")
    if session["status"] != "planned":
        raise HTTPException(400, "Перенести можно только запланированную партию")

    with transaction(db) as cur:
        # 1. Удалить участников, которых нет в новом списке
        placeholders = ",".join(["%s"] * len(data.player_ids))
        cur.execute(
            f"DELETE FROM session_player WHERE session_id = %s AND player_id NOT IN ({placeholders})",
            [session_id, *data.player_ids],
        )
        # 2. Обновить время и стол (триггер проверит конфликты у оставшихся участников)
        cur.execute(
            "UPDATE session SET starts_at = %s, ends_at = %s, table_id = %s WHERE id = %s",
            [data.starts_at, data.ends_at, data.table_id, session_id],
        )
        # 3. Добавить новых участников
        cur.execute("SELECT player_id FROM session_player WHERE session_id = %s", [session_id])
        existing = {r["player_id"] for r in cur.fetchall()}
        for pid in data.player_ids:
            if pid not in existing:
                cur.execute(
                    "INSERT INTO session_player (session_id, player_id) VALUES (%s, %s)",
                    [session_id, pid],
                )
    return get_session(session_id, db)


@router.post("/{session_id}/players", status_code=201)
def add_player(session_id: int, data: PlayerRef, db=Depends(staff_db)):
    get_session(session_id, db)
    execute(db, "INSERT INTO session_player (session_id, player_id) VALUES (%s, %s)",
            [session_id, data.player_id])
    return get_session(session_id, db)


@router.delete("/{session_id}/players/{player_id}")
def remove_player(session_id: int, player_id: int, db=Depends(staff_db)):
    cur = execute(db, "DELETE FROM session_player WHERE session_id = %s AND player_id = %s",
                  [session_id, player_id])
    if cur.rowcount == 0:
        raise HTTPException(404, "Игрок не участвует в этой партии")
    return get_session(session_id, db)


@router.put("/{session_id}/scores")
def save_scores(session_id: int, data: ScoresIn, db=Depends(staff_db)):
    get_session(session_id, db)
    with transaction(db) as cur:
        for item in data.scores:
            cur.execute("UPDATE session_player SET score = %s WHERE session_id = %s AND player_id = %s",
                        [item.score, session_id, item.player_id])
            if cur.rowcount == 0 and not fetch_one(
                    db, "SELECT 1 FROM session_player WHERE session_id = %s AND player_id = %s",
                    [session_id, item.player_id]):
                raise HTTPException(400, f"Игрок {item.player_id} не участвует в этой партии")
    return get_session(session_id, db)


@router.put("/{session_id}/attendance")
def save_attendance(session_id: int, data: AttendanceIn, db=Depends(staff_db)):
    session = fetch_one(db, "SELECT status FROM session WHERE id = %s", [session_id])
    if not session:
        raise HTTPException(404, "Партия не найдена")
    if session["status"] not in ("active", "finished"):
        raise HTTPException(400, "Отметить посещаемость можно только у идущей или завершённой партии")

    with transaction(db) as cur:
        for item in data.attendance:
            cur.execute(
                "UPDATE session_player SET attended = %s WHERE session_id = %s AND player_id = %s",
                [item.attended, session_id, item.player_id],
            )
            if cur.rowcount == 0 and not fetch_one(
                    db, "SELECT 1 FROM session_player WHERE session_id = %s AND player_id = %s",
                    [session_id, item.player_id]):
                raise HTTPException(400, f"Игрок {item.player_id} не участвует в этой партии")
    return get_session(session_id, db)


@router.post("/{session_id}/start")
def start_session(session_id: int, db=Depends(staff_db)):
    execute(db, "CALL sp_start_session(%s)", [session_id])
    return get_session(session_id, db)


@router.post("/{session_id}/finish")
def finish_session(session_id: int, db=Depends(staff_db)):
    execute(db, "CALL sp_finish_session(%s)", [session_id])
    return get_session(session_id, db)


@router.post("/{session_id}/cancel")
def cancel_session(session_id: int, db=Depends(staff_db)):
    if get_session(session_id, db)["status"] == "cancelled":
        raise HTTPException(400, "Партия уже отменена")
    execute(db, "UPDATE session SET status = 'cancelled' WHERE id = %s", [session_id])
    return get_session(session_id, db)