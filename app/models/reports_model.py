
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class ReportBase(SQLModel):
    title: str
    description: str
    category: str
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    state: str
    lga: str
    address: Optional[str] = None
    region: Optional[str] = None


class ReportCreate(ReportBase):
    pass

class ReportRead(ReportBase):
    id: int
    reported_at: datetime
    reporter_id: int

class Report(ReportBase, table=True):
    __tablename__ = "report"
    id: Optional[int] = Field(default=None, primary_key=True)
    reported_at: datetime = Field(default_factory=datetime.utcnow)
    reporter_id: int = Field(foreign_key="healthworker.id")