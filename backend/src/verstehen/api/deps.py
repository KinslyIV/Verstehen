from fastapi import Request

from verstehen.session.sessions import Sessions
from verstehen.session.turns import Turns
from verstehen.store.database import Database


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_turns(request: Request) -> Turns:
    return request.app.state.turns


def get_sessions(request: Request) -> Sessions:
    return request.app.state.sessions
