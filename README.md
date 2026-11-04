# Sound Recorder

A sound recorder for Windows that will look and behave like the Windows 3.1 one,
over every Windows audio API, in every format. [PLAN.md](PLAN.md) has the design
and the phases. Done so far: Phase 1 (finding devices and what they really do),
Phase 2 (the recording engine, driven from the command line), Phase 3 (the
window: recording, playback, File, the menus), Phase 4 (Edit and Effects, and a
Channels choice) and Phase 5 (the Recording Device and Output Format dialogs,
AAC, and Save As at another rate or channel layout). Next: packaging it as an exe.

## Set up

```
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
```

Python 3.12 or later (built on 3.14). Tests: `.venv\Scripts\python -m pytest`.

## The window

```
.venv\Scripts\pythonw -m soundrec.ui [--zoom N] [--device TEXT] [--api API]
sound-recorder gui [--zoom N] [--device TEXT] [--api API]
```

The Windows 3.1 Sound Recorder, drawn pixel for pixel (its layout was measured
from a 3.1 screenshot, and it matches it exactly) in the fonts Windows still
ships: the System font and MS Sans Serif, read straight from their `.fon` files.
Every pixel is doubled by default at 100% display scaling (3x at 150%, 4x at
200%); `--zoom 1` shows 3.1's own 317 x 169. It records from Windows' default recording device over WASAPI shared mode
until Device > Recording Device picks another, or from `--device` / `--api` (the same as `rec`'s).

- **The buttons**: rewind, forward, play, stop, record. Recording starts at the
  position and records over what follows, as in 3.1; the wave box shows what's
  coming in. The scrollbar moves the position (arrows 0.1 s, the trough 1 s).
- **The level meter** (ours, not 3.1's): while recording or playing, two bars in
  the wave box, left along the top and right along the bottom, from -60 dBFS at
  the left edge to 0 at the right: green, yellow from -12, red from -3, with a
  peak-hold tick. Stopped, the box is 3.1's own.
- **File**: New, Open (anything libsndfile reads, and anything else ffmpeg can),
  Save, Save As (the extension picks the format: WAV, FLAC, MP3, Ogg, Opus, AAC
  as .m4a, AIFF...), Revert, Exit. If the format can't hold the sound, or Output
  Format asks for another rate or channels, Save As says so first and saves a
  converted copy: the sound in the window, its name and any unsaved changes all
  stay as they were. A copy can't replace the sound's own file.
- **File > Save Tracks** (ours; a sound of two or more channels): Track 1 to Track
  N each save that one channel as a mono file, and All Tracks saves them all from
  one dialog, as name-1, name-2... They keep the sound's own format and rate if
  the extension stays the same, and another extension picks another format (at
  the nearest rate it can hold, and it says so). They save copies: the sound, its
  file and its changed-or-not state stay as they were. All Tracks asks before
  replacing any file, and writes all of them or none.
- **Edit**: Insert File and Mix with File at the position (the file is converted
  to the sound's rate and channels; into an empty window it becomes the sound),
  Delete Before / After Current Position (they ask first: only Revert brings it
  back).
- **Effects**: Increase Volume by 25% and Decrease Volume (each undoes the
  other: the working copy is float, so nothing clips until it's saved to a
  format that can't go past full scale), Increase Speed by 100% and Decrease
  Speed (pitch too, as in 3.1; resampled, so no aliasing), Add Echo (one repeat at
  half the level, 50 to 500 ms later from a submenu, or any whole number of
  milliseconds from 1 to 5000 through its Custom... box), Reverse. Undo is
  3.1's: Revert.
- **Device > Recording Device**: every API and device, greyed for jacks with
  nothing plugged in. Choosing one asks it nothing: what's shown comes from the scan.
  **Probe** asks the device for its native formats (and an ASIO driver for its
  channels' names), and warns first on the H2n, which a question can knock to the
  wrong rate. It says what's known to go wrong (the H2n's ASIO driver, the Realtek's
  PC Speaker pins). WASAPI exclusive mode isn't offered: see Known trouble.
- **Device > Output Format**: what Save As writes. Format (every one libsndfile
  has, and AAC), encoding (those that really write), quality per codec (MP3
  constant or variable, Vorbis, Opus and AAC rates, FLAC level), rate and channels.
  "From the file's name" and "As the sound" leave those to the name and the sound.
  A file name with another extension still wins. New sounds record at the chosen rate.
- **Device > Mono / Stereo / All N Channels**: what a new sound records. Until you
  pick, a mono device records mono and anything else stereo; Mono mixes channels 1
  and 2. Once there's a sound, recordings take its channels. Playing a sound with
  more channels than the speakers have mixes them down: odd channels left, even
  right, as the meter shows them.
- **Device > Refresh Devices** looks again and says what it found; plugging a
  device in looks again too, quietly.
- If something goes wrong inside the window, it says so, and the details go to
  `%LOCALAPPDATA%\SoundRecorder\errors.log`.
- The caption drags the window; the minimize arrow, the taskbar button and
  Alt+Tab work as for any window. The control-menu box opens 3.1's control menu
  (double-click closes). Menus work with the mouse (press and drag, or click) and
  the keyboard (Alt or F10, the arrows, Enter, the underlined letters, Alt+letter,
  Alt+Space for the control menu, Esc). An item with an arrow opens a cascade: rest
  the pointer on it, click it, or press Right, Enter or its letter; Left or Esc
  closes it, and Right from inside it moves on to the next menu.

## The command line

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

### Recording

```
sound-recorder rec out.flac
sound-recorder rec --device "Stereo Mix" --api WASAPI --capture-rate 48000 --rate 44100 --seconds 60 take.wav
sound-recorder rec --device zoom --api ASIO --pick 2 --channels 1 --bits 24 voice.flac
sound-recorder rec --api Loopback --live what-i-hear.mp3
```

- The file's extension picks the format: `.wav .flac .mp3 .ogg` (Vorbis) `.opus .m4a`
  (AAC, through ffmpeg) `.aiff .caf .w64 .rf64` and everything else libsndfile
  writes. `--bits 8|16|24|32|float`
  sets the depth; 8 and 16 bits get TPDF dither.
- `--device` is part of a name; `--api` picks the API when several have the device
  (otherwise the most direct one wins). No `--device` records from the default.
- `--capture-rate` opens the device at that rate; `--rate` is the file's, converted
  live by soxr (skipped when they match). `--channels`, `--pick 3,4` (device
  channels from 1; several into one channel are mixed) and `--keep-all` set the
  channels. `--exclusive` is WASAPI exclusive mode.
- `--seconds` stops after exactly that long; otherwise Ctrl+C stops. `--live` writes
  the file as it records instead of when it stops.
- At the end it reports what the device delivered: frames per second by the PC's
  clock (a device at the wrong rate shows here), overflows and gaps.

Every take is written as it records to a working copy: raw float32 in
`%LOCALAPPDATA%\SoundRecorder\takes` (or `$SOUNDREC_TAKES`), deleted once the file
is saved. If the recorder dies first, the take survives:

```
sound-recorder recover              lists takes a crash left behind
sound-recorder recover 1            saves take 1 to the file it was meant for
sound-recorder recover 1 other.wav  ... or to another file
sound-recorder recover 1 --discard  deletes it
```

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
  right, and replug it if not. `--device` keeps the probe off it.
  **Cause found (2026-11-03):** the H2n has one clock for both directions, and
  Windows runs its playback endpoint at 48 kHz but its capture endpoint at 44.1
  kHz. Opening its playback side at 48 kHz (even to play silence) switched its
  input from 44,100 to 48,000 frames a second, still labelled 44.1 kHz, and it
  stayed there after the playback stopped. **The cure is to give both endpoints
  the same rate**: Sound control panel, Playback, Speakers (ZOOM H and F Series
  Audio), Properties, Advanced, Default Format 44100 Hz (or set the recording side
  to 48000 Hz). `scripts/h2n_clock.py --play 48000` shows the effect. Done on this
  laptop (both at 44.1 kHz); `--play 44100` then held 44,100 throughout.
- **The H2n in 4-channel surround mode** is a different device to Windows:
  "Microphone (H2n)", 4 channels, 24-bit, on Windows' own USB driver (no ASIO). Its
  endpoints need the same rate set again (they're new), and **"Enable audio
  enhancements" must be off** on Microphone (H2n). With it on, Windows hands all
  four channels over as one copied signal. `sound-recorder rec --device H2n
  --keep-all --bits 24 out.wav` records all four; without `--keep-all` (and in the
  window) the first two. WASAPI opens it only with all four, so all four are
  captured and the rest dropped.
- **The H2n's ASIO driver loses over half the audio.** It hands over one 64-frame
  buffer every 3 ms (21,381 frames a second) at 44.1 and 48 kHz alike, with any
  block size; 64 frames is the only buffer size it offers. `rec` stops such a take
  after 2 s. Record the H2n over WASAPI shared (or MME, DirectSound, WDM-KS) instead.
- **WASAPI exclusive mode repeats audio.** The PortAudio that comes with
  sounddevice (19.7.0-devel) hands over stale buffers again in exclusive mode:
  about 40% more frames than the device makes, many of them exact repeats of
  earlier blocks (seen on the Realtek mic array and Stereo Mix, at every block
  size and latency tried, 2026-11-03; the H2n not tried). `rec --exclusive` stops
  such a take after about 2 s, when the clock check sees it. Record in shared mode
  or over ASIO instead; the window doesn't offer it. The probe's exclusive-mode
  answers are unaffected.
- **Codecs have limits.** MP3 stops at 48 kHz and two channels, and libsndfile
  writes only layer III of it, though it lists I and II. Opus takes only 8, 12, 16,
  24 and 48 kHz, so a 44.1 kHz take goes up to 48 kHz. FLAC stops at 8 channels.
- A `--probe` run usually takes 2-5 s (about 1 s of it starting PortAudio), but
  two runs once took 38 s between them while the laptop was busy. The cause
  wasn't pinned down.
