# Sound Recorder

A sound recorder for Windows that will look and behave like the Windows 3.1 one,
over every Windows audio API, in every format. [PLAN.md](PLAN.md) has the design
and the phases. Done so far: Phase 1 (finding devices and what they really do) and
Phase 2 (the recording engine, driven from the command line). The window comes in
Phase 3.

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

### Recording

```
sound-recorder rec out.flac
sound-recorder rec --device "Stereo Mix" --api WASAPI --capture-rate 48000 --rate 44100 --seconds 60 take.wav
sound-recorder rec --device zoom --api ASIO --pick 2 --channels 1 --bits 24 voice.flac
sound-recorder rec --api Loopback --live what-i-hear.mp3
```

- The file's extension picks the format: `.wav .flac .mp3 .ogg` (Vorbis) `.opus
  .aiff .caf .w64 .rf64` and everything else libsndfile writes. `--bits 8|16|24|32|float`
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
  to 48000 Hz). `scripts/h2n_clock.py --play 48000` shows the effect.
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
  or over ASIO instead. The probe's exclusive-mode answers are unaffected.
- A `--probe` run usually takes 2-5 s (about 1 s of it starting PortAudio), but
  two runs once took 38 s between them while the laptop was busy. The cause
  wasn't pinned down.
