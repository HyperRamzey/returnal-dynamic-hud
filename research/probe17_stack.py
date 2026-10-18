"""probe17: raw screen-stack dump with correct (chain-based) manager discovery.

Read-only. Dumps every entry as raw 24 bytes and tries EVERY u32 field as an
object internal index, resolving each candidate through GUObjectArray and
printing its class chain. Also re-resolves ii=497123 (the 21:53 banner entry).
"""
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

# batched GUObjectArray build: class -> [(ii, obj)], and obj lookup arrays
cch = {}
rev = {}
all_objs = {}
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
            c = struct.unpack_from("<Q", b, j * 24 + 16)[0]
            if not c:
                continue
            ii = (cn << 16) | j
            rev.setdefault(c, []).append((ii, o))
    idx = (cn + 1) << 16
print("rev classes=%d" % len(rev), flush=True)


def resolve(ii):
    cn = ii >> 16
    cb = cch.get(cn)
    if not cb:
        return 0
    return u64(cb + 24 * (ii & 0xFFFF))


def chain_of(c, limit=12):
    out, seen = [], set()
    while c and c not in seen and len(out) < limit:
        seen.add(c)
        out.append(c)
        c = u64(c + 0x40)
    return out


def fmt(c, limit=8):
    return "/".join(known.get(x, "0x%X" % x) for x in chain_of(c, limit))


# find classes whose chain contains UTouristScreenManager
mgr_cls = u64(gb + GAME_RVA["UTouristScreenManager"])
mgr_classes = []
for c in rev:
    for x in chain_of(c, 20):
        if x == mgr_cls:
            mgr_classes.append(c)
            break
print("manager classes: %s" % ["0x%X" % c for c in mgr_classes], flush=True)

for mc in mgr_classes:
    for ii, o in rev.get(mc, ()):
        print("-- mgr instance ii=%d obj=0x%X chain=%s" % (ii, o, fmt(u64(o + 0x10))), flush=True)
        d = u64(o + 0x130)
        n = u32(o + 0x138)
        print("   stack: data=0x%X n=%d" % (d, n), flush=True)
        for k in range(min(n, 12)):
            try:
                b = mem.rpm(d + 24 * k, 24)
            except OSError:
                break
            q = struct.unpack("<QQQ", b)
            print("   entry%d raw: %016X %016X %016X" % (k, q[0], q[1], q[2]), flush=True)
            for foff in (0, 4, 8, 12, 16, 20):
                v = struct.unpack_from("<I", b, foff)[0]
                if 0 < v < count0:
                    eo = resolve(v)
                    if eo:
                        ch = fmt(u64(eo + 0x10))
                        mark = ""
                        if "Pause" in ch or "Tutorial" in ch or "HMQ" in ch or "Slot" in ch or "Widget" in ch:
                            mark = " <--"
                        print("      +%d -> ii=%d obj=0x%X chain=%s%s" % (
                            foff, v, eo, ch, mark), flush=True)
        print("   ctx +0x120..+0x160:", flush=True)
        for off in range(0x120, 0x160, 8):
            print("      +0x%X: %016X" % (off, u64(o + off)), flush=True)

print("\n-- ii=497123 now --", flush=True)
o = resolve(497123)
print("obj=0x%X flags=0x%X" % (o, u32(o + 8)), flush=True)
if o:
    print("chain=%s" % fmt(u64(o + 0x10)), flush=True)

print("\n-- player sanity --", flush=True)
pccls = u64(gb + GAME_RVA["ATouristPlayerController"])
pc = 0
for c in rev:
    if pccls in chain_of(c, 20):
        for ii, o in rev.get(c, ()):
            pc = o
        if pc:
            break
if pc:
    pawn = u64(pc + 0x330)
    hud = u64(pc + 0x390)
    hc = u64(pawn + 0x668)
    hp = struct.unpack("<f", mem.rpm(hc + 0x2AC, 4))[0] if hc else -1
    print("pc=0x%X pawn=0x%X hud=0x%X hp=%.2f menus=%d" % (
        pc, pawn, hud, hp, u32(hud + 0x4BC)), flush=True)

print("DONE", flush=True)
mem.close()
