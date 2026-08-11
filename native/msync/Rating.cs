// Battlegrounds MMR, read from the NetCache service.
//
// Chain (all by field name off the live objects):
//   Hearthstone.HearthstoneJobs.s_dependencyBuilder  (static)
//     ._items[0].m_serviceLocator.m_services          (a Dictionary)
//       -> the entry whose service type name is "NetCache"
//         .m_netCache.valueSlots                       (a Map of NetCache records)
//           -> the NetCacheBaconRatingInfo record
//             .<Rating>k__BackingField                 (the MMR)

using System;

namespace Bgtracker.Msync
{
    internal static class Rating
    {
        public static bool Debug = false;
        private static void Dbg(string s) { if (Debug) Console.Error.WriteLine("[rat] " + s); }

        public static int Read(MonoImage img)
        {
            try
            {
                var jobs = img.FindClass("Hearthstone", "HearthstoneJobs");
                if (jobs == null) { Dbg("no HearthstoneJobs"); return -1; }
                var builderList = jobs.StaticFieldPtr("s_dependencyBuilder");
                var items = img.RefField(builderList, "_items");
                var b0 = img.ArrayRef(items, 0);
                var locator = img.RefField(b0, "m_serviceLocator");
                var services = img.RefField(locator, "m_services");
                Dbg($"services=0x{services.ToInt64():X} class={img.ClassName(img.ClassOfInstance(services))} fields={img.DumpFields(services)}");

                var netCache = FindService(img, services, "NetCache");
                if (netCache == IntPtr.Zero) { Dbg("NetCache service not found"); return -1; }

                var map = img.RefField(netCache, "m_netCache");
                var slots = img.RefField(map, "valueSlots");
                var cap = img.ArrayLength(slots);
                Dbg($"netCache=0x{netCache.ToInt64():X} map=0x{map.ToInt64():X} slots cap={cap}");
                for (int i = 0; i < cap; i++)
                {
                    var rec = img.ArrayRef(slots, i);
                    if (rec == IntPtr.Zero) continue;
                    if (img.ClassName(img.ClassOfInstance(rec)) == "NetCacheBaconRatingInfo")
                        return img.IntField(rec, "<Rating>k__BackingField");
                }
                return -1;
            }
            catch (Exception e)
            {
                Dbg("rating read failed: " + e.Message);
                return -1;
            }
        }

        // The services Dictionary's _entries hold reference values; each service
        // record exposes <ServiceTypeName> and <Service> auto-property fields.
        private static IntPtr FindService(MonoImage img, IntPtr services, string typeName)
        {
            var entries = img.RefField(services, "_entries");
            var count = img.IntField(services, "_count");
            if (!img.Mem.Plausible(entries) || count <= 0 || count > 65536) return IntPtr.Zero;

            // _entries is an array of inline Entry structs
            // { int hashCode; int next; TKey key; TValue value }. The value is a
            // reference (the service record), 8 bytes, and the last field - so it
            // sits at stride - 8. next < -1 marks a freed slot.
            var stride = EntryStride(img, entries);
            var valueOff = stride - IntPtr.Size;
            Dbg($"services entries=0x{entries.ToInt64():X} count={count} stride={stride} valueOff={valueOff}");
            if (stride <= 0) return IntPtr.Zero;

            for (int i = 0; i < count; i++)
            {
                var entry = entries + 32 + i * stride;
                if (img.Mem.ReadI32(entry + 4) < -1) continue;               // freed slot (Entry.next)
                var record = img.Mem.ReadPtr(entry + valueOff);
                if (!img.Mem.Plausible(record)) continue;
                var name = img.ReadString(img.RefField(record, "<ServiceTypeName>k__BackingField"));
                if (i < 3) Dbg($"  svc[{i}] name={name}");
                if (name == typeName)
                    return img.RefField(record, "<Service>k__BackingField");
            }
            return IntPtr.Zero;
        }

        // Size of one Entry struct = the element size stored on the array's own
        // MonoClass (the sizes union holds element_size for array classes).
        private static int EntryStride(MonoImage img, IntPtr array)
        {
            var arrClass = img.ClassOfInstance(array);            // the T[] MonoClass
            if (!img.Mem.Plausible(arrClass)) return 0;
            var size = img.Mem.ReadI32(arrClass + Off.ClassInstanceSize);
            return size > 0 && size < 512 ? size : 0;
        }
    }
}
