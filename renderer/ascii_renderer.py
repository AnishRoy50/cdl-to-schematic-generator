"""ASCII schematic renderer."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple

from models import MOSFET, MOSType, SubcktInstance, Subckt
from layout.placements import (
    CMOSGatePlacement,
    SingleMOSPlacement,
    GenericPlacement,
)


class ASCIIRenderer:
    """Renders placement groups onto a character grid."""

    PARALLEL_SPACING = 24      # must match LayoutEngine
    BASE_ROW = 2               # top margin rows

    def __init__(self, groups: List, subckt: Subckt) -> None:
        self.groups = groups
        self.subckt = subckt
        self.grid: List[List[str]] = []
        self.rows = 0
        self.cols = 0
        # Inter-gate wiring tracking
        self._gate_id = 0
        self._output_pos: Dict[str, Tuple[int, int, int]] = {}     # net->(row, col_end, gate_id)
        self._input_pos: Dict[str, List[Tuple[int, int, int]]] = defaultdict(list)  # net->[(row, col, gate_id)]

    # ── public ─────────────────────────────────────────────────────────────

    def render(self) -> str:
        """Build the ASCII schematic and return it as a string."""
        self._compute_size()
        self._init_grid()
        # Global junction row – all gates share the same PUN / PDN boundary
        cmos_groups = [g for g in self.groups if isinstance(g, CMOSGatePlacement)]
        self._junction_row = (
            self.BASE_ROW + max(self._pun_height(g) for g in cmos_groups)
            if cmos_groups else self.BASE_ROW + 10
        )
        for g in self.groups:
            self._gate_id += 1
            if isinstance(g, CMOSGatePlacement):
                self._draw_cmos_gate(g)
            elif isinstance(g, SingleMOSPlacement):
                self._draw_single_mos(g)
            elif isinstance(g, GenericPlacement):
                self._draw_generic(g)
        self._draw_interconnects()
        return self._grid_to_string()

    # ── grid helpers ───────────────────────────────────────────────────────

    def _compute_size(self) -> None:
        max_row, max_col = self.BASE_ROW, 10
        PS = self.PARALLEL_SPACING

        # Global CMOS height: max PUN + junction(3) + max PDN
        cmos_groups = [g for g in self.groups if isinstance(g, CMOSGatePlacement)]
        if cmos_groups:
            max_pun = max(self._pun_height(g) for g in cmos_groups)
            max_pdn = max(self._pdn_height(g) for g in cmos_groups)
            max_row = max(max_row, self.BASE_ROW + max_pun + 3 + max_pdn)

        for g in self.groups:
            if isinstance(g, CMOSGatePlacement):
                n_up = len(g.pullup_mos)
                if g.pullup_topology == "parallel_series":
                    n_par_up = len(g.pullup_chains)
                elif g.pullup_topology == "parallel":
                    n_par_up = n_up
                else:
                    n_par_up = 1
                if g.pulldown_topology == "parallel_series":
                    n_par_dn = len(g.pulldown_chains)
                elif g.pulldown_topology == "parallel":
                    n_par_dn = len(g.pulldown_mos)
                else:
                    n_par_dn = 1
                max_n = max(n_par_up, n_par_dn)
                max_col = max(max_col, g.wc_mid + (max_n - 1) * PS // 2 + 30)

            elif isinstance(g, SingleMOSPlacement):
                max_row = max(max_row, self.BASE_ROW + 10)
                ts = {MOSType.PMOS: "PMOS", MOSType.NMOS: "NMOS"}.get(
                    g.mos.mos_type, "FET")
                max_col = max(max_col, g.wc + 7 + len(g.mos.name) + len(ts))

            elif isinstance(g, GenericPlacement):
                max_row = max(max_row, self.BASE_ROW + 10)
                lbl = (f"[{g.comp.name}] {g.comp.subckt_name}"
                       if isinstance(g.comp, SubcktInstance)
                       else f"[{g.comp.name}]")
                max_col = max(max_col, g.wc + len(lbl) + 6)

        self.rows = max_row + 4
        self.cols = max_col + 5

    def _init_grid(self) -> None:
        self.grid = [[" "] * self.cols for _ in range(self.rows)]

    def _put(self, r: int, c: int, ch: str) -> None:
        """Place a single character (unconditional)."""
        if 0 <= r < self.rows and 0 <= c < self.cols:
            self.grid[r][c] = ch

    def _puts(self, r: int, c: int, text: str) -> None:
        """Write a string starting at (r, c), overwriting."""
        for i, ch in enumerate(text):
            self._put(r, c + i, ch)

    def _safe_puts(self, r: int, c: int, text: str) -> None:
        """Write string only into empty (space) cells."""
        for i, ch in enumerate(text):
            cc = c + i
            if 0 <= r < self.rows and 0 <= cc < self.cols and self.grid[r][cc] == " ":
                self.grid[r][cc] = ch

    # ── height helpers ────────────────────────────────────────────────────

    @staticmethod
    def _pun_height(g: CMOSGatePlacement) -> int:
        """Height (rows) of a pull-up network."""
        if g.pullup_topology == "parallel":
            return 8
        if g.pullup_topology == "parallel_series":
            return 4 * max(len(ch) for ch in g.pullup_chains) + 4
        return 2 + 4 * len(g.pullup_mos)

    @staticmethod
    def _pdn_height(g: CMOSGatePlacement) -> int:
        """Height (rows) of a pull-down network."""
        if g.pulldown_topology == "parallel":
            return 8
        if g.pulldown_topology == "parallel_series":
            return 4 * max(len(ch) for ch in g.pulldown_chains) + 4
        return 4 * len(g.pulldown_mos) + 2

    # ── primitive drawing helpers ──────────────────────────────────────────

    def _draw_arm(self, r: int, gx: int, wc: int) -> None:
        """Draw channel arm:  ``||---+``"""
        self._put(r, gx, "|")
        self._put(r, gx + 1, "|")
        for c in range(gx + 2, wc):
            self._put(r, c, "-")
        self._put(r, wc, "+")

    def _draw_vwire(self, col: int, r1: int, r2: int) -> None:
        for r in range(r1, r2 + 1):
            if 0 <= r < self.rows and 0 <= col < self.cols:
                cur = self.grid[r][col]
                self._put(r, col, "+" if cur == "-" else "|" if cur in " |" else cur)

    def _draw_hwire(self, row: int, c1: int, c2: int) -> None:
        for c in range(c1, c2 + 1):
            if 0 <= row < self.rows and 0 <= c < self.cols:
                cur = self.grid[row][c]
                self._put(row, c, "+" if cur == "|" else "-" if cur in " -" else cur)

    def _draw_mos_gate_wire(
        self, row: int, gx: int, wc: int, mos: MOSFET,
        is_pmos: bool, label_name: bool = True,
    ) -> None:
        """Draw gate input wire and optional name label for one MOSFET."""
        gate = mos.gate
        type_str = "PMOS" if is_pmos else "NMOS"

        gate_end = gx - 1 if is_pmos else gx

        gate_start = gate_end - 2 - len(gate)
        if gate_start < 0:
            gate_start = 0

        self._puts(row, gate_start, gate)
        wire_begin = gate_start + len(gate) + 1

        # Track gate input position for inter-gate wiring
        self._input_pos[gate].append((row, wire_begin, self._gate_id))

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
        """Draw a complete CMOS gate."""
        PS = self.PARALLEL_SPACING
        wc_mid = g.wc_mid
        r = self.BASE_ROW

        def spread_wcs(n: int) -> List[int]:
            return [wc_mid + int((i - (n - 1) / 2) * PS) for i in range(n)]

        # --- Upper network (pull-up PMOS) ---
        if g.pullup_topology == "parallel":
            r = self._draw_upper_parallel(
                r, spread_wcs(len(g.pullup_mos)), g.pullup_mos, g.supply_net, wc_mid)
        elif g.pullup_topology == "parallel_series":
            r = self._draw_upper_parallel_series(
                r, spread_wcs(len(g.pullup_chains)), g.pullup_chains, g.supply_net, wc_mid)
        else:
            r = self._draw_upper_series(r, wc_mid, g.pullup_mos, g.supply_net)

        # Extend PUN to the global junction row (aligns PUN/PDN boundary)
        if r < self._junction_row:
            self._draw_vwire(wc_mid, r, self._junction_row - 1)
            r = self._junction_row

        # --- Output junction ---
        self._put(r, wc_mid, "|")
        r += 1
        self._put(r, wc_mid, "+")
        out_end = wc_mid + 10
        self._draw_hwire(r, wc_mid + 1, out_end)
        self._puts(r, out_end + 2, g.output_net)
        self._output_pos[g.output_net] = (r, out_end, self._gate_id)
        r += 1
        self._put(r, wc_mid, "|")
        r += 1

        # --- Lower network (pull-down NMOS) ---
        if g.pulldown_topology == "parallel":
            self._draw_lower_parallel(
                r, spread_wcs(len(g.pulldown_mos)), g.pulldown_mos, g.ground_net, wc_mid)
        elif g.pulldown_topology == "parallel_series":
            self._draw_lower_parallel_series(
                r, spread_wcs(len(g.pulldown_chains)), g.pulldown_chains, g.ground_net, wc_mid)
        else:
            self._draw_lower_series(r, wc_mid, g.pulldown_mos, g.ground_net)

    # ── upper-network helpers (PMOS) ──────────────────────────────────────

    def _draw_upper_parallel(self, start_row, wc_list, mos_list, supply, wc_mid):
        r = start_row

        for wc in wc_list:
            self._safe_puts(r, wc - len(supply) // 2, supply)
        r += 1

        for wc in wc_list:
            self._draw_vwire(wc, r, r + 1)
        r += 2

        arm_top, gate_r, arm_bot = r, r + 1, r + 2
        for wc, mos in zip(wc_list, mos_list):
            gx = wc - 5
            self._draw_arm(arm_top, gx, wc)
            self._safe_puts(arm_top, wc + 3, f"{mos.name} PMOS")
            self._draw_mos_gate_wire(gate_r, gx, wc, mos, is_pmos=True, label_name=False)
            self._draw_arm(arm_bot, gx, wc)
        r += 3

        for wc in wc_list:
            self._put(r, wc, "|")
        r += 1

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

    def _draw_upper_series(self, start_row, wc, mos_list, supply):
        r = start_row
        gx = wc - 5

        self._safe_puts(r, wc - len(supply) // 2, supply)
        r += 1
        self._draw_vwire(wc, r, r + 1)
        r += 2

        ordered = list(reversed(mos_list))
        for i, mos in enumerate(ordered):
            self._draw_arm(r, gx, wc)
            self._draw_mos_gate_wire(r + 1, gx, wc, mos, is_pmos=True)
            self._draw_arm(r + 2, gx, wc)
            r += 3
            if i < len(ordered) - 1:
                int_net = mos.drain
                self._put(r, wc, "|")
                self._safe_puts(r, wc + 3, int_net)
                r += 1

        return r

    def _draw_upper_parallel_series(self, start_row, wc_list, chains, supply, wc_mid):
        """Draw parallel series chains for PMOS pull-up."""
        r = start_row
        max_clen = max(len(ch) for ch in chains)

        # Supply labels
        for wc in wc_list:
            self._safe_puts(r, wc - len(supply) // 2, supply)
        r += 1

        # Vertical wires from supply
        for wc in wc_list:
            self._draw_vwire(wc, r, r + 1)
        r += 2

        chain_start = r
        # Draw each chain as a vertical series stack
        for wc, chain in zip(wc_list, chains):
            cr = chain_start
            gx = wc - 5
            ordered = list(reversed(chain))  # supply-side first
            for i, mos in enumerate(ordered):
                self._draw_arm(cr, gx, wc)
                self._safe_puts(cr, wc + 3, f"{mos.name} PMOS")
                self._draw_mos_gate_wire(cr + 1, gx, wc, mos, is_pmos=True, label_name=False)
                self._draw_arm(cr + 2, gx, wc)
                cr += 3
                if i < len(ordered) - 1:
                    int_net = mos.drain
                    self._put(cr, wc, "|")
                    self._safe_puts(cr, wc + 3, int_net)
                    cr += 1

        # Compute where the longest chain ends
        max_end = chain_start + 4 * max_clen - 1

        # Extend shorter chains with vertical wires
        for wc, chain in zip(wc_list, chains):
            chain_end = chain_start + 4 * len(chain) - 1
            if chain_end < max_end:
                self._draw_vwire(wc, chain_end, max_end - 1)

        r = max_end
        # Wire row below chains
        for wc in wc_list:
            self._put(r, wc, "|")
        r += 1

        # Horizontal bus connecting all chains
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

    # ── lower-network helpers (NMOS) ──────────────────────────────────────

    def _draw_lower_series(self, start_row, wc, mos_list, ground):
        r = start_row
        gx = wc - 5

        for i, mos in enumerate(mos_list):
            self._draw_arm(r, gx, wc)
            self._draw_mos_gate_wire(r + 1, gx, wc, mos, is_pmos=False)
            self._draw_arm(r + 2, gx, wc)
            r += 3
            if i < len(mos_list) - 1:
                int_net = mos.source
                self._put(r, wc, "|")
                self._safe_puts(r, wc + 3, int_net)
                r += 1

        self._draw_vwire(wc, r, r + 1)
        r += 2
        self._safe_puts(r, wc - len(ground) // 2, ground)
        return r + 1

    def _draw_lower_parallel(self, start_row, wc_list, mos_list, ground, wc_mid):
        r = start_row

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

        for wc in wc_list:
            self._put(r, wc, "|")
        r += 1

        arm_top, gate_r, arm_bot = r, r + 1, r + 2
        for wc, mos in zip(wc_list, mos_list):
            gx = wc - 5
            self._draw_arm(arm_top, gx, wc)
            self._safe_puts(arm_top, wc + 3, f"{mos.name} NMOS")
            self._draw_mos_gate_wire(gate_r, gx, wc, mos, is_pmos=False, label_name=False)
            self._draw_arm(arm_bot, gx, wc)
        r += 3

        for wc in wc_list:
            self._draw_vwire(wc, r, r + 1)
        r += 2

        for wc in wc_list:
            self._safe_puts(r, wc - len(ground) // 2, ground)
        return r + 1

    def _draw_lower_parallel_series(self, start_row, wc_list, chains, ground, wc_mid):
        """Draw parallel series chains for NMOS pull-down."""
        r = start_row
        max_clen = max(len(ch) for ch in chains)

        # Horizontal bus connecting all chains at top
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

        # Wire row above chains
        for wc in wc_list:
            self._put(r, wc, "|")
        r += 1

        chain_start = r
        # Draw each chain as a vertical series stack
        for wc, chain in zip(wc_list, chains):
            cr = chain_start
            gx = wc - 5
            for i, mos in enumerate(chain):
                self._draw_arm(cr, gx, wc)
                self._safe_puts(cr, wc + 3, f"{mos.name} NMOS")
                self._draw_mos_gate_wire(cr + 1, gx, wc, mos, is_pmos=False, label_name=False)
                self._draw_arm(cr + 2, gx, wc)
                cr += 3
                if i < len(chain) - 1:
                    int_net = mos.source
                    self._put(cr, wc, "|")
                    self._safe_puts(cr, wc + 3, int_net)
                    cr += 1

        # Compute where the longest chain ends
        max_end = chain_start + 4 * max_clen - 1

        # Extend shorter chains with vertical wires
        for wc, chain in zip(wc_list, chains):
            chain_end = chain_start + 4 * len(chain) - 1
            if chain_end < max_end:
                self._draw_vwire(wc, chain_end, max_end - 1)

        r = max_end
        # Vertical wires to ground
        for wc in wc_list:
            self._draw_vwire(wc, r, r + 1)
        r += 2

        # Ground labels
        for wc in wc_list:
            self._safe_puts(r, wc - len(ground) // 2, ground)
        return r + 1

    # ── single MOSFET drawing ─────────────────────────────────────────────

    def _draw_single_mos(self, g: SingleMOSPlacement) -> None:
        wc, mos, B = g.wc, g.mos, self.BASE_ROW
        is_pmos = mos.mos_type == MOSType.PMOS
        if is_pmos:
            top_net, bot_net, _type_str = mos.source, mos.drain, "PMOS"
        elif mos.mos_type == MOSType.NMOS:
            top_net, bot_net, _type_str = mos.drain, mos.source, "NMOS"
        else:
            top_net, bot_net, _type_str = mos.drain, mos.source, "FET"

        gx = wc - 5
        self._safe_puts(B, wc - len(top_net) // 2, top_net)
        self._draw_vwire(wc, B + 1, B + 2)
        self._draw_arm(B + 3, gx, wc)
        self._draw_mos_gate_wire(B + 4, gx, wc, mos, is_pmos)
        self._draw_arm(B + 5, gx, wc)
        self._draw_vwire(wc, B + 6, B + 7)
        self._safe_puts(B + 8, wc - len(bot_net) // 2, bot_net)

    # ── generic component drawing ─────────────────────────────────────────

    def _draw_generic(self, g: GenericPlacement) -> None:
        wc, comp, B = g.wc, g.comp, self.BASE_ROW

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

    # ── grid → string ─────────────────────────────────────────────────────

    def _grid_to_string(self) -> str:
        lines = ["" .join(row).rstrip() for row in self.grid]
        # Trim trailing/leading blank lines
        while lines and not lines[-1].strip():
            lines.pop()
        while len(lines) > 1 and not lines[0].strip() and not lines[1].strip():
            lines.pop(0)
        return "\n".join(lines)

    # ── inter-gate wiring ─────────────────────────────────────────────

    def _draw_interconnects(self) -> None:
        """Draw connecting wires between gate outputs and inputs across groups."""
        for net, (r_out, c_end, gid_out) in self._output_pos.items():
            # Only connect to inputs belonging to DIFFERENT gates
            inputs = [(r, c, gid) for r, c, gid in self._input_pos.get(net, [])
                      if gid != gid_out]
            if not inputs:
                continue

            # Find nearest input (closest column to the output)
            nearest = min(inputs, key=lambda x: x[1])
            nr, nc = nearest[0], nearest[1]

            # Routing column: midpoint of the gap between output label and input label
            c_route = (c_end + nc) // 2
            c_route = max(c_route, c_end + 2)

            if c_route >= self.cols:
                continue

            min_r, max_r = min(r_out, nr), max(r_out, nr)

            # Extend output wire to routing column (safe: only fill spaces)
            for c in range(c_end + 1, c_route + 1):
                if 0 <= c < self.cols and self.grid[r_out][c] == " ":
                    self._put(r_out, c, "-")
            self._put(r_out, c_route, "+")

            # Vertical bus from output row to nearest input row (safe)
            for r in range(min_r, max_r + 1):
                if 0 <= r < self.rows and 0 <= c_route < self.cols:
                    cur = self.grid[r][c_route]
                    if cur == " ":
                        self._put(r, c_route, "|")
                    elif cur == "-":
                        self._put(r, c_route, "+")
            self._put(r_out, c_route, "+")

            # Horizontal connector from routing column to nearest input (safe)
            for c in range(c_route + 1, nc):
                if 0 <= c < self.cols and self.grid[nr][c] == " ":
                    self._put(nr, c, "-")

            # Junction at input row / routing column
            if 0 <= nr < self.rows and 0 <= c_route < self.cols:
                self._put(nr, c_route, "+")
