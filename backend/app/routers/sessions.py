import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import staff_db, staff_user
from ..db import execute, fetch_all, fetch_one, paginate, transaction
from ..schemas import PlayerRef, ScoresIn, SessionIn

router = APIRouter(prefix="/api/sessions", tags=["Партии"])

SESSION_SELECT = """
    SELECT s.id, s.starts_at, s.ends_at, s.status,
           s.game_id, g.title AS game, g.min_players, g.max_players,
           s.table_id, t.number AS table_number, t.capacity,
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
    session["players"] = fetch_all(db, """
        SELECT p.id AS player_id, p.nickname, p.name, p.rating, sp.score, sp.place, sp.rating_delta
          FROM session_player sp JOIN player p ON p.id = sp.player_id
         WHERE sp.session_id = %s
         ORDER BY sp.place IS NULL, sp.place, p.nickname""", [session_id])
    return session


@router.post("", status_code=201)
def create_session(data: SessionIn, user: dict = Depends(staff_user), db=Depends(staff_db)):
    row = fetch_one(db, "CALL sp_create_session(%s, %s, %s, %s, %s, %s)", [
        data.game_id, data.table_id, user["id"], data.starts_at, data.ends_at, json.dumps(data.player_ids),
    ])
    return get_session(row["id"], db)


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