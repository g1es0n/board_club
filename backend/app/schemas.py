from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=100)


class GenreIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class TableIn(BaseModel):
    number: int | None = Field(None, ge=1, le=999)
    capacity: int = Field(ge=2, le=20)
    description: str | None = Field(None, max_length=255)


class GameIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    genre_id: int
    min_players: int = Field(ge=1, le=20)
    max_players: int = Field(ge=1, le=20)
    duration_min: int = Field(ge=5, le=600)
    complexity: int = Field(ge=1, le=5)
    copies: int = Field(ge=1, le=20)

    @model_validator(mode="after")
    def check_players(self):
        if self.max_players < self.min_players:
            raise ValueError("Максимум игроков не может быть меньше минимума")
        return self


class PlayerIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    nickname: str = Field(pattern=r"^[A-Za-z0-9_а-яА-ЯёЁ]{3,30}$")


class SessionIn(BaseModel):
    game_id: int
    table_id: int
    starts_at: datetime
    ends_at: datetime
    player_ids: list[int] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def check(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Время окончания должно быть позже времени начала")
        if len(set(self.player_ids)) != len(self.player_ids):
            raise ValueError("Игрок указан в партии дважды")
        return self


class RescheduleIn(BaseModel):
    starts_at: datetime
    ends_at: datetime
    table_id: int
    player_ids: list[int] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def check(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Время окончания должно быть позже времени начала")
        if len(set(self.player_ids)) != len(self.player_ids):
            raise ValueError("Игрок указан в партии дважды")
        return self


class PlayerRef(BaseModel):
    player_id: int


class ScoreItem(BaseModel):
    player_id: int
    score: int = Field(ge=0, le=100_000)


class ScoresIn(BaseModel):
    scores: list[ScoreItem] = Field(min_length=1)


class AttendanceItem(BaseModel):
    player_id: int
    attended: bool


class AttendanceIn(BaseModel):
    attendance: list[AttendanceItem] = Field(min_length=1)


class BanIn(BaseModel):
    reason: str = Field(min_length=1, max_length=512)
    days: int | None = Field(None, ge=1, le=365)