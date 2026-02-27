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

            engine = LayoutEngine(subckt)
            groups = engine.layout()
            renderer = ASCIIRenderer(groups, subckt)
            ascii_art = renderer.render()
            sections.append(header + "\n" + ascii_art + "\n")

        if not sections:
            return "(No subcircuits found in the netlist.)\n"

        separator = "\n" + "=" * 72 + "\n"
        return separator.join(sections)

    @staticmethod
    def _section_header(name: str, subckt: Subckt) -> str:
        """Build the human-readable header block for one subcircuit."""
        lines = [
            "=" * 72,
            f"  SUBCIRCUIT: {name}",
            f"  Ports:      {' '.join(subckt.ports)}",
        ]
        if subckt.pin_info:
            info = "  Pin Info:   " + "  ".join(
                f"{p}:{d}" for p, d in subckt.pin_info.items()
            )
            lines.append(info)

        stats = defaultdict(int)
        for c in subckt.components:
            stats[c.comp_type.name] += 1
        summary = "  Components: " + ", ".join(f"{v} {k}" for k, v in stats.items())
        lines.append(summary)
        lines.append("=" * 72)
        return "\n".join(lines)
