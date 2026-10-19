# Reverse-engineering findings

Every offset in this document was located from the shipping binaries and then
**re-verified live** against the running game with read-only memory probes
(see `research/`). Module RVAs are stable across launches; heap pointers are
per-launch and are re-resolved at tool startup.

Session dates: initial mapping 2026-10-12; live re-verification 2026-10-18;
drive verification (v1.4.0: subtitles, interaction, alt-fire) 2026-10-19.

## 1. Binaries / modules

| module | role |
|---|---|
| `Returnal-Win64-Shipping.exe` | game process |
| `Returnal-Returnal-Win64-Shipping.dll` | main game code; class globals, GUObjectArray IAT |
| `Returnal-HMQScreen-Win64-Shipping.dll` | screen/UI framework classes (`UHMQ*`) |
| `Returnal-UMG-Win64-Shipping.dll` | UMG widget framework classes |
| `Returnal-CoreUObject-Win64-Shipping.dll` | UObject core |
| `ShaderToggler.addon64` | ReShade addon that performs the actual shader blocking |

## 2. Object system (Unreal Engine 4.x)

- **GUObjectArray**: game DLL IAT slot `RVA 0x8A15B0` holds `FUObjectArray*`.
- `FUObjectArray +0x10` -> chunk table; `+0x24` -> object count (u32).
- Item stride 24 bytes: `+0x00` object pointer, `+0x08` item flags.
  `0x20000000` marks unreachable entries; a `0x10` bit marks default
  objects — both skipped during discovery scans.
- Object header: `+0x08` ObjectFlags (u32), `+0x0C` InternalIndex (u32 —
  stable, never reused), `+0x10` UClass*, `+0x18` FName, `+0x20` Outer.
- Class hierarchy: `UClass* +0x40` = SuperStruct; walk to name a class.
- Internal index -> object: `chunk = idx >> 16`, `slot = idx & 0xFFFF`,
  `obj = *(chunk_table[chunk] + 24 * slot)`.
- Discovery pattern used by the tool: read a class global (module RVA),
  walk each candidate object's class chain, skip CDO/default objects, pick
  the newest InternalIndex — that is the live instance.

Fix-up 2026-10-18: the 24-byte item has **no class field**; the class must be
read from the object (`+0x10`). A probe round was lost to reading item+16 —
see `docs/PROCESS.md` lessons.

## 3. Class globals (module RVAs)

### game DLL (`Returnal-Returnal-Win64-Shipping.dll`)

| RVA | class |
|---|---|
| 0xF6F168 | ATouristPlayerController |
| 0xF6EB10 | ATouristHUD |
| 0xF6FED8 | UTouristScreenManager |
| 0xF64B88 | UPauseMenu |
| 0xF70460 | UTouristTutorialPanel (persistent tutorial shell) |
| 0xF704A0 | UTouristTutorialWidget |
| 0xF64280 | UNotificationWidget |
| 0xF5FAF8 | UHealthComponent |
| 0xF5EBE0 | UFocusAimComponent |
| 0xF5F330 | AGunBase |
| 0xF679A8 | UWeaponClip |
| 0xF57B90 | UAltFireComponent |
| 0xF5DC28 | AEnemyManager |
| 0xF68F80 | USayManagerComponent (subtitle cue source) |
| 0xF60D58 | UInteractionManagerComponent |

### HMQ DLL (`Returnal-HMQScreen-Win64-Shipping.dll`)

| RVA | class |
|---|---|
| 0xA3188 | UHMQScreenManager |
| 0xA32E8 | UHMQScreenWidget |
| 0xA3370 | UHMQSubtitlePlayer |
| 0xA33A8 | UHMQSubtitlesWidget |
| 0xA35D0 | UHMQUserWidget |

### UMG DLL (`Returnal-UMG-Win64-Shipping.dll`)

| RVA | class |
|---|---|
| 0x21B148 | UOverlaySlot |
| 0x21B158 | UPanelSlot |
| 0x21BFA0 | UVisual |
| 0x21BEB0 | UUserWidget |
| 0x21C1C0 | UWidget |

### CoreUObject DLL (`Returnal-CoreUObject-Win64-Shipping.dll`)

| RVA | class |
|---|---|
| 0x2F72E8 / 0x2F72F0 | UObject (both slots hold the UObject class — chain root) |

Class names were recovered in IDA by looking at what references each `.data`
slot: the referencing symbol is `?Z_Construct_UClass_<Name>@@...`, e.g.
`?Z_Construct_UClass_UOverlaySlot@@YAPEAVUClass@@XZ` for UMG RVA 0x21B148.

Verified example chain (a live pause widget):

```
[BP pause class 0x3D0300FD0] -> UPauseMenu -> UHMQScreenWidget ->
UHMQUserWidget -> UUserWidget -> UWidget -> UVisual -> UObject
```

## 4. Live signals (player / HUD)

Member chain:

```
ATouristPlayerController +0x330 -> pawn, +0x390 -> ATouristHUD
pawn +0x668 -> UHealthComponent, +0xEB8 -> UFocusAimComponent,
     +0x820 -> UInteractionManagerComponent,
     +0x1028 / +0x1040 -> AGunBase slots
AGunBase +0x908 -> UWeaponClip, +0xC80 -> UAltFireComponent
USayManagerComponent (class global 0xF68F80) +0x1C8 -> subtitle cue queue
```

| signal | location | notes |
|---|---|---|
| hp | UHealthComponent+0x2AC | float; 3.0 at full, drops on damage (2.00 observed mid-run) |
| ammo in clip | UWeaponClip+0x1A8 | float; 12 -> 0 observed while firing |
| empty/reloading | UWeaponClip+0x1B4 | byte 1 while empty/reloading; refill ramp observed |
| focus aim | UFocusAimComponent+0x198 != 0 | held while RMB |
| aim backup | ATouristHUD+0x514 | same state |
| open-menu count | ATouristHUD+0x4BC | 0 in gameplay, N = N menus; verified against pause open/close |
| alt-fire | UAltFireComponent+0x271/0x272/0x27C | change-based trigger |
| alt-fire input | UAltFireComponent+0x270 | bWantsToAltFireMode; the G key flips it 0↔1 (live-verified 2026-10-19); the mode byte +0x271 never engages in the test save (alt fire locked) |
| alt-fire ready | UAltFireComponent+0x348 | ready flag (mode active && cooldown done); edge 0→1 raises the alt-ready trigger; not observed live yet (locked save) |
| subtitle cue | USayManagerComponent+0x1C8 (+0x1CC capacity) | entries queue count; num>0 = a cue is playing; legitimately hits 0 in the pauses between lines (flap observed 06:22:27 → 06:22:28) — the tool's 2.5 s tail covers it; full chain in docs/PROCESS.md |
| interaction prompt | UInteractionManagerComponent+0x190/0x198/0x230 | selected / focused / override targets; prompt present = any non-null; all 0 at rest (live 2026-10-19), the non-zero case is not yet observed |
| enemy roster | AEnemyManager+0x838/+0x840 | TArray<AEnemyBase*> {Data, Count}; +0xB70 audio threat |
| enemy combat | AEnemyBase+0x8F0 -> controller +0x480 -> aggression comp, state byte +0x151 | in-combat = {4, 5} (matches `IsInCombat`) |

### Screen stack (UTouristScreenManager)

- `+0x130` data pointer, `+0x138` count; 24-byte entries, max observed n=3.
- **Entry layout (live-verified 2026-10-18)**: bytes 0..15 zero in all
  observed entries; `+16` u32 = main object InternalIndex; `+20` u32 = a
  secondary object index (e.g. the widget's container for a pause screen).
- Entries resolve through the GUObjectArray; class chains classify them.
  Observed entries:
  - **pause menu widget** — chain contains UPauseMenu; appears/disappears
    exactly with menu open/close (verified repeatedly);
  - **persistent `UTouristTutorialPanel` layer** — sits on the stack for
    whole tutorial zones in an earlier session while the HUD hid fine
    (classified "benign" for this reason);
  - **tutorial-prompt entry** (2026-10-18 21:53) — main object was a
    `UOverlaySlot` instance (the prompt animates via its slot); the entry
    lived for the exact duration of the adrenaline-levels tutorial banner,
    then left the stack. This is the case v1.3.0's sustained layer rule fixes;
  - two pause menus at once (pause + inventory screens) in an earlier session;
  - **photo mode** (LENS panel) and the **focus-loss auto-pause** both appear
    as pause-classified entries (2026-10-19); the HUD stays forced visible
    while they are open (intended — the game does not draw the HUD in photo
    mode anyway).
- The stack is empty during plain gameplay in the post-tutorial zone.

## 5. ShaderToggler addon

Details and ini consequences: `docs/SHADERTOGGLER.md`. Summary:

- `std::vector<Record>` globals: begin addon `RVA 0x23AF8`, end `0x23B00`;
  Record = 280 bytes (`0x118`); toggle byte at record `+0x110`.
- `1` = that group's shaders blocked ("hidden"), `0` = draw normally.
- Draw hook `sub_180009FA0` (IDA) blocks; the addon's own key handler flips
  the byte; the tool writes it directly (no input injection).
- Enabled groups (current ini): Group0 "Toggle HUD" {2457571040,
  1844482002}; Group1 {1844482002, 3005719831}; Group2 {1844482002};
  Group3 "Toggle Crosshair" {3005719831}.
- Observed consequences: the crosshair (3005719831) is not in Group0, so it
  keeps drawing with the HUD hidden; tutorial-banner backgrounds use
  shader(s) outside Group0 (leftover boxes when hiding mid-banner); subtitle
  text uses a shader inside Group0 (vanishes while the HUD is hidden).

### 2026-10-20 half-HUD incident (v1.4.1)

Live diagnosis during play: the game was healthy (pawn/hp/ammo/menu chains
all readable: hp 4.2, clip 35, menu open), yet only part of the HUD drew.
Reading every record's toggle byte showed Group0 = 0 (the tool's group,
clean) and **Group1 = 1** ("Toggle Everything Except Minimap") - the exact
half-HUD state. The tool only enforces its own group, so a stray F2 hotkey
toggle on Group1 survived every tool tick and nothing on the game side
could restore it.

Fix (v1.4.1): the tool now owns every group whose ini shader set intersects
the driven group's. At arm time, on every tick and on clean exit it forces
those groups (1 and 2 with the shipped ini) to byte 0, and logs
`cleared stray toggle ...`. Disjoint groups (Group3, crosshair-only) are
deliberately left alone. Live-verified: writing Group1 = 1 while the tool
ran was cleared within one 0.2 s tick.

## 6. Method notes / dead ends

- FName pool decode was abandoned: no reliable pool anchor found by module
  scan (probe8); class chains made object names unnecessary.
- Keyboard injection was ruled out by design: the tool only writes the
  addon's toggle byte.
- Heap addresses are per-launch; never persisted. Module RVAs are stable.
- Object InternalIndex values are never reused: a "resolvable but dead"
  index just means the object was garbage-collected, not that a stack entry
  is bogus.
