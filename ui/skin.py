"""The painted skin: generated art routed under the same four draw calls.

Every window's chrome is drawn by exactly four helpers in ui/base.py -
``panel_frame``, ``header_slab``, ``plate``, ``art_frame`` - and this module
is the image-backed version of those four shapes. Each helper asks here
first; a ``None`` answer means "draw it the old way", so a build without the
skin folder, without Pillow, or with one unreadable file paints the exact
vector chrome it painted before. The skin is a coat, not a dependency.

Sources are the clean RGBA files ``tools/make_skin.py`` bakes into
``data/skin/`` (magenta already cut, #000001 already scrubbed). This module
only ever composes and resizes them - at the FINAL pixel size, because
``Canvas.scale`` moves an image item's anchor and nothing else: a photo
painted at base size would stay base size on a 4K screen while every vector
around it doubled.

Why compositions are cached and bounded: the tavern rebuilds itself on every
shop roll, and a panel bake (tile + nine-slice + mask) costs real
milliseconds. The same handful of sizes recurs - a window's width is fixed
and its heights step through its row counts - so an LRU keyed on size turns
every repaint after the first into a dict hit. Bounded, because a resize
drag walks through dozens of transient sizes and an unbounded cache of 4K
RGBA panels is a slow leak.

Every bake takes the WIDGET it will be painted on, because a PhotoImage
belongs to one Tcl interpreter and ``tk._default_root`` is not reliably it:
the settings test drives two managers side by side, and a photo minted
against the first interpreter painted on the second's canvas dies with
``image "pyimageN" doesn't exist``. Binding to the canvas's own interpreter
(``master=``) and keying the cache by that interpreter makes the photo and
its painting surface the same root by construction; a dead interpreter's
leftovers simply age out of the LRU.

THE COLOUR KEY RULE HOLDS HERE TOO. #000001 is the overlay's click-through
hole (ui/base.py TRANS). The sources are scrubbed, but LANCZOS interpolation
between neighbouring darks can land a pixel back on it, so every bake's blue
channel gets the same one-step nudge (1 -> 2) before it becomes a photo - a
1/255 shift in blue on near-black, invisible by construction. Outer edges
against the hole are BINARIZED (alpha 0 or 255): a feathered rim would blend
toward the key colour and wear a dark fringe around every panel.
"""

from __future__ import annotations

from collections import OrderedDict

from paths import APP_DIR, BUNDLE_DIR

try:
    from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageTk
    _PIL = True
except Exception:
    _PIL = False

# The user's own folder beside the exe wins, the bundled copy is the default -
# the same pair, in the same order, as hero_tips and comp_roles.
_DIRS = [APP_DIR / "data" / "skin", BUNDLE_DIR / "data" / "skin"]

# The two files the whole look hangs off. Missing either, the skin is off and
# every helper falls back to vectors; the others degrade one shape at a time.
_REQUIRED = ("panel_wood.png", "frame_gold.png")

_active = None          # tri-state: unknown / on / off, decided once (files)
_enabled = None         # the SETTING: None = not read yet, else the choice
_dir = None
_src = {}               # name -> RGBA source, loaded once, never mutated
_cache = OrderedDict()  # (interp, kind, *params) -> PhotoImage, LRU
_MAX = 96


def set_enabled(on):
    """The settings panel's switch, applied live. The caller repaints."""
    global _enabled
    _enabled = bool(on)


def active() -> bool:
    """Is the tavern skin ON - the setting says yes AND the files exist.

    OFF is the default: the shipped trackers this tool sits beside present
    flat - measured 2026-08-14 off Firestone (flat white-at-8% rows, zero
    radius, zero borders, Open Sans 400 on #190505) and HSReplay (the same
    doctrine on #1a0e1f) - and the default look follows them. The generated
    tavern art is the opt-in, not the baseline.
    """
    global _active, _dir, _enabled
    if _enabled is None:
        # Not wired by a host: OFF. The overlay wires it at boot and the
        # settings panel live; a lazy read of the user's real settings.json
        # was tried here and reviewed out - it made TEST outcomes depend on
        # whatever the machine's live file said (2026-08-14).
        _enabled = False
    if not _enabled:
        return False
    if _active is None:
        _active = False
        if _PIL:
            for d in _DIRS:
                if all((d / f).is_file() for f in _REQUIRED):
                    _dir, _active = d, True
                    break
    return _active


def _load(name):
    """One source image, or None - a missing/corrupt file costs one shape."""
    if name not in _src:
        im = None
        try:
            im = Image.open(_dir / name).convert("RGBA")
            if name == "frame_gold.png":
                # The generator leaves faint alpha specks in the backdrop;
                # recrop to the pixels that are actually THERE so the band
                # measurements below start at the metal, not at a speck.
                bbox = im.getchannel("A").point(
                    lambda a: 255 if a >= 128 else 0).getbbox()
                if bbox:
                    im = im.crop(bbox)
        except Exception:
            im = None
        _keep_src(name, im)
    return _src[name]


def _photo(key, im, master):
    """RGBA -> PhotoImage, scrubbed, cached, bound to ``master``'s interp."""
    # The key-colour nudge (see the module docstring): blue 1 -> 2.
    r, g, b, a = im.split()
    b = b.point(lambda v: 2 if v == 1 else v)
    try:
        photo = ImageTk.PhotoImage(Image.merge("RGBA", (r, g, b, a)),
                                   master=master)
    except Exception:
        return None                      # a dying widget: fall back to vectors
    _cache[key] = photo
    if len(_cache) > _MAX:
        _cache.popitem(last=False)
    return photo


def _key(master, kind, *params):
    """Cache key: the interpreter is part of the identity, because the same
    size baked for another interpreter is a different (and unusable) photo."""
    return (id(master.tk), kind) + params


def _get(key):
    photo = _cache.get(key)
    if photo is not None:
        _cache.move_to_end(key)
    return photo


def _bands(im):
    """The gold frame's band thickness on each side, measured from alpha.

    Measured rather than assumed, because the art does not owe the code a
    number: whatever the generator drew, the mid-row walk from each edge to
    the inner hole IS the band, and the nine-slice below cuts exactly there.
    """
    a = im.getchannel("A").load()
    w, h = im.size
    y, x = h // 2, w // 2

    def walk(seq, at):
        run = 0
        for i in seq:
            if at(i) >= 128:
                run += 1
            elif run:
                break
        return max(1, run)

    return (walk(range(w), lambda i: a[i, y]),               # left
            walk(range(w - 1, -1, -1), lambda i: a[i, y]),   # right
            walk(range(h), lambda i: a[x, i]),               # top
            walk(range(h - 1, -1, -1), lambda i: a[x, i]))   # bottom


def _nine_slice(src, w, h, t):
    """The frame redrawn at (w, h) with a band about ``t`` px thick.

    Corners are cropped and scaled as pictures (they carry the rivets), the
    four edges are stretched along their length only, the middle stays empty.
    Corner size is twice the band, so the corner piece keeps the little run of
    straight edge that lets it meet the stretched edges without a visible cut.
    """
    sw, sh = src.size
    bl, br, bt, bb = _bands(src)
    cs = min(max(bl, br, bt, bb) * 2, sw // 3, sh // 3)   # source corner
    cd = max(2, min(t * 2, w // 3, h // 3))               # target corner
    out = Image.new("RGBA", (w, h))

    def put(box, size, at):
        piece = src.crop(box).resize(size, Image.LANCZOS)
        out.paste(piece, at)

    put((0, 0, cs, cs), (cd, cd), (0, 0))                          # corners
    put((sw - cs, 0, sw, cs), (cd, cd), (w - cd, 0))
    put((0, sh - cs, cs, sh), (cd, cd), (0, h - cd))
    put((sw - cs, sh - cs, sw, sh), (cd, cd), (w - cd, h - cd))
    if w > 2 * cd:                                                 # edges
        put((cs, 0, sw - cs, bt),
            (w - 2 * cd, max(1, round(bt * cd / cs))), (cd, 0))
        bh = max(1, round(bb * cd / cs))
        put((cs, sh - bb, sw - cs, sh), (w - 2 * cd, bh), (cd, h - bh))
    if h > 2 * cd:
        put((0, cs, bl, sh - cs),
            (max(1, round(bl * cd / cs)), h - 2 * cd), (0, cd))
        bw = max(1, round(br * cd / cs))
        put((sw - br, cs, sw, sh - cs), (bw, h - 2 * cd), (w - bw, cd))
    return out


def _tile(src, w, h, tile):
    """The wood repeated at a fixed on-screen grain density."""
    t = src.resize((tile, tile), Image.LANCZOS) if tile != src.width else src
    out = Image.new("RGBA", (w, h))
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            out.paste(t, (x, y))
    return out


def _round_mask(w, h, r, top_only=False):
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    if top_only:
        d.rectangle((0, r, w - 1, h - 1), fill=255)
    # Hard edge: over the click-through hole, a half-covered pixel is a
    # half-keyed pixel (see the module docstring).
    return m.point(lambda v: 255 if v >= 128 else 0)


def panel(c, w, h, r, scale):
    """The whole slab - wood, gold nine-slice, hard rounded silhouette."""
    if not active():
        return None
    key = _key(c, "panel", w, h, r)
    got = _get(key)
    if got is not None:
        return got
    wood, frame = _load("panel_wood.png"), _load("frame_gold.png")
    if wood is None or frame is None or w < 8 or h < 8:
        return None
    im = _tile(wood, w, h, max(64, round(512 * scale)))
    im.alpha_composite(_nine_slice(frame, w, h, max(3, round(4 * scale))))
    im.putalpha(_round_mask(w, h, max(2, r)))
    return _photo(key, im, c)


def header(c, w, h, r):
    """The title strip, squared along its bottom, rounded along its top."""
    if not active():
        return None
    key = _key(c, "header", w, h, r)
    got = _get(key)
    if got is not None:
        return got
    src = _load("header_bar.png")
    if src is None or w < 8 or h < 4:
        return None
    im = src.resize((w, h), Image.LANCZOS)
    im.putalpha(_round_mask(w, h, max(2, r), top_only=True))
    return _photo(key, im, c)


def _slice_filled(src, w, h, cd):
    """The plate redrawn at (w, h) with its corners kept at ``cd`` px.

    The row art is wide (about 7:1); stretched onto a TALL block - the comps
    window's expanded comp, the browser's opened row - a whole resize
    balloons the corners and drags the bright edge band (art the quiet pass
    exempts) right under the text. Same lesson as the quiet pass itself, one
    day later: art holds its shape at the EDGES and the interior is the flat
    face - so corners are copied, edges stretch along their length only, and
    the face fills the middle.
    """
    sw, sh = src.size
    cs = min(sw, sh) // 3
    cd = max(3, min(cd, w // 3, h // 3))
    out = Image.new("RGBA", (w, h))

    def put(box, size, at):
        out.paste(src.crop(box).resize(size, Image.LANCZOS), at)

    put((0, 0, cs, cs), (cd, cd), (0, 0))
    put((sw - cs, 0, sw, cs), (cd, cd), (w - cd, 0))
    put((0, sh - cs, cs, sh), (cd, cd), (0, h - cd))
    put((sw - cs, sh - cs, sw, sh), (cd, cd), (w - cd, h - cd))
    if w > 2 * cd:
        put((cs, 0, sw - cs, cs), (w - 2 * cd, cd), (cd, 0))
        put((cs, sh - cs, sw - cs, sh), (w - 2 * cd, cd), (cd, h - cd))
    if h > 2 * cd:
        put((0, cs, cs, sh - cs), (cd, h - 2 * cd), (0, cd))
        put((sw - cs, cs, sw, sh - cs), (cd, h - 2 * cd), (w - cd, cd))
        if w > 2 * cd:
            put((cs, cs, sw - cs, sh - cs), (w - 2 * cd, h - 2 * cd), (cd, cd))
    return out


def plate(c, w, h, best):
    """One row's plate. Feathered edges stay: it lies ON the opaque panel.

    A row-shaped target takes the art whole, as approved on screen. A target
    much taller than the art's own aspect is sliced instead (_slice_filled):
    the STRETCH, not the art, was what read as broken.
    """
    if not active():
        return None
    key = _key(c, "plate", w, h, best)
    got = _get(key)
    if got is not None:
        return got
    src = _load("plate_best.png" if best else "plate.png")
    if src is None or w < 4 or h < 4:
        return None
    sw, sh = src.size
    if h * sw > w * sh * 1.5:
        # Corner size follows the smaller target dimension at the art's own
        # corner-to-width proportion, so a sliced plate's corners carry the
        # same visual weight as a whole-resized row's.
        im = _slice_filled(src, w, h, round(min(w, h) * (sh // 3) / sw))
    else:
        im = src.resize((w, h), Image.LANCZOS)
    return _photo(key, im, c)


def art_frame(c, w, h, best):
    """The little frame around card art; the hole in the middle is real."""
    if not active():
        return None
    key = _key(c, "artframe", w, h, best)
    got = _get(key)
    if got is not None:
        return got
    src = _load("artframe.png")
    if src is None or w < 4 or h < 4:
        return None
    im = src.resize((w, h), Image.LANCZOS)
    if not best:
        # The quiet variant, matching GOLD -> GOLD_LO in the vector chrome:
        # every frame lit gold would out-shout the one row that matters.
        im = ImageEnhance.Brightness(im).enhance(0.62)
    return _photo(key, im, c)


# ------------------------------------------------------------- deck tiles
#
# NOT gated by active(): this is not the tavern skin, it is how every
# Hearthstone tracker draws a minion row - HSReplay and Firestone paint the
# game's own deck-list tile (a wide slice of the card art) as the row itself,
# right-aligned, melting into the dark bar that carries the name. The tiles
# are already on disk: fetch-art fills assets/tiles/ with the 256x59 slices
# HearthstoneJSON publishes, the same images those trackers use. Copied, not
# invented - the founder's standing direction for this HUD.

_TILE_DIR = APP_DIR / "assets" / "tiles"
_BAR = (30, 24, 17, 255)        # ui.base ROW,      as pixels
_BAR_BEST = (36, 29, 21, 255)   # ui.base PANEL_HI, as pixels
_GOLD = (168, 133, 74, 255)     # ui.base GOLD - the one accent


def _keep_src(key, im):
    """The source cache is BOUNDED too (review find: it interned one PIL
    image per browsed card forever while only the photo cache had the LRU).
    Plain FIFO is enough - sources are cheap to reload on a rare revisit."""
    if len(_src) > 512:
        for k in list(_src)[:128]:
            del _src[k]
    _src[key] = im
    return im


def _tile_src(card):
    """The art slice for a cardId, golden ids folded onto their base BEFORE
    the cache key - a golden pair used to decode the same file twice."""
    base = card[:-2] if card.endswith("_G") else card
    key = "tile:" + base
    if key in _src:
        return _src[key]
    im = None
    p = _TILE_DIR / f"{base}.png"
    if p.is_file():
        try:
            im = Image.open(p).convert("RGBA")
        except Exception:
            im = None
    return _keep_src(key, im)


def tile(c, card, w, h, best=False):
    """One deck-list row: the bar, the art fading in from the right.

    None when the tile is not on disk (art not fetched, a brand-new card) -
    the caller draws its old icon-and-text row, nothing is missing but art.
    """
    if not _PIL or not card or w < 20 or h < 8:
        return None
    key = _key(c, "tile", card, w, h, best)
    got = _get(key)
    if got is not None:
        return got
    src = _tile_src(card)
    if src is None:
        return None
    # The art runs under the WHOLE row - that is the actual deck-list recipe
    # (a right-aligned slice was tried first and showed the art's own bright
    # left flank mid-row): cover-scale, crop the vertical middle, then lay a
    # dark gradient over it - near-solid where the name sits, thinning to
    # the right where the art is the point.
    scale = max(w / src.width, h / src.height)
    art = src.resize((max(w, round(src.width * scale)),
                      max(h, round(src.height * scale))), Image.LANCZOS)
    top = (art.height - h) // 2
    im = art.crop((0, top, w, top + h)).convert("RGBA")
    bar = _BAR_BEST if best else _BAR
    hold = round(w * 0.38)          # solid under the name...
    ramp = bytes(min(255, max(0, int(
        246 if x < hold else 246 - (246 - 60) * (x - hold) / max(1, w - hold))))
        for x in range(w))
    overlay = Image.new("RGBA", (w, h), bar)
    overlay.putalpha(Image.frombytes("L", (w, 1), ramp).resize((w, h)))
    im.alpha_composite(overlay)
    if best:
        ImageDraw.Draw(im).rectangle((0, 0, w - 1, h - 1), outline=_GOLD)
    return _photo(key, im, c)


_CROP_DIR = APP_DIR / "assets" / "crops"
_UI_DIR = APP_DIR / "assets" / "ui"


def ui_icon(c, name, px):
    """One piece of fetched UI chrome (the deck-list gem), scaled. None when
    fetch-art has not run - the caller keeps its drawn look."""
    if not _PIL or px < 6:
        return None
    key = _key(c, "ui", name, px)
    got = _get(key)
    if got is not None:
        return got
    skey = "ui:" + name
    if skey not in _src:
        im = None
        # Shipped chrome first (data/ui, in the repo and the build - the
        # designed tribe emblems), fetched chrome second (assets/ui, what
        # fetch-art pulled - the deck-list gem).
        for d in (APP_DIR / "data" / "ui", BUNDLE_DIR / "data" / "ui",
                  _UI_DIR):
            p = d / f"{name}.png"
            if p.is_file():
                try:
                    im = Image.open(p).convert("RGBA")
                except Exception:
                    im = None
                break
        _keep_src(skey, im)
    src = _src[skey]
    if src is None:
        return None
    return _photo(key, src.resize((px, px), Image.LANCZOS), c)


def round_icon(c, card, px, ring=None):
    """A circular card-art icon, the way the reference draws a counter's
    source in its pill. ``card`` may be an enchantment id - the trailing
    'pe'/'e' is folded onto the base card whose crop fetch-art saved. None
    when there is no art: the caller draws its plain-circle fallback.
    """
    if not _PIL or not card or px < 6:
        return None
    key = _key(c, "ricon", card, px, ring)
    got = _get(key)
    if got is not None:
        return got
    src = None
    stem = card[:-2] if card.endswith("pe") else card
    # Try the id itself, its base card, and the base's visible enchantment
    # ("...pe" accumulators stamp "...e" copies - Eastern Winds' art lives on
    # the stamp, not the bookkeeping id). First art on disk wins.
    for cid in (card, stem, stem + "e",
                stem[:-1] if stem.endswith("e") else stem):
        p = _CROP_DIR / f"{cid}.jpg"
        if p.is_file():
            try:
                src = Image.open(p).convert("RGBA")
            except Exception:
                src = None
            break
    if src is None:
        return None
    im = src.resize((px, px), Image.LANCZOS)
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, px - 1, px - 1), fill=255)
    im.putalpha(mask.point(lambda v: 255 if v >= 128 else 0))
    if ring:
        ImageDraw.Draw(im).ellipse((0, 0, px - 1, px - 1), outline=ring)
    return _photo(key, im, c)


def icon(root):
    """The window/taskbar face - app identity, NOT tavern chrome, so it is
    not behind the skin switch. None only when the file is missing."""
    if not _PIL:
        return None
    key = _key(root, "icon")
    got = _get(key)
    if got is not None:
        return got
    src = None
    for d in _DIRS:
        p = d / "app_icon.png"
        if p.is_file():
            try:
                src = Image.open(p).convert("RGBA")
            except Exception:
                src = None
            break
    if src is None:
        return None
    return _photo(key, src.resize((64, 64), Image.LANCZOS), root)
