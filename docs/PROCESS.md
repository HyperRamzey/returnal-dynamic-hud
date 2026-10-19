# Process journal — how this tool was built

A record of the reverse-engineering and engineering process, so the findings
can be re-derived and extended. Everything here was done on the live
shipping game with **read-only** memory probes first; the only writer in the
project is `hud_dynamic.py` itself (one ShaderToggler toggle byte).

## Tooling

- Python 3 (stdlib only — `ctypes` ReadProcessMemory) for live probing.
- IDA Pro for static analysis and class-name recovery.
- `hud_dynamic.py --selftest` (73 offline checks) as the regression gate.
- `--dry-run` / `--calibrate` modes for live validation without any writes.

## The probe series

Each probe is a small read-only script answering one question. The ones
worth keeping are shipped in `research/` (index in `research/README.md`).

| probe | question | outcome |
|---|---|---|
| probe1–6 | where is the object array / can classes be resolved / enemy states | GUObjectArray via game DLL IAT `0x8A15B0`; class chains; enemy aggression states |
| probe7–8 | can FName be decoded? | no reliable pool anchor; abandoned (class chains suffice) |
| probe9–10 | player member chain | PC -> pawn -> health/focus/guns -> clip |
| probe11 | live watcher, session A (menus/aim) | signal table for aim/menus; screen stack first observed (persistent `UTouristTutorialPanel` entry) |
| probe12 | live watcher, session B (firing) | ammo float 12->0, reload byte, refill ramp |
| probe13 | stack entry + live instance inventory | entry+16 = object InternalIndex; UPauseMenu entries confirmed |
| probe14–15 | module scan for class-global slots | UMG / CoreUObject / HMQ class globals found + live-validated |
| probe16–18 | tutorial-banner class hunt + raw entry dump | entries are `{pad, pad, u32 main@16, u32 aux@20}`; banner entry object = `UOverlaySlot` instance; UMG class names recovered via IDA |
| probe19 | v1.3.0 stack classification live check | pause entry classified correctly; no false layers while in menus |
| probe50 | SayManager / SayHUD subtitle chain | cue queue `+0x1C8`; live SayHUD row walk; inter-line gap flap measured |
| probe51–53 | class-global + component sweeps for v1.4 | `USayManagerComponent` RVA `0xF68F80`; `UInteractionManagerComponent` RVA `0xF60D58`; pawn IMC `+0x820` confirmed live |
| probe54 | v1.4 offset verification pass | every v1.4 chain class + member offset re-read live from a fresh launch |
| probe56 | windowed signal watcher (2026-10-19 session) | hp/ammo/alt/Say/IMC/menu signals against scripted inputs; G key flips `bWantsToAltFireMode` (`+0x270`) 0↔1 |
| probe57 | input-map scan for the alt-fire binding | dead end — no candidate UInputSettings arrays found |
| `ahk_*.ahk` | AutoHotkey v2 input helpers | held-key / click injection for scripted live tests (kept out of the tool) |

## Engineering milestones

1. **Actuation** — ShaderToggler addon reversed in IDA: records vector +
   toggle byte. Direct byte writes replaced any key simulation; "no keyboard
   injection" became a hard design rule.
2. **Detection** — `CombatDetector` (enemy states) + `PlayerTracker` (hp,
   ammo, reload, aim, alt-fire, menus, UI events) with guarded reads; an
   unknown state holds the previous decision instead of guessing.
3. **Hold windows** — every trigger keeps the HUD up for its window,
   refreshed on each change (a burst of fire keeps it up); combat leaves
   after `--exit-delay` seconds of no aggression.
4. **Menu safety (top requirement)** — menu-open count (`HUD+0x4BC`) plus
   UPauseMenu stack entries force the HUD visible and disable hiding
   completely, in both directions, `--invert` included.
5. **UI events** — a tail scan of the GUObjectArray for newly created
   watched UI objects (tutorial/notification/subtitle classes) plus screen
   stack changes raise a 6 s window (best effort).
6. **v1.3.0 — sustained screen layers** — the 2026-10-18 regression analysis
   (below) showed the tutorial banner living ~30 s: the 6 s window expired
   while the banner was still up, so the HUD hid mid-banner and left
   "backgrounds" (shaders outside the toggled set). Fix: classify screen
   stack entries (pause / tutorial-panel shell / anything else = "layer")
   and hold the HUD visible *while a layer is present*, with no window
   expiry. The tutorial-panel shell is deliberately classified benign so
   hiding keeps working in tutorial zones where the stack always carries it.
   `--no-stack-layers` opts out.
7. **v1.4.0 - subtitle cue, interaction prompt, alt-fire ready** - subtitle
   shader separation proved impossible (shared UI shader, verdict below), so
   the tool now triggers off the `SayManager` cue queue instead.
   Interaction prompts (IMC targets `+0x190/+0x198/+0x230`) and alt-fire
   ready (`+0x348` edge) added; photo mode / focus-loss pause confirmed to
   classify as menus. Drive-verified live the same day (next section).
8. **v1.4.1 - group ownership** - a stray F2 toggle on Group1 ("everything
   except minimap") left the HUD half-hidden while Group0 (the driven
   group) was clean; the tool could not undo it. The tool now holds every
   group whose ini shader set overlaps the driven group's at byte 0 (arm,
   every tick, clean exit) and logs the repair. Disjoint groups stay
   user-controlled.

## The 2026-10-18 regression analysis (tutorial banner + subtitles)

**Symptom 1: "tutorials leave backgrounds."** Log evidence from the live
run: a stack entry appeared 21:53:12; the HUD hid at 21:53:20 while the
banner was still up. The banner text is drawn with a shader inside Group0
(blocked) while its background uses other shaders (not blocked) — leftover
boxes. The stack entry itself resolved to a `UOverlaySlot` instance (the
prompt animates via its slot), which is exactly the "layer" case.
Fix (v1.3.0): sustained layer visibility — no window expiry while the layer
is present. Live-verified: pause entries classify as menu, no false layers.

**Symptom 2: "subtitles disappear when the HUD is hidden (they appear if I
zoom in)." — RESOLVED 2026-10-19: no shader-level separation exists.**
Live test: with a subtitle on screen, toggling Group2 (`{1844482002}` alone)
kills the subtitle together with the rest of the HUD text → the subtitle
uses the shared UI shader `1844482002`; removing that hash from Group0 would
disable HUD hiding entirely (only the minimap hash `2457571040` would stay).

Adopted mechanism — **tool-side cue trigger**. Subtitle chain mapped live
(probe50 watcher, 2026-10-19 playback + scout-log cue):

- each displayed line is a fresh `WBP_SayEntry_C` row inside the live
  SayHUD's `VerticalBox_Entries` (walk: HUD `+0x730` → Slots `0x108` → slot
  Content `0x30` → row `+0x720` RichTextBlock → Text `+0x128`); row `SayId`
  matches `SayManager` entry ids;
- `SayManager.Entries` count (`+0x1C8`) is the cue queue: `num>0` spans the
  whole cue including the ~0.4 s inter-line gaps and hits 0 exactly when the
  last line is consumed (each line on screen ~1.6 s; its row is removed from
  the VBox at consumption);
- probe48's "sticky num" was a paused game — frozen mid-cue, and the moment
  play resumed (05:03:05) `num` went 1→0 with the line consumed.

So the tool's subtitle rule: **HUD shown while `SayManager.num>0`** (OR any
live VBox row with `SayId≠0`, belt-and-braces). True "only the subtitles"
would need an external overlay drawing the (fully readable) subtitle text
over a hidden HUD — possible, not built.

## 2026-10-19 drive verification (v1.4.0)

Live session driven over the desktop (windows-mcp + AutoHotkey v2 helpers)
with the tool running in the background:

- idle -> HUD hidden (group byte 1, screenshots); subtitle cue -> HUD visible
  with the line on screen; ammo change (12 -> 10) and held aim each raised
  the HUD (`HUD visible: ammo` / `aim`); pause menu, photo mode and the
  focus-loss auto-pause all force the HUD visible; a screen-stack change
  raised the ui window; after ESC closed the overlay the stack was back at
  n=0.
- Subtitle tail fix: the cue queue legitimately hits 0 between lines
  (hidden 06:22:27 -> visible 06:22:28 flap) -> `HOLD_SAY` raised
  0.7 -> 2.5 s.
- Alt-fire: G flips `bWantsToAltFireMode` (`+0x270`) 0↔1 live; the mode byte
  `+0x271` stays 0 and the ready flag `+0x348` never rises in this save
  (alt fire locked) -> the alt-ready trigger awaits a save with alt fire
  unlocked; likewise no interaction prompt was reached in this save.
- The game auto-pauses on focus loss (`PAUSED / CONTINUE GAMEPLAY`); resume
  needs a click (ESC does not dismiss it). Photo mode (LENS panel) is also a
  pause-classified stack entry; ESC/P do not close it.

## 2026-10-20 half-HUD hotfix (v1.4.1)

Report: during a fight the game black-screened, then the HUD stayed
half-broken ("half gone, half there") and never recovered.

Live state at diagnosis (game still up, paused): Group0 = 0, Group1 = 1,
Group2 = 0, Group3 = 0 -> Group1 ("Toggle Everything Except Minimap") was
the half-HUD. The game itself was healthy: `PlayerTracker` read pc/pawn,
hp 4.2, clip 35, menu-open 1; `CombatDetector` found the EnemyManager; no
TDR or display event existed (the 22:06:21 Application Error was a Returnal
audio-DLL crash from the previous session, 13 s before the current process
started).

Root cause: ShaderToggler's F1-F4 hotkeys are a second writer. Group0 (the
tool's group) can be correct while an overlapping preset (Group1/2) stays
toggled; the tool only ever wrote its own record, so the half state
survived. (Who pressed F2/F3 - a stray key during the crash/recovery or a
`--group` launch - cannot be proven from the state; the missing invariant
can.)

Fix: parse the ini shader sets, compute overlapping groups, hold them at 0
at arm time, every tick and on clean exit; log every repair. Live test:
write Group1 = 1 while the tool runs -> cleared in < 1 tick, log line
`cleared stray toggle on ShaderToggler group(s) 1`. 83-check selftest.

## Verification gates

| gate | what it proves |
|---|---|
| `--selftest` | pure logic + fake-memory discovery paths (83 checks, no game needed) |
| `--dry-run` live session | detection correct, nothing written |
| `--calibrate` live session | field-level signal dump against player actions |
| live acceptance runs | user plays; logs + user report confirm behavior |
| read-only probes (`probe*`) | every offset claim re-checked live |
| single-writer discipline | exactly one tool instance writes the toggle byte at a time |

## Lessons learned

- Module RVAs are stable; the heap is per-launch. Never cache heap pointers.
- The GUObjectArray item has no class field — read the class from the object
  (`+0x10`). A whole probe round was lost to reading item+16 instead.
- InternalIndex is never reused: a resolvable index pointing at a destroyed
  slot just means the object was garbage-collected.
- The screen stack is the game's UI-layer list, not a widget inventory;
  entries can be widgets *or* slots (slot-animated prompts!).
- The tool cannot change *which* pixels are blocked: that is fully determined
  by the ShaderToggler ini group composition. All partial-hiding artifacts
  (leftover backgrounds, surviving crosshair) are ini-scope issues.
- UI frameworks on this build: widget classes live in the UMG module, game
  UI subclasses in HMQScreen (`UHMQUserWidget` -> `UHMQScreenWidget`), and
  game screens on top of those. Names were only recoverable through IDA
  xrefs of `Z_Construct_UClass_*` referencing the `.data` slots.
- Read subtitle rows only from a *live* HUD's VBox. Stale row widgets keep
  dangling Text FText pointers; a probe watcher died printing garbage bytes
  from a cleared row (console cp1252). Sanitise stdout; treat non-live rows
  as noise.
- Live verification needs input automation that does not steal focus:
  inline screen captures (no child console windows) + AHK v2 helpers for
  held-key/click injection; alt-tabbing away auto-pauses the game.
- Tail windows must cover *observed* gaps, not the ideal: the subtitle cue
  queue hits 0 between consecutive lines (~1–2 s observed), hence the 2.5 s
  `HOLD_SAY`; longer scripted pauses can still flap (known limitation).
- When a boolean never leaves 0 live, check the input path first: alt fire
  flips its wants-byte on keypress while the mode byte never engages - the
  feature is locked in that save, not a broken offset chain.
- "Half HUD" is a group-composition state, not corrupt game UI: dump every
  ShaderToggler record's toggle byte before touching anything else. Group0
  being clean does not mean the HUD is.
- ShaderToggler's own hotkeys are a second writer for every group the tool
  does not own. "Single writer" means owning *all* groups that share the
  driven shader set, not just the driven record.
