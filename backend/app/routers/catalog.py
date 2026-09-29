from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import admin_db, staff_db
from ..db import execute, fetch_all, fetch_one, paginate
from ..schemas import GameIn, GenreIn, TableIn

router = APIRouter(prefix="/api", tags=["Справочники"])


def _check_found(cur, what: str):
    if cur.rowcount == 0:
        raise HTTPException(404, f"{what} не найден(а)")


# ---------- Жанры ----------
@router.get("/genres")
def list_genres(db=Depends(staff_db)):
    return fetch_all(db, "SELECT id, name FROM genre ORDER BY name")


@router.post("/genres", status_code=201)
def create_genre(data: GenreIn, db=Depends(admin_db)):
    cur = execute(db, "INSERT INTO genre (name) VALUES (%s)", [data.name])
    return {"id": cur.lastrowid, **data.model_dump()}


@router.delete("/genres/{genre_id}", status_code=204)
def delete_genre(genre_id: int, db=Depends(admin_db)):
    _check_found(execute(db, "DELETE FROM genre WHERE id = %s", [genre_id]), "Жанр")


# ---------- Столы ----------
TABLE_SELECT = "SELECT id, number, capacity, description FROM game_table"


@router.get("/tables")
def list_tables(db=Depends(staff_db)):
    return fetch_all(db, TABLE_SELECT + " ORDER BY number")


@router.post("/tables", status_code=201)
def create_table(data: TableIn, db=Depends(admin_db)):
    cur = execute(db, "INSERT INTO game_table (number, capacity, description) VALUES (%s, %s, %s)",
                  [data.number, data.capacity, data.description])
    new_id = cur.lastrowid
    if data.number is None:
        # По умолчанию номер = id (можно потом изменить через PUT)
        execute(db, "UPDATE game_table SET number = %s WHERE id = %s", [new_id, new_id])
    return fetch_one(db, TABLE_SELECT + " WHERE id = %s", [new_id])


@router.put("/tables/{table_id}")
def update_table(table_id: int, data: TableIn, db=Depends(admin_db)):
    if not fetch_one(db, "SELECT id FROM game_table WHERE id = %s", [table_id]):
        raise HTTPException(404, "Стол не найден")
    execute(db, """
        UPDATE game_table
           SET number = COALESCE(%s, number),
               capacity = %s,
               description = %s
         WHERE id = %s""",
            [data.number, data.capacity, data.description, table_id])
    return fetch_one(db, TABLE_SELECT + " WHERE id = %s", [table_id])


@router.delete("/tables/{table_id}", status_code=204)
def delete_table(table_id: int, db=Depends(admin_db)):
    _check_found(execute(db, "DELETE FROM game_table WHERE id = %s", [table_id]), "Стол")


# ---------- Игры ----------
GAME_SELECT = """
    SELECT g.id, g.title, g.genre_id, gn.name AS genre, g.min_players, g.max_players,
           g.duration_min, g.complexity, g.copies
      FROM game g JOIN genre gn ON gn.id = g.genre_id"""


@router.get("/games")
def list_games(
    search: str | None = None,
    genre_id: int | None = None,
    players: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db=Depends(staff_db),
):
    where, params = [], []
    if search:
        where.append("g.title LIKE %s")
        params.append(f"%{search}%")
    if genre_id:
        where.append("g.genre_id = %s")
        params.append(genre_id)
    if players:
        where.append("%s BETWEEN g.min_players AND g.max_players")
        params.append(players)
    return paginate(db, GAME_SELECT, where, params, "title", page, size)


@router.get("/games/{game_id}")
def get_game(game_id: int, db=Depends(staff_db)):
    game = fetch_one(db, GAME_SELECT + " WHERE g.id = %s", [game_id])
    if not game:
        raise HTTPException(404, "Игра не найдена")
    return game


@router.post("/games", status_code=201)
def create_game(data: GameIn, db=Depends(admin_db)):
    cur = execute(db, """
        INSERT INTO game (title, genre_id, min_players, max_players, duration_min, complexity, copies)
        VALUES (%(title)s, %(genre_id)s, %(min_players)s, %(max_players)s,
                %(duration_min)s, %(complexity)s, %(copies)s)""", data.model_dump())
    return get_game(cur.lastrowid, db)


@router.put("/games/{game_id}")
def update_game(game_id: int, data: GameIn, db=Depends(admin_db)):
    get_game(game_id, db)
    execute(db, """
        UPDATE game SET title = %(title)s, genre_id = %(genre_id)s, min_players = %(min_players)s,
               max_players = %(max_players)s, duration_min = %(duration_min)s,
               complexity = %(complexity)s, copies = %(copies)s
         WHERE id = %(id)s""", {**data.model_dump(), "id": game_id})
    return get_game(game_id, db)


@router.delete("/games/{game_id}", status_code=204)
def delete_game(game_id: int, db=Depends(admin_db)):
    _check_found(execute(db, "DELETE FROM game WHERE id = %s", [game_id]), "Игра")