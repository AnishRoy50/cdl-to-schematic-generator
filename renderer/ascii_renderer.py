"""ASCII schematic renderer.

Consumes placement groups from the :mod:`~cdl_to_schematic.layout` package
and renders them onto a character grid with proper MOSFET transistor symbols.

Topology rendering styles
-------------------------
* **Parallel** transistors are drawn side-by-side with a horizontal
  drain/source bus connecting them.
* **Series** transistors are stacked vertically on a single wire column
  with intermediate-net labels between them.

MOSFET symbol::

         |
    ||---+          (channel arm)
  --||   |          (gate input; ``o`` prepended for PMOS)
    ||---+
         |
"""

from __future__ import annotations

from typing import List

from models import MOSFET, MOSType, SubcktInstance, Subckt
from layout.placements import (
    CMOSGatePlacement,
    SingleMOSPlacement,
    GenericPlacement,
)


class ASCIIRenderer:
    """Renders placement groups onto a character grid.

    Full CMOS NAND2 example::

              VDD               VDD
               |                 |
          ||---+ MP1 PMOS   ||---+ MP3 PMOS
      A --o||  |        B --o||  |
          ||---+            ||---+
               |                 |
               +--------+--------+
                        |
                        +---------- Z
                        |
                   ||---+
           A ------||   |  MN0 NMOS
                   ||---+
                        |  net7
                   ||---+
           B ------||   |  MN1 NMOS
                   ||---+
                        |
                       VSS
    """

    PARALLEL_SPACING = 24      # must match LayoutEngine
    BASE_ROW = 2               # top margin rows

    def __init__(self, groups: List, subckt: Subckt) -> None:
        self.groups = groups
        self.subckt = subckt
        self.grid: List[List[str]] = []
        self.rows = 0
        self.cols = 0

    # ── public ─────────────────────────────────────────────────────────────

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

    # ── grid helpers ───────────────────────────────────────────────────────

    def _compute_size(self) -> None:
        max_row = self.BASE_ROW
        max_col = 10
        PS = self.PARALLEL_SPACING

        for g in self.groups:
            if isinstance(g, CMOSGatePlacement):
                n_up = len(g.pullup_mos)
                n_dn = len(g.pulldown_mos)

                if g.pullup_topology == "parallel":
                    up_h = 8
                else:
                    up_h = 3 + 4 * n_up - 1

                out_h = 3

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

    # ── primitive drawing helpers ──────────────────────────────────────────

    def _draw_arm(self, r: int, gx: int, wc: int) -> None:
        """Draw channel arm:  ``||---+``"""
        self._put(r, gx, "|")
        self._put(r, gx + 1, "|")
        for c in range(gx + 2, wc):
            self._put(r, c, "-")
        self._put(r, wc, "+")

    def _draw_vwire(self, col: int, r1: int, r2: int) -> None:
        """Draw a vertical wire segment (``|``)."""
        for r in range(r1, r2 + 1):
            if 0 <= r < self.rows and 0 <= col < self.cols:
                cur = self.grid[r][col]
                if cur == "-":
                    self._put(r, col, "+")
                elif cur in (" ", "|"):
                    self._put(r, col, "|")

    def _draw_hwire(self, row: int, c1: int, c2: int) -> None:
        """Draw a horizontal wire segment (``-``)."""
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

        gate_end = gx - 1 if is_pmos else gx

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

    # ── upper-network helpers (PMOS) ──────────────────────────────────────

    def _draw_upper_parallel(
        self, start_row: int, wc_list: List[int],
        mos_list: List[MOSFET], supply: str, wc_mid: int,
    ) -> int:
        """Parallel PMOS pull-up: VDD at top, drain bus at bottom."""
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

    def _draw_upper_series(
        self, start_row: int, wc: int,
        mos_list: List[MOSFET], supply: str,
    ) -> int:
        """Series PMOS pull-up: VDD at top, output side at bottom."""
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

    # ── lower-network helpers (NMOS) ──────────────────────────────────────

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
                int_net = mos.source
                self._put(r, wc, "|")
                self._safe_puts(r, wc + 3, int_net)
                r += 1

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

    # ── single MOSFET drawing ─────────────────────────────────────────────

    def _draw_single_mos(self, g: SingleMOSPlacement) -> None:
        """Draw a standalone MOSFET (not part of a CMOS gate)."""
        wc = g.wc
        mos = g.mos
        B = self.BASE_ROW

        is_pmos = (mos.mos_type == MOSType.PMOS)
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

    # ── grid → string ─────────────────────────────────────────────────────

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
