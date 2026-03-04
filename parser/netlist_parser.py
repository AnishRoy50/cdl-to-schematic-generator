"""CDL / SPICE netlist parser."""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from models import (
    Circuit, Component, MOSFET,
    MOSType, SubcktInstance, Subckt,
)

logger = logging.getLogger("cdl2schematic")

_PMOS_PAT = re.compile(r"(pmos|pfet|pch|lvtpfet|hvtpfet|svtpfet)", re.I)
_NMOS_PAT = re.compile(r"(nmos|nfet|nch|lvtnfet|hvtnfet|svtnfet)", re.I)


class NetlistParser:
    """Parses a CDL netlist file into a Circuit data model."""

    def __init__(self) -> None:
        self.circuit = Circuit()
        self._dispatch = {
            "M": self._parse_mosfet,
            "X": self._parse_subckt_instance,
        }

    # ── public API ─────────────────────────────────────────────────────────

    def parse_file(self, filepath: str) -> Circuit:
        """Read and parse a .cdl file."""
        logger.info("Reading CDL file: %s", filepath)
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            raw_lines = fh.readlines()
        self._parse_lines(self._merge_continuation_lines(raw_lines))
        logger.info("Parsing complete — %d subcircuit(s).", len(self.circuit.subcircuits))
        return self.circuit

    @staticmethod
    def _merge_continuation_lines(raw_lines: List[str]) -> List[str]:
        """Merge continuation lines (starting with ``+``) with predecessor."""
        merged: List[str] = []
        for line in raw_lines:
            stripped = line.rstrip("\n\r")
            if stripped.startswith("+") and merged:
                merged[-1] += " " + stripped[1:].strip()
            elif not stripped.startswith("+"):
                merged.append(stripped)
        return merged

    def _parse_lines(self, lines: List[str]) -> None:
        current: Optional[Subckt] = None
        for lineno, line in enumerate(lines, 1):
            s = line.strip()
            if not s:
                continue
            if s.startswith("*"):
                if s.upper().startswith("*.PININFO") and current:
                    self._parse_pininfo(s, current)
                continue

            upper = s.upper()
            if upper.startswith(".SUBCKT"):
                current = self._parse_subckt_header(s)
                if current:
                    self.circuit.subcircuits[current.name] = current
            elif upper.startswith(".ENDS"):
                current = None
            elif not s.startswith("."):
                comp = self._parse_instance(s, lineno)
                if comp:
                    if current:
                        current.add_component(comp)
                    else:
                        self.circuit.top_level_components.append(comp)

    def _parse_instance(self, line: str, lineno: int) -> Optional[Component]:
        handler = self._dispatch.get(line[0].upper())
        if not handler:
            logger.debug("Line %d: Unrecognised — skipped.", lineno)
            return None
        try:
            return handler(line)
        except Exception as exc:
            logger.warning("Line %d: Parse failed — %s", lineno, exc)
            return None

    # ── header parsers ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_subckt_header(line: str) -> Optional[Subckt]:
        tokens = line.split()
        if len(tokens) < 2:
            return None
        return Subckt(name=tokens[1], ports=tokens[2:])

    @staticmethod
    def _parse_pininfo(line: str, subckt: Subckt) -> None:
        body = re.sub(r"^\*\s*\.PININFO\s*", "", line, flags=re.I)
        for tok in body.split():
            if ":" in tok:
                pin, direction = tok.rsplit(":", 1)
                subckt.pin_info[pin] = direction

    # ── component parsers ──────────────────────────────────────────────────

    @staticmethod
    def _split_params(tokens: List[str]) -> Dict[str, str]:
        return dict(tok.split("=", 1) for tok in tokens if "=" in tok)

    def _parse_mosfet(self, line: str) -> Optional[MOSFET]:
        tokens = line.split()
        if len(tokens) < 6:
            return None
        model = tokens[5]
        if _PMOS_PAT.search(model):
            mos_type = MOSType.PMOS
        elif _NMOS_PAT.search(model):
            mos_type = MOSType.NMOS
        else:
            mos_type = MOSType.UNKNOWN
        return MOSFET(tokens[0], tokens[1], tokens[2], tokens[3], tokens[4],
                      model, mos_type, self._split_params(tokens[6:]))

    def _parse_subckt_instance(self, line: str) -> Optional[SubcktInstance]:
        tokens = line.split()
        if len(tokens) < 3:
            return None
        param_start = next(
            (i for i in range(1, len(tokens)) if "=" in tokens[i]), len(tokens))
        net_section = tokens[1:param_start]
        if not net_section:
            return None
        connections = {f"pin{i}": n for i, n in enumerate(net_section[:-1])}
        return SubcktInstance(tokens[0], net_section[-1], connections,
                              self._split_params(tokens[param_start:]))
