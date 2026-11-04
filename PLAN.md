# Sound Recorder — plan

A sound recorder for Windows that looks and behaves like the Windows 3.1 Sound
Recorder. Under the hood it's modern: it finds every capture device through every
Windows audio API, offers each device's real formats and channels, converts as it
records to whatever rate and channel layout you asked for, and saves in any format
the encoders offer (WAV, FLAC, MP3, OGG Vorbis, Opus, AAC and the rest).

## Decisions (2026-11-02, with Matthew)

| Question | Decision |
|----------|----------|
| Stack | **Python.** PortAudio via `sounddevice` for capture, `soundfile` (libsndfile) for writing, `soxr` for resampling, numpy, tkinter canvas for the UI, PyInstaller for the exe |
| Look | **The full 3.1 frame**: navy caption bar, control-menu box, minimize arrow, white menu bar, all drawn by us. Not just 3.1 controls inside a Windows 11 frame |
| Conversion | **Live while recording.** You pick the output rate and channels before you record; the converter runs on the stream |
| Formats | **WAV, plus everything libsndfile offers** (listed from the library at run time, not hard-coded), **plus FLAC, Opus and AAC (.m4a)** |

Why Python and not C# (SoundTransmitter's stack): the two hardest asks, "full device
detection" and "MP3/OGG output", are each one library that already does all of it.
NAudio has no DirectSound capture and would need two separate encoder packages.

## What this laptop has (checked 2026-11-02)

- Python 3.14.4 (system) with `sounddevice` and numpy; PySynthRack's venv (3.12) has
  the same. The project's own `.venv` (3.14) has sounddevice 0.5.6, soundfile 0.14
  (libsndfile 1.2.2, MP3 included), soxr 1.1 and SoundCard 0.4.6. `ffmpeg` is on
  PATH (winget).
- The ZOOM is an **H2n** (USB 1686:0045). It has a bug: when some programs ask it
  about formats it can drop to the wrong sample rate, and voices come out very deep
  until it's replugged (Matthew, 2026-11-02).
- .NET 10 and VS 2026 too, unused here.
- `sounddevice` with `SD_ENABLE_ASIO=1` lists **20 capture devices over five host
  APIs** in one call:

| API | What it showed |
|-----|----------------|
| MME | Sound Mapper, ZOOM Recording Mixer, Microphone Array (4 ch), Stereo Mix |
| DirectSound | Primary Capture Driver, the same three devices |
| WASAPI | Microphone Array (2 ch, 48 kHz), Stereo Mix, ZOOM Recording Mixer (44.1 kHz) |
| WDM-KS | Mic array split into three raw pins (one 2 ch 48 kHz, two 4 ch **16 kHz**), Stereo Mix, ZOOM |
| ASIO | FL Studio ASIO, ZOOM H and F Series ASIO |

  The same microphone array shows as 4 channels to MME, 2 to WASAPI and 4 ch at
  16 kHz on a raw WDM-KS pin. That's the point of probing per API: each one tells a
  different story, and only some of them are the hardware's own.
- No WASAPI loopback devices in that list (this PortAudio build doesn't expose
  them). Stereo Mix covers "record what you hear" on the Realtek only. SoundCard
  fills the gap: it lists a loopback source for every active playback device and
  records from it at any rate and channel count (checked in Phase 1).

## Architecture

```
 capture (one of)                 converter (live)               document
 ───────────────                  ───────────────                ────────
 MME ┐                                                       ┌─> working copy: float32 at the
 DirectSound ├─ sounddevice ─┐                               │   output rate and channels, temp
 WASAPI (shared/exclusive)   ├─> block queue ─> channel map ─┤   file on disk (display, playback,
 WDM-KS                      │                  soxr stream  │   effects, Save)
 ASIO ┘                      │                               │
 WASAPI loopback ── (extra lib, Phase 1) ┘                   └─> optional: straight into the
                                                                 output encoder as it records
```

- **Capture** runs in PortAudio's callback thread and does nothing but copy the block
  into a queue. Everything else happens on a worker thread, so a slow UI can't cause
  a dropout.
- **Channel map**: pick any input channels (e.g. ZOOM inputs 3 and 4), down-mix to
  mono, or keep all of them for a multichannel WAV.
- **Resample**: `soxr.ResampleStream` at very high quality, only when the output rate
  differs from the capture rate. Otherwise samples pass through untouched.
- **Working copy**: the document always holds lossless float32 at the chosen rate and
  channels. Effects and Save work from it, so an MP3 isn't decoded and re-encoded on
  every edit. It is written as it records, so a crash or a three-hour take loses
  nothing, and on restart the app offers to recover it.
- **Direct-to-file** (option): the chosen encoder also runs live, so a long take is
  already saved when you press Stop.
- **Bit depth** is applied on write, with TPDF dither (random noise that hides the
  rounding) when going down to 16 or 8 bits.
- Save As to a *different* rate or channel layout uses the same converter offline
  and saves a copy: unlike the Windows 95 Sound Recorder's "Convert Now", the sound
  in the window stays as it was (Matthew, 2026-11-04).

### Device detection and format probing

- Enumerate every device on every host API, with ASIO enabled before `sounddevice` is
  imported (`SD_ENABLE_ASIO=1`).
- Probe each input over a grid: rates 8 k–384 kHz × uint8 / int16 / int24 / int32 /
  float32 × 1 to the maximum channel count. As built in Phase 1, per API:
  - MME, DirectSound, loopback: not probed. They take anything, because Windows
    converts behind your back; the endpoint's engine format is the native one.
  - WASAPI: `sd.check_input_settings` in **exclusive** mode with
    `explicit_sample_format`, so PortAudio can't quietly substitute another sample
    type. Honest on all three counts. Without that flag, mono passed as well.
  - WDM-KS: rates × channels against the driver's pin. PortAudio converts sample
    types itself, so those can't be seen.
  - ASIO: the driver is loaded once and asked directly through its COM vtable
    (ctypes) for rates, channel names, sample type and buffer sizes. PortAudio's own
    check reloads the driver for every question: FL Studio's took 3.5 s each, 7.5
    minutes for the grid.
- The device dialog shows "native" against "converted by Windows". It probes only
  when asked, because probing can trip the H2n's sample-rate bug.
- Watch for plug and unplug, so a USB mic appears in the list without a restart.
  Built on a change notification on the MMDevices registry key
  (`RegNotifyChangeKeyValue`), which needs no window and no COM callback. It counts a
  change only when endpoint states differ, and waits for a second of quiet after a
  burst. Then PortAudio is re-initialised, which may happen only while no stream
  is open.
- Show disabled, unplugged and not-present endpoints greyed out, from the MMDevices
  registry: so you can see that a jack exists even when nothing is plugged into it.

### Output formats

- Every format and subtype `soundfile` reports at run time: WAV (8-bit unsigned up to
  32-bit float, WAVE_FORMAT_EXTENSIBLE for multichannel), W64 and RF64 (over 4 GB),
  AIFF, AU, CAF, FLAC, OGG Vorbis, Opus, MP3 (libsndfile 1.1 and later), and the old
  oddities (VOC, IRCAM, NIST...).
- **AAC (.m4a)** isn't in libsndfile. It goes through ffmpeg: `imageio-ffmpeg` bundles
  an ffmpeg binary, so the exe still works on a machine without one. Raw PCM goes
  into ffmpeg's stdin, so it can run live too.
- Quality settings per codec: MP3 CBR/VBR, Vorbis and Opus quality, FLAC
  compression level, AAC bitrate.
- Opening files for editing: everything `soundfile` reads, plus anything ffmpeg can
  decode.

### The 3.1 window

- One fixed-size window, as in the original. Drawn on a tkinter canvas: grey face,
  white and dark-grey bevels, black waveform box with a green trace, Position and
  Length either side, the scrollbar, five buttons (rewind, forward, play, stop, and a
  microphone for record).
- **Frame**: `overrideredirect` window with our own navy caption bar, control-menu
  box (its menu works: Restore, Move, Minimize, Close) and minimize arrow. ctypes
  puts back what `overrideredirect` takes away: the taskbar button, Alt+Tab and
  minimizing (`WS_EX_APPWINDOW`, `SetWindowLong`).
- **Menus**: Windows 11 draws Tk's native menus in its own modern style, so the menu
  bar and drop-downs are ours too (small borderless popups), with keyboard mnemonics.
- **Font**: Windows still ships the old bitmap System font, and Tk draws through GDI,
  so it should render. That gets checked first in Phase 3. If it fails, the fallback
  is a pixel font drawn from bitmaps. **Checked (Phase 3)**: Tk renders it exactly
  (four colours, no smoothing). But GDI picks a raster font's size itself, so at 2x
  the labels' MS Sans Serif would switch to its 18-point design. So the glyphs are
  read from Windows' own `vgasys.fon` and `sserife.fon`, and the whole window is
  drawn into a pixel buffer shown as one Tk image (`ui/fonts.py`, `ui/raster.py`).
- **Measured, not remembered** (Phase 3): the layout comes from a 640x480 3.1
  screenshot. The window is 317 x 169; the labels are MS Sans Serif 8 ("Stopped" in
  GDI's made-up bold); menus are flat with no shadow; disabled glyphs go through a
  checkerboard lined up with each button. Drawn inactive with 3.1's menus, ours
  matches it pixel for pixel. Effects' mnemonic is the s.
- **Menus, as in 3.1**, plus one of ours:
  - File: New, Open..., Save, Save As..., Save Tracks (ours: Track 1..., to Track
    N..., All Tracks...), Revert..., Exit
  - Edit: Insert File..., Mix with File..., Delete Before Current Position, Delete
    After Current Position
  - Effects: Increase Volume (by 25%), Decrease Volume, Increase Speed (by 100%),
    Decrease Speed, Add Echo (ours: a submenu, 50 ms to 500 ms), Reverse
  - Device (ours): Recording Device..., Output Format..., Refresh Devices
  - Help: About Sound Recorder...
- A level meter while recording, in keeping with the look (a green bar inside the
  waveform box, or the trace itself going live as it did in 3.1). Both, as built:
  the trace goes live, and at Matthew's request (2026-11-03) two peak-meter bars
  run along the wave box's top and bottom edges (left, right) while recording or
  playing, -60 to 0 dBFS in 3.1's green, yellow and red, with peak hold.

## Phases (one session each)

**Phase 1: devices. Done 2026-11-02** (WORKLOG has the details). Project skeleton and venv (3.14 if `soundfile` and `soxr` have
wheels for it, otherwise 3.12), `soundfile` and `soxr` installed, the device list
over all five APIs, the format probe with native and converted labels, the greyed-out
endpoints, hot-plug refresh, and a loopback answer (`soundcard`, `PyAudioWPatch` or a
small `comtypes` WASAPI capture, whichever works). `sound-recorder --list` prints the
lot. Tests on fake device tables. **Done when** `--list` shows the ZOOM's real native
formats over ASIO and WDM-KS.

**Phase 2: recording engine. Done 2026-11-03.** The ten-minute take ran over WASAPI
from Stereo Mix; the H2n's own couldn't run over ASIO (its driver loses half the
audio) or WASAPI exclusive (PortAudio repeats blocks): WORKLOG. Capture, queue, channel map, live soxr resampling, the
working-copy file, the optional direct-to-file encoder, dither, recovery after a
crash. `sound-recorder rec --device ... --rate 44100 --channels 1 out.flac` records
from the command line. Tests: a sine wave through the converter comes out at the
right pitch and level, with no clicks at block boundaries. **Done when** a ten-minute
take from the ZOOM over ASIO, resampled 48→44.1 kHz, has no dropouts.

**Phase 3: the 3.1 window.** Font check first. Then the frame, the menus, the
waveform display, the scrollbar, the buttons, playback, and File New, Open, Save,
Save As, Revert. **Done when** Matthew says it looks right. **Done 2026-11-03**
(WORKLOG): recording and playback checked through the window (playback by
loopback, with Matthew's OK), the frame tried by Matthew (a caption-drag crash
found and fixed), and he liked it at 2x, now the default. Open and Save As use
Windows' own file dialogs for now.

**Phase 4: Edit and Effects.** The four 3.1 Edit items and the six Effects, on the
working copy, with undo (Revert reloads the saved file, as in 3.1). Inserted and
mixed files are converted to the document's format first. Tests for each effect.
**Built 2026-11-03** (`edits.py`): each command writes a new take block by block
and the document swaps it in, so a failure leaves the sound as it was. Decrease
Volume divides by 1.25, so it undoes Increase; speed is a soxr resample; the echo
(0.25 s, -6 dB, one repeat) was our guess at 3.1's, which Matthew calls a close
match from memory, and it's now 50 to 500 ms from a submenu. Deletes ask first. Also brought
forward from Phase 5 at Matthew's ask: Mono / Stereo / All Channels in the Device
menu, and playback mixing extra channels into stereo. Waits on Matthew's try.

**File > Save Tracks: built 2026-11-04, Matthew's request.** A cascade in the
File menu with one item per channel, plus All Tracks (his yes). Our menus gained
cascades for it (`menus.py`: one level, a second popup window). Each track is
written mono through `Take.save_tracks`, one pass over the take however many
tracks, and `output.replacing` puts them in place all together. Save As's rate and
channel conversion builds on the same two.

**Phase 5: formats and dialogs. Built 2026-11-04** (WORKLOG). The Recording Device
dialog (API, device, native formats, channel names, probing only on request) and
the Output Format dialog (format, encoding, quality, rate, channels), both drawn in
3.1 style on `ui/dialog.py`'s base and `ui/controls.py`'s list box; AAC through
imageio-ffmpeg; Save As converting rate and channels. Rate and channels live in
Output Format, since Windows' own Save dialog can't take a Convert button (my
choice, easy to change). A Save As that converts saves a copy and leaves the sound
in the window alone (Matthew's choice). A channel picker wasn't built: the dialog
shows the channels' names. Waits on Matthew's try.

**Phase 6: package.** PyInstaller one-folder or one-file exe with libsndfile,
PortAudio (ASIO build) and ffmpeg bundled, an icon, settings remembered (last device,
format, folder), and a smoke test of the built exe.

## Risks and open questions

- ~~Loopback.~~ Settled in Phase 1: SoundCard. It sets up COM as multithreaded on
  the thread that imports it, so recording threads in Phase 2 need COM set up
  themselves.
- ~~MP3 in the `soundfile` wheel.~~ Settled: libsndfile 1.2.2 lists MPEG layers I, II
  and III, and in Phase 2 an MP3 written through it read back at the same length,
  pitch and level (so did Vorbis and Opus).
- **The H2n's sample-rate bug.** A format query can leave it at the wrong rate.
  Phase 2 tries a clock check: count the frames a device really delivers per
  wall-clock second against what it claims. If the bug changes how fast samples
  arrive (not known yet), that catches it as it happens, and lets us find which
  query sets it off (WASAPI exclusive, WDM-KS or ASIO), so the probe can avoid that
  query. If it doesn't, a known tone has to be the judge. **Settled in Phase 2**:
  the H2n has one clock for both directions, and Windows ran its playback endpoint
  at 48 kHz and its capture endpoint at 44.1 kHz. Opening the playback side at 48
  kHz moved the capture side to 48,000 frames a second, still labelled 44.1 kHz,
  until a replug. The cure is one rate on both endpoints (Matthew's setting); the
  clock check in `rec` catches it if it happens anyway.
- **The H2n's ASIO driver loses over half the audio** (found in Phase 2): one
  64-frame buffer every 3 ms, 21,381 frames a second, at either rate. Unless its
  control panel has a bigger buffer, the dialog should steer the H2n to WASAPI.
- **WASAPI exclusive capture through PortAudio repeats audio** (found in Phase 2):
  sounddevice's PortAudio 19.7.0-devel re-delivers stale buffers in exclusive mode,
  40-60% more frames than the device makes. The clock check catches it and `rec`
  stops. Exclusive recording needs a newer PortAudio or a WASAPI capture of our own
  before the dialog offers it. Shared mode, ASIO, WDM-KS, MME, DirectSound and
  loopback are all sound.
- **ASIO drivers are single-client.** If FL Studio holds its ASIO driver, or the ZOOM
  is open in another app, opening it fails. Say so plainly in the UI, don't crash.
- **Live conversion and lossy output.** Encoding live means each take is encoded
  once, at record time. Effects then re-encode from the lossless working copy on
  Save, never from the MP3.
- **`overrideredirect` quirks** (taskbar, Alt+Tab, Win+D). These have known ctypes
  fixes, but they're fiddly. Phase 3 starts with them. Done in Phase 3
  (`ui/window.py`): WS_EX_APPWINDOW for the taskbar and Alt+Tab, WS_MINIMIZEBOX and
  ShowWindow for minimizing, SetWindowPos per mouse move for dragging (handing the
  drag to Windows with WM_NCLBUTTONDOWN crashed tkinter); menus in a
  WS_EX_NOACTIVATE popup moved with SetWindowPos (Tk dropped its first move).
  Matthew checked the taskbar, Alt+Tab, minimize and Win+D on 2026-11-03.
- **Licences.** libsndfile, LAME, PortAudio and ffmpeg are LGPL or GPL builds. Fine
  for personal use; worth a look only if the exe is ever given away.
