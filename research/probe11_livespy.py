"""probe11_livespy: change-only live watcher for hud_dynamic signal development.

Usage: python -u probe11_livespy.py [duration_seconds]
"""
import struct
import sys
import time

sys.path.insert(0, ".")
import hud_dynamic as h

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0

GAME_RVA = {
    "ATouristPlayerController": 0xF6F168, "AFirstPersonPlayerCharacter": 0xF5E948,
    "ATouristCharacter": 0xF6C4C8, "UHealthComponent": 0xF5FAF8,
    "UAltFireComponent": 0xF57B90, "UFocusAimComponent": 0xF5EBE0,
    "UGunComponent": 0xF5F558, "UReloadingClip": 0xF68360,
    "UOverheatingClip": 0xF64878, "UGunClip": 0xF5F3B8,
    "ATouristHUD": 0xF6EB10, "UTouristScreenManager": 0xF6FED8,
    "UPauseMenu": 0xF64B88, "UCrosshairWidget": 0xF5BA58,
    "UTouristTutorialWidget": 0xF704A0, "UPlayerHUDInfo": 0xF67038,
    "AGunBase": 0xF5F330, "APlayerGun": 0xF66660,
    "UWeaponManagerComponent": 0xF70E70, "UFixedClip": 0xF5EAE0,
    "UWeaponClip": 0xF679A8, "UNotificationWidget": 0xF64280,
    "UTouristTutorialPanel": 0xF70460,
}
HMQ_RVA = {
    "UHMQScreenManager": 0xA3188, "UHMQScreenWidget": 0xA32E8,
    "UHMQSubtitlesWidget": 0xA33A8, "UHMQSubtitlePlayer": 0xA3370,
}

UI_WATCH = {
    "UTouristTutorialWidget", "UTouristTutorialPanel", "UNotificationWidget",
    "UHMQSubtitlePlayer", "UHMQSubtitlesWidget", "UPauseMenu",
    "UCrosshairWidget", "UTouristScreenManager", "ATouristHUD",
}

pid = h.find_process_id(h.GAME_EXE)
mods = h.module_bases(pid, {h.GAME_DLL.lower(), "returnal-hmqscreen-win64-shipping.dll"})
gb = mods[h.GAME_DLL.lower()]
hmq = mods["returnal-hmqscreen-win64-shipping.dll"]
mem = h.ProcessMem(pid, read_only=True)

T0 = time.time()


def u64(a):
    return mem.u64(a)


def u32(a):
    return mem.u32(a)


def u8(a):
    return mem.u8(a)


def raw(a, n):
    try:
        return mem.rpm(a, n)
    except OSError:
        return None


def sl(v):
    if v >= 0x7FFFFFFFFFFF:
        return "0x%X" % v
    return str(v)


def f32b(b, off):
    if b is None or off + 4 > len(b):
        return 0.0
    return struct.unpack_from("<f", b, off)[0]


bases = {}
for _nm, _rva in GAME_RVA.items():
    bases[_nm] = u64(gb + _rva)
for _nm, _rva in HMQ_RVA.items():
    bases[_nm] = u64(hmq + _rva)
name_by_ptr = {v: k for k, v in bases.items()}


def chain(c, limit=24):
    out = []
    seen = set()
    for _ in range(limit):
        if not c or c in seen:
            break
        seen.add(c)
        out.append(c)
        try:
            c = u64(c + 0x40)
        except OSError:
            break
    return out


def chain_names(c, limit=8):
    return [name_by_ptr.get(x, "0x%X" % x) for x in chain(c, limit)]


def valid_comp(p, base_name, limit=16):
    if p < 0x10000:
        return 0
    try:
        if bases[base_name] in chain(u64(p + 0x10), limit):
            return p
    except OSError:
        pass
    return 0


gua = u64(gb + h.RVA_GUOBJECTARRAY_IAT)
OFF_CT = h.OFF_GUA_CHUNKTABLE
OFF_CNT = h.OFF_GUA_COUNT


def gua_obj(idx):
    try:
        ct = u64(gua + OFF_CT)
        if ct < 0x10000:
            return 0
        c = u64(ct + 8 * (idx >> 16))
        if c < 0x10000:
            return 0
        return u64(c + 24 * (idx & 0xFFFF))
    except OSError:
        return 0


print("== livespy start %.1fs ==" % DUR, flush=True)

t_scan = time.time()
ct0 = u64(gua + OFF_CT)
count0 = u32(gua + OFF_CNT)
rev = {}
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
chains = {c: tuple(chain(c)) for c in rev}
print("scan: %d classes %d objs %.1fs" % (len(rev), count0, time.time() - t_scan), flush=True)


def find_live(nm):
    bp = bases[nm]
    out = []
    for c, ch in chains.items():
        if bp in ch:
            for o in rev.get(c, ()):
                try:
                    if u32(o + 8) & 0x10:
                        continue
                except OSError:
                    continue
                out.append(o)
    return out


PC = 0
PAWN = 0
HC = 0
for o in find_live("ATouristPlayerController"):
    try:
        p = u64(o + 0x330)
        if not p:
            continue
        hc = u64(p + 0x668)
        if not hc:
            continue
        if bases["UHealthComponent"] in chain(u64(hc + 0x10), 12):
            PC, PAWN, HC = o, p, hc
            break
    except OSError:
        pass

FOCUS = 0
GUN = 0
GUN2 = 0
CLIP = 0
CLIP2 = 0
ALTFIRE = 0
HUD = 0
MGR = 0
if PC:
    try:
        FOCUS = valid_comp(u64(PAWN + 0xEB8), "UFocusAimComponent")
        GUN = valid_comp(u64(PAWN + 0x1028), "AGunBase")
        GUN2 = valid_comp(u64(PAWN + 0x1040), "AGunBase")
        CLIP = valid_comp(u64(GUN + 0x908), "UWeaponClip") if GUN else 0
        CLIP2 = valid_comp(u64(GUN2 + 0x908), "UWeaponClip") if GUN2 else 0
        ALTFIRE = valid_comp(u64(GUN + 0xC80), "UAltFireComponent") if GUN else 0
        HUD = valid_comp(u64(PC + 0x390), "ATouristHUD")
    except OSError as e:
        print("WARN ptr resolve:", e, flush=True)
    cands = []
    for o in find_live("UTouristScreenManager"):
        try:
            d = u64(o + 0x130)
            n = u32(o + 0x138)
            ii = u32(o + 0x0C)
            cands.append(((1 if d else 0, 1 if n else 0, ii), o, d, n))
        except OSError:
            pass
    if cands:
        cands.sort(reverse=True)
        MGR = cands[0][1]

print("MAP pc=0x%X pawn=0x%X hc=0x%X focus=0x%X gun=0x%X gun2=0x%X clip=0x%X clip2=0x%X alt=0x%X hud=0x%X mgr=0x%X" % (
    PC, PAWN, HC, FOCUS, GUN, GUN2, CLIP, CLIP2, ALTFIRE, HUD, MGR), flush=True)
if MGR:
    pass

REGIONS = []
if HC:
    REGIONS.append(("hc", HC, 0x280, 0x350))
if FOCUS:
    REGIONS.append(("focus", FOCUS, 0x150, 0x1B0))
if ALTFIRE:
    REGIONS.append(("alt", ALTFIRE, 0x240, 0x2B0))
if CLIP:
    REGIONS.append(("clip", CLIP, 0x270, 0x340))
if CLIP2:
    REGIONS.append(("clip2", CLIP2, 0x270, 0x340))
if GUN:
    REGIONS.append(("gun", GUN, 0x8D0, 0x940))
if HUD:
    REGIONS.append(("hud", HUD, 0x400, 0x540))
if PC:
    REGIONS.append(("pc", PC, 0x750, 0x880))
if PAWN:
    REGIONS.append(("pawns", PAWN, 0x1018, 0x1050))
for o in find_live("UCrosshairWidget")[:2]:
    REGIONS.append(("xhair", o, 0x820, 0x860))
for o in find_live("UTouristTutorialWidget")[:3]:
    REGIONS.append(("tutw", o, 0x700, 0x780))
for o in find_live("UTouristTutorialPanel")[:2]:
    REGIONS.append(("tutp", o, 0x700, 0x780))
for o in find_live("UNotificationWidget")[:2]:
    REGIONS.append(("notif", o, 0x700, 0x780))

last = {}


def read_mgr_stack():
    """Returns (n, tuple of entry strings) or None."""
    if not MGR:
        return None
    try:
        n = u32(MGR + 0x138)
        data = u64(MGR + 0x130)
    except OSError:
        return None
    if n > 64:
        n = 0
    ents = []
    for k in range(n):
        if not data:
            break
        b = raw(data + 24 * k, 24)
        if not b:
            ents.append("?")
            continue
        ii = struct.unpack_from("<I", b, 16)[0]
        o = gua_obj(ii)
        nm = "-"
        if o:
            try:
                nm = "/".join(chain_names(u64(o + 0x10), 6))
            except OSError:
                nm = "?"
        ents.append("%s(%d@0x%X)" % (nm, ii, o))
    return (n, tuple(ents))


PCW = [0x678, 0x758, 0x779, 0x77B, 0x798, 0x800, 0x802, 0x820, 0x828, 0x854, 0x870]
last_pc = None
last_stack = None
last_hb = 0.0
last_tail = 0.0
tail_at = count0

print("-- watching; actions -- ", flush=True)
t_end = T0 + DUR + 6
while time.time() < t_end:
    tk = time.time() - T0
    if tk > DUR:
        break
    # pawn/gun re-resolution
    if PC:
        try:
            pp = u64(PC + 0x330)
            if pp and pp != PAWN:
                print("%6.2f PAWN CHANGED 0x%X -> 0x%X" % (tk, PAWN, pp), flush=True)
                PAWN = pp
                HC = valid_comp(u64(PAWN + 0x668), "UHealthComponent")
                FOCUS = valid_comp(u64(PAWN + 0xEB8), "UFocusAimComponent")
                GUN = valid_comp(u64(PAWN + 0x1028), "AGunBase")
                GUN2 = valid_comp(u64(PAWN + 0x1040), "AGunBase")
                CLIP = valid_comp(u64(GUN + 0x908), "UWeaponClip") if GUN else 0
                CLIP2 = valid_comp(u64(GUN2 + 0x908), "UWeaponClip") if GUN2 else 0
                ALTFIRE = valid_comp(u64(GUN + 0xC80), "UAltFireComponent") if GUN else 0
        except OSError:
            pass
        try:
            g = u64(PAWN + 0x1028)
            if g and g != GUN:
                print("%6.2f GUN SLOT1 CHANGED 0x%X -> 0x%X" % (tk, GUN, g), flush=True)
                GUN = valid_comp(g, "AGunBase")
                CLIP = valid_comp(u64(GUN + 0x908), "UWeaponClip") if GUN else 0
                ALTFIRE = valid_comp(u64(GUN + 0xC80), "UAltFireComponent") if GUN else 0
        except OSError:
            pass
    # region diffs
    for nm, obj, a0, a1 in REGIONS:
        b = raw(obj + a0, a1 - a0)
        if not b:
            continue
        key = (nm, obj)
        lb = last.get(key)
        last[key] = b
        if lb is None or len(lb) != len(b):
            continue
        off = 0
        while off + 4 <= len(b):
            if lb[off:off + 4] != b[off:off + 4]:
                old = struct.unpack_from("<i", lb, off)[0]
                new = struct.unpack_from("<i", b, off)[0]
                oldf = struct.unpack_from("<f", lb, off)[0]
                newf = struct.unpack_from("<f", b, off)[0]
                print("%6.2f %-6s 0x%X+0x%03X: %d->%d (f %.4f->%.4f)" % (
                    tk, nm, obj, a0 + off, old, new, oldf, newf), flush=True)
            off += 4
    # pc flags
    if PC:
        vals = []
        for o in PCW:
            try:
                vals.append(u64(PC + o) if o == 0x798 else u8(PC + o))
            except OSError:
                vals.append(-1)
        vt = tuple(vals)
        if vt != last_pc:
            print("%6.2f pcflags %s" % (tk, " ".join("+0x%X=%s" % (o, sl(v)) for o, v in zip(PCW, vals))), flush=True)
            last_pc = vt
    # mgr stack
    st = read_mgr_stack()
    if st is not None and st != last_stack:
        print("%6.2f MGR stack n=%d %s" % (tk, st[0], " ".join(st[1])), flush=True)
        last_stack = st
    # new UI objects tail scan every 2s
    if tk - last_tail > 2.0:
        last_tail = tk
        try:
            cnt = u32(gua + OFF_CNT)
        except OSError:
            cnt = tail_at
        if cnt > tail_at:
            for i in range(tail_at, min(cnt, tail_at + 30000)):
                o = gua_obj(i)
                if not o:
                    continue
                try:
                    c = u64(o + 0x10)
                    if not c:
                        continue
                    names = chain(c, 16)
                    hit = None
                    for x in names:
                        n2 = name_by_ptr.get(x)
                        if n2 in UI_WATCH:
                            hit = n2
                            break
                    if hit:
                        print("%6.2f NEW %s 0x%X ii=%d cls=0x%X" % (tk, hit, o, i, c), flush=True)
                except OSError:
                    pass
        tail_at = cnt
    # heartbeat
    if tk - last_hb > 5.0:
        last_hb = tk
        extra = ""
        try:
            if HC:
                hp = f32b(raw(HC + 0x2A0, 0x60), 0x0C)
                extra = " hp=%.2f" % hp
        except Exception:
            pass
        try:
            cnt = u32(gua + OFF_CNT)
        except OSError:
            cnt = 0
        stn = last_stack[0] if last_stack else -1
        print("%6.2f HB objs=%d mgr=%d%s" % (tk, cnt, stn, extra), flush=True)
    time.sleep(0.25)

print("DONE %.1f" % (time.time() - T0), flush=True)
mem.close()
