from fastapi import Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.core.model_loader import get_model_manager, ModelManager


def get_db_session(db: Session = Depends(get_db)) -> Session:
    return db


def get_manager() -> ModelManager:
    return get_model_manager()
