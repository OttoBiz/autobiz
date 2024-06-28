from typing import Optional
from pydantic import BaseModel


class ProductSearchQuery(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
