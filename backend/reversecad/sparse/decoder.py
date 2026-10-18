#!/usr/bin/env python3
"""Lossless, bounded decoder for the *observed* v2 sparse point packet format.

No Apple libraries required. Unknown flags, vector lane four, reserved header,
extension bytes, and all source bytes are retained. Does not assign physical
units or imply that a slot is an independent optical return.
"""
from __future__ import annotations
import argparse
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import struct

FIELDS = (
    ("points", "f", 4),
    ("confidences", "f", 1),
    ("cameraPixels", "d", 2),
    ("undistortedCameraPixels", "d", 2),
    ("euclideanDistances", "f", 1),
    ("intensities", "f", 1),
    ("signalToNoiseRatios", "f", 1),
    ("bankIds", "B", 1),
    ("spotIds", "B", 1),
    ("echoIds", "B", 1),
    ("flags", "I", 1),
)

class FormatError(ValueError):
    pass

@dataclass(frozen=True)
class Packet:
    raw: bytes
    header: tuple[int, ...]
    fields: dict[str, tuple]
    sections: dict[str, bytes]
    extra: bytes
    gaps: tuple[tuple[int, bytes], ...]

    @property
    def count(self):
        return self.header[1]

    @property
    def sha256(self):
        return hashlib.sha256(self.raw).hexdigest()

    def to_bytes(self):
        """Reassemble independently preserved slices, including uninterpreted bytes."""
        out = bytearray(len(self.raw))
        out[:128] = struct.pack("<16Q", *self.header)
        for i, (name, _, _) in enumerate(FIELDS):
            start = self.header[i + 2]
            out[start:start + len(self.sections[name])] = self.sections[name]
        out[self.header[14]:self.header[14] + len(self.extra)] = self.extra
        for start, data in self.gaps:
            out[start:start + len(data)] = data
        return bytes(out)

    def positive_geometry_mask(self):
        """Analysis selection, NOT a decoded hardware validity bit."""
        return tuple(c > 0 and p[2] > 0 and all(map(math.isfinite, p[:3]))
                     for c, p in zip(self.fields['confidences'], self.fields['points']))

    def extension_candidate(self):
        """Observed structure only; four float lanes have intentionally neutral names."""
        if len(self.extra) < 24:
            return None
        magic, version, payload_bytes, reserved = struct.unpack_from('<IIQQ', self.extra)
        if magic != 0xD2024C08 or version != 1 or payload_bytes != len(self.extra) - 24 or payload_bytes % 16:
            return None
        return {'magic': magic, 'version': version, 'payload_bytes': payload_bytes,
                'reserved_u64': reserved,
                'records_f32': tuple(struct.iter_unpack('<4f', self.extra[24:])),
                'records_u32': tuple(struct.iter_unpack('<4I', self.extra[24:]))}

def decode_packet(data: bytes) -> Packet:
    raw = bytes(data)
    if len(raw) < 128:
        raise FormatError('Truncated 128-byte header')
    h = struct.unpack_from('<16Q', raw)
    if h[0] != 2:
        raise FormatError(f'Unsupported version {h[0]}; source bytes remain unmodified')
    n = h[1]
    if n > (len(raw) - 128) // 71:
        raise FormatError('Record count cannot fit the packet')
    starts = list(h[2:13]) + [h[14]]
    if starts[0] < 128 or starts != sorted(starts) or starts[-1] > len(raw):
        raise FormatError('Offsets overlap header, are unordered, or exceed packet')
    if h[14] + h[13] > len(raw):
        raise FormatError('Extension exceeds packet')
    fields, sections, gaps = {}, {}, []
    if starts[0] > 128:
        gaps.append((128, raw[128:starts[0]]))
    for i, (name, fmt, width) in enumerate(FIELDS):
        start, end = starts[i:i+2]
        size = struct.calcsize('<' + fmt) * width * n
        if start + size > end:
            raise FormatError(f'{name}: declared array overlaps next section')
        section = raw[start:start+size]
        sections[name] = section
        values = tuple(struct.iter_unpack('<' + fmt * width, section))
        fields[name] = tuple(v[0] for v in values) if width == 1 else values
        if start + size < end:
            gaps.append((start+size, raw[start+size:end]))
    extra_end = h[14] + h[13]
    if extra_end < len(raw):
        gaps.append((extra_end, raw[extra_end:]))
    return Packet(raw, h, fields, sections, raw[h[14]:extra_end], tuple(gaps))

def load_recording(directory: str | Path):
    """Return (event, packet) tuples, checking hashes and exact file coverage."""
    directory = Path(directory)
    raw = (directory/'origin-packets.bin').read_bytes()
    events = [json.loads(line) for line in (directory/'origin-events.jsonl').read_text().splitlines() if line.strip()]
    rows = []
    intervals = []
    for event in events:
        if event.get('event') != 'pointCloudSampleBuffer' or 'seriesOffset' not in event:
            continue
        start, size = event['seriesOffset'], event['seriesBytes']
        if not isinstance(start, int) or not isinstance(size, int) or start < 0 or size < 128 or start + size > len(raw):
            raise FormatError('Invalid series interval')
        packet = decode_packet(raw[start:start+size])
        if packet.sha256 != event['sha256']:
            raise FormatError(f'Hash mismatch at sequence {event.get("sequence")}')
        rows.append((event, packet))
        intervals.append((start, start+size))
    cursor = 0
    for start, end in sorted(intervals):
        if start != cursor:
            raise FormatError('Series contains unindexed bytes or overlapping events')
        cursor = end
    if cursor != len(raw):
        raise FormatError('Series trailing bytes are not indexed')
    return rows

def export_recording(directory, output):
    output = Path(output).resolve()
    source = Path(directory).resolve()
    main_root = Path('/Users/pranav/prelude').resolve()
    if output == source or source in output.parents or output == main_root or main_root in output.parents:
        raise ValueError('Output must be outside the source repository')
    output.mkdir(parents=True, exist_ok=True)
    rows = load_recording(source)
    names = ['sequence', 'pts_seconds', 'slot', 'positive_geometry_selection']
    for name, _, width in FIELDS:
        names += [name] if width == 1 else [f'{name}_{i}' for i in range(width)]
    with (output/'slots.csv').open('w', newline='') as f:
        writer = csv.writer(f); writer.writerow(names)
        for event, packet in rows:
            valid = packet.positive_geometry_mask()
            for j in range(packet.count):
                row = [event['sequence'], event.get('pts'), j, valid[j]]
                for name, _, width in FIELDS:
                    value = packet.fields[name][j]
                    row.extend([value] if width == 1 else value)
                writer.writerow(row)
    with (output/'packets.jsonl').open('w') as f:
        for event, packet in rows:
            f.write(json.dumps({'event': event, 'header_u64': packet.header,
                'sha256': packet.sha256, 'extension_hex': packet.extra.hex(),
                'gaps': [(offset, data.hex()) for offset, data in packet.gaps]})+'\n')
    # Whole immutable source stream preserved alongside neutral typed exports.
    (output/'source-packets.bin').write_bytes(b''.join(p.raw for _, p in sorted(rows, key=lambda ep:ep[0]['seriesOffset'])))
    return {'packets': len(rows), 'slots': sum(p.count for _, p in rows), 'output': str(output)}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export_recording(args.recording, args.output), indent=2))
