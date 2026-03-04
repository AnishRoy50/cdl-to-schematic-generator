"""Enumerations for component and MOSFET types."""

from enum import Enum, auto


class ComponentType(Enum):
    """Enumeration of supported component types."""
    MOSFET = auto()
    SUBCKT_INST = auto()


class MOSType(Enum):
    """MOSFET polarity."""
    NMOS = auto()
    PMOS = auto()
    UNKNOWN = auto()
