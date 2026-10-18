"""probe10: object map - pawn's gun/components, PC's widgets, outers."""
import struct, sys
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
    "ATouristPlayerController": 0xF6F168, "AFirstPersonPlayerCharacter": 0xF5E948,
    "ATouristCharacter": 0xF6C4C8, "UHealthComponent": 0xF5FAF8,
    "UAltFireComponent": 0xF57B90, "UFocusAimComponent": 0xF5EBE0,
    "UGunComponent": 0xF5F558, "UReloadingClip": 0xF68360,
    "UOverheatingClip": 0xF64878, "UGunClip": 0xF5F3B8,
    "ATouristHUD": 0xF6EB10, "UTouristScreenManager": 0xF6FED8,
    "UPauseMenu": 0xF64B88, "UCrosshairWidget": 0xF5BA58,
    "UTouristTutorialWidget": 0xF704A0, "UPlayerHUDInfo": 0xF67038,
    "AGunBase": 0xF5F330, "APlayerGun": 0xF66660,
    "UWeaponManagerComponent": 0xF70E70, "UCameraModifier_FocusAim": 0xF5A900,
    "UCameraModifier_AltFireMode": 0xF5A878, "UFixedClip": 0xF5EAE0,
    "UWeaponClip": 0xF679A8, "UNotificationWidget": 0xF64280,
    "UTouristTutorialPanel": 0xF70460,
}
HMQ_RVA = {
    "UHMQScreenManager": 0xA3188, "UHMQScreenWidget": 0xA32E8,
    "UHMQSubtitlesWidget": 0xA33A8, "UHMQSubtitlePlayer": 0xA3370,
}
bases = {}
for nm, rva in GAME_RVA.items():
    bases[nm] = u64(gb + rva)
for nm, rva in HMQ_RVA.items():
    bases[nm] = u64(hmq + rva)


name_by_ptr = {v: k for k, v in bases.items()}


def chain(c, limit=20):
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


def hit_test(p):
    try:
        c = u64(p + 0x10)
    except OSError:
        return None
    if c < 0x10000:
        return None
    for b in chain(c, 16):
        nm = name_by_ptr.get(b)
        if nm:
            return nm
    return None


def scan_for(obj, span):
    out = []
    try:
        raw = mem.rpm(obj, span)
    except OSError:
        return out
    for off in range(0, len(raw) - 8, 8):
        p = struct.unpack_from("<Q", raw, off)[0]
        if p < 0x10000 or p > 0x7FFFFFFFFFFF:
            continue
        nm = hit_test(p)
        if nm:
            out.append((off, nm, p))
    return out


PC = 0x3D13D4B60
PAWN = u64(PC + 0x330)
print("PC=0x%X PAWN=0x%X" % (PC, PAWN))

print("--- pawn scan (all matching pointers) ---")
gun_ptr = None
for off, nm, p in scan_for(PAWN, 0x3000):
    line = "  pawn+0x%X %-24s 0x%-11X ii=%-7d outer=0x%X" % (off, nm, p, u32(p + 0x0C), u64(p + 0x20))
    print(line)
    if nm in ("AGunBase", "APlayerGun") and gun_ptr is None:
        gun_ptr = p

print("--- pc scan ---")
for off, nm, p in scan_for(PC, 0x3000):
    print("  pc+0x%X %-24s 0x%-11X ii=%-7d outer=0x%X" % (off, nm, p, u32(p + 0x0C), u64(p + 0x20)))

if gun_ptr:
    print("--- gun 0x%X scan ---" % gun_ptr)
    for off, nm, p in scan_for(gun_ptr, 0x2000):
        line = "  gun+0x%X %-24s 0x%-11X ii=%-7d outer=0x%X" % (off, nm, p, u32(p + 0x0C), u64(p + 0x20))
        try:
            if nm in ("UWeaponClip", "UFixedClip", "UReloadingClip", "UOverheatingClip", "UGunClip"):
                line += " v294=%d v298=%d v29C=%d b2A4=%d b2CF=%d b2CD=%d" % (
                    i32(p + 0x294), i32(p + 0x298), i32(p + 0x29C), u8(p + 0x2A4), u8(p + 0x2CF), u8(p + 0x2CD))
            elif nm == "UFocusAimComponent":
                line += " aim=%d/%d" % (u8(p + 0x179), u8(p + 0x17A))
            elif nm == "UAltFireComponent":
                line += " alt=%d,%d,%d fuel=%d" % (u8(p + 0x271), u8(p + 0x272), u8(p + 0x273), u8(p + 0x27C))
        except OSError:
            line += " (read fail)"
        print(line)

print()
print("--- outers of key components ---")
for tag, p in [("focus_3ED7AC800", 0x3ED7AC800), ("focus_3B6D00E00", 0x3B6D00E00),
               ("altfire_3B01C0650", 0x3B01C0650), ("altfire_3CB898080", 0x3CB898080),
               ("guncomp_1899EF5B00", 0x1899EF5B00), ("guncomp_179C07CC0", 0x179C07CC0),
               ("guncomp_18BE26F200", 0x18BE26F200), ("clip_18786C9FC0", 0x18786C9FC0),
               ("clip_3E288AF80", 0x3E288AF80), ("clip_3ABFAC800", 0x3ABFAC800),
               ("APlayerGun_18C3BA40", 0x18C3BA40), ("AGun_150113B20", 0x150113B20),
               ("AGun_3DA8985F0", 0x3DA8985F0)]:
    try:
        o = u64(p + 0x20)
        g = mem.u64(o + 0x20) if o > 0x10000 else 0
        print("  %-22s 0x%-11X outer=0x%-11X outer.outer=0x%X" % (tag, p, o, g))
    except OSError as e:
        print("  %-22s fail %s" % (tag, e))

print()
print("--- manager 0x3C2B6B200 screen stack ---")
M = 0x3C2B6B200
try:
    n = i32(M + 0x138)
    data = u64(M + 0x130)
    print("screens=%d data=0x%X" % (n, data))
    for k in range(min(n, 6)):
        ent = data + 24 * k
        vals = struct.unpack("<3Q", mem.rpm(ent, 24))
        print("  entry%d: %s" % (k, " ".join("0x%X" % v for v in vals)))
except OSError as e:
    print("fail", e)
mem.close()
