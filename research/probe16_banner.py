"""probe16: identify the 'banner' class family + current screen stack.

Read-only. Dumps:
- class objects at module-global RVAs (UMG 0x21B148.., HMQ 0xA35D0, CoreUObject 0x2F72E8)
  and their full super chains (with known-name resolution),
- live instances of the banner class + their early bytes,
- the current screen stack entries with full chains.
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


def u8(a):
    try:
        return mem.u8(a)
    except OSError:
        return 0xFF


RAW_MODULES = {
    "umg": 0x00007FFC209D0000, "cq": 0x00007FFC231F0000,
    "hmq": 0x00007FFBFE420000,
}

GAME_RVA = {
    "ATouristPlayerController": 0xF6F168, "ATouristHUD": 0xF6EB10,
    "UTouristScreenManager": 0xF6FED8, "UPauseMenu": 0xF64B88,
    "UTouristTutorialWidget": 0xF704A0, "UTouristTutorialPanel": 0xF70460,
}
HMQ_RVA = {
    "UHMQScreenManager": 0xA3188, "UHMQScreenWidget": 0xA32E8,
    "UHMQSubtitlesWidget": 0xA33A8, "UHMQSubtitlePlayer": 0xA3370,
    "hmq_A35D0": 0xA35D0, "hmq_A35D8": 0xA35D8,
}
UMG_RVA = {"umg_21B148": 0x21B148, "umg_21B158": 0x21B158, "umg_21BFA0": 0x21BFA0,
           "umg_21BEB0": 0x21BEB0, "umg_21C1C0": 0x21C1C0}
CU_RVA = {"cu_2F72E8": 0x2F72E8, "cu_2F72F0": 0x2F72F0}

known = {}
for nm, rva in GAME_RVA.items():
    known[u64(gb + rva)] = nm + "(game)"
for nm, rva in HMQ_RVA.items():
    known[u64(hmq + rva)] = nm + "(hmq)"
for nm, rva in UMG_RVA.items():
    v = u64(RAW_MODULES["umg"] + rva)
    known[v] = nm + "(umg)"
    print("%-10s @umg+0x%X -> 0x%X" % (nm, rva, v), flush=True)
for nm, rva in CU_RVA.items():
    v = u64(RAW_MODULES["cq"] + rva)
    known[v] = nm + "(cu)"
    print("%-10s @cu+0x%X -> 0x%X" % (nm, rva, v), flush=True)


def chain_full(c, limit=14):
    out, seen = [], set()
    while c and c not in seen and len(out) < limit:
        seen.add(c)
        out.append(c)
        c = u64(c + 0x40)
    return out


def fmt_chain(c, limit=12):
    parts = []
    for x in chain_full(c, limit):
        nm = known.get(x)
        parts.append(("%s(0x%X)" % (nm, x)) if nm else ("0x%X" % x))
    return "/".join(parts)


print("== class chains of module globals ==", flush=True)
for nm, rva in UMG_RVA.items():
    v = u64(RAW_MODULES["umg"] + rva)
    if v:
        print("%-12s 0x%X chain=%s" % (nm, v, fmt_chain(v, 10)), flush=True)
for nm, rva in CU_RVA.items():
    v = u64(RAW_MODULES["cq"] + rva)
    if v:
        print("%-12s 0x%X chain=%s" % (nm, v, fmt_chain(v, 10)), flush=True)
v = u64(hmq + 0xA35D0)
print("%-12s 0x%X chain=%s" % ("hmq_A35D0", v, fmt_chain(v, 10)), flush=True)

banner_c1 = u64(RAW_MODULES["umg"] + 0x21B148)
target_cls = {
    "bannerC1": banner_c1,
    "bannerC2": u64(RAW_MODULES["umg"] + 0x21B158),
    "umg_21BFA0": u64(RAW_MODULES["umg"] + 0x21BFA0),
    "umg_21BEB0": u64(RAW_MODULES["umg"] + 0x21BEB0),
    "umg_21C1C0": u64(RAW_MODULES["umg"] + 0x21C1C0),
    "hmqA35D0": u64(hmq + 0xA35D0),
    "PauseMenu": u64(gb + GAME_RVA["UPauseMenu"]),
    "TutPanel": u64(gb + GAME_RVA["UTouristTutorialPanel"]),
    "TutWidget": u64(gb + GAME_RVA["UTouristTutorialWidget"]),
    "ScreenMgr": u64(gb + GAME_RVA["UTouristScreenManager"]),
    "HMQScreenMgr": u64(hmq + HMQ_RVA["UHMQScreenManager"]),
    "SubsWidget": u64(hmq + HMQ_RVA["UHMQSubtitlesWidget"]),
    "SubPlayer": u64(hmq + HMQ_RVA["UHMQSubtitlePlayer"]),
}
rev = {}
found = {k: [] for k in target_cls}

gua = u64(gb + h.RVA_GUOBJECTARRAY_IAT)
ct0 = u64(gua + h.OFF_GUA_CHUNKTABLE)
count0 = u32(gua + h.OFF_GUA_COUNT)
print("\ngua=0x%X count=%d" % (gua, count0), flush=True)

idx = 0
cch = {}
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
            t = target_cls.get(c)
            if t is not None:
                found[t].append((ii, o))
    idx = (cn + 1) << 16

print("\n== exact-class instance counts ==", flush=True)
for nm, lst in found.items():
    print("  %-12s n=%d %s" % (nm, len(lst),
          " ".join("ii=%d@0x%X" % t for t in lst[:6])), flush=True)

print("\n== banner instance bytes ==", flush=True)
for ii, o in found["bannerC1"][:3]:
    try:
        blob = mem.rpm(o, 0x90)
    except OSError:
        continue
    print("ii=%d obj=0x%X" % (ii, o), flush=True)
    for row in range(0, 0x90, 16):
        qs = struct.unpack_from("<QQ", blob, row)
        print("   +0x%02X: %016X %016X" % (row, qs[0], qs[1]), flush=True)
    for off in range(0, 0x90, 8):
        p = struct.unpack_from("<Q", blob, off)[0]
        if p and p in known:
            print("     +0x%02X -> %s" % (off, known[p]), flush=True)

print("\n== original banner entry object 0x1861DF56E0 ==", flush=True)
o = 0x1861DF56E0
c = u64(o + 0x10)
print("class=0x%X chain=%s flags=0x%X" % (c, fmt_chain(c, 10), u32(o + 8)), flush=True)
try:
    blob = mem.rpm(o, 0x90)
    for row in range(0, 0x90, 16):
        qs = struct.unpack_from("<QQ", blob, row)
        print("   +0x%02X: %016X %016X" % (row, qs[0], qs[1]), flush=True)
except OSError:
    print("   unreadable (freed)", flush=True)

print("\n== current screen stack ==", flush=True)
mgr = found["ScreenMgr"][0][1] if found["ScreenMgr"] else 0
if mgr:
    d = u64(mgr + 0x130)
    n = u32(mgr + 0x138)
    print("mgr=0x%X n=%d data=0x%X" % (mgr, n, d), flush=True)
    for k in range(min(n, 10)):
        try:
            b = mem.rpm(d + 24 * k, 24)
        except OSError:
            break
        eii = struct.unpack_from("<I", b, 16)[0]
        e_ = struct.unpack_from("<QQQ", b)
        eo = 0
        ecn = eii >> 16
        ecb = cch.get(ecn)
        if ecb:
            eo = u64(ecb + 24 * (eii & 0xFFFF))
        echain = fmt_chain(u64(eo + 0x10)) if eo else "?"
        print("  entry%d raw=%016X %016X %016X" % (k, e_[0], e_[1], e_[2]), flush=True)
        print("      ii=%d obj=0x%X chain=%s" % (eii, eo, echain), flush=True)
else:
    print("screen manager instance not found", flush=True)

print("DONE", flush=True)
mem.close()
