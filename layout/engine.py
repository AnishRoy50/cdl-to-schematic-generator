"""CMOS-aware layout engine.

Detects CMOS gate topologies (inverter, NAND, NOR, complex gates) among
the subcircuit's transistors and assigns each component group a horizontal
wire-column position for the renderer.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from models import MOSFET, MOSType, Subckt, Component
from .placements import CMOSGatePlacement, SingleMOSPlacement, GenericPlacement

logger = logging.getLogger("cdl2schematic")


class LayoutEngine:
    """Deterministic layout engine producing placement groups.

    CMOS topology classification
    ----------------------------
    * Pull-up network (PMOS):  parallel ⇒ NAND-style, series ⇒ NOR-style
    * Pull-down network (NMOS): series  ⇒ NAND-style, parallel ⇒ NOR-style
    * Inverter: one PMOS + one NMOS (degenerate parallel-1 case)
    """

    PARALLEL_SPACING = 24   # horizontal distance between parallel transistors
    COL_SPACING = 30        # spacing between unrelated component groups
    MIN_WC_MID = 30         # minimum centre wire column

    def __init__(self, subckt: Subckt) -> None:
        self.subckt = subckt
        self.supply_nets: Set[str] = set()
        self.ground_nets: Set[str] = set()
        self._detect_supply_ground()

    # ── public API ─────────────────────────────────────────────────────────

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

    # ── supply / ground detection ──────────────────────────────────────────

    def _detect_supply_ground(self) -> None:
        """Heuristically classify supply and ground nets by name patterns."""
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
        # pull-up) intermediate nets would be wrongly classified,
        # breaking chain detection.

    # ── CMOS gate detection ────────────────────────────────────────────────

    def _detect_cmos_gates(
        self, mosfets: List[MOSFET],
    ) -> Tuple[List[dict], List[MOSFET]]:
        """Detect CMOS gate topologies among *mosfets*.

        Algorithm
        ---------
        1. Group PMOS/NMOS by drain net.
        2. Find output-net candidates (drain shared by ≥1 PMOS and ≥1 NMOS).
        3. For each output net, classify pull-up and pull-down networks as
           *parallel* or *series* by tracing source→drain chains toward the
           supply/ground rails.

        Returns ``(gates, remaining_mosfets)``.
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

    # ── network classification ─────────────────────────────────────────────

    def _classify_network(
        self,
        direct_mos: List[MOSFET],
        all_of_type: List[MOSFET],
        used: Set[str],
        terminal_nets: Set[str],
    ) -> Tuple[str, List[MOSFET]]:
        """Classify a transistor network as **parallel** or **series**.

        Starting from *direct_mos* (transistors whose drain == output net),
        traces source→drain links toward the supply/ground rails.

        Returns ``(topology, ordered_chain)``.
        """
        # All direct transistors already reach terminal → parallel
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
        """Return the supply/ground net that terminates *chain*."""
        for m in chain:
            if m.source in terminal_nets:
                return m.source
        return chain[-1].source if chain else None
