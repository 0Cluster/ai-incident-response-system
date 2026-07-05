from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    def __init__(
        self,
        db: Session,
        model: type[ModelType],
    ):
        self.db = db
        self.model = model

    def create(self, obj: ModelType) -> ModelType:
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def get(self, obj_id: int) -> ModelType | None:
        return self.db.get(self.model, obj_id)

    def get_all(self) -> list[ModelType]:
        statement = select(self.model)
        result = self.db.execute(statement)
        return list(result.scalars().all())

    def delete(self, obj: ModelType) -> None:
        self.db.delete(obj)
        self.db.commit()
