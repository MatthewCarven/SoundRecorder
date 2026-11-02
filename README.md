# Sound Recorder

A sound recorder for Windows that will look and behave like the Windows 3.1 one,
over every Windows audio API, in every format. [PLAN.md](PLAN.md) has the design
and the phases; this is Phase 1: finding devices and what they really do.

## Set up

```
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
```

Python 3.12 or later (built on 3.14). Tests: `.venv\Scripts\python -m pytest`.

## Use

```
sound-recorder [--list] [--probe] [--device TEXT] [--outputs] [--all]
sound-recorder --watch
```

- `--list` (the default) lists every capture device on every API: WASAPI,
  loopback (recording what a playback device plays), ASIO, WDM-KS, DirectSound
  and MME. `*` marks each API's default. Devices tied to a Windows endpoint show
  its form factor, its bus and the format the audio engine runs it at.
- `--probe` asks each device which formats it really takes (about a second).
- `--device TEXT` keeps only devices whose name contains TEXT.
- `--outputs` lists playback devices too; `--all` adds the endpoints Windows
  hides (phantom "Internal AUX Jack" and the like).
- `--watch` reports devices being plugged in and unplugged until Ctrl+C.

## What the probe's answers mean

Each API tells a different story about the same hardware:

| API | What it answers |
|-----|-----------------|
| WASAPI | **Native**: exclusive mode, the format handed straight to the driver. Shared mode takes anything (Windows converts) |
| ASIO | **Native**: asked of the driver directly, with its channels' names |
| WDM-KS | **Native rates and channels**; PortAudio converts sample types, so those aren't shown |
| DirectSound, MME, loopback | Anything: Windows converts from the engine format shown |

## Known trouble

- **The ZOOM H2n can drop to the wrong sample rate when a program asks it about
  its formats** (Matthew's report: some versions of Audacity do it, and voices
  come out very deep until it's unplugged and plugged back in). `--probe` asks
  the same kind of questions, so after probing the H2n, check that it sounds
  right, and replug it if not. `--device` keeps the probe off it. Which query
  sets it off isn't known yet: see TODO.
- A `--probe` run usually takes 2-5 s (about 1 s of it starting PortAudio), but
  two runs once took 38 s between them while the laptop was busy. The cause
  wasn't pinned down.
