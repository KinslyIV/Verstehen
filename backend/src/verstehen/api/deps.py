from fastapi import Request

from verstehen.session.sessions import SessionService
from verstehen.session.turns import TurnService
from verstehen.store.database import Database


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_turn_service(request: Request) -> TurnService:
    return request.app.state.turn_service


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service
