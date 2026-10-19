hud_dynamic - Dynamic HUD for Returnal (v1.4.1, alpha)

Description

Hides the HUD when nothing needs it, and brings it back the moment something does — fully automatic, with nothing to press and no keystrokes sent.

The tool reads Returnal's own game state and drives ShaderToggler's "Toggle HUD" group for you. While combat, damage, ammo changes, reloads, aiming, alt fire, subtitles, interaction prompts, tutorials or UI layers are happening, the HUD is there; once everything has been quiet for its hold window, the HUD goes away again. Menus are safe: while any menu is open (pause, settings, photo mode) hiding is fully disabled.

How it works, in one line: the ShaderToggler ReShade addon performs the actual shader blocking; this tool only writes that addon's toggle byte inside the game process (re-verified every 0.2 s). No input is injected, no game files are touched, no networking involved.

Subtitles use the same shader as the rest of the HUD text, so they cannot stay visible while the HUD is hidden; instead the HUD comes back on screen while a subtitle line is playing (a "subtitle cue" trigger).

Status - v1.4.1 alpha, tested against the current Steam build. Live-verified: idle hide, subtitle cue, ammo change, aim, menus, UI layers. The health trigger shares the ammo trigger's mechanism; the interaction-prompt and alt-fire triggers are implemented against verified memory chains but have not been witnessed firing yet (the test save had no interactable prompt reached, and alt fire is still locked there). Offsets are specific to the current game build - a game update may require re-verification.

Notes:
- If the tool is force-killed while the HUD was hidden, press F1 (the ShaderToggler key) or relaunch the game - a clean Ctrl+C exit restores it automatically.
- While the tool runs it re-asserts the toggle state every ~0.2 s, so manual toggles of the HUD groups (F1-F3) last only a fraction of a second. The crosshair-only group (F4) is left to you.
- Groups that share HUD shaders with the driven group are held off automatically (v1.4.1): a stray F2/F3 toggle can no longer leave the HUD half-hidden. If it happens while the tool is not running, press the same key again or relaunch the tool.
- The game auto-pauses when it loses focus; the PAUSED overlay counts as a menu, so the HUD stays visible while it is up (by design).

Source and full technical docs: https://github.com/HyperRamzey/returnal-dynamic-hud

Installation instructions

Everything goes into the game folder Returnal\Binaries\Win64\ (next to Returnal-Win64-Shipping.exe):

1. Install ReShade with add-on support — the build from https://reshade.me — into that folder.
2. Download the ShaderToggler addon (https://github.com/FransBouma/ShaderToggler/releases) and put ShaderToggler.addon64 into that folder.
3. Copy ShaderToggler.ini from this download into that folder. If you already have a customized one, back it up first — this replaces it. (This file is what makes the mod work; no in-game shader hunting is needed for the current build.)
4. Copy hud_dynamic.py and hud_dynamic.bat into that folder.
5. Start the game and load into a run, then double-click hud_dynamic.bat (needs Python 3.8+ on PATH — see Requirements). Stop it with Ctrl+C when done.

Main features

- Fully automatic dynamic HUD: nothing to press, no keys are sent to the game, ~0.2 s reaction time.
- Show triggers, each with a short keep-alive window: combat, health change, ammo change, reloading / clip empty, aiming, alt fire used, alt fire ready again, subtitle cue, interaction prompt, tutorial / notification / screen-layer events.
- Menu safety: hiding is completely disabled while any menu is open — pause, settings, photo mode, or the auto-pause overlay.
- Sustained layers: tutorial banners and prompts keep the HUD up for as long as they are on screen.
- Compatibility-first design: the tool only flips ShaderToggler's toggle byte - no hooks, no injection, no input; the included ShaderToggler.ini is the exact verified configuration. Any group that shares HUD shaders with the driven group is held off, so a stray hotkey toggle cannot leave the HUD half-hidden.
- Useful modes: --dry-run (detect only), --calibrate 30 (live signal dump), --selftest (83 offline checks), --invert (reverse behaviour: hidden while fighting instead), --group N (drive a different ShaderToggler group), --exit-delay / --interval tuning.
- Robust attach: works started before or after the game, re-validates the addon layout every tick, and re-attaches after a game restart.

Requirements

- Windows 10/11, 64-bit.
- Returnal (Steam) — current shipping build.
- Python 3.8 or newer (python.org; standard library only, no pip packages).
- ReShade with add-on support (https://reshade.me).
- The ShaderToggler addon (https://github.com/FransBouma/ShaderToggler/releases) plus the ShaderToggler.ini included in this download. Neither is bundled here.

Shout outs

- Frans Bouma — ShaderToggler, the ReShade addon that performs the actual shader blocking (MIT).
- crosire — ReShade, the framework that hosts the addon.
- Housemarque — for Returnal.
