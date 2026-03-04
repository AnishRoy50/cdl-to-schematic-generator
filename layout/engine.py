from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from models import MOSFET, MOSType, Subckt, Component
from .placements import CMOSGatePlacement, SingleMOSPlacement, GenericPlacement

logger = logging.getLogger("cdl2schematic")

_SUPPLY_PAT = re.compile(r"(vdd|vpwr|avdd|dvdd|supply|v_hi)", re.I)
_GROUND_PAT = re.compile(r"(vss|gnd|ground|avss|dvss|v_lo)", re.I)


@dataclass
class _GateInfo:
    pullup: List[MOSFET]
    pulldown: List[MOSFET]
    pullup_topo: str
    pulldown_topo: str
    pullup_chains: List[List[MOSFET]]
    pulldown_chains: List[List[MOSFET]]
    output_net: str
    supply: str
    ground: str


class LayoutEngine:
    """Deterministic layout engine producing placement groups."""

    PARALLEL_SPACING = 24
    COL_SPACING = 30
    ROUTE_SPACING = 15       # extra gap between connected gates for routing wire
    MIN_WC_MID = 30

    def __init__(self, subckt: Subckt) -> None:
        self.subckt = subckt
        all_nets = set(subckt.nets.keys()) | set(subckt.ports)
        self.supply_nets = {n for n in all_nets if _SUPPLY_PAT.search(n)}
        self.ground_nets = {n for n in all_nets if _GROUND_PAT.search(n)} - self.supply_nets

    # ── public API ─────────────────────────────────────────────────────────

    def layout(self) -> List:
        """Produce placement groups with assigned wire columns."""
        mosfets = [c for c in self.subckt.components if isinstance(c, MOSFET)]
        others = [c for c in self.subckt.components if not isinstance(c, MOSFET)]
        gates, remaining = self._detect_cmos_gates(mosfets)
        gates = self._toposort_gates(gates)

        # Compute minimum wc_mid
        all_mos = [m for g in gates for m in g.pullup + g.pulldown] + remaining
        max_gate_len = max((len(m.gate) for m in all_mos), default=0)

        def _par_count(g: _GateInfo) -> int:
            up = (len(g.pullup_chains) if g.pullup_topo == "parallel_series"
                  else len(g.pullup) if g.pullup_topo == "parallel" else 1)
            dn = (len(g.pulldown_chains) if g.pulldown_topo == "parallel_series"
                  else len(g.pulldown) if g.pulldown_topo == "parallel" else 1)
            return max(up, dn)

        max_parallel = max((_par_count(g) for g in gates), default=1)
        wc_mid = max(self.MIN_WC_MID,
                     max_gate_len + 16 + (max_parallel - 1) * self.PARALLEL_SPACING // 2)

        groups: List = []
        col = wc_mid

        # Identify nets that connect one gate's output to another's input
        out_nets = {g.output_net for g in gates}
        intergate_nets: Set[str] = set()
        for g in gates:
            for m in g.pullup + g.pulldown:
                if m.gate in out_nets:
                    intergate_nets.add(m.gate)

        for g in gates:
            n_par = _par_count(g)
            groups.append(CMOSGatePlacement(
                pullup_mos=g.pullup, pulldown_mos=g.pulldown,
                pullup_topology=g.pullup_topo, pulldown_topology=g.pulldown_topo,
                pullup_chains=g.pullup_chains, pulldown_chains=g.pulldown_chains,
                output_net=g.output_net, supply_net=g.supply,
                ground_net=g.ground, wc_mid=col,
            ))
            route_extra = self.ROUTE_SPACING if g.output_net in intergate_nets else 0
            col += (n_par - 1) * self.PARALLEL_SPACING + self.COL_SPACING + route_extra

        for mos in remaining:
            groups.append(SingleMOSPlacement(mos, col))
            col += self.COL_SPACING

        for comp in others:
            groups.append(GenericPlacement(comp, col))
            col += self.COL_SPACING

        return groups

    def _detect_cmos_gates(
        self, mosfets: List[MOSFET],
    ) -> Tuple[List[_GateInfo], List[MOSFET]]:
        """Detect CMOS gate topologies among *mosfets*."""
        pmos_by_drain: Dict[str, List[MOSFET]] = defaultdict(list)
        nmos_by_drain: Dict[str, List[MOSFET]] = defaultdict(list)
        for m in mosfets:
            if m.mos_type == MOSType.PMOS:
                pmos_by_drain[m.drain].append(m)
            elif m.mos_type == MOSType.NMOS:
                nmos_by_drain[m.drain].append(m)

        used: Set[str] = set()
        gates: List[_GateInfo] = []
        all_pmos = [m for m in mosfets if m.mos_type == MOSType.PMOS]
        all_nmos = [m for m in mosfets if m.mos_type == MOSType.NMOS]

        for out_net in sorted(set(pmos_by_drain) & set(nmos_by_drain)):
            pu = [m for m in pmos_by_drain[out_net] if m.name not in used]
            pd = [m for m in nmos_by_drain[out_net] if m.name not in used]
            if not pu or not pd:
                continue

            pu_topo, pu_chain, pu_chains = self._classify_network(pu, all_pmos, used, self.supply_nets)
            pd_topo, pd_chain, pd_chains = self._classify_network(pd, all_nmos, used, self.ground_nets)
            used.update(m.name for m in pu_chain + pd_chain)

            supply = self._terminal_net(pu_chain, self.supply_nets) or "VDD"
            ground = self._terminal_net(pd_chain, self.ground_nets) or "VSS"
            gates.append(_GateInfo(pu_chain, pd_chain, pu_topo, pd_topo,
                                   pu_chains, pd_chains, out_net, supply, ground))

        return gates, [m for m in mosfets if m.name not in used]

    @staticmethod
    def _toposort_gates(gates: List[_GateInfo]) -> List[_GateInfo]:
        """Sort gates so upstream producers come before downstream consumers."""
        n = len(gates)
        if n <= 1:
            return gates
        out_to_idx = {g.output_net: i for i, g in enumerate(gates)}
        # dependency edges: adj[i] = set of indices that depend on gate i
        adj: Dict[int, Set[int]] = defaultdict(set)
        in_deg = [0] * n
        for i, g in enumerate(gates):
            for m in g.pullup + g.pulldown:
                j = out_to_idx.get(m.gate)
                if j is not None and j != i and i not in adj[j]:
                    adj[j].add(i)
                    in_deg[i] += 1
        # Kahn's algorithm
        queue = sorted([i for i in range(n) if in_deg[i] == 0],
                       key=lambda x: gates[x].output_net)
        result: List[int] = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for nxt in sorted(adj[node]):
                in_deg[nxt] -= 1
                if in_deg[nxt] == 0:
                    queue.append(nxt)
            queue.sort(key=lambda x: gates[x].output_net)
        # append any remaining (cycles)
        for i in range(n):
            if i not in set(result):
                result.append(i)
        return [gates[i] for i in result]

    def _classify_network(
        self, direct: List[MOSFET], all_of_type: List[MOSFET],
        used: Set[str], terminals: Set[str],
    ) -> Tuple[str, List[MOSFET], List[List[MOSFET]]]:
        """Classify a network as parallel, series, or parallel_series."""
        if all(m.source in terminals for m in direct):
            return "parallel", list(direct), [[m] for m in direct]

        # Trace each direct transistor as an independent chain
        chains: List[List[MOSFET]] = []
        claimed: Set[str] = set()
        for start_m in direct:
            if start_m.name in claimed:
                continue
            chain: List[MOSFET] = []
            visited: Set[str] = set()
            frontier = [start_m]
            while frontier:
                nxt: List[MOSFET] = []
                for m in frontier:
                    if m.name in visited or m.name in used or m.name in claimed:
                        continue
                    chain.append(m)
                    visited.add(m.name)
                    claimed.add(m.name)
                    if m.source not in terminals:
                        nxt.extend(c for c in all_of_type
                                   if c.name not in visited
                                   and c.name not in used
                                   and c.name not in claimed
                                   and c.drain == m.source)
                frontier = nxt
            if chain:
                chains.append(chain)

        flat = [m for ch in chains for m in ch]
        if len(chains) > 1 and any(len(ch) > 1 for ch in chains):
            return "parallel_series", flat, chains
        elif len(flat) > 1:
            return "series", flat, chains
        else:
            return "parallel", flat, chains

    @staticmethod
    def _terminal_net(chain: List[MOSFET], terminals: Set[str]) -> Optional[str]:
        for m in chain:
            if m.source in terminals:
                return m.source
        return chain[-1].source if chain else None
