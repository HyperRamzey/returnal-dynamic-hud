"""probe9: corrected subclass discovery (SuperStruct @ +0x40) + live state read."""
import struct, sys, time
sys.path.insert(0, ".")
import hud_dynamic as h

pid = h.find_process_id(h.GAME_EXE)
mods = h.module_bases(pid, {h.GAME_DLL.lower(), "returnal-hmqscreen-win64-shipping.dll"})
gb = mods[h.GAME_DLL.lower()]
hmq = mods["returnal-hmqscreen-win64-shipping.dll"]
mem = h.ProcessMem(pid, read_only=True)


def u64(a):
    return mem.u64(a)


def u32(a):
    return mem.u32(a)


def u8(a):
    return mem.u8(a)


def i32(a):
    return struct.unpack("<i", mem.rpm(a, 4))[0]


def f32(a):
    return struct.unpack("<f", mem.rpm(a, 4))[0]


GAME_RVA = {
    "ATouristPlayerController": 0xF6F168,
    "AFirstPersonPlayerCharacter": 0xF5E948,
    "ATouristCharacter": 0xF6C4C8,
    "UHealthComponent": 0xF5FAF8,
    "UAltFireComponent": 0xF57B90,
    "UFocusAimComponent": 0xF5EBE0,
    "UGunComponent": 0xF5F558,
    "UReloadingClip": 0xF68360,
    "UOverheatingClip": 0xF64878,
    "UGunClip": 0xF5F3B8,
    "ATouristHUD": 0xF6EB10,
    "UTouristScreenManager": 0xF6FED8,
    "UPauseMenu": 0xF64B88,
    "UCrosshairWidget": 0xF5BA58,
    "UTouristTutorialWidget": 0xF704A0,
    "UPlayerHUDInfo": 0xF67038,
    "AGunBase": 0xF5F330,
    "APlayerGun": 0xF66660,
    "UWeaponManagerComponent": 0xF70E70,
    "UCameraModifier_FocusAim": 0xF5A900,
    "UCameraModifier_AltFireMode": 0xF5A878,
    "UFixedClip": 0xF5EAE0,
    "UWeaponClip": 0xF679A8,
    "UNotificationWidget": 0xF64280,
    "UTouristTutorialPanel": 0xF70460,
}
HMQ_RVA = {
    "UHMQScreenManager": 0xA3188,
    "UHMQScreenWidget": 0xA32E8,
    "UHMQSubtitlesWidget": 0xA33A8,
    "UHMQSubtitlePlayer": 0xA3370,
}

bases = {}
for nm, rva in GAME_RVA.items():
    bases[nm] = u64(gb + rva)
for nm, rva in HMQ_RVA.items():
    bases[nm] = u64(hmq + rva)

name_by_ptr = {v: k for k, v in bases.items()}


def nc(p):
    return name_by_ptr.get(p, "0x%X" % p)


def chain(c, limit=30):
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


print("== chain sanity (SuperStruct @ +0x40) ==")
for nm in ("UTouristScreenManager", "ATouristPlayerController", "AFirstPersonPlayerCharacter",
           "UGunClip", "UFocusAimComponent", "UPauseMenu", "UHMQSubtitlesWidget", "APlayerGun"):
    print("  %-30s %s" % (nm, " -> ".join(nc(x) for x in chain(bases[nm])[:10])))

gua = u64(gb + h.RVA_GUOBJECTARRAY_IAT)
ct = u64(gua + h.OFF_GUA_CHUNKTABLE)
count = u32(gua + h.OFF_GUA_COUNT)
rev = {}
t0 = time.time()
idx = 0
cache = {}
while idx < count:
    cn = idx >> 16
    cb = cache.get(cn)
    if cb is None:
        cb = u64(ct + 8 * cn)
        cache[cn] = cb
    here = min(0x10000, count - (cn << 16))
    if cb >= 0x10000:
        raw = mem.rpm(cb, here * 24)
        if raw:
            for j in range(here):
                off = j * 24
                obj = struct.unpack_from("<Q", raw, off)[0]
                if not obj:
                    continue
                if struct.unpack_from("<I", raw, off + 8)[0] & 0x20000000:
                    continue
                c = u64(obj + 0x10)
                if c:
                    rev.setdefault(c, []).append(obj)
    idx = (cn + 1) << 16
print("scan: %d classes, %.1fs" % (len(rev), time.time() - t0))

chains = {c: tuple(chain(c)) for c in rev}


def find(nm):
    bp = bases[nm]
    subs = [c for c, ch in chains.items() if bp in ch]
    out = []
    for c in subs:
        for o in rev.get(c, ()):
            try:
                fl = u32(o + 8)
            except OSError:
                continue
            if fl & 0x10:
                continue
            ii = u32(o + 0x0C)
            out.append((o, c, ii))
    out.sort(key=lambda x: -x[2])
    return out


live = {}
print()
for nm in bases:
    objs = find(nm)
    live[nm] = objs
    print("%-30s live=%-3d %s" % (nm, len(objs), [hex(o) for o, _, _ in objs[:4]]))

print()
for nm in ("ATouristPlayerController", "AFirstPersonPlayerCharacter"):
    for o, c, ii in (live.get(nm) or [])[:3]:
        try:
            p330 = u64(o + 0x330)
            p798 = u64(o + 0x798)
            print("%s 0x%X ii=%d cls=0x%X pawn=0x%X hudinfo=0x%X b820/b870/b678=%d/%d/%d" % (
                nm, o, ii, c, p330, p798, u8(o + 0x820), u8(o + 0x870), u8(o + 0x678)))
            if p330 > 0x10000:
                print("    pawn cls chain: %s" % " -> ".join(nc(x) for x in chain(u64(p330 + 0x10))[:10]))
                hc = u64(p330 + 0x668)
                if hc > 0x10000:
                    print("    pawn hc=0x%X hp=%.2f max=%.2f alive=%d low=%d crit=%d dmg=%d" % (
                        hc, f32(hc + 0x2AC), f32(hc + 0x318), u8(hc + 0x2A8),
                        u8(hc + 0x334), u8(hc + 0x335), u8(hc + 0x33B)))
        except OSError as e:
            print(nm, "0x%X fail %s" % (o, e))

print()
for nm in ("AGunBase", "APlayerGun", "UWeaponManagerComponent", "UCameraModifier_FocusAim", "UCameraModifier_AltFireMode"):
    for o, c, ii in (live.get(nm) or [])[:6]:
        try:
            outer = u64(o + 0x20)
            print("%-26s 0x%-12X ii=%-7d cls=0x%-12X outer=0x%X" % (nm, o, ii, c, outer))
        except OSError as e:
            print(nm, "fail", e)

print()
for nm in ("UFocusAimComponent", "UAltFireComponent", "UGunComponent", "UReloadingClip",
           "UOverheatingClip", "UGunClip", "UFixedClip", "UWeaponClip", "UHealthComponent"):
    for o, c, ii in (live.get(nm) or [])[:6]:
        line = "%-20s 0x%-12X ii=%-7d cls=0x%-12X" % (nm, o, ii, c)
        try:
            if nm == "UFocusAimComponent":
                line += " aim=%d/%d" % (u8(o + 0x179), u8(o + 0x17A))
            elif nm == "UAltFireComponent":
                line += " alt=%d,%d,%d fuel=%d" % (u8(o + 0x271), u8(o + 0x272), u8(o + 0x273), u8(o + 0x27C))
            elif nm == "UReloadingClip":
                line += " bullets=%d fired=%d reloading=%d" % (i32(o + 0x294), i32(o + 0x29C), u8(o + 0x2A4))
            elif nm == "UOverheatingClip":
                line += " heat=%d cooldown=%d,%d" % (i32(o + 0x294), u8(o + 0x2CF), u8(o + 0x2CD))
            elif nm == "UHealthComponent":
                line += " hp=%.1f alive=%d outer=0x%X" % (f32(o + 0x2AC), u8(o + 0x2A8), u64(o + 0x20))
            else:
                line += " v294=%d" % i32(o + 0x294)
        except OSError:
            line += " (read fail)"
        print(line)

print()
for nm in ("UTouristScreenManager", "UHMQScreenManager", "UHMQSubtitlesWidget", "UHMQSubtitlePlayer",
           "UPauseMenu", "UTouristTutorialWidget", "UTouristTutorialPanel", "UNotificationWidget",
           "UCrosshairWidget", "UPlayerHUDInfo", "ATouristHUD"):
    for o, c, ii in (live.get(nm) or [])[:5]:
        line = "%-24s 0x%-12X ii=%-7d cls=0x%-12X" % (nm, o, ii, c)
        try:
            if nm in ("UTouristScreenManager", "UHMQScreenManager"):
                line += " screens=%d data=0x%X" % (i32(o + 0x138), u64(o + 0x130))
            elif nm == "UHMQSubtitlePlayer":
                line += " +0x70=0x%X" % u64(o + 0x70)
            elif nm == "ATouristHUD":
                line += " +420=0x%X +522=%d" % (u64(o + 0x420), u8(o + 0x522))
            line += " outer=0x%X" % u64(o + 0x20)
        except OSError:
            line += " (read fail)"
        print(line)
mem.close()
