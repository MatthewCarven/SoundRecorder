# TODO

See PLAN.md for the why.

## Matthew
- [x] `git init` this folder (Phase 1 committed 2026-11-02, branch `master`)
- [ ] Say whether it goes on GitHub, public or private (no remote yet)
- [ ] After any `--probe` that includes the H2n: does it still sound right? Replug if your voice comes out deep

## Phase 1: devices (done 2026-11-02)
- [x] Project skeleton, venv (3.14), `soundfile` + `soxr` + `SoundCard` installed
- [x] Device list over MME, DirectSound, WASAPI, WDM-KS and ASIO (`SD_ENABLE_ASIO`), 23 inputs here
- [x] Format probe: WASAPI exclusive with explicit sample format; WDM-KS rates and channels; ASIO asked directly (rates, channel names, sample type, buffers); shared APIs labelled "converted by Windows" with the engine format
- [x] Disabled, unplugged and not-present endpoints from MMDevices; hidden ones behind `--all`
- [x] Hot-plug: registry change notification, endpoint-state diff, 1 s settle, PortAudio rescan. Checked with the H2n both ways (2026-11-02 21:46 and 21:52)
- [x] Loopback: SoundCard lists and records it, any rate and channel count
- [x] `sound-recorder --list / --probe / --device / --outputs / --all / --watch`
- [x] libsndfile 1.2.2 lists MP3 (layers I-III), OGG Vorbis and Opus, FLAC: no `lameenc` needed
- [x] 40 tests on tables (PortAudio blocked in tests: starting it loads every ASIO driver)

## Phase 2: recording engine
- [ ] Capture callback, block queue, worker thread
- [ ] Recording threads set up COM themselves (SoundCard only sets it up on the thread that imports it)
- [ ] Channel map (pick, down-mix, keep all)
- [ ] Live `soxr.ResampleStream`, skipped when the rates match
- [ ] Working copy (float32 temp file) written as it records; recovery after a crash
- [ ] Direct-to-file encoder option; TPDF dither on the way down to 16 or 8 bits
- [ ] Check an MP3 actually writes and reads back through soundfile
- [ ] `sound-recorder rec ...` on the command line
- [ ] Loopback signal check: a quiet test tone out, the same tone back in (warn Matthew first: it plays through his speakers or headphones)
- [ ] Ten-minute take, 48→44.1 kHz, no dropouts. The H2n's ASIO is 44.1/48 kHz 16-bit only, so the 48→44.1 resample is a fair test. If it drops out, check the chess bot first: it runs at above-normal priority (Matthew)

## Surfaced in Phase 1
- [ ] **H2n sample-rate bug**: a format query can leave it at the wrong rate, so it sounds deep until replugged (Matthew; Audacity does it). Try a clock check (frames delivered per wall-clock second against the claimed rate), then find which query sets it off: WASAPI exclusive, WDM-KS or ASIO. Needs Matthew on hand to replug
- [ ] Unplugging the H2n marked its render endpoint not present at once, but its capture endpoint only 100 s later (21:46:46 / 21:48:26). The rescan saw the device gone straight away, but a capture-only USB mic might be noticed late. Try an `IMMNotificationClient` if it matters
- [ ] Scan on a background thread in the window. A run usually takes 2-5 s (PortAudio itself ~1 s), but two runs once took 38 s while the laptop was busy, cause unknown
- [ ] "ZOOM H and F Series Async ASIO" won't load (CoCreateInstance: E_OUTOFMEMORY); PortAudio skips it too. Probably only works with the device in another mode
- [ ] WDM-KS lists the Realtek's "PC Speaker" reference pins as inputs (48-192 kHz). They're real, but confusing in a device list: label or hide them in the dialog

## Phase 3: the 3.1 window
- [ ] Bitmap System font in Tk: works or not (pixel-font fallback)
- [ ] `overrideredirect` frame + taskbar / Alt+Tab / minimize fixes
- [ ] Own menu bar and drop-downs
- [ ] Waveform box, Position / Length, scrollbar, five buttons, level display
- [ ] Playback; File New / Open / Save / Save As / Revert

## Phase 4: Edit and Effects
- [ ] Insert File, Mix with File, Delete Before / After Current Position
- [ ] Volume ±25%, Speed ±100%, Add Echo, Reverse

## Phase 5: formats and dialogs
- [ ] Recording Device dialog (API, device, native formats, channel names); probe on demand only
- [ ] Output Format dialog (every `soundfile` format and subtype, quality per codec)
- [ ] AAC (.m4a) through ffmpeg (`imageio-ffmpeg`)
- [ ] Save As with a different rate or channel layout

## Phase 6: package
- [ ] PyInstaller build with PortAudio (ASIO), libsndfile and ffmpeg bundled
- [ ] Icon, remembered settings, smoke test of the built exe
