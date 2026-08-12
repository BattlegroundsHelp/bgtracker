// Hearthstone Battlegrounds reads layered on the generic Mono reader:
// the lobby's tribes, your own board / hand / trinkets, and the LEADERBOARD -
// the other seven players, which Power.log never states during recruit.
//
// All of it hangs off GameState.s_instance:
//   - m_availableRacesInBattlegroundsExcludingAmalgam -> the lobby tribes
//   - m_playerMap  -> find the LOCAL player, read its CONTROLLER tag; the one
//                     non-local player is the AI seat that hosts Bob and every
//                     enemy warband (a Battlegrounds game has exactly two
//                     controllers, not eight)
//   - m_entityMap  -> every entity; bucket by controller / zone / card type.
//
// Card ids are read straight out of each entity; no card database is needed.
//
// THE LEADERBOARD, and how its rule was established
// -------------------------------------------------
// Each seat owns one persistent HERO entity that carries
// PLAYER_LEADERBOARD_PLACE. That tag is the whole filter: measured on a live
// game (2026-08-11) exactly eight entities carried it, one per place 1..8,
// while the hero-draft leftovers, Bartender Bob, the anomaly NPC and the two
// placeholder heroes carried none - and neither does the temporary hero copy
// the client creates in PLAY for the fight that is animating.
//
// The numeric tag ids below were pinned by correlating a live memory dump
// against Power.log at the same instant - the log names its tags, so the
// numeric id that matches the named value for EVERY leaderboard hero is that
// tag: PLAYER_LEADERBOARD_PLACE 1373 (8 of 8), PLAYER_TECH_LEVEL 1377 (7 of 7),
// ARMOR 292 (7 of 7), DAMAGE 44 (6 of 6).
//
// BOARDS, and the two traps that are worth the paragraphs
// -------------------------------------------------------
// (1) WHOSE minions are they? The AI seat holds BOB'S SHOP as well as the
// enemy warband, in the same PLAY zone - so reading "the other controller's
// minions" and calling it an opponent board puts your own tavern on someone
// else's row. That is not a theoretical risk: it was caught live, by checking
// a captured "opponent board" against the log's own pre-attack snapshot of the
// same fight and finding four completely different minions - the next shop,
// which the client rolls WHILE the fight is still animating.
//
// Two gates, both needed:
//   * the seat's hero in PLAY must be a hero that holds a LEADERBOARD PLACE.
//     Matching "not Bob" is not enough - measured live, the seat's hero in
//     PLAY can be Bartender Bob (shopping), the Kel'Thuzad NPC, or the
//     opponent whose fight is on screen.
//   * shop minions are dropped by their DRAG-BUY TOKEN. Every minion Bob is
//     offering is escorted by a TB_BaconShop_DragBuy token that names it, and
//     a warband minion never has one - the same discriminator the log-side
//     parser has always used, applied here to memory. Measured on a live
//     recruit: 6 tokens naming exactly the 6 shop minions; on a live fight:
//     7 warband minions, none of them named by a token.
//   * the token is not enough on its own, because the client ROLLS THE NEXT
//     SHOP WHILE THE FIGHT IS STILL ANIMATING and those minions have no token
//     yet. Live reading, mid-fight: eleven minions under the seat, no tokens
//     at all - entity ids 4141..4151 at positions 1-7 (the warband, created
//     with the enemy hero at 4138) and 4696..4702 at positions 1-4 (the next
//     shop). No tag tells the two apart; their CREATION does. A warband is
//     built in the same burst as the hero it belongs to - measured at 3..13
//     ids above it in one fight and 5..43 in another - while the next shop
//     turned up 545 ids later. So only minions created in the hero's own burst
//     are that hero's board.
//
// (2) IS the read coherent? A mid-fight read is a moving target - minions die,
// deathrattles summon, and the client can hold more entities in the seat's
// PLAY zone than a board can ever have. Measured over three real fights: 29
// readings with opponent minions, 21 of them holding MORE THAN SEVEN (up to
// 13), and one capture held positions 1,1,2,3,4,5,6,7 with the same cardId
// twice. A Battlegrounds board is at most seven minions at positions 1..N, so
// anything else is a mixture - and a mixture reported as "their board" is a
// lie. Those readings emit an EMPTY board, and the overlay keeps whatever it
// last saw cleanly instead. This mirrors the rule the overlay already uses for
// hero-draft badge slots: accept a refresh only when the positions are a clean
// permutation, otherwise it is transit.

using System;
using System.Collections.Generic;
using System.Linq;

namespace Bgtracker.Msync
{
    internal sealed class Team
    {
        public string[] Board = new string[0];
        public string[] Hand = new string[0];
        public string[] Trinkets = new string[0];
    }

    /// <summary>One minion as the game currently holds it.</summary>
    internal sealed class Minion
    {
        public string Card = "";
        public int Atk;
        public int Health;      // remaining health: HEALTH - DAMAGE
    }

    /// <summary>One seat on the Battlegrounds leaderboard.</summary>
    internal sealed class LeaderPlayer
    {
        public int Place;
        public string CardId = "";
        public int Health;              // remaining: HEALTH - DAMAGE
        public int Armor;
        public int Tier;                // PLAYER_TECH_LEVEL, 0 when unset
        public bool You;
        public Minion[] Board = new Minion[0];   // empty unless the game holds it
    }

    internal sealed class Snapshot
    {
        public Team Team = new Team();
        public LeaderPlayer[] Players = new LeaderPlayer[0];
    }

    internal static class Hs
    {

        // Hearthstone GameTag ids (stable; from the game's own tag enum).
        private const int TAG_DAMAGE = 44;
        private const int TAG_HEALTH = 45;
        private const int TAG_ATK = 47;
        private const int TAG_ZONE = 49;
        private const int TAG_CONTROLLER = 50;
        private const int TAG_ENTITY_ID = 53;
        private const int TAG_CARDTYPE = 202;
        private const int TAG_ZONE_POSITION = 263;
        private const int TAG_ARMOR = 292;
        private const int TAG_LEADERBOARD_PLACE = 1373;
        private const int TAG_TECH_LEVEL = 1377;
        private const int TAG_SPELL_SCHOOL = 1635;

        // Zone ids.
        private const int ZONE_PLAY = 1;
        private const int ZONE_HAND = 3;

        // CardType ids.
        private const int TYPE_HERO = 3;
        private const int TYPE_MINION = 4;
        private const int TYPE_TRINKET = 44;

        // The tavern keeper and the pre-draft placeholders are HERO-type
        // entities that belong to nobody's seat.
        private const string BobCard = "TB_BaconShopBob";
        private const string PlaceholderCard = "TB_BaconShop_HERO_PH";

        // The token that escorts every minion Bob is offering. Its
        // TAG_DRAG_TARGET holds that minion's entity id - which is how a shop
        // minion is told apart from a warband minion sitting in the same zone
        // under the same controller.
        private const string DragBuyCard = "TB_BaconShop_DragBuy";
        private const int TAG_DRAG_TARGET = 2442;

        // How far above its hero's entity id a warband minion can be created
        // and still belong to that hero's burst. Measured: whole warbands sat
        // 3..43 ids above their hero, and the next shop - rolled during the
        // fight, and carrying no drag-buy token yet - turned up 545 ids later.
        // Anything past this window was made for something else.
        private const int HeroBurstIds = 256;

        /// <summary>One pass over the live entity map: your own board / hand /
        /// trinkets, and every seat on the leaderboard.</summary>
        public static Snapshot ReadState(MonoImage img, IntPtr gameState)
        {
            var snap = new Snapshot();
            int local, seat;
            Controllers(img, gameState, out local, out seat);
            if (local < 0) return snap;

            var entityMap = img.RefField(gameState, "m_entityMap");
            var slots = img.RefField(entityMap, "valueSlots");
            var cap = img.ArrayLength(slots);

            var board = new List<(int pos, string id)>();
            var hand = new List<(int pos, string id)>();
            var trinkets = new List<(int pos, string id)>();
            var mine = new List<(int pos, Minion m)>();       // your board, with stats
            var seatPlay = new List<(int id, int pos, Minion m)>();   // seat's PLAY minions
            var onOffer = new HashSet<int>();   // entity ids Bob is selling
            var leaders = new List<(int entityId, LeaderPlayer p)>();
            var seatHeroes = new List<(string card, int id)>();   // seat heroes in PLAY

            for (int i = 0; i < cap; i++)
            {
                var e = img.ArrayRef(slots, i);
                if (e == IntPtr.Zero) continue;
                var cardId = img.ReadString(img.RefField(e, "m_cardIdInternal"));
                if (string.IsNullOrEmpty(cardId)) continue;

                var tags = ReadTags(img, e);
                var controller = Tag(tags, TAG_CONTROLLER);
                var zone = Tag(tags, TAG_ZONE);
                var type = Tag(tags, TAG_CARDTYPE);
                var pos = Tag(tags, TAG_ZONE_POSITION);

                if (cardId == DragBuyCard)
                {
                    var target = Tag(tags, TAG_DRAG_TARGET);
                    if (target > 0) onOffer.Add(target);   // that minion is Bob's
                    continue;
                }

                if (type == TYPE_HERO)
                {
                    var place = Tag(tags, TAG_LEADERBOARD_PLACE);
                    if (place > 0)
                    {
                        leaders.Add((Tag(tags, TAG_ENTITY_ID), new LeaderPlayer
                        {
                            Place = place,
                            CardId = cardId,
                            Health = Remaining(tags),
                            Armor = Math.Max(0, Tag(tags, TAG_ARMOR)),
                            Tier = Math.Max(0, Tag(tags, TAG_TECH_LEVEL)),
                            You = controller == local,
                        }));
                    }
                    else if (controller == seat && zone == ZONE_PLAY
                             && cardId != BobCard && cardId != PlaceholderCard)
                    {
                        // a candidate: whose fight is this, and which burst is it?
                        seatHeroes.Add((cardId, Tag(tags, TAG_ENTITY_ID)));
                    }
                    continue;
                }

                if (controller == seat)
                {
                    if (zone == ZONE_PLAY && type == TYPE_MINION)
                        seatPlay.Add((Tag(tags, TAG_ENTITY_ID), pos,
                                      ReadMinion(cardId, tags)));
                    continue;
                }
                if (controller != local) continue;

                if (zone == ZONE_PLAY && type == TYPE_MINION)
                {
                    board.Add((pos, cardId));
                    mine.Add((pos, ReadMinion(cardId, tags)));
                }
                else if (zone == ZONE_HAND) hand.Add((pos, cardId));
                // Equipped trinkets sit in PLAY on the hero and carry a real spell
                // school; pool/offer copies live elsewhere and read as NONE. Both
                // gates keep only the trinkets you actually hold.
                else if (type == TYPE_TRINKET && zone == ZONE_PLAY && Tag(tags, TAG_SPELL_SCHOOL) > 0)
                    trinkets.Add((pos, cardId));
            }

            snap.Team.Board = board.OrderBy(x => x.pos).Select(x => x.id).ToArray();
            snap.Team.Hand = hand.OrderBy(x => x.pos).Select(x => x.id).ToArray();
            snap.Team.Trinkets = trinkets.OrderBy(x => x.pos).Select(x => x.id).ToArray();

            // One row per place. Two entities claiming one place would be a lie
            // about who is where, so the persistent seat entity wins - it is the
            // older one, i.e. the lower entity id.
            var players = leaders
                .OrderBy(x => x.entityId)
                .GroupBy(x => x.p.Place)
                .Select(g => g.First().p)
                .OrderBy(p => p.Place)
                .ToArray();

            foreach (var p in players)
                if (p.You) p.Board = Coherent(mine);

            // Whose warband is it? Exactly one of the seat's heroes in PLAY has
            // to be a player on the leaderboard - the seat can also be holding
            // Bartender Bob or the Kel'Thuzad NPC at the same time, and "the
            // last hero the scan happened to see" is not an answer. No single
            // match, no attribution.
            var owners = seatHeroes
                .Select(h => (hero: h, player: players.FirstOrDefault(
                    p => !p.You && p.CardId == h.card)))
                .Where(x => x.player != null)
                .ToArray();
            if (owners.Length != 1) return snap;

            // Their board: minions the seat is holding that Bob is not selling
            // and that were created in this hero's own burst - see trap (2).
            var heroId = owners[0].hero.id;
            owners[0].player.Board = Coherent(seatPlay
                .Where(x => !onOffer.Contains(x.id)
                            && x.id > heroId && x.id - heroId <= HeroBurstIds)
                .Select(x => (x.pos, x.m)).ToList());
            snap.Players = players;
            return snap;
        }

        /// <summary>A board, or nothing. See trap (2) at the top of this file:
        /// at most seven minions, at positions 1..N with no gap and no
        /// duplicate. Anything else is a half-resolved moment, and the honest
        /// answer to "what is on their board" is then silence.</summary>
        private static Minion[] Coherent(List<(int pos, Minion m)> minions)
        {
            if (minions.Count == 0 || minions.Count > 7) return new Minion[0];
            var seen = new HashSet<int>();
            foreach (var x in minions)
                if (x.pos < 1 || x.pos > minions.Count || !seen.Add(x.pos))
                    return new Minion[0];
            return minions.OrderBy(x => x.pos).Select(x => x.m).ToArray();
        }

        private static Minion ReadMinion(string cardId, Dictionary<int, int> tags) =>
            new Minion
            {
                Card = cardId,
                Atk = Math.Max(0, Tag(tags, TAG_ATK)),
                Health = Remaining(tags),
            };

        // What the game shows: printed health less damage taken. A missing
        // HEALTH tag means the entity never had one - report 0, never a guess.
        private static int Remaining(Dictionary<int, int> tags)
        {
            var hp = Tag(tags, TAG_HEALTH);
            if (hp < 0) return 0;
            return Math.Max(0, hp - Math.Max(0, Tag(tags, TAG_DAMAGE)));
        }

        // The local player's CONTROLLER id, from the one m_playerMap entry whose
        // m_local flag is set, and the other entry's - the AI seat that hosts
        // Bob and every enemy warband. -1 when there is no game in progress.
        private static void Controllers(MonoImage img, IntPtr gameState,
                                        out int local, out int seat)
        {
            local = -1;
            seat = -1;
            var playerMap = img.RefField(gameState, "m_playerMap");
            var slots = img.RefField(playerMap, "valueSlots");
            var cap = img.ArrayLength(slots);
            for (int i = 0; i < cap; i++)
            {
                var p = img.ArrayRef(slots, i);
                if (p == IntPtr.Zero) continue;
                var controller = Tag(ReadTags(img, p), TAG_CONTROLLER);
                if (controller < 0) continue;
                if (img.BoolField(p, "m_local")) local = controller;
                else if (seat < 0) seat = controller;
            }
        }

        // An entity's tags live in m_tags (a TagMap) -> m_values (a
        // Dictionary<int,int>). The dictionary's _entries is an array of INLINE
        // Entry structs { int hashCode; int next; int key; int value } (16 bytes);
        // a slot with next < -1 is a freed entry. Array data starts 32 bytes in.
        private const int EntryStride = 16, EntryNext = 4, EntryKey = 8, EntryValue = 12, ArrayData = 32;

        private static Dictionary<int, int> ReadTags(MonoImage img, IntPtr entity)
        {
            var tags = new Dictionary<int, int>();
            var dict = img.RefField(img.RefField(entity, "m_tags"), "m_values");
            if (!img.Mem.Plausible(dict)) return tags;
            var entries = img.RefField(dict, "_entries");
            var count = img.IntField(dict, "_count");
            if (!img.Mem.Plausible(entries) || count <= 0 || count > 8192) return tags;
            for (int i = 0; i < count; i++)
            {
                var e = entries + ArrayData + i * EntryStride;
                if (img.Mem.ReadI32(e + EntryNext) < -1) continue;   // freed slot
                tags[img.Mem.ReadI32(e + EntryKey)] = img.Mem.ReadI32(e + EntryValue);
            }
            return tags;
        }

        private static int Tag(Dictionary<int, int> tags, int key) =>
            tags.TryGetValue(key, out var v) ? v : -1;
    }
}
