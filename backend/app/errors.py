import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pymysql import MySQLError, OperationalError

log = logging.getLogger("board_club")

DUPLICATE_MESSAGES = {
    "player.nickname": "Такой никнейм уже занят",
    "staff.login": "Такой логин уже занят",
    "game.title": "Игра с таким названием уже есть",
    "genre.name": "Такой жанр уже есть",
    "game_table.number": "Стол с таким номером уже есть",
    "session_player.PRIMARY": "Игрок уже участвует в этой партии",
}

CHECK_MESSAGES = {
    "chk_game_players": "Максимум игроков не может быть меньше минимума",
    "chk_table_capacity": "Вместимость стола — минимум 2 места",
    "chk_session_time": "Время окончания должно быть позже времени начала",
}

FIELD_NAMES = {
    "title": "Название", "name": "Имя/название", "nickname": "Никнейм", "genre_id": "Жанр",
    "min_players": "Мин. игроков", "max_players": "Макс. игроков", "duration_min": "Длительность",
    "complexity": "Сложность", "copies": "Копий", "number": "Номер стола", "capacity": "Вместимость",
    "starts_at": "Начало", "ends_at": "Окончание", "player_ids": "Участники", "score": "Очки",
    "login": "Логин", "password": "Пароль",
}

PYDANTIC_MESSAGES = {
    "missing": lambda c: "обязательное поле",
    "greater_than_equal": lambda c: f"значение не меньше {c['ge']}",
    "less_than_equal": lambda c: f"значение не больше {c['le']}",
    "string_too_short": lambda c: f"минимум {c['min_length']} симв.",
    "string_too_long": lambda c: f"максимум {c['max_length']} симв.",
    "string_pattern_mismatch": lambda c: "недопустимые символы или длина",
    "too_short": lambda c: f"нужно минимум {c['min_length']}",
    "too_long": lambda c: f"не больше {c['max_length']}",
    "int_parsing": lambda c: "должно быть целым числом",
    "int_type": lambda c: "должно быть целым числом",
    "datetime_parsing": lambda c: "неверный формат даты и времени",
    "datetime_from_date_parsing": lambda c: "неверный формат даты и времени",
    "date_from_datetime_parsing": lambda c: "неверный формат даты",
    "string_type": lambda c: "должно быть строкой",
}


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": message})


async def mysql_error_handler(request: Request, exc: MySQLError) -> JSONResponse:
    code = exc.args[0] if exc.args else 0
    text = str(exc.args[1]) if len(exc.args) > 1 else ""

    if code == 1644:
        return _error(400, text)
    if code == 1062:
        key = text.rsplit("'", 2)[-2] if "'" in text else ""
        return _error(409, DUPLICATE_MESSAGES.get(key, "Такая запись уже существует"))
    if code == 1451:
        return _error(409, "Запись нельзя удалить: она используется в других данных (например, в истории партий)")
    if code == 1452:
        return _error(400, "Указана несуществующая запись: проверьте игру, жанр, стол или игрока")
    if code == 3819:
        name = next((k for k in CHECK_MESSAGES if k in text), None)
        return _error(400, CHECK_MESSAGES.get(name, "Данные нарушают ограничения базы данных"))
    if code in (1142, 1143, 1370):
        return _error(403, "Недостаточно прав для этой операции")
    if isinstance(exc, OperationalError) and code in (2003, 2006, 2013):
        return _error(503, "База данных недоступна, попробуйте позже")

    log.exception("Необработанная ошибка MySQL %s: %s", code, text)
    return _error(500, "Внутренняя ошибка базы данных")


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    parts = []
    for err in exc.errors():
        field = next((str(p) for p in reversed(err["loc"]) if isinstance(p, str) and p != "body"), "")
        translate = PYDANTIC_MESSAGES.get(err["type"])
        msg = translate(err.get("ctx", {})) if translate else err["msg"].removeprefix("Value error, ")
        parts.append(f"{FIELD_NAMES.get(field, field)}: {msg}" if field else msg)
    return _error(422, "Некорректные данные. " + "; ".join(parts))


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Необработанная ошибка")
    return _error(500, "Внутренняя ошибка сервера")