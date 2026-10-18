"""probe14: scan the game/HMQ module images for the globals that store the
unnamed class pointers from probe13 (banner chain + pause chain tail).
Read-only."""
import ctypes
import struct
import sys
import time

sys.path.insert(0, ".")
import hud_dynamic as h

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
mods = h.module_bases(pid, {h.GAME_DLL.lower(), h.HMQ_DLL.lower()})
game_base = mods[h.GAME_DLL.lower()]
hmq_base = mods[h.HMQ_DLL.lower()]
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
READABLE = (0x02, 0x04, 0x20, 0x40)  # RO, RW, EX_R, EX_RW

hits = {t: [] for t in TARGETS}
patterns = {t: struct.pack("<Q", t) for t in TARGETS}


def scan(start, end, label):
    addr = start
    while addr < end:
        mbi = MBI()
        if not k32.VirtualQueryEx(mem.hproc, ctypes.c_void_p(addr),
                                  ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        rbase = mbi.BaseAddress or 0
        rsize = mbi.RegionSize or 0x1000
        nxt = rbase + rsize
        if nxt <= addr:
            break
        if (mbi.State == MEM_COMMIT and mbi.Protect & 0xFF in READABLE
                and not mbi.Protect & PAGE_GUARD
                and not mbi.Protect & PAGE_NOACCESS):
            off = 0
            while off < rsize:
                want = min(0x400000, rsize - off)  # 4MB per read
                try:
                    blob = mem.rpm(rbase + off, want)
                except OSError:
                    break
                for t, pat in patterns.items():
                    pos = blob.find(pat)
                    while pos != -1:
                        va = rbase + off + pos
                        hits[t].append(va)
                        pos = blob.find(pat, pos + 1)
                off += want
        addr = nxt


t0 = time.time()
print("scanning game module 0x%X.." % game_base, flush=True)
scan(game_base, game_base + 0x20000000, "game")
print("scanning hmq module 0x%X.. (%.1fs)" % (hmq_base, time.time() - t0), flush=True)
scan(hmq_base, hmq_base + 0x4000000, "hmq")

for t, va_list in hits.items():
    lbl = TARGETS[t]
    in_game = [va for va in va_list if game_base <= va < game_base + 0x20000000]
    in_hmq = [va for va in va_list if hmq_base <= va < hmq_base + 0x4000000]
    print("0x%X %-9s hits=%d (game=%d hmq=%d)" % (
        t, lbl, len(va_list), len(in_game), len(in_hmq)), flush=True)
    for va in in_game[:12]:
        print("    game RVA 0x%X" % (va - game_base), flush=True)
    for va in in_hmq[:12]:
        print("    hmq  RVA 0x%X" % (va - hmq_base), flush=True)

print("DONE %.1fs" % (time.time() - t0), flush=True)
mem.close()
