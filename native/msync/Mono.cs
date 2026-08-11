// Clean-room Mono/Unity managed-memory reader.
//
// This walks the same public structures every Unity memory tool walks - the
// layout is fixed by Unity's Mono fork (Unity-Technologies/mono) and the
// Microsoft PE format, not by anyone's tool. We open the game process for
// READ ONLY and never write to it.
//
// The chain, top to bottom:
//   process -> mono module -> mono_get_root_domain export -> MonoDomain
//   -> assembly list -> the "Assembly-CSharp" MonoImage
//   -> that image's class cache -> a MonoClass by name
//   -> a static or instance field value.
//
// Offsets live in Offsets.cs, each annotated with the struct field it is.

using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace Bgtracker.Msync
{
    /// <summary>Read-only view into another process's memory.</summary>
    internal sealed class ProcessMemory : IDisposable
    {
        [Flags]
        private enum Access : uint { VmRead = 0x0010, QueryInformation = 0x0400 }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr OpenProcess(uint access, bool inherit, int pid);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CloseHandle(IntPtr h);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool ReadProcessMemory(
            IntPtr h, IntPtr baseAddress, byte[] buffer, int size, out int read);

        private IntPtr handle;

        public ProcessMemory(int pid)
        {
            handle = OpenProcess((uint)(Access.VmRead | Access.QueryInformation), false, pid);
            if (handle == IntPtr.Zero)
                throw new InvalidOperationException(
                    "OpenProcess failed (err " + Marshal.GetLastWin32Error() + "). " +
                    "Run from the same account as the game.");
        }

        public byte[] Read(IntPtr address, int size)
        {
            var buf = new byte[size];
            if (!ReadProcessMemory(handle, address, buf, size, out var got) || got != size)
                throw new InvalidOperationException(
                    "ReadProcessMemory failed at 0x" + address.ToInt64().ToString("X") +
                    " (err " + Marshal.GetLastWin32Error() + ").");
            return buf;
        }

        /// <summary>A user-space heap pointer we can plausibly dereference. Guards
        /// the walk against the odd garbage/uninitialised slot in a live hash map.</summary>
        public bool Plausible(IntPtr a)
        {
            var v = a.ToInt64();
            return v > 0x10000 && v < 0x7FFFFFFFFFFF;
        }

        public long ReadI64(IntPtr a) => BitConverter.ToInt64(Read(a, 8), 0);
        public IntPtr ReadPtr(IntPtr a) => new IntPtr(ReadI64(a));
        public int ReadI32(IntPtr a) => BitConverter.ToInt32(Read(a, 4), 0);
        public uint ReadU32(IntPtr a) => BitConverter.ToUInt32(Read(a, 4), 0);

        /// <summary>NUL-terminated ASCII (Mono stores type/field names this way).</summary>
        public string ReadCString(IntPtr a, int max = 512)
        {
            if (a == IntPtr.Zero) return null;
            var sb = new StringBuilder();
            var chunk = Read(a, max);
            for (int i = 0; i < chunk.Length && chunk[i] != 0; i++) sb.Append((char)chunk[i]);
            return sb.ToString();
        }

        public void Dispose()
        {
            if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; }
        }
    }

    /// <summary>A resolved MonoClass: its address plus lazy field lookups.</summary>
    internal sealed class MonoClass
    {
        private readonly MonoImage img;
        public readonly IntPtr Addr;
        public readonly string Namespace;
        public readonly string Name;

        public MonoClass(MonoImage img, IntPtr addr, string ns, string name)
        {
            this.img = img; Addr = addr; Namespace = ns; Name = name;
        }

        /// <summary>Byte offset of an instance field within an object of this class,
        /// or -1 if not found. (MonoClassField: type*, name*, parent*, offset.)</summary>
        public int FieldOffset(string field)
        {
            var m = img.Mem;
            var fields = m.ReadPtr(Addr + Off.ClassFields);
            var count = m.ReadI32(Addr + Off.ClassFieldCount);
            for (int i = 0; i < count; i++)
            {
                var f = fields + i * Off.FieldSize;
                var name = m.ReadCString(m.ReadPtr(f + Off.FieldName));
                if (name == field) return m.ReadI32(f + Off.FieldOffsetValue);
            }
            return -1;
        }

        /// <summary>Value of a static field of this class (the vtable static store).</summary>
        public IntPtr StaticFieldPtr(string field)
        {
            var m = img.Mem;
            var off = FieldOffset(field);
            if (off < 0) return IntPtr.Zero;
            var runtimeInfo = m.ReadPtr(Addr + Off.ClassRuntimeInfo);
            if (runtimeInfo == IntPtr.Zero) return IntPtr.Zero;
            var vtable = m.ReadPtr(runtimeInfo + Off.RuntimeInfoDomainVtables);
            if (vtable == IntPtr.Zero) return IntPtr.Zero;
            var vtableSize = m.ReadI32(Addr + Off.ClassVTableSize);
            var staticData = m.ReadPtr(vtable + Off.VTableData + IntPtr.Size * vtableSize);
            return m.ReadPtr(staticData + off);
        }
    }

    /// <summary>The Assembly-CSharp image and its class cache.</summary>
    internal sealed class MonoImage
    {
        public readonly ProcessMemory Mem;
        private readonly IntPtr imageAddr;

        private MonoImage(ProcessMemory mem, IntPtr imageAddr)
        {
            Mem = mem; this.imageAddr = imageAddr;
        }

        /// <summary>Attach to a process and locate the Assembly-CSharp image.</summary>
        public static MonoImage Attach(Process game, string assembly = "Assembly-CSharp")
        {
            var mono = FindMonoModule(game);
            var mem = new ProcessMemory(game.Id);

            var fnAddr = FindRootDomainFn(mem, mono);
            // x64 mono_get_root_domain: `mov rax,[rip+disp32]; ret`. rip is the
            // address just past the 7-byte instruction, so disp32 sits at +3.
            var disp = mem.ReadI32(fnAddr + 3) + 7;
            var domain = mem.ReadPtr(fnAddr + disp);

            // MonoDomain.domain_assemblies -> singly linked GSList of MonoAssembly*.
            for (var node = mem.ReadPtr(domain + Off.DomainAssemblies);
                 node != IntPtr.Zero;
                 node = mem.ReadPtr(node + IntPtr.Size))
            {
                var assemblyPtr = mem.ReadPtr(node);                       // GSList.data
                var namePtr = mem.ReadPtr(assemblyPtr + IntPtr.Size * 2);  // MonoAssembly.aname.name
                if (mem.ReadCString(namePtr) == assembly)
                    return new MonoImage(mem, mem.ReadPtr(assemblyPtr + Off.AssemblyImage));
            }
            mem.Dispose();
            throw new InvalidOperationException("Assembly '" + assembly + "' not found in the process.");
        }

        // -- generic reads on live managed objects --------------------------
        // An object's first word is its MonoVTable*; the vtable's first word is
        // its MonoClass*. From the class we resolve any field by name (walking
        // base classes for inherited fields).

        public IntPtr ClassOfInstance(IntPtr instance)
        {
            if (!Mem.Plausible(instance)) return IntPtr.Zero;
            var vtable = Mem.ReadPtr(instance);
            return Mem.Plausible(vtable) ? Mem.ReadPtr(vtable) : IntPtr.Zero;
        }

        public string ClassName(IntPtr classAddr) =>
            classAddr == IntPtr.Zero ? null : Mem.ReadCString(Mem.ReadPtr(classAddr + Off.ClassName));

        // A generic-inst class (e.g. Map`2) carries no field list of its own; the
        // fields live on its generic type DEFINITION. Field byte offsets are shared
        // between the two, so we read the field list off the definition and apply
        // the offsets to the live instance.
        private IntPtr FieldHoldingClass(IntPtr cls)
        {
            if (!Mem.Plausible(cls)) return cls;
            var kind = Mem.Read(cls + Off.ClassKind, 1)[0] & 0x7;
            if (kind != 3) return cls;                              // 3 == GInst
            var genericClass = Mem.ReadPtr(cls + Off.ClassGenericClass);
            var def = genericClass == IntPtr.Zero ? IntPtr.Zero : Mem.ReadPtr(genericClass);
            return def == IntPtr.Zero ? cls : def;
        }

        /// <summary>Instance-field byte offset for the object at <paramref name="instance"/>,
        /// searching the object's class and its base classes; -1 if absent.</summary>
        public int InstanceFieldOffset(IntPtr instance, string field)
        {
            for (var cls = ClassOfInstance(instance); Mem.Plausible(cls);)
            {
                var fc = FieldHoldingClass(cls);
                if (!Mem.Plausible(fc)) break;
                var fields = Mem.ReadPtr(fc + Off.ClassFields);
                var count = Mem.ReadI32(fc + Off.ClassFieldCount);
                if (Mem.Plausible(fields) && count > 0 && count <= 4096)
                {
                    for (int i = 0; i < count; i++)
                    {
                        var f = fields + i * Off.FieldSize;
                        if (Mem.ReadCString(Mem.ReadPtr(f + Off.FieldName)) == field)
                            return Mem.ReadI32(f + Off.FieldOffsetValue);
                    }
                }
                cls = Mem.ReadPtr(fc + Off.ClassParent);   // walk the resolved chain
            }
            return -1;
        }

        /// <summary>"name@offset" for every field on the object's class + bases - debug aid.</summary>
        public string DumpFields(IntPtr instance)
        {
            var sb = new StringBuilder();
            for (var cls = ClassOfInstance(instance); cls != IntPtr.Zero;)
            {
                var fc = FieldHoldingClass(cls);
                sb.Append('[').Append(ClassName(cls)).Append("] ");
                var fields = Mem.ReadPtr(fc + Off.ClassFields);
                var count = Mem.ReadI32(fc + Off.ClassFieldCount);
                if (fields == IntPtr.Zero || count <= 0 || count > 4096) sb.Append("(none) ");
                else for (int i = 0; i < count; i++)
                {
                    var f = fields + i * Off.FieldSize;
                    sb.Append(Mem.ReadCString(Mem.ReadPtr(f + Off.FieldName)))
                      .Append('@').Append(Mem.ReadI32(f + Off.FieldOffsetValue)).Append(' ');
                }
                cls = Mem.ReadPtr(fc + Off.ClassParent);
            }
            return sb.ToString();
        }

        public IntPtr RefField(IntPtr instance, string field)
        {
            var off = InstanceFieldOffset(instance, field);
            return off < 0 ? IntPtr.Zero : Mem.ReadPtr(instance + off);
        }

        public int IntField(IntPtr instance, string field)
        {
            var off = InstanceFieldOffset(instance, field);
            return off < 0 ? 0 : Mem.ReadI32(instance + off);
        }

        public bool BoolField(IntPtr instance, string field)
        {
            var off = InstanceFieldOffset(instance, field);
            return off >= 0 && Mem.Read(instance + off, 1)[0] != 0;
        }

        /// <summary>Read a MonoString: length at +0x10, UTF-16 chars at +0x14.</summary>
        public string ReadString(IntPtr strPtr)
        {
            if (!Mem.Plausible(strPtr)) return null;
            var len = Mem.ReadI32(strPtr + IntPtr.Size * 2);
            if (len <= 0 || len > 256) return len == 0 ? "" : null;
            var bytes = Mem.Read(strPtr + Off.UnicodeString, len * 2);
            return Encoding.Unicode.GetString(bytes);
        }

        // SZARRAY of reference types: element count at +0x18, elements from +0x20.
        public int ArrayLength(IntPtr arr) =>
            Mem.Plausible(arr) ? Mem.ReadI32(arr + IntPtr.Size * 3) : 0;

        public IntPtr ArrayRef(IntPtr arr, int i) =>
            Mem.Plausible(arr) ? Mem.ReadPtr(arr + IntPtr.Size * 4 + i * IntPtr.Size) : IntPtr.Zero;

        /// <summary>Find a class by namespace + name in the image's class cache
        /// (a MonoInternalHashTable of MonoClass*, chained on next_class_cache).</summary>
        public MonoClass FindClass(string ns, string name)
        {
            var cache = imageAddr + Off.ImageClassCache;
            var size = Mem.ReadU32(cache + Off.HashTableSize);
            var table = Mem.ReadPtr(cache + Off.HashTableTable);
            for (long bucket = 0; bucket < (long)size; bucket++)
            {
                for (var cls = Mem.ReadPtr(table + (int)(bucket * IntPtr.Size));
                     cls != IntPtr.Zero;
                     cls = Mem.ReadPtr(cls + Off.ClassNextInCache))
                {
                    var cn = Mem.ReadCString(Mem.ReadPtr(cls + Off.ClassName));
                    if (cn != name) continue;
                    var cns = Mem.ReadCString(Mem.ReadPtr(cls + Off.ClassNamespace)) ?? "";
                    if (cns == ns) return new MonoClass(this, cls, cns, cn);
                }
            }
            return null;
        }

        // -- native module + PE export lookup -------------------------------

        private static ProcessModule FindMonoModule(Process game)
        {
            foreach (ProcessModule mod in game.Modules)
                if (string.Equals(mod.ModuleName, "mono-2.0-bdwgc.dll", StringComparison.OrdinalIgnoreCase))
                    return mod;
            throw new InvalidOperationException(
                "mono-2.0-bdwgc.dll not found - is this a Mono-backed Unity game?");
        }

        // Parse the module's PE export table (read straight from process memory)
        // to find mono_get_root_domain. Offsets are the Microsoft PE format.
        private static IntPtr FindRootDomainFn(ProcessMemory mem, ProcessModule mono)
        {
            var baseAddr = mono.BaseAddress;
            int Rva(int rva) => mem.ReadI32(baseAddr + rva);

            var peHeader = mem.ReadI32(baseAddr + 0x3C);              // e_lfanew
            var exportDir = mem.ReadI32(baseAddr + peHeader + 0x88);  // PE32+ export dir RVA
            var numFns = Rva(exportDir + 0x14);                      // NumberOfFunctions
            var addrArray = Rva(exportDir + 0x1C);                    // AddressOfFunctions
            var nameArray = Rva(exportDir + 0x20);                    // AddressOfNames

            for (int i = 0; i < numFns; i++)
            {
                var nameRva = Rva(nameArray + i * 4);
                var fnName = mem.ReadCString(baseAddr + nameRva, 64);
                if (fnName == "mono_get_root_domain")
                    return baseAddr + Rva(addrArray + i * 4);
            }
            throw new InvalidOperationException("mono_get_root_domain export not found.");
        }
    }
}
