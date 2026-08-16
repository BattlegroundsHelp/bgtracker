"""bgtracker overlay windows - the registry and the plugin contract.

One window per concern. Each one is a self-contained plugin with its own
trigger, its own clear, its own default position and its own remembered drag
offset. There is deliberately NO shared mode enum anywhere in this package:
every live bug the single morphing panel produced (odds one fight late, a
stale tavern, a COMBAT header sitting over the shop) came from one state
machine trying to be several surfaces at once.

THE CONTRACT
------------
A window subclasses ``ui.base.BaseWindow`` and declares:

  KEY             unique id; also its key in .overlay.json (its own position)
  TITLE           header text
  EVENTS          tuple of event names the router should deliver to it
  COLUMN / DY     default anchor: which edge of the Hearthstone window, and
                  how far down it - see the layout table below
  BADGE_KIND      optional: "hero"|"trinket"|"shop"|"choice" gives it a
                  click-through badge strip over the real cards
  BADGE_PRIORITY  higher priority strips hide lower ones while both would show
  TIMEOUT_MS      optional auto-close backstop
  QUIT_BUTTON     draw the overlay's quit control (exactly one window does)

and implements:

  draw(canvas) -> int        paint the body, return the height in px
  on_event(name, payload)    react; call self.show() / self.hide() / redraw()
  on_click(x, y) -> bool     optional; True means "consumed, do not drag"
  reset()                    optional; a new game began

To add a window: write the module, add its class to WINDOWS below, and make
the reader emit its events. Nothing else in the overlay needs to change - the
router dispatches purely on EVENTS, and a window that raises is reported and
skipped rather than taking the others down with it.

THE EVENTS
----------
Lifecycle events are keyed to the PowerTaskList copy of Power.log, which is
the copy that is in sync with the screen. GameState may be read for DATA
(boards, shop contents) because it is complete and early; it must never drive
show/hide, or windows describe a moment that is not on screen yet.

  status      str                          -> comps, browser
  game        None (new game detected)     -> every window resets
  lobby       {seen, exact, comps, all}    -> comps, browser, session
  board       {size, lean, hits, names}    -> comps, counters
  gold        int                          -> tavern, counters
  tavern      {rows, slots, roll, lean}    -> tavern (rebuild), pick windows
                                              (a later roll closes them)
  tavern_gone None                         -> tavern (screen entered combat)
  combat      {seq, round}                 -> combat (screen entered combat)
  combat_over None                         -> combat (screen back in tavern)
  odds        {seq, round, win, tie, loss, n} -> combat
  hero        {rows, tuned}                -> heropick
  hero_slots  {rows, tuned}                -> heropick (corrected card order)
  hero_over   None                         -> heropick (hero was picked)
  heropower   {rows, roll}                 -> heropower
  trinket     {rows, tuned, roll}          -> trinkets
  discover    {rows, roll}                 -> discover
  picks_over  None                         -> heropower, trinkets, discover
  hero_over   None                         -> heropick, session (takes its band
                                              back once the draft is gone)
  players     {round, rows}                -> players. OPTIONAL, and the only
                                              event with no log source at all:
                                              it exists only when the memory
                                              reader (native/msync) is built.
                                              Without it the window never opens
                                              and nothing else changes.
  counters    {gold_base, tier, ...}       -> counters, OPTIONAL: nothing emits
                                              it today, so the window tails the
                                              log itself. A reader that starts
                                              pushing it wins and the window
                                              drops its own feed - two sources
                                              for one number is the bug this
                                              contract exists to prevent.

DEFAULT LAYOUT (all draggable; each remembers its own place)
-----------------------------------------------------------
Down the RIGHT edge of the game window, in reserved bands - the surfaces that
describe the state of play:
  counters y+8 (62px)   combat y+70 (78px)
  tavern y+156 (232px)  comps  y+396 (the rest)
Down the LEFT edge, the surfaces that describe cards you are choosing between:
they open while those cards occupy the middle of the screen, and a panel on
the right would sit over them (the trinket row reaches x 0.79 of the window):
  browser  y+8 (34px, a slim bar until it is clicked open)
  session / heropick y+70 (256px)   heropower y+334 (150px)
  trinkets / players y+492 (272px)  discover  y+772 (the rest)

Non-overlap is structural, not a hope: every window's MAX_H is its band, so a
long shop or an expanded comp list can never spill into its neighbour. The
last window in each column takes the remaining height. Verified on a
1920x1080 game window: 10 windows, zero overlapping pairs at maximum height,
all inside the game rect.

Three bands are shared on purpose, and only ever by one window at a time:
  * session and heropick both want y+70 on the left. The draft owns it while
    it is up; session hides on ``hero`` and comes back on ``hero_over``, and
    only while it still sits in its default slot (drag it and it stays up).
  * players and trinkets both want y+492 on the left. Same deal, same reason:
    a trinket dialog is a moment, the leaderboard is a standing surface, so
    players hides on ``trinket`` and returns on ``picks_over`` (with its own
    timeout as a backstop, since a dialog that is dismissed oddly must not
    cost the leaderboard the rest of the game).
  * browser is a one-line bar; clicking ``browse`` expands it over the left
    column. That is a deliberate act by the player, it is draggable, and a new
    game collapses it again.

SCALING
-------
Every number above is in BASE pixels, measured against a 1920x1080 game
window, and they stay that way at any scale: ``draw()`` is written in base
pixels and ``ui.base`` scales the finished canvas, the panel geometry and the
fonts. So the bands tile a 4K game exactly the way they tile a 1080p one, and
a window module needs no scale arithmetic of its own. When the player scales
past what the game window can hold, the column keeps its band order and the
excess runs off the BOTTOM edge - it never doubles back over a neighbour
(``BaseWindow.default_xy`` states the invariant).

The whole public surface is four names in ``ui.base`` - ``set_scale(s)``,
``get_scale()``, ``auto_scale()`` and ``SCALE_MIN``/``SCALE_MAX``, plus
``set_badge_scale``/``get_badge_scale`` for the badges, which are sized by the
GAME window rather than by this preference. Nothing is persisted here: the
storage belongs to ``settings.py`` and the panel in ``ui/settings.py``, which
is the one window in this package that is deliberately NOT an overlay surface
(it is clickable and focusable, and it is not in WINDOWS). See the SCALING
section at the top of ui/base.py.

TURNING A WINDOW OFF
--------------------
The settings panel offers one switch per entry in WINDOWS, and off means the
class is never built: not built, not routed to, no badge strip. Hiding it
instead would leave it consuming its events and holding a strip in the
priority list that can suppress another window's badges. Live changes go
through ``WindowManager.enable``/``disable``, which ask their owner to rebuild
the router - it indexes windows by event once, at construction.
"""

from __future__ import annotations

import re

from .browser import BrowserWindow
from .combat import CombatWindow
from .comps import CompsWindow
from .counters import CountersWindow
from .curve import CurveWindow
from .effects import EffectsWindow
from .micro import (GoldMicro, RollsMicro, TierMicro, TriplesMicro,
                    TrinketMicro, TurnMicro, UpgradeMicro)
from .discover import DiscoverWindow
from .heropick import HeroPickWindow
from .heropower import HeroPowerWindow
from .players import PlayersWindow
from .session import SessionWindow
from .tavern import TavernWindow
from .trinkets import TrinketWindow

# The registry. Order is construction order only - windows are independent.
WINDOWS = (
    CountersWindow,
    # One micro window per counter - the numbers' normal home. The strip
    # above keeps the state and the log feed they all read, and draws itself
    # only when every one of these is switched off.
    GoldMicro,
    TierMicro,
    UpgradeMicro,
    TriplesMicro,
    RollsMicro,
    TrinketMicro,
    TurnMicro,
    EffectsWindow,
    CurveWindow,
    CombatWindow,
    TavernWindow,
    CompsWindow,
    BrowserWindow,
    SessionWindow,
    DiscoverWindow,
    HeroPickWindow,
    HeroPowerWindow,
    TrinketWindow,
    PlayersWindow,
)

__all__ = [
    "WINDOWS", "BrowserWindow", "CombatWindow", "CompsWindow", "CountersWindow",
    "DiscoverWindow", "GoldMicro", "HeroPickWindow", "HeroPowerWindow",
    "PlayersWindow", "RollsMicro", "TierMicro", "TriplesMicro",
    "TrinketMicro", "TurnMicro", "UpgradeMicro",
    "SessionWindow", "TavernWindow", "TrinketWindow", "classify_choice",
]

# A hero power reads "<set>_HERO_<n>p" or "TB_BaconShop_HP_<n>"; the hero
# itself is the same id without the trailing p.
_HP_TAIL = re.compile(r"_HERO_\d+[a-z]?p$")
_HERO_TAIL = re.compile(r"_HERO_\d+(_SKIN_[A-Z])?(_G)?$")


def classify_choice(card_ids, heroes=(), trinkets=(), hero_powers=()):
    """Which window does this choose-one dialog belong to?

    Every choose-one in Battlegrounds - the hero draft, the trinket shop, a
    hero-power choice, a minion discover, a Dark Gift - arrives as the same
    EntityChoices block. Splitting them is a card-identity question, answered
    from the card database (HearthstoneJSON), with a shape fallback so the
    classification still works offline with no cache:

      trinket    every option is a Battlegrounds trinket   ("...MagicItem...")
      hero       every option is a Battlegrounds hero      ("..._HERO_nnn")
      heropower  every option is a hero power    ("TB_BaconShop_HP_", "...p")
      discover   anything else: minions, Dark Gifts, spells, treasures

    Measured against a real Power.log (5 games, 103 blocks) these four buckets
    account for every block: 13 hero/trinket fours, 5 hero-power threes, the
    rest minion discovers and Dark Gifts.
    """
    ids = [c for c in card_ids if c]
    if not ids:
        return "discover"

    def is_trinket(cid):
        return cid in trinkets or "MagicItem" in cid or "Trinket" in cid

    def is_hero_power(cid):
        if cid in hero_powers:
            return True
        return cid.startswith("TB_BaconShop_HP_") or _HP_TAIL.search(cid) is not None

    def is_hero(cid):
        if is_hero_power(cid):
            return False
        return cid in heroes or _HERO_TAIL.search(cid) is not None

    if all(is_trinket(c) for c in ids):
        return "trinket"
    if all(is_hero_power(c) for c in ids):
        return "heropower"
    if all(is_hero(c) for c in ids):
        return "hero"
    return "discover"
