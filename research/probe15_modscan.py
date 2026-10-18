"""probe15: enumerate ALL modules of the game process and scan each module
image for the unnamed class pointers (banner chain family). Read-only.
"""
import ctypes
import struct
import sys
import time

sys.path.insert(0, ".")
import hud_dynamic as h
from ctypes import wintypes

TARGETS = {
    0x11150880: "banner_C1",
    0x1112A840: "banner_C2",
    0x1112ACC0: "common_C3",
    0x54C0D00: "tail_C4",
    0x3A83BCA00: "hmq_BP",
    0x11155BC0: "chain_E",
    0x1112AF00: "chain_F",
}

pid = h.find_process_id(h.GAME_EXE)
hproc = h.k32.OpenProcess(h.PROCESS_QUERY_INFORMATION | h.PROCESS_VM_READ, False, pid)
mem = h.ProcessMem(pid, read_only=True)


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", ctypes.c_uint32),
                ("PartitionId", ctypes.c_uint16),
                ("alignment1", ctypes.c_uint16),
                ("RegionSize", ctypes.c_size_t),
                ("State", ctypes.c_uint32),
                ("Protect", ctypes.c_uint32),
                ("Type", ctypes.c_uint32),
                ("alignment2", ctypes.c_uint32)]


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.VirtualQueryEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                               ctypes.POINTER(MBI), ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t

MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
READABLE = (0x02, 0x04, 0x20, 0x40)

# ---- enumerate all modules ----
needed = wintypes.DWORD(0)
cap = 2048
buf = (wintypes.HMODULE * cap)()
if not h.psapi.EnumProcessModulesEx(hproc, buf, ctypes.sizeof(buf),
                                    ctypes.byref(needed), h.LIST_MODULES_ALL):
    print("EnumProcessModulesEx failed")
    sys.exit(1)
n = needed.value // ctypes.sizeof(wintypes.HMODULE)
name_buf = wintypes.WCHAR * 260
modules = []
for i in range(min(n, cap)):
    hmod = buf[i]
    name = name_buf()
    if h.psapi.GetModuleBaseNameW(hproc, hmod, name, 260) == 0:
        continue
    mi = h.MODULEINFO()
    if h.psapi.GetModuleInformation(hproc, hmod, ctypes.byref(mi), ctypes.sizeof(mi)):
        modules.append((h.wchar_str(name), mi.lpBaseOfDll, mi.SizeOfImage))

print("== %d modules ==" % len(modules), flush=True)
for name, base, size in modules:
    print("  %-52s base=0x%016X size=0x%X" % (name, base, size), flush=True)

# ---- scan each module image ----
hits = {t: [] for t in TARGETS}
patterns = {t: struct.pack("<Q", t) for t in TARGETS}
t0 = time.time()


def scan_region(base, size, label):
    addr = base
    end = base + size
    while addr < end:
        mbi = MBI()
        if not k32.VirtualQueryEx(hproc, ctypes.c_void_p(addr),
                                  ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        rbase = mbi.BaseAddress or 0
        rsize = mbi.RegionSize or 0x1000
        nxt = rbase + rsize
        if nxt <= addr:
            break
        if (mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in READABLE
                and not mbi.Protect & PAGE_GUARD):
            off = 0
            while off < rsize:
                want = min(0x400000, rsize - off)
                try:
                    blob = mem.rpm(rbase + off, want)
                except OSError:
                    off += want
                    continue
                for t, pat in patterns.items():
                    pos = blob.find(pat)
                    while pos != -1:
                        hits[t].append((label, rbase + off + pos - base))
                        pos = blob.find(pat, pos + 1)
                off += want
        addr = nxt


for name, base, size in modules:
    scan_region(base, size, name)

print("scan of all module images took %.1fs" % (time.time() - t0), flush=True)
for t, lst in hits.items():
    lbl = TARGETS[t]
    uniq = sorted(set(lst))
    print("0x%X %-9s unique=%d" % (t, lbl, len(uniq)), flush=True)
    for mod, rva in uniq[:16]:
        print("    %-40s RVA 0x%X" % (mod, rva), flush=True)

print("DONE %.1fs" % (time.time() - t0), flush=True)
mem.close()
