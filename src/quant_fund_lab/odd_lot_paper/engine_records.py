"""Mutable records used by the historical execution phases and state bridge."""
from dataclasses import dataclass


@dataclass
class EngineStop:
    stop: float
    high_close: float
    distance: float


@dataclass
class EngineOrder:
    side: str
    quantity: int
    reason: str
    stop: float = 0.0
    signal_price: float = 0.0
    distance: float = 0.0
    signal_volume: float = 0.0
