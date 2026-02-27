"""CDL / SPICE netlist parser.

Reads a ``.cdl`` file and produces a :class:`~cdl_to_schematic.models.Circuit`
object containing all parsed subcircuits and their components.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from models import (
    BJT,
    Capacitor,
    Circuit,
    Component,
    Diode,
    MOSFET,
    MOSType,
    Resistor,
    SubcktInstance,
    Subckt,
)

logger = logging.getLogger("cdl2schematic")

# Common PMOS / NMOS model-name patterns (case-insensitive heuristics)
_PMOS_PATTERNS = re.compile(
    r"(pmos|pfet|pch|lvtpfet|hvtpfet|svtpfet)", re.IGNORECASE,
)
_NMOS_PATTERNS = re.compile(
    r"(nmos|nfet|nch|lvtnfet|hvtnfet|svtnfet)", re.IGNORECASE,
)


class NetlistParser:
    """Parses a CDL netlist file into a :class:`Circuit` data model.

    Handles continuation lines, comment stripping, and graceful
    recovery from malformed content.
    """

    def __init__(self) -> None:
        self.circuit = Circuit()

    # ── public API ─────────────────────────────────────────────────────────

    def parse_file(self, filepath: str) -> Circuit:
        """Read and parse a ``.cdl`` file, returning a *Circuit* object."""
        logger.info("Reading CDL file: %s", filepath)
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                raw_lines = fh.readlines()
        except OSError as exc:
            logger.error("Cannot open file %s: %s", filepath, exc)
            raise

        merged = self._merge_continuation_lines(raw_lines)
        self._parse_lines(merged)
        logger.info(
            "Parsing complete — %d subcircuit(s) found.",
            len(self.circuit.subcircuits),
        )
        return self.circuit

    # ── internal helpers ───────────────────────────────────────────────────

    @staticmethod
    def _merge_continuation_lines(raw_lines: List[str]) -> List[str]:
        """Merge continuation lines (starting with ``+``) with predecessor."""
        merged: List[str] = []
        for line in raw_lines:
            stripped = line.rstrip("\n\r")
            if stripped.startswith("+"):
                if merged:
                    merged[-1] += " " + stripped[1:].strip()
                else:
                    logger.warning("Continuation line with no predecessor — skipped.")
            else:
                merged.append(stripped)
        return merged

    def _parse_lines(self, lines: List[str]) -> None:
        """Walk through merged lines and dispatch to handlers."""
        current_subckt: Optional[Subckt] = None

        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            # Comment line (starting with ``*`` but not ``*.PININFO``)
            if stripped.startswith("*"):
                if stripped.upper().startswith("*.PININFO"):
                    if current_subckt is not None:
                        self._parse_pininfo(stripped, current_subckt)
                    else:
                        logger.warning(
                            "Line %d: .PININFO outside subcircuit.", lineno,
                        )
                continue

            upper = stripped.upper()

            # .SUBCKT
            if upper.startswith(".SUBCKT"):
                current_subckt = self._parse_subckt_header(stripped)
                if current_subckt:
                    self.circuit.subcircuits[current_subckt.name] = current_subckt
                continue

            # .ENDS
            if upper.startswith(".ENDS"):
                if current_subckt:
                    logger.debug("End of subcircuit %s", current_subckt.name)
                current_subckt = None
                continue

            # Skip other SPICE directives
            if stripped.startswith("."):
                logger.debug("Line %d: Ignoring directive: %s", lineno, stripped[:60])
                continue

            # Instance lines
            comp = self._parse_instance(stripped, lineno)
            if comp is None:
                continue

            if current_subckt is not None:
                current_subckt.add_component(comp)
            else:
                self.circuit.top_level_components.append(comp)

    # ── instance dispatcher ────────────────────────────────────────────────

    def _parse_instance(self, stripped: str, lineno: int) -> Optional[Component]:
        """Dispatch to the correct component parser based on first character."""
        first_char = stripped[0].upper()
        try:
            if first_char == "M":
                return self._parse_mosfet(stripped)
            if first_char == "X":
                return self._parse_subckt_instance(stripped)
            if first_char == "R":
                return self._parse_resistor(stripped)
            if first_char == "C":
                return self._parse_capacitor(stripped)
            if first_char == "D":
                return self._parse_diode(stripped)
            if first_char == "Q":
                return self._parse_bjt(stripped)
            logger.debug("Line %d: Unrecognised — skipped.", lineno)
        except Exception as exc:
            logger.warning("Line %d: Failed to parse — %s. Skipping.", lineno, exc)
        return None

    # ── header parsers ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_subckt_header(line: str) -> Optional[Subckt]:
        """Parse ``.SUBCKT name port1 port2 ...``."""
        tokens = line.split()
        if len(tokens) < 2:
            logger.warning("Malformed .SUBCKT line: %s", line)
            return None
        name = tokens[1]
        ports = tokens[2:]
        logger.debug("Subcircuit: %s  ports=%s", name, ports)
        return Subckt(name=name, ports=ports)

    @staticmethod
    def _parse_pininfo(line: str, subckt: Subckt) -> None:
        """Parse ``*.PININFO pin:dir pin:dir ...``."""
        body = re.sub(r"^\*\s*\.PININFO\s*", "", line, flags=re.IGNORECASE)
        for token in body.split():
            if ":" in token:
                pin, direction = token.rsplit(":", 1)
                subckt.pin_info[pin] = direction

    # ── component parsers ──────────────────────────────────────────────────

    @staticmethod
    def _split_params(tokens: List[str]) -> Dict[str, str]:
        """Extract ``key=value`` pairs from a token list."""
        params: Dict[str, str] = {}
        for tok in tokens:
            if "=" in tok:
                key, _, val = tok.partition("=")
                params[key.strip()] = val.strip()
        return params

    def _parse_mosfet(self, line: str) -> Optional[MOSFET]:
        """Parse ``M<name> D G S B model [params...]``."""
        tokens = line.split()
        if len(tokens) < 6:
            logger.warning("Incomplete MOSFET line: %s", line[:80])
            return None
        name = tokens[0]
        drain, gate, source, bulk = tokens[1], tokens[2], tokens[3], tokens[4]
        model = tokens[5]
        params = self._split_params(tokens[6:])
        mos_type = self._infer_mos_type(model)
        logger.debug("MOSFET %s  type=%s  model=%s", name, mos_type.name, model)
        return MOSFET(name, drain, gate, source, bulk, model, mos_type, params)

    @staticmethod
    def _infer_mos_type(model: str) -> MOSType:
        """Heuristic to classify PMOS vs NMOS from model name."""
        if _PMOS_PATTERNS.search(model):
            return MOSType.PMOS
        if _NMOS_PATTERNS.search(model):
            return MOSType.NMOS
        return MOSType.UNKNOWN

    def _parse_subckt_instance(self, line: str) -> Optional[SubcktInstance]:
        """Parse ``X<name> net1 net2 ... / subckt_name [params...]``."""
        tokens = line.split()
        if len(tokens) < 3:
            logger.warning("Incomplete X-instance line: %s", line[:80])
            return None
        name = tokens[0]

        param_start = len(tokens)
        for i in range(1, len(tokens)):
            if "=" in tokens[i]:
                param_start = i
                break

        net_section = tokens[1:param_start]
        if not net_section:
            logger.warning("Cannot determine subcircuit for X-instance: %s", name)
            return None
        subckt_ref = net_section[-1]
        connection_nets = net_section[:-1]
        params = self._split_params(tokens[param_start:])

        connections = {f"pin{i}": n for i, n in enumerate(connection_nets)}
        return SubcktInstance(name, subckt_ref, connections, params)

    def _parse_resistor(self, line: str) -> Optional[Resistor]:
        tokens = line.split()
        if len(tokens) < 3:
            return None
        return Resistor(tokens[0], tokens[1], tokens[2], self._split_params(tokens[3:]))

    def _parse_capacitor(self, line: str) -> Optional[Capacitor]:
        tokens = line.split()
        if len(tokens) < 3:
            return None
        return Capacitor(tokens[0], tokens[1], tokens[2], self._split_params(tokens[3:]))

    def _parse_diode(self, line: str) -> Optional[Diode]:
        tokens = line.split()
        if len(tokens) < 3:
            return None
        return Diode(tokens[0], tokens[1], tokens[2], self._split_params(tokens[3:]))

    def _parse_bjt(self, line: str) -> Optional[BJT]:
        tokens = line.split()
        if len(tokens) < 4:
            return None
        name, c, b, e = tokens[0], tokens[1], tokens[2], tokens[3]
        substrate = tokens[4] if len(tokens) > 4 and "=" not in tokens[4] else ""
        model_idx = 5 if substrate else 4
        model = (
            tokens[model_idx]
            if len(tokens) > model_idx and "=" not in tokens[model_idx]
            else ""
        )
        start = model_idx + 1 if model else model_idx
        params = self._split_params(tokens[start:])
        return BJT(name, c, b, e, substrate, model, params)
