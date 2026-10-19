# hud_dynamic — dynamic HUD for Returnal

Version 1.4.0 (alpha) — see **Changelog** and **Known limitations** at the bottom.

Hides the HUD when nothing needs it, shows it the moment something does.
Fully automatic: attach, detect, actuate, re-attach after game restarts —
no hotkey to press, **no keystrokes sent at all**.

Built on top of [ShaderToggler](https://github.com/FransBouma/ShaderToggler)
(ReShade addon): the tool drives ShaderToggler's "Toggle HUD" group state
directly in memory, so the actual shader blocking is still done by the addon.

```
any trigger live   -> HUD visible  (group toggle byte = 0)
all triggers idle  -> HUD hidden   (group toggle byte = 1)
```

Triggers (each keeps the HUD on for its hold window, refreshed on every
new change — a burst of shots/damage keeps it up):

| Trigger | Hold |
|---|---|
| Combat (enemy aggression states) | 3 s after the last fight (see `--exit-delay`) |
| Health change | 3 s |
| Ammo change (fired, pickup, refill) | 3 s |
| Reloading / clip empty | 2 s |
| Aim (RMB focus) held | whole time held |
| Alt-fire used | 4 s |
| Alt-fire ready again (cooldown / refill finished) | 3 s |
| Subtitle cue on screen | cue + 2.5 s tail (covers the pauses between lines) |
| Interaction prompt target present | prompt + 0.9 s tail |
| New tutorial / notification / subtitle object, or any screen-stack change | 6 s (best effort) |
| **Tutorial prompt / any screen-stack layer** (not a menu, not the tutorial-panel shell) | **sustained while present** (`--no-stack-layers` opts out) |
| **ANY menu open** (pause, settings, photo mode, ...) | hiding fully disabled while open |

Subtitles are drawn by the shared HUD-text shader, so they cannot stay while
the rest of the HUD is hidden — instead the HUD comes back up while a subtitle
cue is on screen (background in `docs/SHADERTOGGLER.md`).

## Requirements

- Windows 10/11 x64, Python 3.8+ (no third-party packages — stdlib only)
- Returnal (Steam), tested against the current shipping build
- ReShade with add-on support — the unsigned build from <https://reshade.me>
- [ShaderToggler](https://github.com/FransBouma/ShaderToggler)
  ([releases](https://github.com/FransBouma/ShaderToggler/releases), MIT):
  `ShaderToggler.addon64` loaded in the game process (this is what actually
  blocks the HUD shaders)
- `ShaderToggler.ini` with the four groups below — or just copy the verified
  one shipped here: `setup/ShaderToggler.ini`

## Install

Everything goes into `Returnal\Binaries\Win64\` (next to
`Returnal-Win64-Shipping.exe`):

1. Install ReShade **with add-on support** (<https://reshade.me>).
2. Download the ShaderToggler addon
   ([releases](https://github.com/FransBouma/ShaderToggler/releases)) and put
   `ShaderToggler.addon64` there.
3. Copy `setup/ShaderToggler.ini` from this repo there too. It replaces
   ShaderToggler's own ini — back up yours first if you customized it. It is
   the verified working configuration, so **no shader hunting is needed** for
   the current Returnal build.
4. Put `hud_dynamic.py` + `hud_dynamic.bat` there.
5. Start the game, then run `hud_dynamic.bat`.

The tool waits for the game, attaches, validates the addon layout, and runs.
Stop it with `Ctrl+C` — it restores the HUD to visible on exit.

## Shipped ShaderToggler configuration

[`setup/ShaderToggler.ini`](setup/ShaderToggler.ini) — byte-identical copy of
the verified working install (SHA256
`27A042E807B8FBC8C211B58F794753FF5A483545CB52CF9DFFF581354933E7C3`):

| group | name | shader hashes |
|---|---|---|
| 0 | Toggle HUD | 2457571040, 1844482002 |
| 1 | Toggle Everything Except Minimap | 1844482002, 3005719831 |
| 2 | Toggle Everything Except Minimap and Crosshair | 1844482002 |
| 3 | Toggle Crosshair | 3005719831 |

The tool drives group 0 by default (`--group N` for another). The addon's own
toggle hotkeys still work for manual use; the tool re-asserts its state within
~0.2 s. If a game update changes the HUD shaders, re-hunt (see
`docs/SHADERTOGGLER.md`).

## Usage

```
hud_dynamic.bat                  # normal mode, ~0.2 s reaction
hud_dynamic.bat --dry-run        # detect and log only, never write
hud_dynamic.bat --calibrate 30   # detailed detection dump for 30 s, no writes
hud_dynamic.bat --invert         # HUD hidden IN fights, visible outside
hud_dynamic.bat --no-stack-layers # ignore screen layers as a sustained reason
hud_dynamic.bat --exit-delay 5   # seconds out of combat before hiding (default 3)
hud_dynamic.bat --group 1        # drive a different ShaderToggler group
hud_dynamic.bat --selftest       # offline logic tests, game not needed
python hud_dynamic.py --version
```

While it runs, the HUD follows the triggers within ~0.2 s (`--interval`;
the expensive ui tail scan stays at ~1 s). Manual hotkey presses are
overridden within ~0.2 s (the tool re-asserts its state each tick), and
toggle state is not persisted by ShaderToggler — every game launch starts
with the HUD visible.

## How it works

**Detection** (read-only) walks the game's own object system each tick:

```
game DLL IAT 0x8A15B0             -> &GUObjectArray
AEnemyManager class global        -> game DLL RVA 0xF5DC28
AEnemyManager +0x838/+0x840       -> TArray<AEnemyBase*> {Data, Count}
AEnemyBase +0x8F0                 -> AEnemyControllerBase*
AEnemyControllerBase +0x480       -> UEnemyAggressionComponent*
UEnemyAggressionComponent +0x151  -> EAggressionState byte
combat = state in {4, 5}          (= AEnemyControllerBase::IsInCombat)
```

Player/HUD signal chain (verified live against the running game on
2026-10-18 and again 2026-10-19; class chains walked via SuperStruct at
+0x40):

```
ATouristPlayerController (class global RVA 0xF6F168)
  +0x330 pawn, +0x390 ATouristHUD
pawn +0x668 UHealthComponent, +0xEB8 UFocusAimComponent,
  +0x820 UInteractionManagerComponent,
  +0x1028/+0x1040 gun slots;  gun +0x908 UWeaponClip, +0xC80 UAltFireComponent
UHealthComponent +0x2AC           -> hp float        (health trigger)
UWeaponClip +0x1A8 / +0x1B4       -> ammo float / reloading byte
UFocusAimComponent +0x198         -> focus aim held (ATouristHUD +0x514 too)
UAltFireComponent +0x270/0x271/0x272/0x27C -> alt-fire bytes (change-based);
  +0x348 -> ready flag (cooldown/refill finished)  (alt-ready trigger)
UInteractionManagerComponent +0x190/0x198/0x230 -> prompt target
  (selected / focused / override; prompt present = any non-null)
USayManagerComponent (class global RVA 0xF68F80)
  +0x1C8 -> subtitle cue queue depth > 0     (subtitle trigger)
ATouristHUD +0x4BC                -> open-menu count (menu => hiding disabled)
UTouristScreenManager +0x138/0x130 -> screen stack; 24-byte entries
  {pad, pad, u32 main index @16, u32 aux index @20} resolve via the
  GUObjectArray to live screen objects; class chains classify them:
  UPauseMenu => menu open, UTouristTutorialPanel = benign shell,
  anything else = layer held visible
```

**Actuation** writes one byte: ShaderToggler keeps a `std::vector<Record>`
(begin/end globals at addon RVA `0x23AF8`/`0x23B00`, records 280 bytes,
toggle byte at `+0x110`). The addon's draw hook blocks a group's shaders when
that byte is 1. The tool writes the byte directly, re-validating the vector
layout every tick, and verifies each write by reading it back. No `SendInput`,
no hooks, no injection.

**Holds and menu override**: combat leaves after 3 s (`--exit-delay`) without
aggression; every other trigger holds the HUD for its window (health/ammo
3 s, reload 2 s, alt-fire 4 s, alt-ready 3 s, subtitle cue +2.5 s tail,
interaction prompt +0.9 s tail, ui events 6 s) measured from the last
observed change, and aim keeps it up while held. While a menu is open (HUD menu
counter or a UPauseMenu on the screen stack) the HUD is forced visible and
hiding is disabled entirely. Screen-stack layers that are not menus (e.g.
tutorial prompt banners) hold the HUD visible for as long as they are
present — not for a fixed window — while the persistent tutorial-panel
shell is treated as benign so hiding keeps working in tutorial zones. An
unknown detector state holds the previous HUD state instead of counting as
"out of combat".

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `waiting for Returnal-Win64-Shipping.exe ...` | game not started yet — normal |
| `ShaderToggler.addon64 is not loaded` | ReShade not loaded in the game process (add-on support off or proxy DLL renamed), or addon missing — the tool re-scans every 30 s, but the game usually needs a restart with ReShade active |
| `group control not armed: ...` | ini group count doesn't match the addon, or addon version differs (layout changed) |
| `open_process failed (Access denied)` | run the terminal as the same user; if the game runs elevated, elevate the tool |
| `player: no player controller` | normal at boot/main menu — the tool re-scans every 5 s until a run starts |
| HUD doesn't change in `--dry-run` | expected — dry-run never writes; use normal mode |

Check `--calibrate 30` output (`CAL ...` lines) if combat detection looks
wrong: it prints enemy counts, per-enemy aggression states, and threat per
second with no writes.

## Docs

- `docs/FINDINGS.md` — every reverse-engineered offset/signal with the
  evidence that verified it
- `docs/PROCESS.md` — how the tool was reverse-engineered and built (probe
  series, regression analyses, verification gates, lessons)
- `docs/SHADERTOGGLER.md` — addon integration, group composition and the
  subtitle verdict (shared shader — the tool-side cue trigger is the fix)
- `setup/ShaderToggler.ini` — the verified ShaderToggler configuration
  (groups + shader hashes) the tool drives
- `research/` — the raw read-only probe scripts and session logs
- `NEXUS_POST.md` (repo root) — the ready-to-paste Nexus Mods page text

## Notes for publishing

Distribution package = `hud_dynamic.py` + `hud_dynamic.bat` + this README +
`setup/ShaderToggler.ini`. ShaderToggler itself is **not** included — users
get it from its upstream project (github.com/FransBouma/ShaderToggler, MIT).
Offsets are specific to the current Returnal shipping build; if the game
updates, re-verify them
(module RVA + struct offsets) before trusting detection.

- Single-player, local process only: the tool reads/writes the memory of the
  Returnal process on this machine. It does not touch networking, saves, or
  other processes, and sends no input events.
- `--selftest` (73 checks) runs without the game and is the regression gate
  for logic + layout assumptions. All offsets were re-verified live against
  the running game on 2026-10-18, and v1.4.0 was drive-verified live on
  2026-10-19; re-verify after any game update.

Known limitations (v1.4.0 alpha):

- The interaction-prompt and alt-fire triggers are implemented against
  live-verified chains but have not been observed firing yet: the
  verification save had no interactable prompt reached, and alt fire was
  still locked there (its `+0x348` ready flag never rises). They stay
  defensive change-detectors meanwhile.
- Health changes share the ammo trigger's mechanism (live-verified); an hp
  drop itself was observed live on 2026-10-18.
- The game auto-pauses on focus loss; the PAUSED overlay and photo mode both
  classify as menus, so the HUD stays forced visible while they are up
  (intended).
- If the tool is force-killed while the HUD was hidden, press F1 (the
  ShaderToggler hotkey) or relaunch the game — a clean Ctrl+C exit restores
  visibility itself.

## Changelog

- **v1.4.0** (2026-10-19) — subtitle-cue trigger (`SayManager` queue),
  interaction-prompt trigger, alt-fire-ready trigger; drive-verified live
  against the current build (idle hide, subtitle, ammo, aim, menus, UI
  layers).
- **v1.3.0** — sustained screen layers: tutorial prompts hold the HUD while
  present; pause/inventory classification; `--no-stack-layers`.

Earlier revisions: git history and `archive/`.

## Credits

- [ShaderToggler](https://github.com/FransBouma/ShaderToggler) — the ReShade
  addon that performs the actual shader blocking — by **Frans Bouma**
  ([releases](https://github.com/FransBouma/ShaderToggler/releases), MIT).
- [ReShade](https://reshade.me) — the framework that hosts the addon — by
  **crosire**.
- `setup/ShaderToggler.ini` is a configuration file for that addon; neither
  project's binaries are bundled here.
