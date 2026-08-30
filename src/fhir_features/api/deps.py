"""Request dependencies."""

from fastapi import Request

from fhir_features.store.db import Database


def get_db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


def get_valuesets_version(request: Request) -> str:
    version: str = request.app.state.valuesets_version
    return version
