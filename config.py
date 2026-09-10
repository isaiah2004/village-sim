"""
Central configuration for the village economic simulation.

Design stance (post-redesign): the AIC is an OBSERVER, not a planner.
  * Villagers ignore the AIC. They behave from their own beliefs/fears.
  * The AIC posts bounties that ONLY THE PLAYER can see -- the isekai
    information edge made mechanical: a privileged channel ordinary NPCs lack.
  * Crisis is real and has consequences. If the player doesn't act, the
    village suffers; the AIC merely measures it.
  * Belief-driven demand (panic-buying when shortage is recently felt) is the
    seam where the knowledge-gating system will later plug in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Resource(str, Enum):
    WOOD = "wood"       # fuel; consumed daily, much more in winter
    FOOD = "food"       # consumed daily, year round
    TOOL = "tool"       # capital good: boosts gather yield, built from wood
    WOODLOT = "woodlot" # capital good: a managed grove that YIELDS wood each day


# Consumable resources that deplete from reserves every day.
CONSUMABLES = (Resource.WOOD, Resource.FOOD)


class Season(str, Enum):
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"


SEASON_ORDER = (Season.SPRING, Season.SUMMER, Season.AUTUMN, Season.WINTER)


@dataclass
class Config:
    # ----- scenario (DESIGN.md "scenarios are DATA") -----
    # The named world archetype this config was built from. `scenario.make_config`
    # attaches the live Scenario object as `cfg.scenario` (a non-field attribute, so
    # persistence serializes only the name and the world reattaches by name on load).
    # Defaults to "frostpine" so a bare Config() is the historical baseline.
    scenario_name: str = "frostpine"

    # ----- time -----
    season_length: int = 30          # days per season
    years: float = 2.0               # how long to run

    # ----- population -----
    n_villagers: int = 12
    seed: int = 7

    # ----- daily consumption per agent -----
    food_per_day: float = 1.0
    # wood (heating) demand depends on season
    wood_per_day: dict = field(default_factory=lambda: {
        Season.SPRING: 0.45,
        Season.SUMMER: 0.3,
        Season.AUTUMN: 0.7,
        Season.WINTER: 2.0,          # heating spike: winter labor can't keep up alone
    })

    # ----- production -----
    # base yield from one gathering action, per resource
    base_yield: dict = field(default_factory=lambda: {
        Resource.WOOD: 2.0,
        Resource.FOOD: 2.5,          # food is comfortably producible -> wood is the scarce good
    })
    # season multiplier on gather yield (winter is hard: less daylight, frozen ground)
    season_yield_mult: dict = field(default_factory=lambda: {
        Season.SPRING: 1.1,
        Season.SUMMER: 1.2,
        Season.AUTUMN: 1.0,
        Season.WINTER: 0.6,
    })
    stamina_per_day: float = 2.0     # ~two gather actions per day
    effort_per_gather: float = 1.0

    # tools
    tool_yield_bonus: float = 0.6    # +60% gather yield when holding a tool
    tool_wood_cost: float = 4.0      # wood consumed to craft one tool
    tool_durability: int = 40        # gather-actions before a tool wears out
    tool_intrinsic_value: float = 30.0

    # ----- money / market -----
    start_money: float = 150.0
    intrinsic_value: dict = field(default_factory=lambda: {
        Resource.WOOD: 5.0,
        Resource.FOOD: 6.0,
        Resource.TOOL: 30.0,
        Resource.WOODLOT: 60.0,
    })
    price_smoothing: float = 0.4     # EMA factor toward the clearing price
    price_imbalance_k: float = 0.14  # how strongly price drifts on excess demand/supply
    # Floor at 40% of intrinsic ~= cost-of-production. Goods always command some
    # value even when nobody is currently bidding (you can still gather them at
    # this cost, so the market won't trade below it for long).
    price_floor_mult: float = 0.4
    price_cap_mult: float = 5.0      # price cap as a multiple of intrinsic

    # ----- effort / overproduction control -----
    effort_cost: float = 4.0         # money-equivalent cost of one gather action
    surplus_gather_cap: float = 2.0  # stop gathering surplus once reserve > target*this

    # ----- villager planning (deliberately myopic) -----
    villager_horizon: int = 4        # days of look-ahead; too short to prep for winter
    reserve_buffer_days: float = 3.0 # target reserve = horizon need * this/horizon
    surplus_sell_mult: float = 1.6   # sell stock above target*this
    critical_reserve_days: float = 1.0  # below this -> emergency / unmet-need risk

    # ----- belief / fear (villager scarcity perception) -----
    # Villagers don't see the AIC. They react to what they've EXPERIENCED:
    # personal shortages and (with smaller weight) neighbours' shortages.
    # Higher perceived scarcity -> higher reservation price + larger reserve target.
    # This is the seam the knowledge-gating system will plug into later.
    fear_personal_gain: float = 0.6   # +scarcity per unit of own unmet need
    fear_witness_gain: float = 0.04   # +scarcity per neighbour unmet need (gossip-thin)
    fear_decay: float = 0.04          # daily decay toward 0
    fear_price_mult: float = 1.5      # reservation price multiplier at full fear
    fear_buffer_mult: float = 2.5     # reserve-target multiplier at full fear

    # ----- knowledge propagation (Stage 3: gossip replaces the oracle) -----
    # When OFF (default), the witness signal is the village-wide unmet aggregate
    # (the original behaviour -- keeps all validated scenarios byte-identical).
    # When ON, that oracle is replaced by beliefs that had to TRAVEL to each
    # villager through the social graph, with delay, fidelity loss, and echo caps.
    propagation_enabled: bool = False
    social_degree: int = 3            # avg villager-to-villager acquaintances
    hub_degree: int = 8              # extra reach of hub nodes (market maker = tavern)
    transmit_budget: int = 2          # how many neighbours an agent tells per day
    transmit_threshold: float = 0.12  # min belief (value*confidence) worth repeating
    channel_fidelity: float = 0.9     # confidence retained per transmission hop
    rumour_exaggeration: float = 0.06 # per-hop upward drift of claimed magnitude (fear grows in the retelling)
    echo_factor: float = 0.15         # repeats of an ALREADY-HEARD root barely move confidence…
    corroboration_factor: float = 1.0 # …but a NEW independent root corroborates fully
    villager_authority: float = 0.35  # how much a random villager's word is trusted
    rumour_fear_gain: float = 0.5     # how strongly a held scarcity-belief inflates perceived_scarcity/day

    # ----- capital goods (Phase 1: does contribution generalise past consumables?) -----
    # A WOODLOT is an owned, persistent asset that YIELDS wood every day. It tests
    # whether the realized-effect payout credits a builder for INFRASTRUCTURE that
    # keeps producing over time -- income without direct labour. Off by default so
    # the validated scenarios stay byte-identical.
    # Dependents: households that garden food but can't chop wood, and buy it. A
    # small stipend (crafts/alms/family) keeps them solvent in normal seasons so
    # their vulnerability shows up specifically in winter, not as year-round destitution.
    dependent_stipend: float = 6.0    # money/day income for a dependent household

    capital_goods_enabled: bool = False

    # ----- second crisis: summer food blight (Track A #2) -----
    # A blight cuts food gather yield during its season, creating a SECOND scarce
    # good and a competing crisis -- food in summer alongside wood in winter -- to
    # test whether the loop stays interesting under two pressures rather than one
    # wood/winter axis. OFF by default so the validated scenarios and golden stay
    # byte-identical; a body or demo opts in. No special-casing is needed
    # elsewhere: food is already first-class, so food fear, the FOOD market, and
    # the AIC's fair-value channel all respond to the shortfall on their own.
    food_blight_enabled: bool = False
    food_blight_season: Season = Season.SUMMER  # the season the blight bites
    # 0.12 = food gather at 12% of normal during the blight. Chosen so the crisis
    # is real (idle villagers suffer ~40 summer food unmet, comparable to winter
    # wood) yet fully rescuable by a player who stocks food and sells into it --
    # mild cuts (>=0.2) just trigger elastic over-provisioning and no crisis.
    food_blight_yield_mult: float = 0.12        # food gather yield during the blight

    woodlot_wood_cost: float = 8.0    # base wood cost; upgrading TO level L costs cost*L
    woodlot_wood_output: float = 1.5  # wood yielded per active day, PER LEVEL
    woodlot_upkeep_food: float = 0.5  # food its workers eat per day, PER LEVEL; no food -> it idles
    woodlot_max_level: int = 5

    # ----- needs registry (Layer 2: the index prices ANY registered problem) -----
    # "Need" is data, not code (see DESIGN.md). The accountant prices and attributes
    # every registered need through one uniform pipeline -- no per-scenario logic.
    # Wood is always a rewarded need (exactly as it has always behaved). Food is
    # always registered and PRICED like wood; whether meeting it PAYS realized-effect
    # contribution is opt-in below, default OFF so the golden master stays
    # byte-identical. Turning it on is pure data: it proves the index is universal,
    # not a food special-case.
    reward_food_need: bool = False

    # ----- interventions (Layer 3: how the player changes the world) -----
    # A pre-authored library of world-changes (interventions.py), each gated by
    # preconditions (capital, standing, enabling knowledge) and applying an
    # authored effect to world-state. OFF by default so the validated scenarios
    # never perform one and stay byte-identical; a body/demo opts in.
    interventions_enabled: bool = False

    # ----- loans / capital (Layer 3: financing an intervention via a merchant) -----
    # A merchant may lend capital to fund an intervention; the borrower repays
    # principal + interest over a term, and defaults if they can't. Deterministic
    # sim state -- the LLM merchant only negotiates the numbers; the sim enforces
    # them. OFF by default so validated scenarios never take a loan and stay
    # byte-identical.
    loans_enabled: bool = False
    loan_max_interest: float = 0.6    # the sim clamps any negotiated interest to this
    loan_max_term_days: int = 120     # and the term to this

    # ----- AI Accountant (observer, not planner) -----
    accountant_enabled: bool = True
    # How realized contribution is PRICED when your resource meets someone else's
    # need. False (legacy) = the marginal bounty, which collapses to 0 once the
    # shortage is relieved -- so solving a crisis scores ~0. True = the resource's
    # FAIR VALUE (floors at intrinsic, rises with scarcity) -- so keeping someone
    # warm always earns its real worth, most in deep winter. The latter is what
    # makes the score reward realized IMPACT, per the project's core aim.
    reward_at_fair_value: bool = False
    accountant_horizon: int = 35     # foresight used to PRICE contributions, not to nudge villagers
    accountant_bounty_max: float = 6.0  # max per-unit bounty it publishes for the player
    accountant_lambda: float = 0.5   # upstream credit attenuation per lineage hop
    accountant_budget_per_day: float = 120.0  # cap on realized-contribution payout / day
    # The AIC's prediction can lag behind reality so it doesn't act as a perfect oracle.
    accountant_pessimism: float = 0.9  # discount on its production capacity estimate
    # Anti-exploitation surveillance:
    hoard_stock_threshold: float = 30.0
    scarcity_price_mult: float = 1.4
    hoard_fee_rate: float = 0.5

    @property
    def total_days(self) -> int:
        return int(self.season_length * 4 * self.years)

    def season_for_day(self, day: int) -> Season:
        idx = (day // self.season_length) % 4
        return SEASON_ORDER[idx]

    def day_in_season(self, day: int) -> int:
        return day % self.season_length

    def days_until_season(self, day: int, target: Season) -> int:
        """Days from `day` until the next start of `target` season."""
        for ahead in range(0, self.season_length * 4 + 1):
            if self.day_in_season(day + ahead) == 0 and self.season_for_day(day + ahead) == target:
                return ahead
        return self.season_length * 4
