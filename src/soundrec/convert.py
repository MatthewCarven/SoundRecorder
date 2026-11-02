"""The live converter: captured blocks in, the document's channels and rate out.

Blocks are float32, frames x channels. The channel map runs first (so a
down-mix resamples one channel, not two), then soxr's streaming resampler,
which keeps its filter state from block to block: the output is the same,
sample for sample, as resampling the whole take in one go, so block
boundaries leave no trace.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import soxr

QUALITY = "VHQ"  # soxr's very high quality: about 1000x real time for stereo here


@dataclass(frozen=True)
class ChannelMap:
    """Which captured channels make which output channels.

    Three shapes: route the picked channels one to one (keep all, or pick
    ZOOM inputs 3 and 4), down-mix them to mono (their average), or copy one
    channel to every output (a mono mic as stereo).
    """
    inputs: int              # channels captured
    pick: tuple[int, ...]    # captured channels used, 0-based
    outputs: int

    @classmethod
    def build(cls, inputs: int, outputs: int, pick=None) -> ChannelMap:
        pick = tuple(range(inputs)) if pick is None else tuple(pick)
        if inputs < 1 or outputs < 1:
            raise ValueError("needs at least one channel in and one out")
        if not pick:
            raise ValueError("no channels picked")
        bad = [c + 1 for c in pick if not 0 <= c < inputs]
        if bad:
            raise ValueError(f"channel {bad[0]} isn't captured (1-{inputs})")
        if len(pick) != outputs and outputs != 1 and len(pick) != 1:
            raise ValueError(f"{len(pick)} channels can't make {outputs}: "
                             f"pick {outputs}, or mix down to 1")
        return cls(inputs, pick, outputs)

    @property
    def is_identity(self) -> bool:
        return self.pick == tuple(range(self.inputs)) and self.outputs == self.inputs

    def describe(self) -> str:
        names = ", ".join(str(c + 1) for c in self.pick)
        if self.is_identity:
            return "all channels as captured"
        if self.outputs == len(self.pick):
            return f"channels {names}" if len(self.pick) > 1 else f"channel {names}"
        if self.outputs == 1:
            return f"channels {names} mixed to mono"
        return f"channel {names} copied to {self.outputs} channels"

    def apply(self, block: np.ndarray) -> np.ndarray:
        if self.is_identity:
            return block
        picked = block[:, self.pick]
        if self.outputs == len(self.pick):
            return picked
        if self.outputs == 1:
            return picked.mean(axis=1, keepdims=True, dtype=np.float32)
        return np.repeat(picked, self.outputs, axis=1)


class Resampler:
    """soxr's streaming resampler, or nothing at all when the rates match."""

    def __init__(self, in_rate: int, out_rate: int, channels: int, quality: str = QUALITY):
        self.in_rate, self.out_rate, self.channels = in_rate, out_rate, channels
        self.passthrough = in_rate == out_rate
        self._stream = None if self.passthrough else soxr.ResampleStream(
            in_rate, out_rate, channels, dtype="float32", quality=quality)

    def process(self, block: np.ndarray) -> np.ndarray:
        if self.passthrough:
            return block
        return self._stream.resample_chunk(np.ascontiguousarray(block, dtype=np.float32))

    def flush(self) -> np.ndarray:
        """What the filter still holds; call once, at the end of the take."""
        empty = np.zeros((0, self.channels), np.float32)
        return empty if self.passthrough else self._stream.resample_chunk(empty, last=True)


class Converter:
    """Channel map, then resampler: one captured block in, one output block out."""

    def __init__(self, in_rate: int, in_channels: int, out_rate: int, out_channels: int,
                 pick=None, quality: str = QUALITY):
        self.map = ChannelMap.build(in_channels, out_channels, pick)
        self.resampler = Resampler(in_rate, out_rate, out_channels, quality)
        self.in_rate, self.out_rate = in_rate, out_rate

    def process(self, block: np.ndarray) -> np.ndarray:
        return self.resampler.process(self.map.apply(block))

    def flush(self) -> np.ndarray:
        return self.resampler.flush()
