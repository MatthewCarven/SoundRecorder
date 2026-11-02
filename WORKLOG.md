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

## 2026-11-03: Phase 2, the recording engine

New modules: `convert.py` (channel map, then soxr's `ResampleStream` at VHQ, skipped
when the rates match), `output.py` (format from the file name, bit depth, TPDF
dither, a `Writer`, a preflight that opens the codec at the take's rate before
recording), `takes.py` (the working copy), `engine.py` (`Recorder`: queue, worker,
stats, levels), `capture.py` (PortAudio and loopback sources), `com.py` (COM
apartments). `cli.py` gained `rec` and `recover`. 136 tests (96 new), 4.5 s.

How it hangs together:
- The capture thread only copies the block into a `SimpleQueue` with a timestamp.
  The worker gathers ~10 ms of blocks (ASIO's come every 1.3 ms from the H2n),
  converts, writes the working copy, the `--live` file if any, the peaks and the
  stats. Behind, it catches up without pausing.
- Each source opens, runs and closes its stream on its own thread in the apartment
  its API wants: STA for PortAudio, MTA for soundcard's loopback. Opening ASIO from
  a fresh STA thread (not the one that started PortAudio) works.
- Working copy: raw float32 (`.f32`) plus a `.json`, in
  `%LOCALAPPDATA%\SoundRecorder\takes`. The owner locks a byte past the end of the
  `.json` (`msvcrt.locking`) for as long as it holds the take, so a take nobody
  holds is one a crash left. flush per batch, fsync every 5 s. Tests redirect the
  folder with `$SOUNDREC_TAKES` (autouse fixture), and one kills a real recording
  subprocess and recovers its take.
- PCM is quantised by us, not libsndfile: libsndfile scales float by 32767 where
  PortAudio and its own reading use 32768, so 16-bit capture wouldn't come back bit
  for bit. Blocks already on the target's grid skip the dither. 24/32 bits are rounded.
- Clock check: a running least-squares slope of frames delivered against arrival
  time, over every block, with its uncertainty. The first version (frames between
  the first and last block) flagged DirectSound at +1.3% on a 3 s take: it delivers
  in 64 ms lumps.

Converter tests: a 997 Hz sine at 48 kHz, fed in blocks of 1 to 5000 frames
(64 and 480 among them), comes out at 44.1 kHz identical to a one-shot
`soxr.resample`, the level within 0.001 dB, zero phase shift, and no sample more
than 1e-5 from the ideal sine (which also pins the pitch to under 0.0001 Hz). A
ten-minute 48 to 44.1 kHz take through the engine comes out with exactly 26,460,000
frames and the sine's phase where it belongs in 25 windows across it. An MP3, a
Vorbis and an Opus file write and read back with pitch and level intact.

On hardware (all 3 s takes, Stereo Mix or loopback, so nothing from the room):
WASAPI shared, MME, DirectSound, WDM-KS, loopback (MP3 written live) and ASIO
through FL Studio's driver all recorded, with no overflows. The H2n wasn't opened.
MME and DirectSound now capture at the engine's rate by default: PortAudio says
44.1 kHz for them, which made Windows resample 48 to 44.1 kHz before we saw it.

The ten-minute take: `rec --device "Stereo Mix" --api WASAPI --capture-rate 48000
--rate 44100 --seconds 600`, 07:10:39-07:20:43, with the chess engine running at
Normal priority. 28,800,480 frames in, exactly 26,460,000 out (600.0 s), clock
48,000.0 frames/s, no overflows, longest wait between blocks 14 ms, worker never
behind. Stereo Mix carried near-silence (about -188 dBFS), so the file is ±1 LSB of
dither; the count and the clock are the evidence. The same take from the H2n over
ASIO waits for Matthew (below).

**WASAPI exclusive capture is broken in sounddevice's PortAudio (19.7.0-devel).**
The clock check read 94,418 frames/s on a 48 kHz exclusive take from Stereo Mix.
Timed directly: shared mode gives 48,012 frames/s; exclusive gives 66-87 k frames/s
at every block size (0, 480, 960, 4800) and latency (low, high, 50 ms, 200 ms)
tried, on Stereo Mix and the mic array alike. PortAudio's own ADC timestamps keep
real time while the frames run ahead. Counting the mic array's blocks by hash
(nothing kept): shared mode, 299 blocks in 3 s, no repeats; exclusive, 420 blocks
with 122 exact repeats of earlier blocks. So it re-delivers stale buffers. Now the
engine judges the clock as it records (`Stats.clock_problem`: more than 1% off and
well past its own uncertainty, after 2 s), and `rec` stops such a take with a plain
explanation. A device stuck at the wrong rate would trip the same check.

Found: Windows runs the H2n's playback endpoint at 48 kHz and its capture endpoint
at 44.1 kHz. If one clock serves both directions, whichever opens last sets it, and
recordings labelled 44.1 kHz would really be 48 kHz: deep voices.

### The H2n tests (Matthew on hand to replug)

New `scripts/h2n_clock.py`: records the H2n over WASAPI shared and fits frames
against the PC's clock per stretch, optionally playing silence to its playback
endpoint in the middle. Counts frames only; no audio kept.

- 07:55 baseline, capture alone: 44,099.8 frames/s for 44,100. Healthy.
- 07:55 the ten-minute take over ASIO, 48 to 44.1 kHz: stopped by the clock check
  after 4.6 s. The driver delivered **21,333 frames/s**. A bare sounddevice callback
  at 44.1 kHz got the same: one 64-frame buffer every 3.00 ms (21,381 frames/s by the
  PC's clock and PortAudio's ADC times alike), and with a 512-frame block size, 512
  every 24 ms. So the ZOOM driver services its buffer on a fixed 3 ms tick and its
  one buffer size (64) holds 1.5 ms: over half the audio is lost. Not our engine.
- 07:56 baseline again after ASIO at 48 and 44.1 kHz: 44,100.3. ASIO didn't trip it.
- 07:57 **the bug, caught**: capture alone 44,098.2; with silence playing to
  "Speakers (ZOOM H and F Series Audio)" at 48 kHz (WASAPI shared), **48,000.4**;
  playback stopped, still **48,000.1**. One clock for both directions, and it stays
  at whatever opened last until a replug. Audacity opening its output at 48 kHz fits.
  Cure: both endpoints on one rate, Matthew's setting (TODO).

So the H2n's ten-minute take couldn't be done over ASIO (driver) or WASAPI exclusive
(PortAudio). Over WASAPI shared it's the path the Stereo Mix take already proved.
The test left the H2n at 48 kHz: Matthew replugged it, and at 08:41 its capture
read 44,098.1 frames/s again. He then set its playback endpoint to 44.1 kHz 16-bit,
matching the capture side. 08:45, `h2n_clock.py --play 44100`: alone 44,098.6,
with silence playing 44,099.4, after 44,100.0. Cured, with no replug.

### The H2n in 4-channel surround mode

Matthew switched it to 4-channel surround. It dropped off USB and came back as a
different device on Windows' own USB audio driver: "Microphone (H2n)", **4 channels,
24-bit**, 44.1 kHz, and "Headphones (H2n)", 2 ch, 24-bit, **48 kHz** (new endpoints,
new defaults: the mismatch again). There's no ASIO in this mode; ZOOM's driver isn't
used. `h2n_clock.py` now takes device names and finds either mode's by default.

- With the mismatch, Windows wouldn't open Headphones (H2n) at all in shared mode,
  at 48 kHz or 44.1 ("Invalid sample rate"). Once Matthew set it to 44.1 kHz it
  opened. So this driver seems to refuse a clashing rate rather than let the clock
  drift, unlike ZOOM's. With matched rates, `--play 44100` kept the input at 44,100.2.
- The first fingerprint had all four channels as one signal: the same level to
  0.1 dB, correlation 1.000, and every difference under one 24-bit step (float
  rounding). Over WDM-KS, past Windows' engine, the four were distinct (peaks
  -44.7/-44.2/-45.9/-45.7 dBFS). The cause was **"Enable audio enhancements"** on
  Microphone (H2n): with it unticked, WASAPI gave four distinct channels too.
- Fingerprint with enhancements off (09:01, room sound): RMS -56.9/-59.6/-56.2/-55.3
  dBFS. Correlation 1-2 0.17 (a wide pair), 3-4 0.84 (a narrower pair), 1-3 0.47 and
  2-4 0.44, the opposite corners 0.13 and 0.21. Two stereo pairs, 1 and 3 on one
  side, 2 and 4 on the other: the front XY and rear MS sets, presumably. Which pair
  is which needs sound from known directions.

## 2026-11-03: Phase 3, the 3.1 window

A side session from the Phase 2 one. New package `soundrec.ui`: `fonts.py`,
`raster.py`, `face.py`, `menus.py`, `window.py`, `dialog.py`, `document.py`,
`audio.py`, `app.py`. `sound-recorder gui` or `python -m soundrec.ui` opens it.
189 tests (53 new), 4.4 s.

**Font check.** Tk resolves "System" to the bitmap face (16 px, bold) and draws it
exactly: an off-screen grab showed four colours, no smoothing; asking for 32 px
pixel-doubles it. But GDI picks a raster font's size itself, and MS Sans Serif
(sserife.fon) has its own 10-24 point designs, so a 2x window would get a
different font. So `fonts.py` reads the glyphs out of the `.fon` files (NE
resources holding FNT bitmaps), synthesising bold as GDI does (drawn twice, a
pixel apart), and the window is drawn into a numpy buffer handed to Tk as one PPM
image. That also lets tests draw the whole window with no window.

**The look, measured.** A 640x480 screenshot of the real 3.1 Sound Recorder
(toastytech.com's GUI gallery), read pixel by pixel in the browser: 317 x 169, a
1-pixel border, 18-pixel caption and menu bar, a sunken status box ("Stopped" in
MS Sans Serif 8 bold, which I'd have guessed was System), Position / wave / Length
panels in MS Sans Serif 8, the scrollbar, five 56 x 23 buttons. Disabled glyphs
are a checkerboard of the solid ones. Static text sits a pixel left of centre; the
caption's doesn't. A 3.1 control-menu screenshot gave the menus: flat white, no
shadow, 18-pixel items with the text at the top, 7-pixel separators, the
accelerator column 8 pixels after the widest label, disabled text #C0C0C0, and the
mnemonic underline a pixel left except under a first letter. Drawn inactive with
3.1's menus, `face.paint` matched the screenshot in every visible pixel (53,573;
the first try was off by 183, all the checkerboard's phase on two buttons: each
3.1 button was a child window, so the pattern lines up with each button's corner).
Effects' mnemonic turned out to be the s.

**The frame.** Tk makes an overrideredirect window a tool window: no taskbar
button, no Alt+Tab, no minimize. `window.py` swaps WS_EX_TOOLWINDOW for
WS_EX_APPWINDOW and adds WS_MINIMIZEBOX, then hides and reshows it so the taskbar
notices; minimizing is ShowWindow, dragging is WM_NCLBUTTONDOWN on HTCAPTION.
Checked in code (styles set, minimize and restore work); the taskbar and Alt+Tab
want Matthew's eyes. Menus open in a second window with WS_EX_NOACTIVATE, so the
caption stays active and keys keep coming. Tk activates any window it creates
(even withdrawn) and, inside the app, dropped the popup's first `wm geometry` move
while taking its size (plain Tk didn't, in four variants); SetWindowPos moves it.

**Checked without disturbing Matthew**: the app run with every window at alpha 0,
the foreground handed back at once, and each window grabbed with
PrintWindow(PW_RENDERFULLCONTENT), which reads a window's own surface (an
off-screen window paints nothing, so grabs came back black until it sat on screen,
invisible). Snapshots of every menu, the control menu, recording, stopped.
Recording through it from Stereo Mix (WASAPI): 3 s gave 144,480 frames at 48 kHz;
1 s more at the start recorded over it, length unchanged; Exit asked to save and
deleted the working copy. The default device it picked is WASAPI "Microphone
(H2n)" (4-channel mode); the first scan took 0.5 s.

**The GIL.** An ASIO callback at the H2n's 64 frames needs the GIL every 1.3 ms,
and Python lets a busy thread keep it 5 ms. A stand-in thread waking every 1.3 ms
was up to 2.6 ms late while the window painted at 25 fps (a full 2x paint takes
5.2 ms), 32 times past 1.3 ms in 5 s; with `sys.setswitchinterval(0.0005)` 1.5 ms
at worst, once. The window sets it. The H2n itself can't be tried: 4-channel mode
has no ASIO.

**Not done**: playback is written (WASAPI shared with auto_convert, so the device
keeps its own rate) and tested against a fake PortAudio, but not heard: it waits
for Matthew's OK. Open and Save As use Windows' own file dialogs.

### Playback, heard (Matthew's OK)

A 997 Hz tone at -30 dBFS, 1.5 s with 10 ms fades, opened in the (invisible) window
and played with its Play button to Windows' default playback device, Headphones
(Realtek, 44.1 kHz), while a Recorder took that device's loopback. Seven plays:

- 48 kHz sound (Windows converting 48 to 44.1 kHz and back for the loopback),
  twice: 997.00 Hz, RMS -32.99 dBFS against -33.01 sent, a fitted amplitude of
  exactly -30.00, onset 33-36 ms after Play (PortAudio says 24 ms of buffering),
  5 ms loudness steady within 0.2 dB, the Position readout climbing to 1.50 s and
  the buttons coming back as they should.
- 44.1 kHz (nothing converted), five times. The first came back **89 ms too long
  with a near-silent stretch inside**. The Player then gained an underflow count
  (PortAudio's own flag). The next four: 0 underflows, no silence, and phase
  tracked every 20 ms with no steps (a slipped or repeated sample would show as
  one). soundcard was also instrumented for the last three: it made up no silence.
- soundcard's `_record_chunk` returns zeros whenever no loopback packet comes for 4
  device periods (~40 ms), even while sound is playing, and the late packets still
  arrive afterwards: that makes a take longer with a silent stretch, as seen. A real
  underrun would look the same in a loopback take, so the one long beep stays
  unattributed; Matthew may have heard it (TODO).
- What the fit left over (-64 dBFS, -31 dB under the tone, strongest near 840 and
  1340 Hz) was there before the first beep too: other sound playing on the
  headphones, which loopback hears as well.

190 tests.
