// Hearthstone Battlegrounds reads layered on the generic Mono reader:
// the lobby's tribes, and your own board / hand / trinkets.
//
// All of it hangs off GameState.s_instance:
//   - m_availableRacesInBattlegroundsExcludingAmalgam -> the lobby tribes
//   - m_playerMap  -> find the LOCAL player, read its CONTROLLER tag
//   - m_entityMap  -> every entity; keep the ones your controller owns and
//                     bucket them by zone / card type.
//
// Card ids are read straight out of each entity; no card database is needed.

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

    internal static class Hs
    {

        // Hearthstone GameTag ids (stable; from the game's own tag enum).
        private const int TAG_ZONE = 49;
        private const int TAG_CONTROLLER = 50;
        private const int TAG_CARDTYPE = 202;
        private const int TAG_ZONE_POSITION = 263;
        private const int TAG_SPELL_SCHOOL = 1635;

        // Zone ids.
        private const int ZONE_PLAY = 1;
        private const int ZONE_HAND = 3;

        // CardType ids.
        private const int TYPE_MINION = 4;
        private const int TYPE_TRINKET = 44;

        /// <summary>Read your board / hand / trinkets from the live GameState instance.</summary>
        public static Team ReadTeam(MonoImage img, IntPtr gameState)
        {
            var controller = LocalController(img, gameState);
            var team = new Team();
            if (controller < 0) return team;

            var entityMap = img.RefField(gameState, "m_entityMap");
            var slots = img.RefField(entityMap, "valueSlots");
            var cap = img.ArrayLength(slots);

            var board = new List<(int pos, string id)>();
            var hand = new List<(int pos, string id)>();
            var trinkets = new List<(int pos, string id)>();

            for (int i = 0; i < cap; i++)
            {
                var e = img.ArrayRef(slots, i);
                if (e == IntPtr.Zero) continue;
                var cardId = img.ReadString(img.RefField(e, "m_cardIdInternal"));
                if (string.IsNullOrEmpty(cardId)) continue;

                var tags = ReadTags(img, e);
                if (Tag(tags, TAG_CONTROLLER) != controller) continue;

                var zone = Tag(tags, TAG_ZONE);
                var type = Tag(tags, TAG_CARDTYPE);
                var pos = Tag(tags, TAG_ZONE_POSITION);

                if (zone == ZONE_PLAY && type == TYPE_MINION) board.Add((pos, cardId));
                else if (zone == ZONE_HAND) hand.Add((pos, cardId));
                // Equipped trinkets sit in PLAY on the hero and carry a real spell
                // school; pool/offer copies live elsewhere and read as NONE. Both
                // gates keep only the trinkets you actually hold.
                else if (type == TYPE_TRINKET && zone == ZONE_PLAY && Tag(tags, TAG_SPELL_SCHOOL) > 0)
                    trinkets.Add((pos, cardId));
            }

            team.Board = board.OrderBy(x => x.pos).Select(x => x.id).ToArray();
            team.Hand = hand.OrderBy(x => x.pos).Select(x => x.id).ToArray();
            team.Trinkets = trinkets.OrderBy(x => x.pos).Select(x => x.id).ToArray();
            return team;
        }

        // The local player's CONTROLLER id, from the one m_playerMap entry whose
        // m_local flag is set. -1 when there is no game in progress.
        private static int LocalController(MonoImage img, IntPtr gameState)
        {
            var playerMap = img.RefField(gameState, "m_playerMap");
            var slots = img.RefField(playerMap, "valueSlots");
            var cap = img.ArrayLength(slots);
            for (int i = 0; i < cap; i++)
            {
                var p = img.ArrayRef(slots, i);
                if (p == IntPtr.Zero || !img.BoolField(p, "m_local")) continue;
                return Tag(ReadTags(img, p), TAG_CONTROLLER);
            }
            return -1;
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
