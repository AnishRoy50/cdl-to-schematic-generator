"""High-level orchestrator: parse → layout → render for each subcircuit."""

from __future__ import annotations

from collections import defaultdict
from typing import List

from models import Subckt, Circuit
from layout import LayoutEngine
from renderer import ASCIIRenderer


class SchematicBuilder:
    """Builds ASCII schematics for every subcircuit in a *Circuit*."""

    def __init__(self, circuit: Circuit) -> None:
        self.circuit = circuit

    def build_all(self) -> str:
        """Generate ASCII schematics for every subcircuit, concatenated."""
        sections: List[str] = []
        for name, subckt in self.circuit.subcircuits.items():
            header = self._section_header(name, subckt)
            if not subckt.components:
                sections.append(header + "\n  (no components)\n")
                continue
            art = ASCIIRenderer(LayoutEngine(subckt).layout(), subckt).render()
            sections.append(f"{header}\n{art}\n")
        return ("\n" + "=" * 72 + "\n").join(sections) if sections else "(No subcircuits found.)\n"

    @staticmethod
    def _section_header(name: str, subckt: Subckt) -> str:
        stats = defaultdict(int)
        for c in subckt.components:
            stats[c.comp_type.name] += 1
        lines = [
            "=" * 72,
            f"  SUBCIRCUIT: {name}",
            f"  Ports:      {' '.join(subckt.ports)}",
        ]
        if subckt.pin_info:
            lines.append("  Pin Info:   " + "  ".join(
                f"{p}:{d}" for p, d in subckt.pin_info.items()))
        lines.append("  Components: " + ", ".join(f"{v} {k}" for k, v in stats.items()))
        lines.append("=" * 72)
        return "\n".join(lines)
