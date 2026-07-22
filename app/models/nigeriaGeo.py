from typing import List, Optional
from sqlmodel import SQLModel, Field, Relationship
from enum import Enum

class StateBase(SQLModel):
    name: str = Field(index=True) 
    alias: str = Field(index=True) 
    capital: Optional[str] = None  

class State(StateBase, table=True):
    __tablename__ = "state"
    id: Optional[int] = Field(default=None, primary_key=True)
    lgas: List["LGA"] = Relationship(back_populates="state")  


class LGABase(SQLModel):
    name: str = Field(index=True)  
    state_id: int = Field(foreign_key="state.id") 

class LGA(LGABase, table=True):
    __tablename__ = "lga"
    id: Optional[int] = Field(default=None, primary_key=True)
    state: Optional[State] = Relationship(back_populates="lgas")