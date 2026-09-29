from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import staff_db
from ..db import execute, fetch_all, fetch_one, paginate
from ..schemas import BanIn, PlayerIn

router = APIRouter(prefix="/api/players", tags=["Игроки"])

PLAYER_SELECT = ("SELECT id, name, nickname, registered_at, rating, is_active, "
                 "banned_until, ban_reason FROM player")


@router.get("")
def list_players(
    search: str | None = None,
    active_only: bool = True,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db=Depends(staff_db),
):
    where, params = [], []
    if search:
        where.append("(name LIKE %s OR nickname LIKE %s)")
        params += [f"%{search}%", f"%{search}%"]
    if active_only:
        where.append("is_active")
    return paginate(db, PLAYER_SELECT, where, params, "nickname", page, size)


@router.get("/{player_id}")
def get_player(player_id: int, db=Depends(staff_db)):
    player = fetch_one(db, PLAYER_SELECT + " WHERE id = %s", [player_id])
    if not player:
        raise HTTPException(404, "Игрок не найден")
    return player


@router.post("", status_code=201)
def create_player(data: PlayerIn, db=Depends(staff_db)):
    cur = execute(db, "INSERT INTO player (name, nickname) VALUES (%s, %s)", [data.name, data.nickname])
    return get_player(cur.lastrowid, db)


@router.put("/{player_id}")
def update_player(player_id: int, data: PlayerIn, db=Depends(staff_db)):
    get_player(player_id, db)
    execute(db, "UPDATE player SET name = %s, nickname = %s WHERE id = %s",
            [data.name, data.nickname, player_id])
    return get_player(player_id, db)


@router.delete("/{player_id}")
def deactivate_player(player_id: int, db=Depends(staff_db)):
    """Мягкая деактивация (без указания причины)."""
    get_player(player_id, db)
    execute(db, "UPDATE player SET is_active = FALSE WHERE id = %s", [player_id])
    return get_player(player_id, db)


@router.post("/{player_id}/activate")
def activate_player(player_id: int, db=Depends(staff_db)):
    """Реактивация ранее деактивированного игрока."""
    get_player(player_id, db)
    execute(db, "UPDATE player SET is_active = TRUE, banned_until = NULL, ban_reason = NULL WHERE id = %s",
            [player_id])
    return get_player(player_id, db)


@router.post("/{player_id}/ban")
def ban_player(player_id: int, data: BanIn, db=Depends(staff_db)):
    """
    Бан игрока.
    - Если указан `days` — временный бан: игрок не может быть добавлен в партии
      до указанного момента, но остаётся активным (виден в рейтинге).
    - Без `days` — полный бан: игрок деактивируется и пропадает из рейтинга.
    """
    get_player(player_id, db)
    if data.days:
        execute(db,
                "UPDATE player SET banned_until = DATE_ADD(NOW(), INTERVAL %s DAY), ban_reason = %s WHERE id = %s",
                [data.days, data.reason, player_id])
    else:
        execute(db,
                "UPDATE player SET is_active = FALSE, banned_until = NULL, ban_reason = %s WHERE id = %s",
                [data.reason, player_id])
    return get_player(player_id, db)


@router.post("/{player_id}/unban")
def unban_player(player_id: int, db=Depends(staff_db)):
    """Снимает любой бан (временный или полный)."""
    get_player(player_id, db)
    execute(db,
            "UPDATE player SET is_active = TRUE, banned_until = NULL, ban_reason = NULL WHERE id = %s",
            [player_id])
    return get_player(player_id, db)


@router.get("/{player_id}/history")
def player_history(player_id: int, db=Depends(staff_db)):
    get_player(player_id, db)
    return fetch_all(db, """
        SELECT s.id AS session_id, s.starts_at, g.title AS game, s.status,
               sp.score, sp.place, sp.rating_delta, sp.attended
          FROM session_player sp
          JOIN session s ON s.id = sp.session_id
          JOIN game g    ON g.id = s.game_id
         WHERE sp.player_id = %s
         ORDER BY s.starts_at DESC""", [player_id])