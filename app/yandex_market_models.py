from dataclasses import dataclass, asdict
from typing import List, Optional
from datetime import datetime, timezone

@dataclass
class StockItem:
    count: int
    type: str = "FIT"
    updatedAt: Optional[str] = None

    def __post_init__(self):
        if not self.updatedAt:
            self.updatedAt = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

@dataclass
class SKUStock:
    sku: str
    warehouseId: int
    items: List[StockItem]

@dataclass
class PriceValue:
    value: float
    currencyId: str = "RUR"

@dataclass
class OfferPrice:
    offerId: str
    price: PriceValue

def to_dict(obj):
    return asdict(obj)
