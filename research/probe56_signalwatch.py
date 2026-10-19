"""probe56_signalwatch.py - read-only change logger for drive verification.

Watches the live player chain each poll (default 5 Hz): pawn -> gun ->
clip + alt-fire component, the InteractionManager on the pawn, the
SayManager queue, and health. Prints a line only when a value changes,
plus a full snapshot every 5 seconds. Never writes anything.
"""
import time

import probe_lib as P

P.set_log(r"C:\Users\admin\AppData\Local\Temp\opencode\probe56.out")
P.say("=== probe56 signal watch %s (read-only) ===" % time.strftime("%H:%M:%S"))
P.init()
P.build_names()

PC_OFF = 0x330
PAWN_HEALTH = 0x668
PAWN_IMC = 0x820
PAWN_GUN1 = 0x1028
GUN_CLIP = 0x908
GUN_ALTFIRE = 0xC80
CLIP_AMMO = 0x1A8
CLIP_RELOAD = 0x1B4
ALT_W = 0x270
ALT_MODE = 0x271
ALT_FIRING = 0x272
ALT_SHOT = 0x273
ALT_FUEL = 0x274
ALT_FUELSTATE = 0x27C
ALT_READY = 0x348
IMC_SEL = 0x190
IMC_FOC = 0x198
IMC_MODE = 0x229
IMC_OVR = 0x230
HC_HP = 0x2AC
SAY_NUM = 0x1C8
SAY_MAX = 0x1CC

PAWN = [0]
SAY = [0]


def rd(fn, a, default=None):
    try:
        return fn(a)
    except OSError:
        return default


def find_pawn():
    best = 0
    for obj, nm, cn, c in P.iter_objects():
        if cn == "BP_PlayerCharacter_C" and not nm.startswith("Default__"):
            best = obj
    return best


def find_say():
    best = 0
    for obj, nm, cn, c in P.iter_objects():
        if not nm.startswith("Default__") and "SayManager" in cn:
            best = obj          # GUA order: last = newest InternalIndex
    return best


def fmt(v):
    if isinstance(v, float):
        return "%.3f" % v
    if isinstance(v, int) and v > 0xFFFF:
        return "0x%X" % v
    return str(v)


def snap():
    s = {}
    pawn = PAWN[0]
    s["pawn"] = pawn
    gun = rd(P.u64, pawn + PAWN_GUN1)
    s["gun"] = gun
    if gun:
        clip = rd(P.u64, gun + GUN_CLIP)
        s["clip"] = clip
        if clip:
            s["ammo"] = rd(P.f32, clip + CLIP_AMMO)
            s["rl"] = rd(P.u8, clip + CLIP_RELOAD)
        af = rd(P.u64, gun + GUN_ALTFIRE)
        s["af"] = af
        if af:
            s["w"] = rd(P.u8, af + ALT_W)
            s["mode"] = rd(P.u8, af + ALT_MODE)
            s["firing"] = rd(P.u8, af + ALT_FIRING)
            s["shot"] = rd(P.u8, af + ALT_SHOT)
            s["fuel"] = rd(P.f32, af + ALT_FUEL)
            s["fstate"] = rd(P.u32, af + ALT_FUELSTATE)
            s["rdy"] = rd(P.u8, af + ALT_READY)
    imc = rd(P.u64, pawn + PAWN_IMC)
    s["imc"] = imc
    if imc:
        s["sel"] = rd(P.u64, imc + IMC_SEL)
        s["foc"] = rd(P.u64, imc + IMC_FOC)
        s["ovr"] = rd(P.u64, imc + IMC_OVR)
        s["md"] = rd(P.u8, imc + IMC_MODE)
    hc = rd(P.u64, pawn + PAWN_HEALTH)
    s["hc"] = hc
    if hc:
        s["hp"] = rd(P.f32, hc + HC_HP)
    say = SAY[0]
    s["say"] = rd(P.u32, say + SAY_NUM)
    s["saymax"] = rd(P.u32, say + SAY_MAX)
    return s


PAWN[0] = find_pawn()
P.say("pawn=0x%X" % PAWN[0])
SAY[0] = find_say()
P.say("say=0x%X" % SAY[0])

prev = {}
t0 = time.time()
last_snap = -10.0
last_refind = t0
while True:
    now = time.time()
    el = now - t0
    if not PAWN[0] or rd(P.u64, PAWN[0] + 0x10, 0) is None:
        if now - last_refind > 5.0:
            last_refind = now
            PAWN[0] = find_pawn()
            SAY[0] = find_say()
            P.say("t=%6.1f REFIND pawn=0x%X say=0x%X" % (el, PAWN[0], SAY[0]))
    s = snap()
    if s != prev:
        ch = {k: v for k, v in s.items() if prev.get(k) != v}
        P.say("t=%6.1f %s" % (el, " ".join("%s=%s" % (k, fmt(v))
                                           for k, v in ch.items())))
        prev = s
    if el - last_snap >= 5.0:
        last_snap = el
        P.say("SNAP t=%6.1f %s" % (el, " ".join("%s=%s" % (k, fmt(v))
                                                for k, v in s.items())))
    time.sleep(0.2)
