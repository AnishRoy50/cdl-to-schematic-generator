"""Subcircuit and top-level Circuit container models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .components import Component
from .net import Net


@dataclass
class Subckt:
    """Represents a .SUBCKT definition."""
    name: str
    ports: List[str] = field(default_factory=list)
    pin_info: Dict[str, str] = field(default_factory=dict)  # pin -> direction
    components: List[Component] = field(default_factory=list)
    nets: Dict[str, Net] = field(default_factory=dict)

    def get_or_create_net(self, net_name: str) -> Net:
        """Retrieve existing Net or create a new one."""
        if net_name not in self.nets:
            self.nets[net_name] = Net(net_name)
        return self.nets[net_name]

    def add_component(self, comp: Component) -> None:
        """Register a component and update net connectivity."""
        self.components.append(comp)
        for _role, net_name in comp.get_terminals().items():
            net = self.get_or_create_net(net_name)
            net.connected_components.append(comp.name)


@dataclass
class Circuit:
    """Top-level container holding all parsed subcircuits."""
    subcircuits: Dict[str, Subckt] = field(default_factory=dict)
    top_level_components: List[Component] = field(default_factory=list)
