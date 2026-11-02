# TODO

See PLAN.md for the why.

## Matthew
- [x] `git init` this folder (Phase 1 committed 2026-11-02, branch `master`)
- [x] GitHub: github.com/MatthewCarven/SoundRecorder, public; `origin` added
- [x] Push: `master` pushed 2026-11-03 (Claude, at Matthew's say-so), tracking `origin/master`
- [ ] After any `--probe` that includes the H2n: does it still sound right? Replug if your voice comes out deep
- [x] Replug the H2n: the clock test of 2026-11-03 07:58 left it stuck at 48 kHz (deep). Replugged; 08:41 it read 44,098 frames/s again
- [x] Give the H2n's two endpoints the same rate, so it can't happen again: Sound control panel, Playback, Speakers (ZOOM H and F Series Audio), Properties, Advanced, Default Format 44100 Hz. Done 2026-11-03 08:44; `scripts/h2n_clock.py --play 44100` then held 44,099-44,100 throughout, no replug needed. (Headphones (Realtek) went from 48 kHz to 44.1 kHz 24-bit on the way; harmless)

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
- [x] Capture callback, block queue, worker thread (`engine.py`, `capture.py`)
- [x] Recording threads set up COM themselves: STA for PortAudio, MTA for loopback (`com.py`)
- [x] Channel map (pick, down-mix, keep all, mono copied to stereo)
- [x] Live `soxr.ResampleStream` (VHQ), skipped when the rates match
- [x] Working copy (raw float32 + .json, locked while owned) written as it records; recovery after a crash (`takes.py`, `sound-recorder recover`)
- [x] Direct-to-file encoder option (`--live`); TPDF dither on the way down to 16 or 8 bits (`output.py`)
- [x] Check an MP3 actually writes and reads back through soundfile (and Vorbis, Opus)
- [x] `sound-recorder rec ...` on the command line
- [x] Recorded from every API: WASAPI shared, MME, DirectSound, WDM-KS (Stereo Mix), loopback (Headphones), ASIO (FL Studio's driver). Not yet the H2n itself. WASAPI exclusive opens but repeats audio (below)
- [x] Clock check: frames per second by the PC's clock (least-squares over every block, with its uncertainty); `rec` stops a take more than 1% off
- [ ] Loopback signal check: a quiet test tone out, the same tone back in (warn Matthew first: it plays through his speakers or headphones)
- [x] Ten-minute take, 48→44.1 kHz, no dropouts: WASAPI shared from Stereo Mix, 2026-11-03 07:10-07:20, 28,800,480 frames in, exactly 26,460,000 out, clock 48,000.0 frames/s, no overflows, longest wait between blocks 14 ms, worker never behind (chess engine running at Normal priority). The same through the engine in the tests, phase checked across the take. From the H2n over ASIO: still to do, below

## Surfaced in Phase 1
- [x] **H2n sample-rate bug**: a format query can leave it at the wrong rate, so it sounds deep until replugged (Matthew; Audacity does it). The clock check found it (Phase 2, 2026-11-03): opening its playback endpoint at 48 kHz moves its one clock there, and the capture side, labelled 44.1 kHz, stays at 48 kHz until replugged. ASIO at 48 kHz didn't do it. Whether the probe's 48 kHz checks on the capture side can do it too wasn't tried; with both endpoints on one rate it shouldn't matter
- [ ] Unplugging the H2n marked its render endpoint not present at once, but its capture endpoint only 100 s later (21:46:46 / 21:48:26). The rescan saw the device gone straight away, but a capture-only USB mic might be noticed late. Try an `IMMNotificationClient` if it matters
- [ ] Scan on a background thread in the window. A run usually takes 2-5 s (PortAudio itself ~1 s), but two runs once took 38 s while the laptop was busy, cause unknown
- [ ] "ZOOM H and F Series Async ASIO" won't load (CoCreateInstance: E_OUTOFMEMORY); PortAudio skips it too. Probably only works with the device in another mode
- [ ] WDM-KS lists the Realtek's "PC Speaker" reference pins as inputs (48-192 kHz). They're real, but confusing in a device list: label or hide them in the dialog

## Surfaced in Phase 2
- [ ] **WASAPI exclusive capture is broken in sounddevice's PortAudio (19.7.0-devel)**: it re-delivers stale buffers, 40-60% more frames than the device makes, many exact repeats (Realtek mic array and Stereo Mix, every block size and latency tried). `rec` stops such a take after ~2 s. Options: a newer PortAudio build, or our own WASAPI exclusive capture (ctypes, like asio.py). Until then Phase 5's dialog shouldn't offer exclusive recording
- [x] **H2n deep-voices bug: cause found** (2026-11-03, `scripts/h2n_clock.py --play 48000`): capture alone 44,098 frames/s; with silence playing to its playback endpoint at 48 kHz, 48,000 frames/s, and still 48,000 after the playback stopped. One clock for both directions, and Windows has the two endpoints at different rates. Cure: same rate on both (Matthew, below)
- [ ] **The H2n's ASIO driver delivers 21,381 frames/s**: one 64-frame buffer every 3.00 ms, at 44.1 and 48 kHz, with any block size, even from a bare callback. Over half the audio is lost. Its only buffer size is 64. Look for a buffer setting in the driver's own control panel (IASIO::controlPanel, vtable slot 21, could open it from asio.py); otherwise the Phase 5 dialog should warn against ASIO for it
- [ ] Ten-minute take from the H2n: blocked over ASIO (above) and WASAPI exclusive (the PortAudio bug). Over WASAPI shared it's the same path as the Stereo Mix take, which passed
- [ ] Phase 3: with the H2n's 64-frame ASIO buffer the callback wants the GIL every 1.3 ms; check for overflows with the window drawing (the CLI's main thread just sleeps)
- [x] H2n in 4-channel surround mode: Windows' own USB driver, "Microphone (H2n)" 4 ch 24-bit, no ASIO. Its endpoints came up at 44.1/48 kHz, so Matthew set "Headphones (H2n)" to 44.1 kHz 24-bit too (2026-11-03); the clock then held with playback running
- [x] Windows' "audio enhancements" on Microphone (H2n) collapsed its four channels into one copied signal in shared mode (WASAPI, MME, DirectSound). Unticked by Matthew; WDM-KS bypasses them anyway
- [ ] The Phase 5 dialog could warn when a multichannel device's channels arrive identical (enhancements on, or a mono device posing as stereo): `h2n_clock.py`'s correlation check, run for a second
- [ ] Which of the H2n's 4-channel pairs is front XY and which rear MS, and which channel is left: snap fingers at known spots and read the levels (Matthew there)
- [ ] Loopback's clock reading means little while nothing plays: soundcard pads silence by its own timer
- [ ] WAV stops at 4 GB (about 6.7 hours of 44.1 kHz 16-bit stereo; 3.4 h of float): Phase 5's Save could switch to RF64 past that. The working copy has no such limit

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
