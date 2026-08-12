# msync — the memory reader

`msync` is the small, optional helper that reads the Battlegrounds lobby state
Hearthstone never writes to its log: the **tribes in the lobby** (known at hero
select), your **rating**, your **board / hand / trinkets**, and the
**leaderboard** — the other players, with the boards the game is holding for
them. The overlay uses these for exact lobby tribes, lobby-tuned hero picks,
board synergy, and the OTHER PLAYERS window.

It is a **clean-room** reader. It walks the standard Mono/Unity managed heap —
the layout of which is fixed by the public Mono runtime source Unity ships
([Unity-Technologies/mono](https://github.com/Unity-Technologies/mono):
`metadata-internals.h`, `class-internals.h`, `domain-internals.h`) and the
Microsoft PE format. Every struct offset in `Offsets.cs` is annotated with the
public field it comes from. It opens the game process **read-only** and never
writes to it, injects code, or automates anything.

## Opt-in, and where it sits in the rules

Reading another process's memory is the one thing that crosses the letter of
Blizzard's EULA (see the main README's "Safety" section). So `msync` is **not
bundled** — you build it yourself, knowingly. Without it, the overlay falls back
to inferring tribes from the log and simply knows less, later.

## Build

Needs the .NET SDK (`dotnet`). From the repo root:

```bash
dotnet build native/msync -c Release
```

That produces `native/msync/bin/Release/net48/msync.exe`, which `bgtracker.py`
finds on its own.

## Run it by hand

```bash
native/msync/bin/Release/net48/msync.exe          # one reading, then exit
native/msync/bin/Release/net48/msync.exe --watch  # a JSON line every few seconds
native/msync/bin/Release/net48/msync.exe --diag    # show where the walk resolved
```

Output is one JSON line:

```json
{"ok":true,"rating":4758,"races":[15,24,14,23,43],
 "board":["BG36_704","BG34_140"],"hand":["BG32_330_G"],"trinkets":[],
 "players":[{"place":1,"card":"BG27_HERO_801_SKIN_A","health":22,"armor":0,
             "tier":4,"you":false,
             "board":[{"card":"BG36_524","atk":10,"health":9}]}]}
```

`ok` is true when a lobby's tribes are known. `races` are Hearthstone Race enum
ids. At the menu you get `{"ok":false,"rating":<mmr>,"races":[]}`.

`players` is the leaderboard, one entry per seat, in place order — hero cardId,
health (already less damage taken), armour, tavern tier, and `you` for your own
seat. Fields are only ever ADDED to this line, never renamed, so an older
reader keeps working.

A player's `board` is **empty unless the game is really holding those minions**,
which in practice means a fight against them has been staged. Empty means "not
seen", never "they have nothing". A reading that cannot be trusted - more
minions than a board can hold, or positions that are not a clean 1..N - also
reports empty, because the seat that hosts the enemy warband also hosts Bob's
shop and half-resolved moments genuinely mix the two. Minions the tavern is
offering are excluded by their drag-buy token, the same way the log-side parser
tells a shop from a warband.

## On fragility

This does **not** break on balance or content patches — fields are resolved by
name, so new cards and number changes are invisible to it. What moves the offsets
is a Unity **engine** upgrade (a few times a year). When that happens, the values
in `Offsets.cs` are re-derived from the same public Mono headers; `DumpFields` in
`Mono.cs` is the diagnostic that helps do it against a live process.

## Files

| file | what |
|---|---|
| `Mono.cs` | the generic reader: process memory, the domain→assembly→class walk, and by-name field/string/array reads on live objects |
| `Offsets.cs` | every Mono/PE struct offset, annotated with its source field |
| `HsBattlegrounds.cs` | Hearthstone reads: tribes, your board / hand / trinkets, and the leaderboard |
| `Rating.cs` | the Battlegrounds MMR, via the NetCache service |
| `Program.cs` | the CLI and JSON output |
