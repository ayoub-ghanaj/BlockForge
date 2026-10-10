"""Bounded-memory schematic writers for large, mostly empty perimeter volumes."""

import gzip
import math
import os
import struct
import tempfile
import time
from array import array
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..core import exporters, nbt
from ..core.palette import canonical_state

MAX_VOLUME = 64_000_000
MAX_BLOCKS = 2_000_000


def validate(build):
    size = build["size"]
    if len(size) != 3 or any(type(v) is not int or not 1 <= v <= 2052 for v in size):
        raise ValueError("Invalid perimeter dimensions")
    if math.prod(size) > MAX_VOLUME:
        raise ValueError("Perimeter exceeds 64 million bounding cells; reduce height or dimensions")
    if not 1 <= len(build["cells"]) <= MAX_BLOCKS:
        raise ValueError("Perimeters support up to two million placed blocks")
    if type(build["data_version"]) is not int or build["data_version"] < 1519:
        raise ValueError("Choose a Java 1.13 or newer palette")
    palette = build["palette"]
    if not 1 <= len(palette) < 65534 or len(set(palette)) != len(palette):
        raise ValueError("Invalid perimeter palette")
    for state in palette:
        if state.split("[")[0] in ("minecraft:air", "minecraft:void_air", "minecraft:cave_air"):
            raise ValueError("Air is reserved for empty cells")
        canonical_state(state)
    seen = set()
    sx, sy, sz = size
    for x, y, z, i in build["cells"]:
        if any(type(v) is not int for v in (x, y, z, i)) or not (
            0 <= x < sx and 0 <= y < sy and 0 <= z < sz and 0 <= i < len(palette)
        ):
            raise ValueError("Perimeter block is outside its bounds or palette")
        pos = x + sx * (z + sz * y)
        if pos in seen:
            raise ValueError("Overlapping perimeter blocks")
        seen.add(pos)


class DenseChunks:
    """Only positions and values of placed blocks are retained between passes."""

    def __init__(self, build):
        sx, sy, sz = build["size"]
        self.volume = sx * sy * sz
        cells = np.asarray(build["cells"], dtype=np.int64)
        positions = cells[:, 0] + sx * (cells[:, 2] + sz * cells[:, 1])
        order = np.argsort(positions)
        self.positions = positions[order]
        self.values = (cells[order, 3] + 1).astype(np.uint16)

    def __iter__(self):
        previous = 0
        for start in range(0, self.volume, 65536):
            end = min(self.volume, start + 65536)
            stop = int(np.searchsorted(self.positions, end))
            chunk = np.zeros(end - start, dtype=np.uint16)
            chunk[self.positions[previous:stop] - start] = self.values[previous:stop]
            previous = stop
            yield chunk


@dataclass
class Stream:
    count: int
    chunks: object


@dataclass
class StreamList:
    kind: int
    count: int
    values: object


def payload(output, kind, value):
    if kind in (7, 12) and isinstance(value, Stream):
        output.write(struct.pack(">i", value.count))
        written = 0
        for chunk in value.chunks():
            output.write(chunk)
            written += len(chunk)
        if written != value.count * (8 if kind == 12 else 1):
            raise ValueError("Streaming NBT array length mismatch")
    elif kind == 9:
        if isinstance(value, StreamList):
            element, count, values = value.kind, value.count, value.values()
        else:
            element, values = value
            count = len(values)
        output.write(bytes([element]) + struct.pack(">i", count))
        written = 0
        for item in values:
            payload(output, element, item)
            written += 1
        if written != count:
            raise ValueError("Streaming NBT list length mismatch")
    elif kind == 10:
        for name, (tag, item) in value.items():
            output.write(bytes([tag]) + nbt.string(name))
            payload(output, tag, item)
        output.write(b"\0")
    else:
        output.write(nbt.payload(kind, value))


def encode(output, compound, name=""):
    output.write(b"\x0a" + nbt.string(name))
    payload(output, 10, compound)


def varint_chunks(dense):
    for values in dense:
        lengths = 1 + (values >= 128).astype(np.uint8) + (values >= 16384).astype(np.uint8)
        offsets = np.cumsum(lengths, dtype=np.int64) - lengths
        result = np.empty(int(lengths.sum()), dtype=np.uint8)
        result[offsets] = (values & 127) | np.where(values >= 128, 128, 0).astype(np.uint16)
        mask = values >= 128
        result[offsets[mask] + 1] = ((values[mask] >> 7) & 127) | np.where(
            values[mask] >= 16384, 128, 0
        ).astype(np.uint16)
        mask = values >= 16384
        result[offsets[mask] + 2] = values[mask] >> 14
        yield result.tobytes()


def continuous_longs(dense, bits):
    # Chunk sizes are multiples of 64, hence each chunk starts on a long boundary.
    for values in dense:
        values = values.astype(np.uint64)
        offsets = np.arange(len(values), dtype=np.uint64) * bits
        words = offsets // 64
        shifts = offsets % 64
        result = np.zeros((len(values) * bits + 63) // 64, dtype=np.uint64)
        np.bitwise_or.at(result, words, values << shifts)
        overflow = shifts + bits > 64
        np.bitwise_or.at(result, words[overflow] + 1, values[overflow] >> (64 - shifts[overflow]))
        yield result.astype(">u8").tobytes()


def schematic(build, dense, name, author):
    sx, sy, sz = build["size"]
    palette = ["minecraft:air"] + build["palette"]
    byte_count = (
        dense.volume + int((dense.values >= 128).sum()) + int((dense.values >= 16384).sum())
    )
    return {
        "Version": (3, 2),
        "DataVersion": (3, build["data_version"]),
        "Width": (2, sx),
        "Height": (2, sy),
        "Length": (2, sz),
        "Offset": (11, [0, 0, 0]),
        "PaletteMax": (3, len(palette)),
        "Palette": (10, {s: (3, i) for i, s in enumerate(palette)}),
        "BlockData": (7, Stream(byte_count, lambda: varint_chunks(dense))),
        "BlockEntities": (9, (10, [])),
        "Entities": (9, (10, [])),
        "Metadata": (
            10,
            {"Name": (8, name), "Author": (8, author), "Date": (4, int(time.time() * 1000))},
        ),
    }


def litematic(build, dense, name, author):
    palette = ["minecraft:air"] + build["palette"]
    bits = max(2, (len(palette) - 1).bit_length())
    now = int(time.time() * 1000)
    region = {
        "Position": (10, nbt.compound_xyz((0, 0, 0))),
        "Size": (10, nbt.compound_xyz(build["size"])),
        "BlockStatePalette": (9, (10, [nbt.block_state(s) for s in palette])),
        "BlockStates": (
            12,
            Stream((dense.volume * bits + 63) // 64, lambda: continuous_longs(dense, bits)),
        ),
        "TileEntities": (9, (10, [])),
        "Entities": (9, (10, [])),
        "PendingBlockTicks": (9, (10, [])),
        "PendingFluidTicks": (9, (10, [])),
    }
    meta = {
        "Name": (8, name),
        "Author": (8, author),
        "Description": (8, "Minecraft Builder Perimeter Designer"),
        "RegionCount": (3, 1),
        "TimeCreated": (4, now),
        "TimeModified": (4, now),
        "TotalBlocks": (3, len(build["cells"])),
        "TotalVolume": (3, dense.volume),
        "EnclosingSize": (10, nbt.compound_xyz(build["size"])),
    }
    return {
        "Version": (3, 5),
        "SubVersion": (3, 1),
        "MinecraftDataVersion": (3, build["data_version"]),
        "Metadata": (10, meta),
        "Regions": (10, {"Build": (10, region)}),
    }


def section_stream(build):
    sx, sy, sz = build["size"]
    palette = ["minecraft:void_air", "minecraft:air"] + build["palette"]
    groups = {}
    for x, y, z, index in build["cells"]:
        groups.setdefault((x // 16, y // 16, z // 16), array("H")).extend(
            ((x % 16) + 16 * (z % 16) + 256 * (y % 16), index + 2)
        )
    for cy in range((sy + 15) // 16):
        for cz in range((sz + 15) // 16):
            for cx in range((sx + 15) // 16):
                values = np.zeros((16, 16, 16), dtype=np.uint16)
                values[
                    : min(16, sy - cy * 16), : min(16, sz - cz * 16), : min(16, sx - cx * 16)
                ] = 1
                values = values.ravel()
                entries = groups.get((cx, cy, cz))
                if entries:
                    pairs = np.frombuffer(entries, dtype=np.uint16).reshape(-1, 2)
                    values[pairs[:, 0]] = pairs[:, 1]
                used, inverse = np.unique(values, return_inverse=True)
                states = {"palette": (9, (10, [nbt.block_state(palette[i]) for i in used]))}
                if len(used) > 1:
                    bits = max(4, (len(used) - 1).bit_length())
                    per_word = 64 // bits
                    packed = np.zeros(
                        ((4096 + per_word - 1) // per_word, per_word), dtype=np.uint64
                    )
                    packed.ravel()[:4096] = inverse
                    words = (packed << (np.arange(per_word, dtype=np.uint64) * bits)).sum(
                        axis=1, dtype=np.uint64
                    )
                    states["data"] = (12, words.tolist())
                yield {"X": (3, cx), "Y": (3, cy), "Z": (3, cz), "BlockStates": (10, states)}


def blueprint(output, build, name, author):
    header = nbt.encode(
        {
            "Version": (3, 2),
            "Name": (8, name),
            "Author": (8, author),
            "Tags": (9, (8, ["Blender", "Perimeter"])),
            "ThumbnailYaw": (5, 135.0),
            "ThumbnailPitch": (5, 60.0),
            "LockedThumbnail": (1, 1),
            "BlockCount": (3, len(build["cells"])),
            "ContainsAir": (1, len(build["cells"]) < math.prod(build["size"])),
        }
    )
    png = exporters.thumbnail(build)
    output.write(
        struct.pack(">II", 0x0AE5BB36, len(header)) + header + struct.pack(">I", len(png)) + png
    )
    length_offset = output.tell()
    output.write(b"\0" * 4)
    start = output.tell()
    sections = math.prod((v + 15) // 16 for v in build["size"])
    compound = {
        "DataVersion": (3, build["data_version"]),
        "BlockRegion": (9, StreamList(10, sections, lambda: section_stream(build))),
        "BlockEntities": (9, (10, [])),
        "Entities": (9, (10, [])),
    }
    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as stream:
        encode(stream, compound)
    end = output.tell()
    output.seek(length_offset)
    output.write(struct.pack(">I", end - start))
    output.seek(end)


def write(path, build, kind, name="Perimeter", author=""):
    validate(build)
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            if kind == "bp":
                blueprint(output, build, name, author)
            else:
                dense = DenseChunks(build)
                compound = {"schem": schematic, "litematic": litematic}[kind](
                    build, dense, name, author
                )
                with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as stream:
                    encode(stream, compound, "Schematic" if kind == "schem" else "")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
