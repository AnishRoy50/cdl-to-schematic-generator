#!/usr/bin/env python3
"""
CDL Netlist to ASCII Schematic Converter
=========================================

Reads a Circuit Description Language (.cdl) netlist file, parses transistor-level
circuit descriptions, builds an internal connectivity model, and generates a
readable ASCII schematic saved to a .txt file.

Supports:
    - .SUBCKT / .ENDS blocks
    - .PININFO directives
    - MOSFET instances (M prefix), subcircuit instances (X prefix)
    - Future-ready stubs for R, C, D, Q components
    - Continuation lines (+)
    - Comment lines (*)
    - Multiple subcircuits and hierarchical instantiation

Usage:
    python cdl_to_ascii_schematic.py input.cdl output.txt
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logger = logging.getLogger("cdl2schematic")


# ===========================================================================
# Data Model
# ===========================================================================

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


@dataclass
class Net:
    """Represents an electrical net (node) in the circuit."""
    name: str
    connected_components: List[str] = field(default_factory=list)

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, Net):
            return self.name == other.name
        return NotImplemented


class Component(ABC):
    """Abstract base class for all circuit components."""

    def __init__(self, name: str, comp_type: ComponentType):
        self.name = name
        self.comp_type = comp_type
        self.params: Dict[str, str] = {}

    @abstractmethod
    def get_terminals(self) -> Dict[str, str]:
        """Return mapping of terminal-role -> net-name."""
        ...

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name})"


class MOSFET(Component):
    """
    MOSFET component.

    CDL format:  M<name> <drain> <gate> <source> <bulk> <model> [params...]
    """

    def __init__(self, name: str, drain: str, gate: str, source: str,
                 bulk: str, model: str, mos_type: MOSType = MOSType.UNKNOWN,
                 params: Optional[Dict[str, str]] = None):
        super().__init__(name, ComponentType.MOSFET)
        self.drain = drain
        self.gate = gate
        self.source = source
        self.bulk = bulk
        self.model = model
        self.mos_type = mos_type
        if params:
            self.params = params

    def get_terminals(self) -> Dict[str, str]:
        return {"D": self.drain, "G": self.gate, "S": self.source, "B": self.bulk}


class SubcktInstance(Component):
    """Hierarchical subcircuit instantiation (X prefix)."""

    def __init__(self, name: str, subckt_name: str, connections: Dict[str, str],
                 params: Optional[Dict[str, str]] = None):
        super().__init__(name, ComponentType.SUBCKT_INST)
        self.subckt_name = subckt_name
        self.connections = connections  # pin -> net
        if params:
            self.params = params

    def get_terminals(self) -> Dict[str, str]:
        return dict(self.connections)


class Resistor(Component):
    """Resistor component (R prefix) — stub for future use."""

    def __init__(self, name: str, pos: str, neg: str,
                 params: Optional[Dict[str, str]] = None):
        super().__init__(name, ComponentType.RESISTOR)
        self.pos = pos
        self.neg = neg
        if params:
            self.params = params

    def get_terminals(self) -> Dict[str, str]:
        return {"P": self.pos, "N": self.neg}


class Capacitor(Component):
    """Capacitor component (C prefix) — stub for future use."""

    def __init__(self, name: str, pos: str, neg: str,
                 params: Optional[Dict[str, str]] = None):
        super().__init__(name, ComponentType.CAPACITOR)
        self.pos = pos
        self.neg = neg
        if params:
            self.params = params

    def get_terminals(self) -> Dict[str, str]:
        return {"P": self.pos, "N": self.neg}


class Diode(Component):
    """Diode component (D prefix) — stub for future use."""

    def __init__(self, name: str, anode: str, cathode: str,
                 params: Optional[Dict[str, str]] = None):
        super().__init__(name, ComponentType.DIODE)
        self.anode = anode
        self.cathode = cathode
        if params:
            self.params = params

    def get_terminals(self) -> Dict[str, str]:
        return {"A": self.anode, "K": self.cathode}


class BJT(Component):
    """BJT component (Q prefix) — stub for future use."""

    def __init__(self, name: str, collector: str, base: str, emitter: str,
                 substrate: str = "", model: str = "",
                 params: Optional[Dict[str, str]] = None):
        super().__init__(name, ComponentType.BJT)
        self.collector = collector
        self.base = base
        self.emitter = emitter
        self.substrate = substrate
        self.model = model
        if params:
            self.params = params

    def get_terminals(self) -> Dict[str, str]:
        terminals = {"C": self.collector, "B": self.base, "E": self.emitter}
        if self.substrate:
            terminals["S"] = self.substrate
        return terminals


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
        for role, net_name in comp.get_terminals().items():
            net = self.get_or_create_net(net_name)
            net.connected_components.append(comp.name)


@dataclass
class Circuit:
    """Top-level container holding all parsed subcircuits."""
    subcircuits: Dict[str, Subckt] = field(default_factory=dict)
    top_level_components: List[Component] = field(default_factory=list)


# ===========================================================================
# Parser
# ===========================================================================

# Common PMOS / NMOS model-name patterns (case-insensitive heuristics)
_PMOS_PATTERNS = re.compile(r"(pmos|pfet|pch|pfet|lvtpfet|hvtpfet|svtpfet)", re.IGNORECASE)
_NMOS_PATTERNS = re.compile(r"(nmos|nfet|nch|nfet|lvtnfet|hvtnfet|svtnfet)", re.IGNORECASE)


class NetlistParser:
    """
    Parses a CDL netlist file into a Circuit data model.

    Handles continuation lines, comment stripping, and graceful
    recovery from malformed content.
    """

    def __init__(self):
        self.circuit = Circuit()

    # ----- public API -------------------------------------------------------

    def parse_file(self, filepath: str) -> Circuit:
        """Read and parse a .cdl file, returning a Circuit object."""
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

    # ----- internal helpers -------------------------------------------------

    @staticmethod
    def _merge_continuation_lines(raw_lines: List[str]) -> List[str]:
        """Merge continuation lines (starting with '+') with their predecessor."""
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

            # Comment line (starting with * but not *.PININFO)
            if stripped.startswith("*"):
                # Check for *.PININFO
                if stripped.upper().startswith("*.PININFO"):
                    if current_subckt is not None:
                        self._parse_pininfo(stripped, current_subckt)
                    else:
                        logger.warning("Line %d: .PININFO outside subcircuit.", lineno)
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
            first_char = stripped[0].upper()
            try:
                if first_char == "M":
                    comp = self._parse_mosfet(stripped)
                elif first_char == "X":
                    comp = self._parse_subckt_instance(stripped)
                elif first_char == "R":
                    comp = self._parse_resistor(stripped)
                elif first_char == "C":
                    comp = self._parse_capacitor(stripped)
                elif first_char == "D":
                    comp = self._parse_diode(stripped)
                elif first_char == "Q":
                    comp = self._parse_bjt(stripped)
                else:
                    logger.debug("Line %d: Unrecognised — skipped.", lineno)
                    continue
            except Exception as exc:
                logger.warning("Line %d: Failed to parse — %s. Skipping.", lineno, exc)
                continue

            if comp is None:
                continue

            if current_subckt is not None:
                current_subckt.add_component(comp)
            else:
                self.circuit.top_level_components.append(comp)

    # --- header parsers -----------------------------------------------------

    @staticmethod
    def _parse_subckt_header(line: str) -> Optional[Subckt]:
        """Parse `.SUBCKT name port1 port2 ...`."""
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
        """Parse `*.PININFO pin:dir pin:dir ...`."""
        # Remove leading *.PININFO
        body = re.sub(r"^\*\s*\.PININFO\s*", "", line, flags=re.IGNORECASE)
        for token in body.split():
            if ":" in token:
                pin, direction = token.rsplit(":", 1)
                subckt.pin_info[pin] = direction

    # --- component parsers --------------------------------------------------

    @staticmethod
    def _split_params(tokens: List[str]) -> Dict[str, str]:
        """Extract key=value pairs from a token list, ignoring plain tokens."""
        params: Dict[str, str] = {}
        for tok in tokens:
            if "=" in tok:
                key, _, val = tok.partition("=")
                params[key.strip()] = val.strip()
        return params

    def _parse_mosfet(self, line: str) -> Optional[MOSFET]:
        """Parse M-line:  M<name> D G S B model [params...]"""
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
        """Parse X-line:  X<name> net1 net2 ... / subckt_name [params...]"""
        tokens = line.split()
        if len(tokens) < 3:
            logger.warning("Incomplete X-instance line: %s", line[:80])
            return None
        name = tokens[0]
        # Separate net tokens from param tokens
        net_tokens: List[str] = []
        param_start = len(tokens)
        subckt_name_idx = -1

        # Strategy: all tokens before first key=value that are not key=value are nets.
        # The last such token is the subckt name.
        for i in range(1, len(tokens)):
            if "=" in tokens[i]:
                param_start = i
                break
        # Everything from 1..param_start-1:  nets + subckt_name (last token)
        net_section = tokens[1:param_start]
        if not net_section:
            logger.warning("Cannot determine subcircuit for X-instance: %s", name)
            return None
        subckt_ref = net_section[-1]
        connection_nets = net_section[:-1]
        params = self._split_params(tokens[param_start:])

        # Build connection dict (positional — actual pin mapping requires subckt def)
        connections = {f"pin{i}": n for i, n in enumerate(connection_nets)}
        return SubcktInstance(name, subckt_ref, connections, params)

    def _parse_resistor(self, line: str) -> Optional[Resistor]:
        tokens = line.split()
        if len(tokens) < 3:
            return None
        name = tokens[0]
        pos, neg = tokens[1], tokens[2]
        params = self._split_params(tokens[3:])
        return Resistor(name, pos, neg, params)

    def _parse_capacitor(self, line: str) -> Optional[Capacitor]:
        tokens = line.split()
        if len(tokens) < 3:
            return None
        name = tokens[0]
        pos, neg = tokens[1], tokens[2]
        params = self._split_params(tokens[3:])
        return Capacitor(name, pos, neg, params)

    def _parse_diode(self, line: str) -> Optional[Diode]:
        tokens = line.split()
        if len(tokens) < 3:
            return None
        name = tokens[0]
        anode, cathode = tokens[1], tokens[2]
        params = self._split_params(tokens[3:])
        return Diode(name, anode, cathode, params)

    def _parse_bjt(self, line: str) -> Optional[BJT]:
        tokens = line.split()
        if len(tokens) < 4:
            return None
        name = tokens[0]
        c, b, e = tokens[1], tokens[2], tokens[3]
        substrate = tokens[4] if len(tokens) > 4 and "=" not in tokens[4] else ""
        model_idx = 5 if substrate else 4
        model = tokens[model_idx] if len(tokens) > model_idx and "=" not in tokens[model_idx] else ""
        start = model_idx + 1 if model else model_idx
        params = self._split_params(tokens[start:])
        return BJT(name, c, b, e, substrate, model, params)


# ===========================================================================
# Layout & Rendering — Placement Data Structures
# ===========================================================================

@dataclass
class CMOSGatePlacement:
    """A CMOS logic gate with complementary pull-up and pull-down networks.

    Handles inverters, NAND, NOR, and other CMOS topologies by classifying
    pull-up (PMOS) and pull-down (NMOS) networks as parallel or series.
    """
    pullup_mos: List[MOSFET]       # PMOS transistors (pull-up network)
    pulldown_mos: List[MOSFET]     # NMOS transistors (pull-down network)
    pullup_topology: str           # "parallel" or "series"
    pulldown_topology: str         # "parallel" or "series"
    output_net: str
    supply_net: str
    ground_net: str
    wc_mid: int                    # center wire column


@dataclass
class SingleMOSPlacement:
    """A standalone MOSFET (not part of any CMOS gate)."""
    mos: MOSFET
    wc: int


@dataclass
class GenericPlacement:
    """A non-MOSFET component (subcircuit instance, R, C, etc.)."""
    comp: Component
    wc: int


# ===========================================================================
# Layout Engine
# ===========================================================================

class LayoutEngine:
    """
    Deterministic layout engine that detects CMOS gate topologies (inverter,
    NAND, NOR, complex gates) and assigns placement groups for the renderer.

    CMOS topology classification:
      - Pull-up network (PMOS): parallel => NAND-style, series => NOR-style
      - Pull-down network (NMOS): series  => NAND-style, parallel => NOR-style
      - Inverter: one PMOS + one NMOS (degenerate parallel-1 case)
    """

    PARALLEL_SPACING = 24   # horizontal distance between parallel transistors
    COL_SPACING = 30        # spacing between unrelated component groups
    MIN_WC_MID = 30         # minimum center wire column

    def __init__(self, subckt: Subckt):
        self.subckt = subckt
        self.supply_nets: Set[str] = set()
        self.ground_nets: Set[str] = set()
        self._detect_supply_ground()

    # ----- public API -------------------------------------------------------

    def layout(self) -> List:
        """Produce placement groups with assigned wire columns."""
        mosfets = [c for c in self.subckt.components if isinstance(c, MOSFET)]
        others  = [c for c in self.subckt.components if not isinstance(c, MOSFET)]

        gates, remaining_mos = self._detect_cmos_gates(mosfets)

        # Compute minimum wc_mid so gate labels and parallel spread fit
        max_gate_len = 0
        for g in gates:
            for m in g["pullup"] + g["pulldown"]:
                max_gate_len = max(max_gate_len, len(m.gate))
        for m in remaining_mos:
            max_gate_len = max(max_gate_len, len(m.gate))

        max_parallel = 1
        for g in gates:
            if g["pullup_topology"] == "parallel":
                max_parallel = max(max_parallel, len(g["pullup"]))
            if g["pulldown_topology"] == "parallel":
                max_parallel = max(max_parallel, len(g["pulldown"]))

        wc_mid = max(
            self.MIN_WC_MID,
            max_gate_len + 16 + (max_parallel - 1) * self.PARALLEL_SPACING // 2,
        )

        groups: List = []
        col = wc_mid

        for g in gates:
            n_up = len(g["pullup"]) if g["pullup_topology"] == "parallel" else 1
            n_dn = len(g["pulldown"]) if g["pulldown_topology"] == "parallel" else 1
            max_n = max(n_up, n_dn)
            total_width = (max_n - 1) * self.PARALLEL_SPACING
            groups.append(CMOSGatePlacement(
                pullup_mos=g["pullup"],
                pulldown_mos=g["pulldown"],
                pullup_topology=g["pullup_topology"],
                pulldown_topology=g["pulldown_topology"],
                output_net=g["output_net"],
                supply_net=g["supply"],
                ground_net=g["ground"],
                wc_mid=col,
            ))
            col += total_width + self.COL_SPACING

        for mos in remaining_mos:
            groups.append(SingleMOSPlacement(mos, col))
            col += self.COL_SPACING

        for comp in others:
            groups.append(GenericPlacement(comp, col))
            col += self.COL_SPACING

        return groups

    # ----- supply / ground detection ----------------------------------------

    def _detect_supply_ground(self) -> None:
        """Heuristically classify supply and ground nets."""
        supply_hints = re.compile(
            r"(vdd|vpwr|avdd|dvdd|supply|v_hi)", re.IGNORECASE)
        ground_hints = re.compile(
            r"(vss|gnd|ground|avss|dvss|v_lo)", re.IGNORECASE)

        all_nets = set(self.subckt.nets.keys()) | set(self.subckt.ports)
        for net in all_nets:
            if supply_hints.search(net):
                self.supply_nets.add(net)
            elif ground_hints.search(net):
                self.ground_nets.add(net)

        # NOTE: We intentionally do NOT infer supply/ground from MOSFET
        # source connectivity.  In series stacks (NAND pull-down, NOR
        # pull-up) the intermediate nets would be wrongly classified,
        # breaking series-chain detection.  Name-pattern heuristics are
        # sufficient for standard CMOS designs.

    # ----- CMOS gate detection ----------------------------------------------

    def _detect_cmos_gates(
        self, mosfets: List[MOSFET],
    ) -> Tuple[List[dict], List[MOSFET]]:
        """
        Detect CMOS gate topologies among the given MOSFETs.

        Algorithm
        ---------
        1. Group PMOS/NMOS by drain net.
        2. Find output-net candidates (drain shared by at least one PMOS
           and one NMOS — the starting point of both networks).
        3. For each output net, classify pull-up (PMOS) and pull-down (NMOS)
           networks as *parallel* or *series* by tracing source→drain chains
           toward the supply/ground rails.

        Returns (gates, remaining_mosfets).
        """
        pmos_list = [m for m in mosfets if m.mos_type == MOSType.PMOS]
        nmos_list = [m for m in mosfets if m.mos_type == MOSType.NMOS]

        pmos_by_drain: Dict[str, List[MOSFET]] = defaultdict(list)
        nmos_by_drain: Dict[str, List[MOSFET]] = defaultdict(list)
        for m in pmos_list:
            pmos_by_drain[m.drain].append(m)
        for m in nmos_list:
            nmos_by_drain[m.drain].append(m)

        used: Set[str] = set()
        gates: List[dict] = []

        # Output net candidates — nets where both PMOS and NMOS drains meet
        output_candidates = sorted(
            set(pmos_by_drain.keys()) & set(nmos_by_drain.keys())
        )

        for out_net in output_candidates:
            pu_cands = [m for m in pmos_by_drain[out_net] if m.name not in used]
            pd_cands = [m for m in nmos_by_drain[out_net] if m.name not in used]
            if not pu_cands or not pd_cands:
                continue

            pu_topo, pu_chain = self._classify_network(
                pu_cands, pmos_list, used, self.supply_nets)
            pd_topo, pd_chain = self._classify_network(
                pd_cands, nmos_list, used, self.ground_nets)

            supply = self._terminal_net(pu_chain, self.supply_nets)
            ground = self._terminal_net(pd_chain, self.ground_nets)

            for m in pu_chain + pd_chain:
                used.add(m.name)

            gates.append({
                "pullup":            pu_chain,
                "pulldown":          pd_chain,
                "pullup_topology":   pu_topo,
                "pulldown_topology": pd_topo,
                "output_net":        out_net,
                "supply":            supply or "VDD",
                "ground":            ground or "VSS",
            })

        remaining = [m for m in mosfets if m.name not in used]
        return gates, remaining

    # ------------------------------------------------------------------ #

    def _classify_network(
        self,
        direct_mos: List[MOSFET],
        all_of_type: List[MOSFET],
        used: Set[str],
        terminal_nets: Set[str],
    ) -> Tuple[str, List[MOSFET]]:
        """
        Starting from *direct_mos* (transistors whose drain == output net),
        classify the network as **parallel** or **series** by tracing
        source→drain links toward the supply/ground rails.

        Returns ``(topology, ordered_chain)`` where *ordered_chain* lists
        transistors from the output side toward the terminal rail.
        """
        # All direct transistors already reach terminal via source → parallel
        if all(m.source in terminal_nets for m in direct_mos):
            return "parallel", list(direct_mos)

        # Trace series chain
        chain: List[MOSFET] = []
        visited: Set[str] = set()
        frontier = list(direct_mos)

        while frontier:
            next_frontier: List[MOSFET] = []
            for m in frontier:
                if m.name in visited or m.name in used:
                    continue
                chain.append(m)
                visited.add(m.name)
                if m.source not in terminal_nets:
                    for cand in all_of_type:
                        if (cand.name not in visited
                                and cand.name not in used
                                and cand.drain == m.source):
                            next_frontier.append(cand)
            frontier = next_frontier

        topo = "series" if len(chain) > 1 else "parallel"
        return topo, chain

    @staticmethod
    def _terminal_net(
        chain: List[MOSFET], terminal_nets: Set[str],
    ) -> Optional[str]:
        """Return the supply/ground net that terminates the chain."""
        for m in chain:
            if m.source in terminal_nets:
                return m.source
        return chain[-1].source if chain else None


# ===========================================================================
# ASCII Renderer
# ===========================================================================

class ASCIIRenderer:
    """
    Renders CMOS gate placement groups onto a character grid.

    Topology rendering styles
    -------------------------
    * **Parallel** transistors are drawn side-by-side; their drain (or
      source) terminals are connected by a horizontal bus.
    * **Series** transistors are stacked vertically on a single wire
      column with intermediate-net labels between them.

    MOSFET symbol::

             |
        ||---+          (channel arm)
      --||   |          (gate; 'o' prepended for PMOS)
        ||---+
             |

    Full CMOS NAND2 example::

              VDD               VDD
               |                 |
          ||---+ MP1        ||---+ MP3
      A --o||  |        B --o||  |
          ||---+            ||---+
               |                 |
               +--------+--------+
                        |
                        +---------- Z
                        |
                   ||---+
           A ------||   |  MN0
                   ||---+
                        |  net7
                   ||---+
           B ------||   |  MN1
                   ||---+
                        |
                       VSS
    """

    PARALLEL_SPACING = 24      # must match LayoutEngine
    BASE_ROW = 2               # top margin rows

    def __init__(self, groups: List, subckt: Subckt):
        self.groups = groups
        self.subckt = subckt
        self.grid: List[List[str]] = []
        self.rows = 0
        self.cols = 0

    # ----- public -----------------------------------------------------------

    def render(self) -> str:
        """Build the ASCII schematic and return it as a string."""
        self._compute_size()
        self._init_grid()
        for g in self.groups:
            if isinstance(g, CMOSGatePlacement):
                self._draw_cmos_gate(g)
            elif isinstance(g, SingleMOSPlacement):
                self._draw_single_mos(g)
            elif isinstance(g, GenericPlacement):
                self._draw_generic(g)
        return self._grid_to_string()

    # ----- grid helpers -----------------------------------------------------

    def _compute_size(self) -> None:
        max_row = self.BASE_ROW
        max_col = 10
        PS = self.PARALLEL_SPACING

        for g in self.groups:
            if isinstance(g, CMOSGatePlacement):
                n_up = len(g.pullup_mos)
                n_dn = len(g.pulldown_mos)

                # Upper network height
                if g.pullup_topology == "parallel":
                    up_h = 8           # label+2wire + 3sym + wire + bus
                else:
                    up_h = 3 + 4 * n_up - 1   # supply+2wire, then 3 per mos + 1 gap

                out_h = 3              # wire, junction, wire

                if g.pulldown_topology == "parallel":
                    dn_h = 8
                else:
                    dn_h = 4 * n_dn + 2

                h = up_h + out_h + dn_h

                max_n = max(
                    n_up if g.pullup_topology == "parallel" else 1,
                    n_dn if g.pulldown_topology == "parallel" else 1,
                )
                spread = (max_n - 1) * PS
                right = g.wc_mid + spread // 2 + 30
                max_row = max(max_row, self.BASE_ROW + h)
                max_col = max(max_col, right)

            elif isinstance(g, SingleMOSPlacement):
                max_row = max(max_row, self.BASE_ROW + 10)
                ts = ("PMOS" if g.mos.mos_type == MOSType.PMOS
                      else "NMOS" if g.mos.mos_type == MOSType.NMOS
                      else "FET")
                right = g.wc + 6 + len(g.mos.name) + 1 + len(ts)
                max_col = max(max_col, right)

            elif isinstance(g, GenericPlacement):
                max_row = max(max_row, self.BASE_ROW + 10)
                if isinstance(g.comp, SubcktInstance):
                    lbl = f"[{g.comp.name}] {g.comp.subckt_name}"
                else:
                    lbl = f"[{g.comp.name}]"
                right = g.wc + len(lbl) + 6
                max_col = max(max_col, right)

        self.rows = max_row + 4
        self.cols = max_col + 5

    def _init_grid(self) -> None:
        self.grid = [[" "] * self.cols for _ in range(self.rows)]

    def _put(self, r: int, c: int, ch: str) -> None:
        if 0 <= r < self.rows and 0 <= c < self.cols:
            self.grid[r][c] = ch

    def _puts(self, r: int, c: int, text: str) -> None:
        for i, ch in enumerate(text):
            self._put(r, c + i, ch)

    def _safe_puts(self, r: int, c: int, text: str) -> None:
        for i, ch in enumerate(text):
            cc = c + i
            if 0 <= r < self.rows and 0 <= cc < self.cols and self.grid[r][cc] == " ":
                self.grid[r][cc] = ch

    # ----- primitive drawing helpers ----------------------------------------

    def _draw_arm(self, r: int, gx: int, wc: int) -> None:
        """Draw channel arm:  ||---+"""
        self._put(r, gx, "|")
        self._put(r, gx + 1, "|")
        for c in range(gx + 2, wc):
            self._put(r, c, "-")
        self._put(r, wc, "+")

    def _draw_vwire(self, col: int, r1: int, r2: int) -> None:
        for r in range(r1, r2 + 1):
            if 0 <= r < self.rows and 0 <= col < self.cols:
                cur = self.grid[r][col]
                if cur == "-":
                    self._put(r, col, "+")
                elif cur in (" ", "|"):
                    self._put(r, col, "|")

    def _draw_hwire(self, row: int, c1: int, c2: int) -> None:
        for c in range(c1, c2 + 1):
            if 0 <= row < self.rows and 0 <= c < self.cols:
                cur = self.grid[row][c]
                if cur == "|":
                    self._put(row, c, "+")
                elif cur in (" ", "-"):
                    self._put(row, c, "-")

    def _draw_mos_gate_wire(
        self, row: int, gx: int, wc: int, mos: MOSFET,
        is_pmos: bool, label_name: bool = True,
    ) -> None:
        """Draw gate input wire and optional name label for one MOSFET."""
        gate = mos.gate
        type_str = "PMOS" if is_pmos else "NMOS"

        if is_pmos:
            gate_end = gx - 1      # room for 'o' bubble
        else:
            gate_end = gx

        gate_start = gate_end - 2 - len(gate)
        if gate_start < 0:
            gate_start = 0

        self._puts(row, gate_start, gate)
        wire_begin = gate_start + len(gate) + 1

        if is_pmos:
            self._draw_hwire(row, wire_begin, gx - 2)
            self._put(row, gx - 1, "o")
        else:
            self._draw_hwire(row, wire_begin, gx - 1)

        self._put(row, gx, "|")
        self._put(row, gx + 1, "|")
        self._put(row, wc, "|")

        if label_name:
            self._puts(row, wc + 4, f"{mos.name} {type_str}")

    # ===================================================================
    # CMOS gate drawing
    # ===================================================================

    def _draw_cmos_gate(self, g: CMOSGatePlacement) -> None:
        """Draw a complete CMOS gate (INV / NAND / NOR / complex)."""
        PS = self.PARALLEL_SPACING
        wc_mid = g.wc_mid
        B = self.BASE_ROW
        n_up = len(g.pullup_mos)
        n_dn = len(g.pulldown_mos)

        def spread_wcs(n: int) -> List[int]:
            """Compute wire-column positions centred on *wc_mid*."""
            return [wc_mid + int((i - (n - 1) / 2) * PS) for i in range(n)]

        # --- Upper network (pull-up PMOS) ---
        r = B
        if g.pullup_topology == "parallel":
            up_wcs = spread_wcs(n_up)
            r = self._draw_upper_parallel(
                r, up_wcs, g.pullup_mos, g.supply_net, wc_mid)
        else:
            r = self._draw_upper_series(
                r, wc_mid, g.pullup_mos, g.supply_net)

        # --- Output junction ---
        self._put(r, wc_mid, "|")
        r += 1
        self._put(r, wc_mid, "+")
        out_end = wc_mid + 10
        self._draw_hwire(r, wc_mid + 1, out_end)
        self._puts(r, out_end + 2, g.output_net)
        r += 1
        self._put(r, wc_mid, "|")
        r += 1

        # --- Lower network (pull-down NMOS) ---
        if g.pulldown_topology == "parallel":
            dn_wcs = spread_wcs(n_dn)
            self._draw_lower_parallel(
                r, dn_wcs, g.pulldown_mos, g.ground_net, wc_mid)
        else:
            self._draw_lower_series(
                r, wc_mid, g.pulldown_mos, g.ground_net)

    # ----- upper-network helpers (PMOS) -----------------------------------

    def _draw_upper_parallel(
        self, start_row: int, wc_list: List[int],
        mos_list: List[MOSFET], supply: str, wc_mid: int,
    ) -> int:
        """Parallel PMOS pull-up: VDD at top, drain bus at bottom."""
        r = start_row

        # Supply labels
        for wc in wc_list:
            self._safe_puts(r, wc - len(supply) // 2, supply)
        r += 1

        # Wires from supply
        for wc in wc_list:
            self._draw_vwire(wc, r, r + 1)
        r += 2

        # MOSFET symbols — 3 rows: top-arm, gate, bottom-arm
        arm_top, gate_r, arm_bot = r, r + 1, r + 2
        for wc, mos in zip(wc_list, mos_list):
            gx = wc - 5
            self._draw_arm(arm_top, gx, wc)
            self._safe_puts(arm_top, wc + 3, f"{mos.name} PMOS")
            self._draw_mos_gate_wire(
                gate_r, gx, wc, mos, is_pmos=True, label_name=False)
            self._draw_arm(arm_bot, gx, wc)
        r += 3

        # Wires from drains down to bus row
        for wc in wc_list:
            self._put(r, wc, "|")
        r += 1

        # Horizontal drain bus
        if len(wc_list) > 1:
            left, right = min(wc_list), max(wc_list)
            for wc in wc_list:
                self._put(r, wc, "|")
            if wc_mid not in wc_list:
                self._put(r, wc_mid, "|")
            self._draw_hwire(r, left, right)
        else:
            self._put(r, wc_mid, "|")
        r += 1

        return r

    def _draw_upper_series(
        self, start_row: int, wc: int,
        mos_list: List[MOSFET], supply: str,
    ) -> int:
        """Series PMOS pull-up: VDD at top, output side at bottom."""
        r = start_row
        gx = wc - 5

        # Supply label + wires
        self._safe_puts(r, wc - len(supply) // 2, supply)
        r += 1
        self._draw_vwire(wc, r, r + 1)
        r += 2

        # Draw from supply-side toward output (reverse the output→supply chain)
        ordered = list(reversed(mos_list))
        for i, mos in enumerate(ordered):
            self._draw_arm(r, gx, wc)
            self._draw_mos_gate_wire(r + 1, gx, wc, mos, is_pmos=True)
            self._draw_arm(r + 2, gx, wc)
            r += 3
            if i < len(ordered) - 1:
                int_net = mos.drain      # intermediate net below this PMOS
                self._put(r, wc, "|")
                self._safe_puts(r, wc + 3, int_net)
                r += 1

        return r

    # ----- lower-network helpers (NMOS) -----------------------------------

    def _draw_lower_series(
        self, start_row: int, wc: int,
        mos_list: List[MOSFET], ground: str,
    ) -> int:
        """Series NMOS pull-down: output at top, VSS at bottom."""
        r = start_row
        gx = wc - 5

        for i, mos in enumerate(mos_list):
            self._draw_arm(r, gx, wc)
            self._draw_mos_gate_wire(r + 1, gx, wc, mos, is_pmos=False)
            self._draw_arm(r + 2, gx, wc)
            r += 3
            if i < len(mos_list) - 1:
                int_net = mos.source     # intermediate net below this NMOS
                self._put(r, wc, "|")
                self._safe_puts(r, wc + 3, int_net)
                r += 1

        # Wire to ground + label
        self._draw_vwire(wc, r, r + 1)
        r += 2
        self._safe_puts(r, wc - len(ground) // 2, ground)
        return r + 1

    def _draw_lower_parallel(
        self, start_row: int, wc_list: List[int],
        mos_list: List[MOSFET], ground: str, wc_mid: int,
    ) -> int:
        """Parallel NMOS pull-down: drain bus at top, VSS at bottom."""
        r = start_row

        # Horizontal drain bus
        if len(wc_list) > 1:
            left, right = min(wc_list), max(wc_list)
            for wc in wc_list:
                self._put(r, wc, "|")
            if wc_mid not in wc_list:
                self._put(r, wc_mid, "|")
            self._draw_hwire(r, left, right)
        else:
            self._put(r, wc_mid, "|")
        r += 1

        # Wires from bus
        for wc in wc_list:
            self._put(r, wc, "|")
        r += 1

        # MOSFET symbols
        arm_top, gate_r, arm_bot = r, r + 1, r + 2
        for wc, mos in zip(wc_list, mos_list):
            gx = wc - 5
            self._draw_arm(arm_top, gx, wc)
            self._safe_puts(arm_top, wc + 3, f"{mos.name} NMOS")
            self._draw_mos_gate_wire(
                gate_r, gx, wc, mos, is_pmos=False, label_name=False)
            self._draw_arm(arm_bot, gx, wc)
        r += 3

        # Wires to ground
        for wc in wc_list:
            self._draw_vwire(wc, r, r + 1)
        r += 2

        # Ground labels
        for wc in wc_list:
            self._safe_puts(r, wc - len(ground) // 2, ground)
        return r + 1

    # ----- single MOSFET drawing -------------------------------------------

    def _draw_single_mos(self, g: SingleMOSPlacement) -> None:
        """Draw a standalone MOSFET (not part of a CMOS gate)."""
        wc = g.wc
        mos = g.mos
        B = self.BASE_ROW

        is_pmos = (mos.mos_type == MOSType.PMOS)
        if is_pmos:
            top_net, bot_net, type_str = mos.source, mos.drain, "PMOS"
        elif mos.mos_type == MOSType.NMOS:
            top_net, bot_net, type_str = mos.drain, mos.source, "NMOS"
        else:
            top_net, bot_net, type_str = mos.drain, mos.source, "FET"

        gx = wc - 5
        self._safe_puts(B, wc - len(top_net) // 2, top_net)
        self._draw_vwire(wc, B + 1, B + 2)
        self._draw_arm(B + 3, gx, wc)
        self._draw_mos_gate_wire(B + 4, gx, wc, mos, is_pmos)
        self._draw_arm(B + 5, gx, wc)
        self._draw_vwire(wc, B + 6, B + 7)
        self._safe_puts(B + 8, wc - len(bot_net) // 2, bot_net)

    # ----- generic component drawing ---------------------------------------

    def _draw_generic(self, g: GenericPlacement) -> None:
        """Draw a non-MOSFET component as a labelled box."""
        wc = g.wc
        comp = g.comp
        B = self.BASE_ROW

        terminals = comp.get_terminals()
        t_list = list(terminals.values())
        top_net = t_list[0] if len(t_list) >= 1 else ""
        bot_net = t_list[1] if len(t_list) >= 2 else ""

        if isinstance(comp, SubcktInstance):
            label = f"[{comp.name}] {comp.subckt_name}"
        else:
            label = f"[{comp.name}]"

        if top_net:
            self._safe_puts(B, wc - len(top_net) // 2, top_net)
            self._draw_vwire(wc, B + 1, B + 3)

        box_start = max(0, wc - len(label) // 2)
        self._puts(B + 4, box_start, label)

        if bot_net:
            self._draw_vwire(wc, B + 5, B + 7)
            self._safe_puts(B + 8, wc - len(bot_net) // 2, bot_net)

    # ----- grid to string --------------------------------------------------

    def _grid_to_string(self) -> str:
        """Convert the grid to a trimmed string."""
        lines: List[str] = []
        for row in self.grid:
            line = "".join(row).rstrip()
            lines.append(line)
        while lines and not lines[-1].strip():
            lines.pop()
        while len(lines) > 1 and not lines[0].strip() and not lines[1].strip():
            lines.pop(0)
        return "\n".join(lines)



# ===========================================================================
# Schematic Builder — orchestrates per-subcircuit layout + render
# ===========================================================================

class SchematicBuilder:
    """High-level orchestrator: parse -> layout -> render for each subcircuit."""

    def __init__(self, circuit: Circuit):
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


# ===========================================================================
# Main entry point
# ===========================================================================

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Convert a CDL netlist to an ASCII schematic (.txt).",
        epilog="Example: python cdl_to_ascii_schematic.py input.cdl output.txt",
    )
    parser.add_argument("input", help="Path to input .cdl netlist file")
    parser.add_argument("output", help="Path to output .txt schematic file")
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    # Parse
    cdl_parser = NetlistParser()
    try:
        circuit = cdl_parser.parse_file(args.input)
    except Exception as exc:
        logger.error("Failed to parse input file: %s", exc)
        sys.exit(1)

    # Build schematics
    builder = SchematicBuilder(circuit)
    schematic_text = builder.build_all()

    # Write output
    try:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(schematic_text)
        logger.info("Schematic written to %s", args.output)
    except OSError as exc:
        logger.error("Failed to write output file: %s", exc)
        sys.exit(1)

    print(f"Done. Schematic saved to: {args.output}")


if __name__ == "__main__":
    main()
