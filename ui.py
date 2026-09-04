"""
Interactive console for the village economic simulation.

Run with:  python ui.py

Design stance (lessons from earlier diagnostic prototype):
  The previous UI failed because it told the player WHAT happened, never WHY.
  This rewrite makes cause-and-effect visible: every panel either shows a
  primitive of the sim or explains how a derived number was computed.

Top-line status cards (Money / Stamina / Wood / Food / Bounty / Flag) so the
key state is always in your eye. Below: an AIC panel that names its own
reasoning and a market BOOK panel showing the actual top bid / top ask, so
you can tell why your order did or didn't clear. Below: village snapshot.
Below: action + order entry. Below: chart (price, village reserve, your $).
Below: "Last day" panel listing every concrete event that happened.
"""
from __future__ import annotations

import tkinter as tk
from collections import Counter
from tkinter import ttk

from agents import GatherAction, HumanStrategy, Order
from config import Config, Resource
from world import World


# Palette
BG       = "#161819"
PANEL    = "#212427"
PANEL_HI = "#2a2f33"
TXT      = "#dde2e6"
TXT_DIM  = "#9aa3aa"
ACCENT   = "#f0c060"
GOOD     = "#7ec07e"
BAD      = "#e07474"
WARN     = "#e0a040"
INFO     = "#7ba6e0"
BTN      = "#3a5a8a"
BTN_GO   = "#3a7a3a"
BTN_W    = "#a05030"


# ---------- helper widgets ----------

def card(parent, title, init_value="", value_color=TXT, width=14):
    """A status card: small title above a big value."""
    frame = tk.Frame(parent, bg=PANEL_HI, bd=1, relief=tk.SOLID, padx=10, pady=6)
    tk.Label(frame, text=title, bg=PANEL_HI, fg=TXT_DIM,
             font=("Segoe UI", 8), anchor="w").pack(fill=tk.X)
    val = tk.Label(frame, text=init_value, bg=PANEL_HI, fg=value_color,
                   font=("Segoe UI", 13, "bold"), anchor="w", width=width)
    val.pack(fill=tk.X)
    return frame, val


def section(parent, title, expand=False):
    frame = tk.LabelFrame(parent, text=title, bg=PANEL, fg=ACCENT,
                          font=("Segoe UI", 10, "bold"), bd=1, relief=tk.SOLID,
                          padx=8, pady=6)
    frame.pack(fill=tk.BOTH if expand else tk.X, padx=8, pady=4, expand=expand)
    return frame


def info_label(parent):
    lbl = tk.Label(parent, text="", bg=PANEL, fg=TXT,
                   font=("Consolas", 10), justify=tk.LEFT, anchor="nw")
    lbl.pack(fill=tk.BOTH, expand=True)
    return lbl


# ---------- main UI ----------

class GameUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Village Sim — Player Console")
        root.geometry("1100x900")
        root.configure(bg=BG)

        self.cfg = Config()
        self.strategy = HumanStrategy()
        self.world = World(self.cfg, player_strategy=self.strategy)
        self.day = 0
        self.queued_actions: list = []
        self.queued_orders: list = []
        self.log_lines: list[str] = []
        # history for the chart
        self.h_day:       list[int]   = []
        self.h_wood_px:   list[float] = []
        self.h_village_w: list[float] = []
        self.h_money:     list[float] = []
        self.h_bounty:    list[float] = []

        self.world.begin_day(0)
        self._build_widgets()
        self._refresh()

    # =====================================================================
    # widget construction
    # =====================================================================
    def _build_widgets(self):
        # ----- header -----
        hdr = tk.Frame(self.root, bg=PANEL, pady=6)
        hdr.pack(fill=tk.X)
        self.hdr_title = tk.Label(hdr, bg=PANEL, fg=ACCENT,
                                   font=("Segoe UI", 15, "bold"))
        self.hdr_title.pack()
        self.hdr_sub = tk.Label(hdr, bg=PANEL, fg=TXT_DIM, font=("Segoe UI", 9))
        self.hdr_sub.pack()

        # ----- status card row -----
        cards = tk.Frame(self.root, bg=BG)
        cards.pack(fill=tk.X, padx=8, pady=6)
        for i in range(6):
            cards.grid_columnconfigure(i, weight=1)
        (f0, self.card_money) = card(cards, "MONEY",       width=10)
        (f1, self.card_stam)  = card(cards, "STAMINA",     width=10)
        (f2, self.card_wood)  = card(cards, "WOOD",        width=10)
        (f3, self.card_food)  = card(cards, "FOOD",        width=10)
        (f4, self.card_fair)  = card(cards, "WOOD FAIR/$", width=10)
        (f5, self.card_flag)  = card(cards, "FLAG",        width=10)
        for i, f in enumerate((f0, f1, f2, f3, f4, f5)):
            f.grid(row=0, column=i, sticky="ew", padx=3)

        # ----- AIC | Market book (two columns) -----
        twocol = tk.Frame(self.root, bg=BG)
        twocol.pack(fill=tk.X, padx=8, pady=4)
        twocol.grid_columnconfigure(0, weight=1, uniform="c")
        twocol.grid_columnconfigure(1, weight=1, uniform="c")

        aic_box = tk.LabelFrame(twocol, text="AI ACCOUNTANT", bg=PANEL, fg=ACCENT,
                                font=("Segoe UI", 10, "bold"), bd=1, relief=tk.SOLID,
                                padx=10, pady=6)
        aic_box.grid(row=0, column=0, sticky="nsew", padx=4, pady=2)
        self.aic_label = info_label(aic_box)

        book_box = tk.LabelFrame(twocol, text="MARKET BOOK  (yesterday's clearing)",
                                  bg=PANEL, fg=ACCENT,
                                  font=("Segoe UI", 10, "bold"), bd=1, relief=tk.SOLID,
                                  padx=10, pady=6)
        book_box.grid(row=0, column=1, sticky="nsew", padx=4, pady=2)
        self.book_label = info_label(book_box)

        # ----- Village snapshot -----
        vil = section(self.root, "VILLAGE  (12 NPCs)")
        self.village_label = info_label(vil)

        # ----- Actions -----
        act = section(self.root, "ACTIONS")
        btn_row = tk.Frame(act, bg=PANEL)
        btn_row.pack(anchor="w")
        self.btn_wood = tk.Button(btn_row, text="Gather Wood", bg=BTN, fg="white",
                                   width=14, font=("Segoe UI", 10, "bold"),
                                   command=self._action_wood)
        self.btn_wood.grid(row=0, column=0, padx=3)
        self.btn_food = tk.Button(btn_row, text="Gather Food", bg=BTN, fg="white",
                                   width=14, font=("Segoe UI", 10, "bold"),
                                   command=self._action_food)
        self.btn_food.grid(row=0, column=1, padx=3)
        tk.Button(btn_row, text="Clear queue", bg=BTN_W, fg="white", width=12,
                  command=self._clear_actions).grid(row=0, column=2, padx=3)
        self.queue_label = tk.Label(act, bg=PANEL, fg=TXT,
                                     font=("Consolas", 10), anchor="w", justify=tk.LEFT)
        self.queue_label.pack(fill=tk.X, pady=(4, 0))

        # ----- Orders -----
        orders = section(self.root, "ORDERS")
        row = tk.Frame(orders, bg=PANEL)
        row.pack(anchor="w")
        tk.Label(row, text="Side", bg=PANEL, fg=TXT_DIM).grid(row=0, column=0)
        self.side_var = tk.StringVar(value="sell")
        ttk.Combobox(row, textvariable=self.side_var, values=["sell", "buy"],
                     width=5, state="readonly").grid(row=0, column=1, padx=4)
        tk.Label(row, text="Resource", bg=PANEL, fg=TXT_DIM).grid(row=0, column=2)
        self.res_var = tk.StringVar(value="wood")
        ttk.Combobox(row, textvariable=self.res_var, values=["wood", "food"],
                     width=5, state="readonly").grid(row=0, column=3, padx=4)
        tk.Label(row, text="Qty", bg=PANEL, fg=TXT_DIM).grid(row=0, column=4)
        self.qty_entry = tk.Entry(row, width=8, bg=PANEL_HI, fg=TXT, insertbackground=TXT)
        self.qty_entry.grid(row=0, column=5, padx=2)
        tk.Label(row, text="Price", bg=PANEL, fg=TXT_DIM).grid(row=0, column=6)
        self.price_entry = tk.Entry(row, width=8, bg=PANEL_HI, fg=TXT, insertbackground=TXT)
        self.price_entry.grid(row=0, column=7, padx=2)
        tk.Button(row, text="Post", bg=BTN, fg="white", width=8,
                  command=self._post_order).grid(row=0, column=8, padx=4)
        tk.Button(row, text="Clear", bg=BTN_W, fg="white", width=8,
                  command=self._clear_orders).grid(row=0, column=9, padx=2)

        quick = tk.Frame(orders, bg=PANEL)
        quick.pack(anchor="w", pady=(4, 0))
        tk.Button(quick, text="Sell ALL wood @ top bid", bg=BTN, fg="white",
                  command=lambda: self._quick_sell_all(Resource.WOOD)).grid(row=0, column=0, padx=3)
        tk.Button(quick, text="Sell ALL food @ top bid", bg=BTN, fg="white",
                  command=lambda: self._quick_sell_all(Resource.FOOD)).grid(row=0, column=1, padx=3)
        tk.Button(quick, text="Buy 5 wood @ top ask", bg=BTN, fg="white",
                  command=lambda: self._quick_buy(Resource.WOOD, 5)).grid(row=0, column=2, padx=3)
        tk.Button(quick, text="Buy 5 food @ top ask", bg=BTN, fg="white",
                  command=lambda: self._quick_buy(Resource.FOOD, 5)).grid(row=0, column=3, padx=3)

        self.orders_label = tk.Label(orders, bg=PANEL, fg=TXT,
                                      font=("Consolas", 10), anchor="w", justify=tk.LEFT)
        self.orders_label.pack(fill=tk.X, pady=(4, 0))

        # ----- Advance -----
        adv = tk.Frame(self.root, bg=BG)
        adv.pack(fill=tk.X, padx=8, pady=6)
        self.adv_btn = tk.Button(adv, text="▶  ADVANCE DAY  ▶",
                                  bg=BTN_GO, fg="white",
                                  font=("Segoe UI", 12, "bold"),
                                  command=self._advance_day)
        self.adv_btn.pack(side=tk.LEFT, padx=4)
        tk.Button(adv, text="Skip 10 (rest)", bg=BTN, fg="white",
                  command=lambda: self._auto_rest(10)).pack(side=tk.LEFT, padx=4)
        tk.Button(adv, text="Skip 30 (rest)", bg=BTN, fg="white",
                  command=lambda: self._auto_rest(30)).pack(side=tk.LEFT, padx=4)
        # Reset goes on the right so it's not next to Advance Day (avoid mis-clicks).
        tk.Button(adv, text="↻  RESET SIM", bg=BTN_W, fg="white",
                  font=("Segoe UI", 10, "bold"),
                  command=self._reset_simulation).pack(side=tk.RIGHT, padx=4)

        # ----- Chart -----
        chart_box = section(self.root, "TIMELINE  •  wood price (orange) • village wood (purple) • your $ (green) • bounty earned (yellow)")
        self.chart = tk.Canvas(chart_box, height=110, bg="#0c0d0e", highlightthickness=0)
        self.chart.pack(fill=tk.X)

        # ----- Last day -----
        log_box = section(self.root, "LAST DAY  /  HISTORY", expand=True)
        self.log_text = tk.Text(log_box, height=8, bg="#0c0d0e", fg=TXT,
                                 font=("Consolas", 9), bd=0)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # =====================================================================
    # state -> widgets
    # =====================================================================
    def _refresh(self):
        w = self.world
        p = w.player
        season = self.cfg.season_for_day(self.day)
        dis = self.cfg.day_in_season(self.day)
        ctx = w._player_ctx
        is_flagged = "PLAYER" in w.accountant.state.hoard_flags

        # ---- header ----
        self.hdr_title.config(text=f"Day {self.day + 1} / {self.cfg.total_days}    {season.value.upper()}    "
                                    f"day {dis + 1} of {self.cfg.season_length}")
        self.hdr_sub.config(text="The AIC observes the village. Villagers cannot see its bounty — you can.")

        # ---- status cards ----
        gather_queued = sum(1 for a in self.queued_actions if isinstance(a, GatherAction))
        stam_remain = max(0, int(p.daily_stamina) - gather_queued)
        wood_px = w.ref_price[Resource.WOOD]
        wood_fair = w.accountant.state.fair_price.get(
            Resource.WOOD, self.cfg.intrinsic_value[Resource.WOOD])
        # color the fair card by how far above market it is — that's the
        # opportunity signal: green if fair >> market (wood undervalued, buy/gather),
        # red if fair << market (wood overvalued, sell), white if roughly in line.
        gap = wood_fair - wood_px
        if gap > 0.5:
            fair_color = GOOD
        elif gap < -0.5:
            fair_color = BAD
        else:
            fair_color = TXT
        self.card_money.config(text=f"${p.money:,.0f}")
        self.card_stam .config(text=f"{stam_remain}/{int(p.daily_stamina)}",
                                fg=GOOD if stam_remain > 0 else WARN)
        self.card_wood .config(text=f"{p.qty(Resource.WOOD):.1f}")
        self.card_food .config(text=f"{p.qty(Resource.FOOD):.1f}")
        self.card_fair .config(text=f"${wood_fair:.2f}", fg=fair_color)
        self.card_flag .config(text="FLAGGED" if is_flagged else "clean",
                                fg=BAD if is_flagged else GOOD)

        # ---- AIC panel ----
        wood_y = p.expected_gather_yield(Resource.WOOD, ctx)
        food_y = p.expected_gather_yield(Resource.FOOD, ctx)
        deficit_w = w.accountant.state.predicted_deficit.get(Resource.WOOD, 0.0)
        deficit_f = w.accountant.state.predicted_deficit.get(Resource.FOOD, 0.0)
        fair_w = w.accountant.state.fair_price.get(Resource.WOOD, self.cfg.intrinsic_value[Resource.WOOD])
        fair_f = w.accountant.state.fair_price.get(Resource.FOOD, self.cfg.intrinsic_value[Resource.FOOD])
        intrinsic_w = self.cfg.intrinsic_value[Resource.WOOD]
        intrinsic_f = self.cfg.intrinsic_value[Resource.FOOD]
        food_px = w.ref_price[Resource.FOOD]

        def signal(market, fair):
            gap = fair - market
            if gap > 0.5:
                return f"market UNDERVALUED by ${gap:.2f} → consider gathering/buying"
            if gap < -0.5:
                return f"market OVERVALUED by ${-gap:.2f} → consider selling"
            return "market roughly in line with fair value"

        aic_text = (
            f"AIC FAIR-VALUE ESTIMATE (player-only signal):\n"
            f"   wood   fair ${fair_w:5.2f}   market ${wood_px:5.2f}   ({fair_w/intrinsic_w:.2f}× intrinsic)\n"
            f"          {signal(wood_px, fair_w)}\n"
            f"   food   fair ${fair_f:5.2f}   market ${food_px:5.2f}   ({fair_f/intrinsic_f:.2f}× intrinsic)\n"
            f"          {signal(food_px, fair_f)}\n"
            f"\n"
            f"REASONING  (fair = intrinsic × scarcity premium):\n"
            f"   wood: forecast deficit over next {self.cfg.accountant_horizon}d = {deficit_w:+.1f} units\n"
            f"   food: forecast deficit over next {self.cfg.accountant_horizon}d = {deficit_f:+.1f} units\n"
            f"   AIC's capacity estimate is pessimistic (×{self.cfg.accountant_pessimism:g}) — it doesn't trust\n"
            f"   the village to fix scarcity on its own.\n"
            f"\n"
            f"STABILISATION PAYMENTS (realized contribution ledger):\n"
            f"   paid you so far: ${p.bonus_earned:.2f}    today: ${p.bonus_earned - w._player_bonus_at_day_start:.2f}\n"
            f"\n"
            f"PER-GATHER YIELD (you):  wood ≈ {wood_y:.1f}    food ≈ {food_y:.1f}"
        )
        if is_flagged:
            stock = p.qty(Resource.WOOD)
            sales = w.accountant._sales_ema.get("PLAYER", 0.0)
            offers = w.accountant._honest_offer_ema.get("PLAYER", 0.0)
            aic_text += (
                f"\n\n"
                f"⚠ HOARDING FLAG ACTIVE\n"
                f"   your wood stock:           {stock:.1f}\n"
                f"   recent sales (EMA):        {sales:.2f} /day\n"
                f"   honest offers (EMA):       {offers:.2f} /day\n"
                f"   threshold:                 stock>{self.cfg.hoard_stock_threshold:.0f}\n"
                f"   need to post sell orders at <={1.5:.1f}×ref price to avoid the flag.\n"
                f"   fee being levied: ${(stock - self.cfg.hoard_stock_threshold) * self.cfg.hoard_fee_rate:.2f}/day"
            )
        self.aic_label.config(text=aic_text)

        # ---- Market book (yesterday) ----
        self.book_label.config(text=self._market_book_text())

        # ---- Village snapshot ----
        villagers = [a for a in w.agents if not a.is_player and not a.is_market_maker]
        n = len(villagers)
        v_money = sum(a.money for a in villagers) / max(n, 1)
        v_wood = sum(a.qty(Resource.WOOD) for a in villagers)
        v_food = sum(a.qty(Resource.FOOD) for a in villagers)
        # how many villagers are "tight" on a resource (< 1 day reserve)?
        tight_w = sum(1 for a in villagers if a.qty(Resource.WOOD) < ctx.wood_need)
        tight_f = sum(1 for a in villagers if a.qty(Resource.FOOD) < ctx.food_need)
        fear_w  = sum(a.fear(Resource.WOOD) for a in villagers) / max(n, 1)
        broke   = sum(1 for a in villagers if a.money < 5)
        self.village_label.config(text=(
            f"  Wood  total {v_wood:>6.1f}   {tight_w} villager(s) with < 1d reserve    avg fear {fear_w:.2f}\n"
            f"  Food  total {v_food:>6.1f}   {tight_f} villager(s) with < 1d reserve\n"
            f"  Average villager money ${v_money:.2f}   ({broke} villager(s) effectively broke)"
        ))

        # ---- action queue ----
        cnt = Counter()
        for a in self.queued_actions:
            if isinstance(a, GatherAction):
                cnt[f"Gather {a.resource.value.title()}"] += 1
        qsum = ", ".join(f"{k}×{v}" for k, v in cnt.items()) or "(none — you'll rest)"
        self.queue_label.config(text=f"  Queued: {qsum}    Stamina to use: {stam_remain}")

        # ---- orders queue ----
        if not self.queued_orders:
            self.orders_label.config(text="  Posted: (none)")
        else:
            lines = []
            for o in self.queued_orders:
                lines.append(f"  {o.side.upper():4} {o.qty:>5.1f} {o.resource.value:<4} @ ${o.price:>5.2f}")
            self.orders_label.config(text="  Posted:\n" + "\n".join(lines))

        # ---- buttons ----
        can_gather = stam_remain > 0
        self.btn_wood.config(state=tk.NORMAL if can_gather else tk.DISABLED)
        self.btn_food.config(state=tk.NORMAL if can_gather else tk.DISABLED)
        if self.day >= self.cfg.total_days:
            self.adv_btn.config(state=tk.DISABLED, text="── GAME OVER ──", bg=PANEL)

        # ---- log + chart ----
        self.log_text.delete("1.0", tk.END)
        for line in self.log_lines[-300:]:
            self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self._draw_chart()

    def _market_book_text(self) -> str:
        """Show top 3 bids + top 3 asks per resource from yesterday's book."""
        out = []
        floor_w = self.cfg.intrinsic_value[Resource.WOOD] * self.cfg.price_floor_mult
        floor_f = self.cfg.intrinsic_value[Resource.FOOD] * self.cfg.price_floor_mult
        for r in (Resource.WOOD, Resource.FOOD):
            orders = self.world.last_orders.get(r, [])
            clearing = self.world.last_clearings.get(r)
            bids = sorted([o for o in orders if o.side == "buy"], key=lambda o: -o.price)[:3]
            asks = sorted([o for o in orders if o.side == "sell"], key=lambda o: o.price)[:3]
            fair = self.world.accountant.state.fair_price.get(r, self.cfg.intrinsic_value[r])
            market = self.world.ref_price[r]
            floor = floor_w if r == Resource.WOOD else floor_f
            tag = ""
            if fair > market + 0.5:    tag = "  ←  market undervalued"
            elif fair < market - 0.5:  tag = "  ←  market overvalued"
            out.append(f"{r.value.upper():>4}   market ${market:5.2f}   fair ${fair:5.2f}   floor ${floor:.2f}{tag}")
            if clearing and clearing.volume > 1e-6:
                out.append(f"  yesterday: {clearing.volume:.1f} units cleared @ ${clearing.price:.2f}")
            else:
                out.append("  yesterday: no trades cleared")
            if bids:
                out.append("  top BIDS  (what someone will pay):")
                for b in bids:
                    if b.agent_id == "PLAYER":
                        name = "YOU"
                    elif self.world.by_id.get(b.agent_id) and self.world.by_id[b.agent_id].is_market_maker:
                        name = "MARKET"
                    else:
                        name = b.agent_id
                    out.append(f"    {name:>6}  {b.qty:>5.1f} @ ${b.price:>5.2f}")
            else:
                out.append("  top BIDS:  (no one posted a buy order)")
            if asks:
                out.append("  top ASKS  (what someone will sell for):")
                for a in asks:
                    if a.agent_id == "PLAYER":
                        name = "YOU"
                    elif self.world.by_id.get(a.agent_id) and self.world.by_id[a.agent_id].is_market_maker:
                        name = "MARKET"
                    else:
                        name = a.agent_id
                    out.append(f"    {name:>6}  {a.qty:>5.1f} @ ${a.price:>5.2f}")
            else:
                out.append("  top ASKS:  (no one posted a sell order)")
            out.append("")
        return "\n".join(out).rstrip()

    def _draw_chart(self):
        c = self.chart
        c.delete("all")
        w = max(int(c.winfo_width()), 200)
        h = max(int(c.winfo_height()), 80)
        if len(self.h_day) < 2:
            return
        def line(series, color, scale=None):
            mx = max(scale, max(series), 0.1) if scale else max(max(series), 0.1)
            pts = []
            n = len(series)
            for i, v in enumerate(series):
                x = 4 + (w - 8) * i / max(n - 1, 1)
                y = h - 4 - (h - 8) * (v / mx)
                pts.extend([x, y])
            if len(pts) >= 4:
                c.create_line(*pts, fill=color, width=2)
            return mx

        mx_px = line(self.h_wood_px,  "#f0a040")
        mx_v  = line(self.h_village_w, "#b070d0")
        mx_m  = line(self.h_money,    "#7ec07e")
        mx_b  = line(self.h_bounty,   "#f0e040")
        c.create_text(8, 10, anchor="w",
                      text=f"wood px ${mx_px:.2f}", fill="#f0a040",
                      font=("Consolas", 8))
        c.create_text(8, 24, anchor="w",
                      text=f"village wood {mx_v:.0f}", fill="#b070d0",
                      font=("Consolas", 8))
        c.create_text(8, 38, anchor="w",
                      text=f"$ {mx_m:.0f}", fill="#7ec07e",
                      font=("Consolas", 8))
        c.create_text(8, 52, anchor="w",
                      text=f"bounty earned ${mx_b:.2f}", fill="#f0e040",
                      font=("Consolas", 8))

    # =====================================================================
    # callbacks
    # =====================================================================
    def _action_wood(self):
        self.queued_actions.append(GatherAction(Resource.WOOD)); self._refresh()

    def _action_food(self):
        self.queued_actions.append(GatherAction(Resource.FOOD)); self._refresh()

    def _clear_actions(self):
        self.queued_actions = []; self._refresh()

    def _post_order(self):
        try:
            qty = float(self.qty_entry.get())
            price = float(self.price_entry.get())
        except ValueError:
            return
        if qty <= 0 or price <= 0:
            return
        side = self.side_var.get()
        res = Resource.WOOD if self.res_var.get() == "wood" else Resource.FOOD
        self.queued_orders.append(Order("PLAYER", res, side, qty, price))
        self.qty_entry.delete(0, tk.END); self.price_entry.delete(0, tk.END)
        self._refresh()

    def _clear_orders(self):
        self.queued_orders = []; self._refresh()

    def _quick_sell_all(self, r: Resource):
        """
        Sell every unit above 1-day reserve at a price guaranteed to clear:
        undercut the cheapest existing ask. Floored at production cost so you
        never give it away. If you want a higher price, post the order manually.
        """
        p = self.world.player
        keep = self.world._player_ctx.wood_need if r == Resource.WOOD else self.world._player_ctx.food_need
        sellable = max(0.0, p.qty(r) - keep)
        if sellable < 0.1:
            self.log_lines.append(
                f"  Quick-sell {r.value}: nothing to sell (you have {p.qty(r):.1f}, keeping {keep:.1f}).")
            self._refresh()
            return
        last = self.world.last_orders.get(r, [])
        asks = sorted([o.price for o in last if o.side == "sell"])
        bids = sorted([o.price for o in last if o.side == "buy"], reverse=True)
        floor = self.cfg.intrinsic_value[r] * self.cfg.price_floor_mult
        if asks:
            price = max(floor, asks[0] - 0.01)        # undercut the cheapest seller
        elif bids:
            price = max(floor, bids[0])               # meet the top bid
        else:
            price = max(floor, self.world.ref_price[r] * 0.9)
        self.queued_orders.append(Order("PLAYER", r, "sell", sellable, price))
        self._refresh()

    def _quick_buy(self, r: Resource, qty: float):
        """Buy at a price guaranteed to clear: outbid the highest existing buyer."""
        last = self.world.last_orders.get(r, [])
        bids = sorted([o.price for o in last if o.side == "buy"], reverse=True)
        asks = sorted([o.price for o in last if o.side == "sell"])
        if bids:
            price = bids[0] + 0.01                    # outbid the top buyer
        elif asks:
            price = asks[0]                           # meet the lowest ask
        else:
            price = self.world.ref_price[r] * 1.1
        self.queued_orders.append(Order("PLAYER", r, "buy", qty, price))
        self._refresh()

    # ---------- day advance ----------
    def _advance_day(self):
        if self.day >= self.cfg.total_days:
            return
        # commit decisions
        self.strategy.planned_actions = self.queued_actions[:]
        self.strategy.planned_orders = self.queued_orders[:]

        pre_money = self.world._player_money_at_day_start
        pre_bonus = self.world._player_bonus_at_day_start
        pre_wood = self.world.player.qty(Resource.WOOD)
        pre_food = self.world.player.qty(Resource.FOOD)

        # execute today
        self.world.execute_day()

        self._log_day(pre_money, pre_bonus, pre_wood, pre_food)
        self._record_history()

        self.day += 1
        if self.day < self.cfg.total_days:
            self.world.begin_day(self.day)
        self.queued_actions = []
        self.queued_orders = []
        self._refresh()

    def _log_day(self, pre_money, pre_bonus, pre_wood, pre_food):
        """Tell the player concretely what happened today."""
        w = self.world
        p = w.player
        season = self.cfg.season_for_day(self.day).value
        dm = p.money - pre_money
        db = p.bonus_earned - pre_bonus
        dw = p.qty(Resource.WOOD) - pre_wood
        df = p.qty(Resource.FOOD) - pre_food
        flag = "  [HOARDING-FLAGGED]" if "PLAYER" in w.accountant.state.hoard_flags else ""
        head = f"── Day {self.day + 1} ({season}) ──   Δ$ {dm:+.2f}  Δwood {dw:+.1f}  Δfood {df:+.1f}{flag}"
        self.log_lines.append(head)

        # gather actions executed
        gathers = [a for a in self.strategy.planned_actions if isinstance(a, GatherAction)] \
            if hasattr(self.strategy, "planned_actions") else []
        # (already drained by decide_actions, so use what we queued)
        wood_g = sum(1 for a in self.queued_actions if isinstance(a, GatherAction) and a.resource == Resource.WOOD)
        food_g = sum(1 for a in self.queued_actions if isinstance(a, GatherAction) and a.resource == Resource.FOOD)
        cap = int(p.daily_stamina)
        used = min(wood_g + food_g, cap)
        if used > 0:
            self.log_lines.append(f"   • gathered: wood ×{min(wood_g, cap)}, food ×{min(food_g, max(cap - wood_g, 0))}")
        elif self.queued_actions:
            self.log_lines.append(f"   • queued {len(self.queued_actions)} actions but stamina cap was {cap}")

        # market outcomes for the player
        for r in (Resource.WOOD, Resource.FOOD):
            posted = [o for o in self.queued_orders if o.resource == r]
            if not posted:
                continue
            clearing = w.last_clearings.get(r)
            cleared_for_me = 0.0
            if clearing:
                for t in clearing.trades:
                    if t.buyer_id == "PLAYER" or t.seller_id == "PLAYER":
                        cleared_for_me += t.qty
            for o in posted:
                if cleared_for_me > 0:
                    cp = clearing.price if clearing else 0
                    self.log_lines.append(
                        f"   • {o.side.upper()} {o.qty:.1f} {r.value} @ ${o.price:.2f}  →  cleared {cleared_for_me:.1f} @ ${cp:.2f}")
                else:
                    # explain why nothing cleared
                    book = w.last_orders.get(r, [])
                    if o.side == "sell":
                        bids = [b.price for b in book if b.side == "buy"]
                        if bids:
                            top = max(bids)
                            self.log_lines.append(
                                f"   - SELL {o.qty:.1f} {r.value} @ ${o.price:.2f}  ->  NO TRADE "
                                f"(highest bid was ${top:.2f})")
                        else:
                            self.log_lines.append(
                                f"   - SELL {o.qty:.1f} {r.value} @ ${o.price:.2f}  ->  NO TRADE "
                                f"(no one posted a buy order)")
                    else:
                        asks = [a.price for a in book if a.side == "sell"]
                        if asks:
                            low = min(asks)
                            self.log_lines.append(
                                f"   - BUY  {o.qty:.1f} {r.value} @ ${o.price:.2f}  ->  NO TRADE "
                                f"(lowest ask was ${low:.2f})")
                        else:
                            self.log_lines.append(
                                f"   - BUY  {o.qty:.1f} {r.value} @ ${o.price:.2f}  ->  NO TRADE "
                                f"(no one posted a sell order)")
                cleared_for_me = 0  # already reported the bundle

        # consumption + bounty
        own_unmet = w._per_agent_unmet.get("PLAYER", {})
        if own_unmet.get(Resource.WOOD, 0) > 0.01 or own_unmet.get(Resource.FOOD, 0) > 0.01:
            self.log_lines.append(
                f"   • YOU went short: wood {own_unmet.get(Resource.WOOD, 0):.1f}, food {own_unmet.get(Resource.FOOD, 0):.1f}")
        if db > 0.005:
            self.log_lines.append(f"   • AIC paid you ${db:.2f}  (bounty for realized contribution)")
        # village suffering today
        vu = w.village_unmet
        if vu[Resource.WOOD] > 0.1 or vu[Resource.FOOD] > 0.1:
            self.log_lines.append(
                f"   • VILLAGE SHORT today: wood {vu[Resource.WOOD]:.1f}, food {vu[Resource.FOOD]:.1f}")
        # hoarding fee tally
        if "PLAYER" in w.accountant.state.hoard_flags:
            stock = p.qty(Resource.WOOD)
            fee = max(0.0, (stock - self.cfg.hoard_stock_threshold) * self.cfg.hoard_fee_rate)
            if fee > 0.01:
                self.log_lines.append(f"   • AIC levied a hoarding fee: -${fee:.2f}")

    def _record_history(self):
        w = self.world
        villagers = [a for a in w.agents if not a.is_player and not a.is_market_maker]
        self.h_day.append(self.day)
        self.h_wood_px.append(w.ref_price[Resource.WOOD])
        self.h_village_w.append(sum(a.qty(Resource.WOOD) for a in villagers))
        self.h_money.append(w.player.money)
        self.h_bounty.append(w.player.bonus_earned)
        # cap so chart stays readable
        cap = 240
        if len(self.h_day) > cap:
            for s in (self.h_day, self.h_wood_px, self.h_village_w, self.h_money, self.h_bounty):
                del s[:-cap]

    def _reset_simulation(self):
        """Throw out the current sim and start over from day 0 with a fresh world."""
        self.strategy = HumanStrategy()
        self.world = World(self.cfg, player_strategy=self.strategy)
        self.day = 0
        self.queued_actions = []
        self.queued_orders = []
        self.log_lines = ["── SIMULATION RESET ──"]
        self.h_day.clear(); self.h_wood_px.clear()
        self.h_village_w.clear(); self.h_money.clear(); self.h_bounty.clear()
        self.world.begin_day(0)
        self.adv_btn.config(state=tk.NORMAL, text="▶  ADVANCE DAY  ▶", bg=BTN_GO)
        self._refresh()

    def _auto_rest(self, n):
        for _ in range(n):
            if self.day >= self.cfg.total_days:
                break
            self.strategy.planned_actions = []
            self.strategy.planned_orders = []
            self.world.execute_day()
            self._record_history()
            self.day += 1
            if self.day < self.cfg.total_days:
                self.world.begin_day(self.day)
        self.log_lines.append(f"── Auto-rested to day {self.day + 1} ──")
        self._refresh()


def main():
    root = tk.Tk()
    GameUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
