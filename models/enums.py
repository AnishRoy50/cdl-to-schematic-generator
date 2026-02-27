"""Enumerations for component and MOSFET types."""

from enum import Enum, auto


class ComponentType(Enum):
    """Enumeration of supported component types."""
    MOSFET = auto()
    RESISTOR = auto()
    CAPACITOR = auto()
    DIODE = auto()
    BJT = auto()
    SUBCKT_INST = auto()


class MOSType(Enum):
    """MOSFET polarity."""
    NMOS = auto()
    PMOS = auto()
    UNKNOWN = auto()
