"""Net (electrical node) data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Net:
    """Represents an electrical net (node) in the circuit."""
    name: str
    connected_components: List[str] = field(default_factory=list)

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Net):
            return self.name == other.name
        return NotImplemented
