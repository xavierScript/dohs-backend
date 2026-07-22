from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from .base import Base

class LassaFeverStructured(Base, table=True):
    __tablename__ = "lassa_fever_structured"

    id: int = Field(default=None, primary_key=True)
    timestamp: datetime = Field(nullable=False)
    location: str = Field(nullable=False)
    case_count: int = Field(default=0)
    temperature: float = Field(nullable=True)
    humidity: float = Field(nullable=True)
    rodent_density: float = Field(nullable=True)
    symptoms: str = Field(nullable=True)
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    state: str
    lga: str
    address: Optional[str] = None
    region: Optional[str] = None
    
class LassaFeverUnstructured(Base, table=True):
    __tablename__ = "lassa_fever_unstructured"

    id: int = Field(default=None, primary_key=True)
    timestamp: datetime = Field(nullable=False)
    source: str = Field(nullable=False)  
    content: str = Field(nullable=False)
   
    ingested_at: datetime = Field(default=datetime.utcnow)



