// msync - print the Battlegrounds lobby's tribes (and, later, rating + board)
// as one JSON line, read live out of Hearthstone's memory. Drop-in for the
// old tribes.exe: same JSON contract the Python side already parses.
//
//   msync            one reading, then exit
//   msync --watch    a JSON line every few seconds until killed
//   msync --diag     show where the memory walk resolved (troubleshooting)
//
// The tribe list is the one thing Hearthstone never writes to Power.log, yet it
// is known at hero select. Everything here is a read-only memory read; nothing
// is written to the game and no code is injected.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Threading;

namespace Bgtracker.Msync
{
    internal static class Program
    {
        private const int PollSeconds = 3;

        // GameState.s_instance holds the live game; its available-races list is the
        // lobby's tribes as Hearthstone Race enum ids.
        private const string GameStateClass = "GameState";
        private const string RacesField = "m_availableRacesInBattlegroundsExcludingAmalgam";

        private static int Main(string[] args)
        {
            var watch = args.Contains("--watch");
            var diag = args.Contains("--diag");
            Rating.Debug = diag;

            do
            {
                try
                {
                    Emit(ReadOnce(diag));
                }
                catch (Exception e)
                {
                    Emit(new Result { ok = false, error = e.Message });
                }

                if (watch) Thread.Sleep(PollSeconds * 1000);
            }
            while (watch);

            return 0;
        }

        private static Result ReadOnce(bool diag)
        {
            var game = Process.GetProcessesByName("Hearthstone").FirstOrDefault();
            if (game == null)
                return new Result { ok = false, error = "Hearthstone is not running" };

            var image = MonoImage.Attach(game);

            // Rating lives in NetCache, independent of any active game - it is
            // valid at the menu too, so read it before the game-state gate.
            var rating = Rating.Read(image);

            var gs = image.FindClass("", GameStateClass);
            if (gs == null)
                return new Result { ok = false, rating = rating, error = "GameState class not found" };

            var instance = gs.StaticFieldPtr("s_instance");
            var diagInfo = diag
                ? "GameState@0x" + gs.Addr.ToInt64().ToString("X") +
                  " s_instance@0x" + instance.ToInt64().ToString("X")
                : null;

            // No game in progress (menu / between games): rating still stands.
            if (instance == IntPtr.Zero)
                return new Result { ok = false, rating = rating, races = new int[0], diag = diagInfo };

            var racesOff = gs.FieldOffset(RacesField);
            if (racesOff < 0)
                return new Result { ok = false, rating = rating, error = "races field not found", diag = diagInfo };

            var races = ReadIntList(image.Mem, image.Mem.ReadPtr(instance + racesOff));
            var team = Hs.ReadTeam(image, instance);
            return new Result
            {
                ok = races.Length > 0,
                rating = rating,
                races = races,
                board = team.Board,
                hand = team.Hand,
                trinkets = team.Trinkets,
                diag = diagInfo,
            };
        }

        // A List<int>: object header, then T[] _items, then int _size. On x64 that
        // puts _items at 0x10 and _size at 0x18. An int[] stores its length at
        // +0x18 and its elements from +0x20.
        private static int[] ReadIntList(ProcessMemory mem, IntPtr list)
        {
            if (list == IntPtr.Zero) return new int[0];
            var items = mem.ReadPtr(list + 0x10);
            var size = mem.ReadI32(list + 0x18);
            if (items == IntPtr.Zero || size <= 0 || size > 64) return new int[0];
            var arr = new int[size];
            for (int i = 0; i < size; i++)
                arr[i] = mem.ReadI32(items + 0x20 + i * 4);
            return arr;
        }

        // -- tiny dependency-free JSON (ints + one string), matching tribes.exe --

        private sealed class Result
        {
            public bool ok;
            public int rating = -1;
            public int[] races = new int[0];
            public string[] board = new string[0];
            public string[] hand = new string[0];
            public string[] trinkets = new string[0];
            public string error;
            public string diag;
        }

        private static void Emit(Result r)
        {
            var sb = new StringBuilder("{");
            sb.Append("\"ok\":").Append(r.ok ? "true" : "false");
            sb.Append(",\"rating\":").Append(r.rating.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"races\":[").Append(string.Join(",",
                r.races.Select(x => x.ToString(CultureInfo.InvariantCulture)))).Append(']');
            sb.Append(",\"board\":").Append(JsonStrArray(r.board));
            sb.Append(",\"hand\":").Append(JsonStrArray(r.hand));
            sb.Append(",\"trinkets\":").Append(JsonStrArray(r.trinkets));
            if (r.error != null) sb.Append(",\"error\":").Append(JsonStr(r.error));
            if (r.diag != null) sb.Append(",\"diag\":").Append(JsonStr(r.diag));
            sb.Append('}');
            Console.WriteLine(sb.ToString());
            Console.Out.Flush();
        }

        private static string JsonStrArray(string[] items) =>
            "[" + string.Join(",", items.Select(JsonStr)) + "]";

        private static string JsonStr(string s)
        {
            var sb = new StringBuilder("\"");
            foreach (var c in s)
            {
                if (c == '"' || c == '\\') sb.Append('\\').Append(c);
                else if (c < 0x20) sb.Append(' ');
                else sb.Append(c);
            }
            return sb.Append('"').ToString();
        }
    }
}
