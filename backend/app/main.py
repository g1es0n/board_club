import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pymysql import MySQLError

from . import auth
from .errors import mysql_error_handler, unhandled_error_handler, validation_error_handler
from .routers import catalog, players, reports, sessions

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Клуб настольных игр")

app.add_exception_handler(MySQLError, mysql_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

for module in (auth, catalog, players, sessions, reports):
    app.include_router(module.router)

app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "static", html=True), name="static")