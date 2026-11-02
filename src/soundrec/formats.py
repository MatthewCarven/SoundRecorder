"""Sample rates, sample types and channel counts: the lists, and how they read."""

# What the probe tries. 8 kHz is the telephone, 11.025 kHz is Windows 3.1's
# own default, and 352.8/384 kHz turn up on high-end interfaces.
RATES = (8000, 11025, 16000, 22050, 32000, 44100, 48000,
         88200, 96000, 176400, 192000, 352800, 384000)

# sounddevice's names for PortAudio's sample formats, smallest first.
SAMPLE_TYPES = ("uint8", "int16", "int24", "int32", "float32")

TYPE_TEXT = {
    "uint8": "8-bit",
    "int16": "16-bit",
    "int24": "24-bit",
    "int32": "32-bit",
    "float32": "32-bit float",
    "float64": "64-bit float",
    # ASIO's left-aligned types: fewer bits of signal in a 32-bit container.
    "int32/16": "16-bit (in 32)",
    "int32/18": "18-bit (in 32)",
    "int32/20": "20-bit (in 32)",
    "int32/24": "24-bit (in 32)",
}


def khz(rate: float) -> str:
    """44100 -> '44.1', 48000 -> '48', 11025 -> '11.025'."""
    return f"{rate / 1000:g}"


def rates_text(rates) -> str:
    rates = sorted(rates)
    return ", ".join(khz(r) for r in rates) + " kHz" if rates else "no rate"


def types_text(types) -> str:
    return ", ".join(TYPE_TEXT.get(t, t) for t in types) if types else "no sample type"


def channels_text(counts) -> str:
    """[2] -> 'stereo', [1, 2, 3, 4] -> '1-4 ch', [1, 2, 6] -> '1, 2, 6 ch'."""
    counts = sorted(set(counts))
    if not counts:
        return "no channels"
    if len(counts) == 1:
        return {1: "mono", 2: "stereo"}.get(counts[0], f"{counts[0]} ch")
    if counts == list(range(counts[0], counts[-1] + 1)):
        return f"{counts[0]}-{counts[-1]} ch"
    return ", ".join(map(str, counts)) + " ch"
