from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import public_db, staff_db
from ..db import fetch_all, fetch_one

router = APIRouter(prefix="/api", tags=["Отчёты"])


def _period(date_from: date | None, date_to: date | None) -> tuple[str, list]:
    where, params = ["s.status = 'finished'"], []
    if date_from:
        where.append("s.starts_at >= %s")
        params.append(date_from)
    if date_to:
        where.append("s.starts_at < DATE_ADD(%s, INTERVAL 1 DAY)")
        params.append(date_to)
    return " AND ".join(where), params


@router.get("/reports/top-players")
def top_players(limit: int = Query(10, ge=1, le=100), db=Depends(staff_db)):
    return fetch_all(db, "SELECT * FROM v_player_rating ORDER BY place, nickname LIMIT %s", [limit])


@router.get("/reports/game-popularity")
def game_popularity(date_from: date | None = None, date_to: date | None = None, db=Depends(staff_db)):
    where, params = _period(date_from, date_to)
    return fetch_all(db, f"""
        SELECT g.title AS game, gn.name AS genre,
               COUNT(DISTINCT s.id)         AS sessions,
               COUNT(DISTINCT sp.player_id) AS unique_players
          FROM session s
          JOIN game g            ON g.id = s.game_id
          JOIN genre gn          ON gn.id = g.genre_id
          JOIN session_player sp ON sp.session_id = s.id
         WHERE {where}
         GROUP BY g.id, g.title, gn.name
         ORDER BY sessions DESC, unique_players DESC""", params)


@router.get("/reports/table-load")
def table_load(date_from: date | None = None, date_to: date | None = None, db=Depends(staff_db)):
    where, params = _period(date_from, date_to)
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    cols = ",\n".join(
        f"ROUND(SUM(CASE WHEN WEEKDAY(s.starts_at) = {i} "
        f"THEN TIMESTAMPDIFF(MINUTE, s.starts_at, s.ends_at) ELSE 0 END) / 60, 1) AS {d}"
        for i, d in enumerate(days))
    return fetch_all(db, f"""
        SELECT t.number AS table_number, COUNT(s.id) AS sessions,
               {cols},
               ROUND(COALESCE(SUM(TIMESTAMPDIFF(MINUTE, s.starts_at, s.ends_at)), 0) / 60, 1) AS total_hours
          FROM game_table t
          LEFT JOIN session s ON s.table_id = t.id AND {where}
         GROUP BY t.id, t.number
         ORDER BY t.number""", params)


@router.get("/reports/player-card/{player_id}")
def player_card(player_id: int, db=Depends(staff_db)):
    player = fetch_one(db,
        "SELECT id, name, nickname, rating, registered_at, is_active, banned_until, ban_reason "
        "FROM player WHERE id = %s", [player_id])
    if not player:
        raise HTTPException(404, "Игрок не найден")
    history = fetch_all(db, """
        SELECT s.starts_at, g.title AS game, sp.score, sp.place, sp.rating_delta, sp.attended,
               1000 + SUM(sp.rating_delta) OVER (ORDER BY s.starts_at, s.id) AS rating_after
          FROM session_player sp
          JOIN session s ON s.id = sp.session_id
          JOIN game g    ON g.id = s.game_id
         WHERE sp.player_id = %s AND s.status = 'finished'
         ORDER BY s.starts_at, s.id""", [player_id])
    favorite = fetch_all(db, """
        SELECT g.title AS game, COUNT(*) AS sessions, SUM(sp.place = 1) AS wins
          FROM session_player sp
          JOIN session s ON s.id = sp.session_id
          JOIN game g    ON g.id = s.game_id
         WHERE sp.player_id = %s AND s.status = 'finished'
         GROUP BY g.id, g.title
         ORDER BY sessions DESC, wins DESC
         LIMIT 3""", [player_id])
    return {"player": player, "history": history, "favorite_games": favorite}


# ---------- Публичный рейтинг ----------
@router.get("/public/rating", tags=["Публичный рейтинг"])
def public_rating(search: str | None = None, db=Depends(public_db)):
    if search:
        return fetch_all(db, "SELECT * FROM v_player_rating WHERE nickname LIKE %s ORDER BY place, nickname",
                         [f"%{search}%"])
    return fetch_all(db, "SELECT * FROM v_player_rating ORDER BY place, nickname")


@router.get("/public/players/{nickname}", tags=["Публичный рейтинг"])
def public_player(nickname: str, db=Depends(public_db)):
    stats = fetch_one(db, "SELECT * FROM v_player_rating WHERE nickname = %s", [nickname])
    if not stats:
        raise HTTPException(404, "Игрок с таким никнеймом не найден")
    history = fetch_all(db, """
        SELECT starts_at, game, players, score, place, rating_delta
          FROM v_player_history WHERE nickname = %s ORDER BY starts_at DESC""", [nickname])
    return {"stats": stats, "history": history}