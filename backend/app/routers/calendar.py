from datetime import date

from fastapi import APIRouter, Depends, Query

from ..auth import staff_db
from ..db import fetch_all

router = APIRouter(prefix="/api/calendar", tags=["Календарь"])


@router.get("")
def calendar(
    date_from: date = Query(..., description="Начало диапазона"),
    date_to: date = Query(..., description="Конец диапазона"),
    db=Depends(staff_db),
):
    """
    Возвращает все партии, пересекающиеся с указанным диапазоном дат.
    Границы включительны.
    """
    return fetch_all(db, """
        SELECT s.id, s.starts_at, s.ends_at, s.status,
               g.title AS game,
               t.number AS table_number, t.description AS table_description, t.capacity,
               st.full_name AS host,
               (SELECT COUNT(*) FROM session_player sp WHERE sp.session_id = s.id) AS players_count
          FROM session s
          JOIN game g       ON g.id = s.game_id
          JOIN game_table t ON t.id = s.table_id
          JOIN staff st     ON st.id = s.host_id
         WHERE s.starts_at < DATE_ADD(%s, INTERVAL 1 DAY)
           AND s.ends_at > %s
         ORDER BY s.starts_at""", [date_to, date_from])