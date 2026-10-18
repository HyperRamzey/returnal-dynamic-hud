"""probe18: raw screen-stack dump (fixed class reads). Read-only."""
import struct
import sys

sys.path.insert(0, ".")
import hud_dynamic as h

pid = h.find_process_id(h.GAME_EXE)
mods = h.module_bases(pid, {h.GAME_DLL.lower(), h.HMQ_DLL.lower()})
gb = mods[h.GAME_DLL.lower()]
hmq = mods[h.HMQ_DLL.lower()]
mem = h.ProcessMem(pid, read_only=True)


def u64(a):
    try:
        return mem.u64(a)
    except OSError:
        return 0


def u32(a):
    try:
        return mem.u32(a)
    except OSError:
        return 0xFFFFFFFF


GAME_RVA = {
    "ATouristPlayerController": 0xF6F168, "ATouristHUD": 0xF6EB10,
    "UTouristScreenManager": 0xF6FED8, "UPauseMenu": 0xF64B88,
    "UTouristTutorialWidget": 0xF704A0, "UTouristTutorialPanel": 0xF70460,
}
HMQ_RVA = {
    "UHMQScreenManager": 0xA3188, "UHMQScreenWidget": 0xA32E8,
    "UHMQSubtitlesWidget": 0xA33A8, "UHMQSubtitlePlayer": 0xA3370,
    "UHMQUserWidget": 0xA35D0,
}
UMG_BASE = 0x00007FFC209D0000
UMG_RVA = {"UOverlaySlot": 0x21B148, "UPanelSlot": 0x21B158,
           "UVisual": 0x21BFA0, "UUserWidget": 0x21BEB0, "UWidget": 0x21C1C0}

known = {}
for nm, rva in GAME_RVA.items():
    known[u64(gb + rva)] = nm
for nm, rva in HMQ_RVA.items():
    known[u64(hmq + rva)] = nm
for nm, rva in UMG_RVA.items():
    known[u64(UMG_BASE + rva)] = nm

gua = u64(gb + h.RVA_GUOBJECTARRAY_IAT)
ct0 = u64(gua + h.OFF_GUA_CHUNKTABLE)
count0 = u32(gua + h.OFF_GUA_COUNT)
print("gua=0x%X count=%d" % (gua, count0), flush=True)

cch = {}
obj_by_class = {}
idx = 0
while idx < count0:
    cn = idx >> 16
    cb = cch.get(cn)
    if cb is None:
        cb = u64(ct0 + 8 * cn) if ct0 > 0x10000 else 0
        cch[cn] = cb
    here = min(0x10000, count0 - (cn << 16))
    if cb and cb > 0x10000:
        try:
            b = mem.rpm(cb, here * 24)
        except OSError:
            idx = (cn + 1) << 16
            continue
        for j in range(here):
            o = struct.unpack_from("<Q", b, j * 24)[0]
            if not o:
                continue
            fl = struct.unpack_from("<I", b, j * 24 + 8)[0]
            if fl & 0x10 or fl & 0x20000000:
                continue
            c = u64(o + 0x10)          # <-- class read from OBJECT (+0x10)
            if not c:
                continue
            ii = (cn << 16) | j
            obj_by_class.setdefault(c, []).append((ii, o))
    idx = (cn + 1) << 16
print("classes with objects=%d" % len(obj_by_class), flush=True)


def chain_of(c, limit=20):
    out, seen = [], set()
    while c and c not in seen and len(out) < limit:
        seen.add(c)
        out.append(c)
        c = u64(c + 0x40)
    return out


def fmt(c, limit=10):
    return "/".join(known.get(x, "0x%X" % x) for x in chain_of(c, limit))


def resolve(ii):
    cn = ii >> 16
    cb = cch.get(cn)
    if not cb:
        return 0
    return u64(cb + 24 * (ii & 0xFFFF))


mgr_cls = u64(gb + GAME_RVA["UTouristScreenManager"])
pc_cls = u64(gb + GAME_RVA["ATouristPlayerController"])
mgr_found = pc_found = 0
for c, lst in obj_by_class.items():
    ch = chain_of(c, 20)
    if mgr_cls in ch:
        for ii, o in lst:
            print("== MGR ii=%d obj=0x%X class=0x%X chain=%s" % (ii, o, c, fmt(c)), flush=True)
            mgr_found = o
    if pc_cls in ch:
        for ii, o in lst:
            print("== PC ii=%d obj=0x%X class=0x%X chain=%s" % (ii, o, c, fmt(c)), flush=True)
            pc_found = o

if mgr_found:
    o = mgr_found
    d = u64(o + 0x130)
    n = u32(o + 0x138)
    print("stack data=0x%X n=%d" % (d, n), flush=True)
    for k in range(min(n, 12)):
        try:
            b = mem.rpm(d + 24 * k, 24)
        except OSError:
            break
        q = struct.unpack("<QQQ", b)
        print("entry%d raw: %016X %016X %016X" % (k, q[0], q[1], q[2]), flush=True)
        seen = set()
        for foff in (0, 4, 8, 12, 16, 20):
            v = struct.unpack_from("<I", b, foff)[0]
            if 0 < v < count0 and v not in seen:
                seen.add(v)
                eo = resolve(v)
                if eo:
                    ec = u64(eo + 0x10)
                    print("   +%d -> ii=%d obj=0x%X chain=%s" % (foff, v, eo, fmt(ec)), flush=True)

if pc_found:
    pc = pc_found
    pawn = u64(pc + 0x330)
    hud = u64(pc + 0x390)
    hc = u64(pawn + 0x668)
    hp = struct.unpack("<f", mem.rpm(hc + 0x2AC, 4))[0] if hc else -1
    print("pc=0x%X pawn=0x%X hud=0x%X hp=%.2f menus=%d" % (
        pc, pawn, hud, hp, u32(hud + 0x4BC)), flush=True)

print("-- ii=497123 now --", flush=True)
o = resolve(497123)
print("obj=0x%X chain=%s flags=0x%X" % (o, fmt(u64(o + 0x10)) if o else "-", u32(o + 8) if o else 0), flush=True)
print("DONE", flush=True)
mem.close()
