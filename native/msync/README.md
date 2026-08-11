# msync — the memory reader

`msync` is the small, optional helper that reads the Battlegrounds lobby state
Hearthstone never writes to its log: the **tribes in the lobby** (known at hero
select), your **rating**, and your **board / hand / trinkets**. The overlay uses
these for exact lobby tribes, lobby-tuned hero picks, and board synergy.

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
 "board":["BG36_704","BG34_140"],"hand":["BG32_330_G"],"trinkets":[]}
```

`ok` is true when a lobby's tribes are known. `races` are Hearthstone Race enum
ids. At the menu you get `{"ok":false,"rating":<mmr>,"races":[]}`.

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
| `HsBattlegrounds.cs` | Hearthstone reads: tribes, and your board / hand / trinkets |
| `Rating.cs` | the Battlegrounds MMR, via the NetCache service |
| `Program.cs` | the CLI and JSON output |
