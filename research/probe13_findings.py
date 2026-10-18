"""probe13: identify stack-entry objects from live_run2.out + inventory live
tutorial/subtitle/widget instances. Read-only."""
import struct
import sys
import time

sys.path.insert(0, ".")
import hud_dynamic as h

GAME_RVA = {
    "ATouristPlayerController": 0xF6F168, "ATouristHUD": 0xF6EB10,
    "UTouristScreenManager": 0xF6FED8, "UPauseMenu": 0xF64B88,
    "UTouristTutorialWidget": 0xF704A0, "UTouristTutorialPanel": 0xF70460,
    "UNotificationWidget": 0xF64280, "UHealthComponent": 0xF5FAF8,
    "UFocusAimComponent": 0xF5EBE0, "AGunBase": 0xF5F330,
    "UWeaponClip": 0xF679A8, "UAltFireComponent": 0xF57B90,
}
HMQ_RVA = {
    "UHMQScreenManager": 0xA3188, "UHMQScreenWidget": 0xA32E8,
    "UHMQSubtitlesWidget": 0xA33A8, "UHMQSubtitlePlayer": 0xA3370,
}

pid = h.find_process_id(h.GAME_EXE)
mods = h.module_bases(pid, {h.GAME_DLL.lower(), h.HMQ_DLL.lower()})
gb = mods[h.GAME_DLL.lower()]
hmq = mods[h.HMQ_DLL.lower()]
mem = h.ProcessMem(pid, read_only=True)


def u64(a):
    return mem.u64(a)


def u32(a):
    return mem.u32(a)


def raw(a, n):
    try:
        return mem.rpm(a, n)
    except OSError:
        return None


bases = {}
for nm, rva in GAME_RVA.items():
    bases[nm] = u64(gb + rva)
for nm, rva in HMQ_RVA.items():
    bases[nm] = u64(hmq + rva)
name_by_ptr = {v: k for k, v in bases.items()}


def chain(c, limit=24):
    out, seen = [], set()
    while c and c not in seen and len(out) < limit:
        seen.add(c)
        out.append(c)
        try:
            c = u64(c + 0x40)
        except OSError:
            break
    return out


def cnames(c, limit=8):
    return [name_by_ptr.get(x, "0x%X" % x) for x in chain(c, limit)]


gua = u64(gb + h.RVA_GUOBJECTARRAY_IAT)


def gua_obj(idx):
    ct = u64(gua + h.OFF_GUA_CHUNKTABLE)
    cb = u64(ct + 8 * (idx >> 16))
    return u64(cb + 24 * (idx & 0xFFFF))


print("== probe13 start ==", flush=True)
t0 = time.time()
ct0 = u64(gua + h.OFF_GUA_CHUNKTABLE)
count0 = u32(gua + h.OFF_GUA_COUNT)
rev = {}
cch = {}
idx = 0
while idx < count0:
    cn = idx >> 16
    cb = cch.get(cn)
    if cb is None:
        cb = u64(ct0 + 8 * cn) if ct0 > 0x10000 else 0
        cch[cn] = cb
    here = min(0x10000, count0 - (cn << 16))
    if cb and cb > 0x10000:
        b = raw(cb, here * 24)
        if b:
            for j in range(here):
                o = struct.unpack_from("<Q", b, j * 24)[0]
                if not o:
                    continue
                if struct.unpack_from("<I", b, j * 24 + 8)[0] & 0x20000000:
                    continue
                c = u64(o + 0x10)
                if c:
                    rev.setdefault(c, []).append(o)
    idx = (cn + 1) << 16
chains_cache = {c: tuple(chain(c)) for c in rev}
print("scan: %d classes %d objs %.1fs" % (len(rev), count0, time.time() - t0), flush=True)

for i in (497123, 505489, 500160, 505554, 425611, 425478):
    o = gua_obj(i)
    if o:
        try:
            c = u64(o + 0x10)
            fl = u32(o + 8)
            print("ii=%-7d obj=0x%-12X flags=0x%X chain=%s" % (
                i, o, fl, "/".join(cnames(c, 7))), flush=True)
        except OSError:
            print("ii=%-7d obj=0x%-12X unreadable" % (i, o), flush=True)
    else:
        print("ii=%-7d (not resolvable)" % i, flush=True)

print("-- live instances --", flush=True)
for nm in ("UTouristTutorialWidget", "UTouristTutorialPanel", "UNotificationWidget",
           "UPauseMenu", "UHMQSubtitlesWidget", "UHMQSubtitlePlayer",
           "UHMQScreenWidget"):
    bph = bases.get(nm, 0)
    if not bph:
        continue
    hits = []
    for c, ch in chains_cache.items():
        if bph in ch:
            for o in rev.get(c, ()):
                try:
                    fl = u32(o + 8)
                except OSError:
                    continue
                if fl & 0x10:
                    continue
                if fl & 0x20000000:
                    continue
                hits.append((u32(o + 0x0C), o))
    hits.sort()
    print("%-28s live=%d %s" % (nm, len(hits),
          " ".join("%d@0x%X" % (ii, o) for ii, o in hits[:12])), flush=True)

# current screen stack
mgr = 0
for o in rev.get(bases["UTouristScreenManager"], ()):
    try:
        d = u64(o + 0x130)
        n = u32(o + 0x138)
        mgr = o
        print("mgr=0x%X n=%d" % (o, n), flush=True)
        for k in range(min(n, 8)):
            b = raw(d + 24 * k, 24)
            if not b:
                break
            eii = struct.unpack_from("<I", b, 16)[0]
            eo = gua_obj(eii)
            ec = u64(eo + 0x10) if eo else 0
            print("  entry%d ii=%d obj=0x%X chain=%s" % (
                k, eii, eo, "/".join(cnames(ec, 5))), flush=True)
        break
    except OSError:
        continue

# signal sanity
pc = 0
for c, ch in chains_cache.items():
    if bases["ATouristPlayerController"] in ch:
        for o in rev.get(c, ()):
            if not (u32(o + 8) & 0x10):
                pc = o
if pc:
    pawn = u64(pc + 0x330)
    hud = u64(pc + 0x390)
    hc = u64(pawn + 0x668)
    print("pc=0x%X pawn=0x%X hc=0x%X hud=0x%X" % (pc, pawn, hc, hud), flush=True)
    try:
        print("  hp=%.2f menus=%d aim=%d" % (
            struct.unpack("<f", raw(hc + 0x2AC, 4))[0], u32(hud + 0x4BC),
            mem.u8(hud + 0x514)), flush=True)
    except OSError:
        pass
print("DONE %.1f" % (time.time() - t0), flush=True)
mem.close()
