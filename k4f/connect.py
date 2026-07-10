import struct
from typing import AsyncIterator, Tuple


HEADER_SIZE = 5  # 1 byte flag + 4 bytes length


def encode_unary(data: bytes, flag_byte: int = 0x00) -> bytes:
    return struct.pack("!BI", flag_byte, len(data)) + data


def decode_frame_header(data: bytes) -> Tuple[int, int]:
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Need at least {HEADER_SIZE} bytes for frame header")
    flag, length = struct.unpack("!BI", data[:HEADER_SIZE])
    return flag, length


async def read_streamed_frames(
    stream: AsyncIterator[bytes],
) -> AsyncIterator[Tuple[int, bytes]]:
    buffer = bytearray()

    async for chunk in stream:
        buffer.extend(chunk)

        while True:
            if len(buffer) < HEADER_SIZE:
                break

            flag, length = decode_frame_header(bytes(buffer[:HEADER_SIZE]))

            frame_total = HEADER_SIZE + length
            if len(buffer) < frame_total:
                break

            payload = bytes(buffer[HEADER_SIZE:frame_total])
            buffer = buffer[frame_total:]

            yield flag, payload
