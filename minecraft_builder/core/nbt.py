"""Small dependency-free NBT writer. Tags are (type ID, value) pairs."""

import struct


def string(value):
    # Java DataOutput.writeUTF uses modified UTF-8, including surrogate pairs.
    units = value.encode("utf-16-be", "surrogatepass")
    result = bytearray()
    for i in range(0, len(units), 2):
        c = (units[i] << 8) | units[i + 1]
        if 1 <= c <= 0x7F:
            result.append(c)
        elif c <= 0x7FF:
            result.extend((0xC0 | (c >> 6), 0x80 | (c & 63)))
        else:
            result.extend((0xE0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63)))
    if len(result) > 65535:
        raise ValueError("NBT string exceeds 65535 encoded bytes")
    return struct.pack(">H", len(result)) + result


def signed64(n):
    n &= (1 << 64) - 1
    return n if n < 1 << 63 else n - (1 << 64)


def payload(kind, value):
    if kind in (1, 2, 3, 4, 5, 6):
        return struct.pack({1: ">b", 2: ">h", 3: ">i", 4: ">q", 5: ">f", 6: ">d"}[kind], value)
    if kind == 7:
        return struct.pack(">i", len(value)) + bytes(value)
    if kind == 8:
        return string(value)
    if kind == 9:
        element, values = value
        return (
            bytes([element])
            + struct.pack(">i", len(values))
            + b"".join(payload(element, v) for v in values)
        )
    if kind == 10:
        return (
            b"".join(bytes([k]) + string(name) + payload(k, v) for name, (k, v) in value.items())
            + b"\0"
        )
    if kind in (11, 12):
        fmt = ">i" if kind == 11 else ">q"
        return struct.pack(">i", len(value)) + b"".join(
            struct.pack(fmt, int(v) if kind == 11 else signed64(v)) for v in value
        )
    raise ValueError("Unsupported NBT tag")


def encode(compound, name=""):
    return b"\x0a" + string(name) + payload(10, compound)


def compound_xyz(values):
    return {k: (3, int(v)) for k, v in zip(("x", "y", "z"), values)}


def block_state(state):
    from .shapes import split_state

    name, props = split_state(state)
    data = {"Name": (8, name)}
    if props:
        data["Properties"] = (10, {k: (8, v) for k, v in props.items()})
    return data


def pack_bits(values, bits, padded=False):
    """Litematica spans long boundaries; modern chunk sections pad each long."""
    per_long = 64 // bits
    count = (len(values) + per_long - 1) // per_long if padded else (len(values) * bits + 63) // 64
    words = [0] * count
    for index, value in enumerate(values):
        if not 0 <= value < 1 << bits:
            raise ValueError("Palette index does not fit bit width")
        word, offset = (
            (divmod(index, per_long)[0], (index % per_long) * bits)
            if padded
            else divmod(index * bits, 64)
        )
        words[word] |= (value << offset) & ((1 << 64) - 1)
        if not padded and offset + bits > 64:
            words[word + 1] |= value >> (64 - offset)
    return words
