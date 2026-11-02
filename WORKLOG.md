# WORKLOG

## 2026-11-02: plan

Matthew asked for a sound recorder like the Windows 3.1 one: record through
DirectSound "or similar", offer every format and channel count the device has,
optionally resample to a requested rate, MP3 and OGG output as a bonus, and full
device detection. Plan only this session.

Checked the laptop (read-only):
- Python 3.14.4 with `sounddevice` and numpy; no `soundfile`, `soxr` or `lameenc`.
  ffmpeg on PATH. .NET 10 and VS 2026 too.
- `sounddevice` with `SD_ENABLE_ASIO=1` lists 20 inputs over MME, DirectSound,
  WASAPI, WDM-KS and ASIO, including the ZOOM H/F interface and its ASIO driver, and
  the FL Studio ASIO driver. The Realtek mic array reads as 4 ch (MME), 2 ch 48 kHz
  (WASAPI) and 4 ch 16 kHz (a raw WDM-KS pin). No loopback devices in this PortAudio
  build.
- Looked at SoundTransmitter (C#, NAudio.Wasapi, own Kaiser-sinc resampler) and
  PySynthRack (Python, sounddevice, imageio-ffmpeg) for what's reusable.

Decisions (PLAN.md has the detail):
- Python: sounddevice, soundfile, soxr, numpy, tkinter canvas, PyInstaller.
- The full 3.1 frame, caption bar included, drawn by us.
- Conversion runs live while recording; the document keeps a lossless float32
  working copy at the output rate and channels.
- Output: WAV plus every format libsndfile offers, plus FLAC, Opus and AAC (AAC
  through ffmpeg).
- Six phases, one session each, starting with devices.

Not a git repo yet: flagged to Matthew.

## 2026-11-02: Phase 1, devices

Package `soundrec` under `src/`, installed editable in `.venv` (Python 3.14):
`pa.py` (sounddevice with ASIO switched on), `endpoints.py` (MMDevices registry),
`devices.py` (one list over every API), `loopback.py` (SoundCard), `probe.py`,
`asio.py` (direct driver query), `hotplug.py`, `formats.py`, `cli.py`. 40 tests.

What the APIs turned out to say, from grids over every input (13 rates × 5 sample
types × each channel count):
- MME and DirectSound accept every combination: Windows converts, so they're not
  probed. The engine format from the registry is shown instead.
- WASAPI exclusive accepted mono and every sample type until
  `explicit_sample_format=True`. With it, the mic array and Stereo Mix are 48 kHz,
  16-bit, stereo only, and the H2n 44.1/48 kHz, 16-bit, 1-2 ch.
- WDM-KS answers rates and channels honestly (mic array pins: one at 48 kHz 2 ch, two
  at 16 kHz 4 ch) but takes every sample type, since PortAudio converts.
- ASIO through PortAudio answers rates only, and reloads the driver for each
  question: FL Studio ASIO took 461 s for the grid. Asked directly through its
  vtable (ctypes, its own STA thread), FL Studio's driver answered everything in
  0.07 s: 22.05-192 kHz, float32, inputs "In 1"/"In 2", buffers 256-4096. The H2n's
  driver says 44.1/48 kHz, int16, two inputs, buffer 64: the same as WASAPI
  exclusive. The "Async" ZOOM driver fails CoCreateInstance with E_OUTOFMEMORY.
- Loopback via SoundCard: all three active playback devices, recording at
  48 kHz/2 ch, 44.1 kHz/1 ch and 11.025 kHz/1 ch all worked (silence: nothing
  was playing). It sets up COM as multithreaded on the importing thread, so `pa` is
  always imported first to keep that thread single-threaded for ASIO.

A full `--probe` takes 2-5 s, about 1 s of it starting PortAudio (the same with
ASIO off). Two runs once took 38 s between them while the chess engine was busy at
above-normal priority; not pinned down.

Hot-plug: Matthew unplugged and replugged the H2n with `--watch` running. Unplug at
21:46:46 (render endpoint not present, PortAudio 23 → 17 inputs). The capture
endpoint was only marked not present at 21:48:26. Replug at 21:52:27: both active,
23 inputs again, in the same second.

Matthew's warnings, mid-session:
- If recording drops out, his chess bot runs at above-normal priority.
- The H2n can drop to the wrong sample rate when a program asks it about formats
  (some Audacity versions do it), and voices go very deep until a replug. `--probe`
  asks those questions and was run on it about five times before he mentioned it;
  the replug for the hot-plug test reset it anyway. Added `--device` so the probe
  can leave it alone, a README warning, and a TODO to find which query sets it off.

Tests: a conftest blocks importing `soundrec.pa` for the whole run. The first
version did it per test, after collection had already started PortAudio (24 s,
every ASIO driver loaded); now the suite takes 1 s.
