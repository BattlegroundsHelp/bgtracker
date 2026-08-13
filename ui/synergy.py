"""MECHANICAL synergy: what a card does for the board you already have.

The tavern's stars answer a statistical question - "how do players who bought
this finish?" - and they need a stats source to answer anything at all. This
module answers a different question from the CARD DATABASE alone, so it works
on a machine with no stats source, no community feed and no memory reader:

    this card pays off Beasts, and you are holding four of them

Everything here comes out of ``bgtracker.bg_pool()``: each minion's races, its
mechanics and its printed text. That is this patch's data by definition -
fetched from the card database rather than written down by anybody.

WHAT COUNTS AS SYNERGY, and why it is only these three things
-------------------------------------------------------------
1. The card's TEXT names a tribe ("give your Beasts +2/+1", "Discover a
   Dragon"). That is the card telling you what it is for, in its own words.
2. MAGNETIC. A magnetic minion attaches to a Mech, so it pays off Mechs even
   though its text never says the word.
3. Blood Gems pay off Quilboar - the gems are a Quilboar mechanic and the text
   says "Blood Gem" rather than "Quilboar".

Deliberately NOT counted, because each would fire on nearly every card and a
tag that is always on says nothing: "your minions" / "friendly minions" (every
buff says that), Spellcraft (it pays off spells, not Naga), and a minion simply
BELONGING to a tribe - that last one is reported separately and only once you
already hold two of that tribe, where it stops being a fact about the card and
becomes a fact about your board.

The COUNT is shown only when the board is actually known (the memory reader,
native/msync). Without it the payoff is still named - that half is pure card
text - and no number is printed, because "how many Beasts do you hold" has no
answer in Power.log.
"""

from __future__ import annotations

import re

# Tribe -> how a card's own text spells it, and how we print it. The enum name
# and the printed word differ for exactly two tribes (MECHANICAL/Mech,
# QUILBOAR/Quilboar), which is why this table exists instead of .title().
TRIBE_TEXT = {
    "BEAST": (r"Beasts?", "Beasts"),
    "DEMON": (r"Demons?", "Demons"),
    "DRAGON": (r"Dragons?", "Dragons"),
    "ELEMENTAL": (r"Elementals?", "Elementals"),
    "MECHANICAL": (r"Mechs?", "Mechs"),
    "MURLOC": (r"Murlocs?", "Murlocs"),
    "NAGA": (r"Naga", "Naga"),
    "PIRATE": (r"Pirates?", "Pirates"),
    "QUILBOAR": (r"Quilboars?", "Quilboar"),
    "UNDEAD": (r"Undead", "Undead"),
}

# How many of a tribe you must hold before the SHORT tag is worth the tavern's
# one slot. Two: one of a tribe is not a build, and the tag has to earn the
# place it takes from the comp label.
SHORT_MIN = 2

_TRIBE_RE = {t: re.compile(r"\b" + pat + r"\b") for t, (pat, _) in TRIBE_TEXT.items()}
_MARKUP = re.compile(r"<[^>]+>|\[x\]")
_BLOOD_GEM = re.compile(r"\bBlood Gems?\b")


def plain(text: str) -> str:
    """Card text without the game's markup, on one line."""
    return re.sub(r"\s+", " ", _MARKUP.sub("", text or "")).strip()


def payoff_tribes(entry) -> set:
    """The tribes this card is FOR, judged from what it prints and carries."""
    if not entry:
        return set()
    text = plain(entry.get("text"))
    mechs = set(entry.get("mechanics") or ())
    out = {t for t, rx in _TRIBE_RE.items() if rx.search(text)}
    if "MAGNETIC" in mechs:
        out.add("MECHANICAL")
    if _BLOOD_GEM.search(text):
        out.add("QUILBOAR")
    return out


def held_counts(names, name_tribes) -> tuple:
    """(tribe -> how many you hold, how many count as EVERY tribe).

    An Amalgam-style minion belongs to every tribe at once. Adding it to all
    ten counts would inflate ten numbers off one minion, so it is counted
    separately and printed separately - see ``format_synergy``.
    """
    counts, wild = {}, 0
    for nm in names or ():
        races = name_tribes.get(nm) or set()
        if "ALL" in races:
            wild += 1
            continue
        for r in races:
            if r in TRIBE_TEXT:
                counts[r] = counts.get(r, 0) + 1
    return counts, wild


def _pick_tribe(tribes, held):
    """Which of several tribes this card gets to name.

    ONE rule, used by every branch below: most held first, and ties broken by
    the alphabetically FIRST tribe. The tie-break is not cosmetic - a card
    naming two tribes you hold none of (or the same number of) has no better
    answer, and without a stated rule the answer came from set iteration
    order, which is not stable across runs. Alphabetical means a card that
    pays off Beasts and Demons on an empty board says "Beasts" today, tomorrow
    and on the next roll.

    ``held`` empty (no memory reader, so no board at all) collapses to plain
    alphabetical, which is the same rule with every count at zero.
    """
    return min(tribes, key=lambda t: (-held.get(t, 0), t))


def synergy(entry, held=None, wild=0, board_known=False):
    """What this card does for the board, or None.

    ``held`` is the tribe->count map from ``held_counts``; ``board_known`` says
    whether the board could be read at all. Those are different states and are
    shown differently: an empty board we CAN read means "you hold none of
    these", a board we cannot read means "we do not know" - and the second one
    must never be printed as a zero.

    Returns {"tribe", "word", "held", "wild", "payoff"}, where ``held`` is None
    when the board is unknown.
    """
    held = held or {}
    pays = payoff_tribes(entry)
    if pays:
        # More than one tribe named: the one you actually hold is the one worth
        # printing.
        tribe = _pick_tribe(pays, held if board_known else {})
        return {"tribe": tribe, "word": TRIBE_TEXT[tribe][1],
                "held": held.get(tribe, 0) if board_known else None,
                "wild": wild if board_known else 0, "payoff": True}
    # Not a payoff card: it may still be another body for a tribe you are
    # already stacking. Two is the floor - one of a tribe is not a build.
    if board_known:
        own = [r for r in (entry.get("races") or ()) if r in TRIBE_TEXT]
        best = _pick_tribe(own, held) if own else None
        if best and held.get(best, 0) >= 2:
            return {"tribe": best, "word": TRIBE_TEXT[best][1],
                    "held": held[best], "wild": wild, "payoff": False}
    return None


def _singular(word):
    return word[:-1] if word.endswith("s") else word


def format_synergy(syn):
    """(short, full): the tavern column has about 14 characters, the discover
    panel has a whole line. (None, None) when there is nothing to say.

    ``short`` is deliberately None whenever there is no count to print. The
    tavern row has ONE slot on its right and already uses it for the comp tag,
    so the mechanical read only takes that slot when it is the more specific
    of the two - "Beasts 4" is about this board, "pays off Beasts" is a fact
    about the card that the discover panel has room to say in full.
    """
    if not syn:
        return None, None
    word, held, wild = syn["word"], syn["held"], syn.get("wild", 0)
    if held is None:
        # Board unknown: name the payoff, print no count. A "member of a tribe
        # you are stacking" row cannot exist here - it is entirely a claim
        # about the board - so only the payoff case has anything to say.
        if not syn["payoff"]:
            return None, None
        return None, f"pays off {word}"
    total = held + wild
    plus = f" (+{wild} any)" if wild else ""
    if syn["payoff"]:
        # A payoff for a tribe you hold ONE of is not a synergy, it is a
        # coincidence: measured on the live pool, 103 of 274 minions name a
        # tribe, so with no floor the tavern's one slot would fill up with
        # "Quilboar 0" and push the comp tag off every row. The full line
        # still says it - knowing a payoff is dead is worth a line in the
        # discover panel, where there is room for it.
        if total < SHORT_MIN:
            return None, f"pays off {word} · you hold {held}{plus}"
        return f"▸ {word} {total}", f"pays off {word} · you hold {held}{plus}"
    # Same short form as a payoff card on purpose: in the tavern's one narrow
    # slot both mean "this is about Beasts, and you have four". Which of the
    # two it is only matters when there is room to say it, and the discover
    # panel has that room.
    return (f"▸ {word} {total}",
            f"another {_singular(word)} · you hold {held}{plus}")
