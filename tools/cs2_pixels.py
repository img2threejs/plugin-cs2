#!/usr/bin/env python3
"""Pixel measurement for the CS2 terminal review. Standard library only.

Every number this module returns is computed from decoded pixels. Nothing is defaulted, estimated
or substituted: an image that cannot be decoded raises ImageDecodeError, and the callers refuse an
image that has no measurable subject instead of scoring it.

Procedure, shared by every metric so reference and render are always treated identically:

  1. Decode the 8-bit non-interlaced PNG.
  2. Estimate the background from the four frame corners (median colour, 75th percentile of the
     corner noise) and mark a sample as subject when it is opaque and either farther from the
     background than max(24, 2.4 x noise) or visibly saturated and not near-white. A frame with a
     meaningful transparent area is masked by alpha instead. This is the rule the base pipeline's
     Tier-1 diagnostics use, restated here because a plugin may not import forge.*.
  3. Nearest-sample the frame onto a GRID x GRID lattice and keep the largest 4-connected blob as the
     silhouette. The lattice stretches the frame, so callers require reference and render frames of
     the same aspect ratio.

All measurements run on that lattice. Scope: these are silhouette, colour-distribution and
local-structure agreement numbers. They do not measure specular response, normal detail or wear, and
an aligned but differently lit render can still score high on them. The definitions travel with every
produced metrics file so a reader sees exactly what was and was not measured.
"""
from __future__ import annotations

import math
import struct
import zlib
from typing import Callable, NamedTuple

GRID = 224
MIN_SUBJECT_FRACTION = 0.035   # smaller than this and the mask is noise, not a silhouette
MAX_SUBJECT_FRACTION = 0.9     # larger than this and the subject is not isolated from the background
MAX_PIXELS = 40_000_000
HISTOGRAM_SHIFT = 4            # 16 levels per channel for the finish colour-distribution measure
REGION_SHIFT = 6               # 4 levels per channel for painted-region colour bins
MAX_PAINTED_REGIONS = 4
MIN_REGION_SHARE = 0.01
TILE_COUNT = 4                 # TILE_COUNT x TILE_COUNT tiles for the structural detail windows
MAX_DETAIL_FEATURES = 4
MIN_TILE_CELLS = 64
MIN_CORRELATION_CELLS = 16
FLAT_VARIANCE = 1e-9
DIGITS = 6

PARAMETERS = {
    "grid": GRID,
    "minSubjectFraction": MIN_SUBJECT_FRACTION,
    "maxSubjectFraction": MAX_SUBJECT_FRACTION,
    "histogramLevelsPerChannel": 256 >> HISTOGRAM_SHIFT,
    "regionLevelsPerChannel": 256 >> REGION_SHIFT,
    "maxPaintedRegions": MAX_PAINTED_REGIONS,
    "minRegionShare": MIN_REGION_SHARE,
    "detailTiles": f"{TILE_COUNT}x{TILE_COUNT}",
    "maxDetailFeatures": MAX_DETAIL_FEATURES,
    "minTileCells": MIN_TILE_CELLS,
    "digits": DIGITS,
}

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class ImageDecodeError(ValueError):
    """The bytes are not an image this module can decode exactly."""


class Image(NamedTuple):
    width: int
    height: int
    pixel: Callable[[int, int], tuple[int, int, int, int]]
    corners: list[tuple[int, int, int, int]]


class Sampled(NamedTuple):
    width: int
    height: int
    rgb: list[tuple[int, int, int]]
    subject: list[bool]
    raw_fraction: float
    subject_fraction: float


def _unfilter(raw: bytes, height: int, row_bytes: int, bpp: int) -> list[bytes]:
    rows: list[bytes] = []
    previous = bytes(row_bytes)
    offset = 0
    for _ in range(height):
        kind = raw[offset]
        line = raw[offset + 1: offset + 1 + row_bytes]
        offset += 1 + row_bytes
        if kind == 0:
            current = line
        elif kind == 1:
            work = bytearray(line)
            for index in range(bpp, row_bytes):
                work[index] = (work[index] + work[index - bpp]) & 0xFF
            current = bytes(work)
        elif kind == 2:
            current = bytes((a + b) & 0xFF for a, b in zip(line, previous))
        elif kind == 3:
            work = bytearray(line)
            for index in range(row_bytes):
                left = work[index - bpp] if index >= bpp else 0
                work[index] = (work[index] + ((left + previous[index]) >> 1)) & 0xFF
            current = bytes(work)
        elif kind == 4:
            work = bytearray(line)
            for index in range(row_bytes):
                a = work[index - bpp] if index >= bpp else 0
                b = previous[index]
                c = previous[index - bpp] if index >= bpp else 0
                estimate = a + b - c
                pa, pb, pc = abs(estimate - a), abs(estimate - b), abs(estimate - c)
                predictor = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                work[index] = (work[index] + predictor) & 0xFF
            current = bytes(work)
        else:
            raise ImageDecodeError(f"PNG scanline uses unknown filter type {kind}")
        rows.append(current)
        previous = current
    return rows


def decode_png(data: bytes) -> Image:
    if not data.startswith(PNG_SIGNATURE):
        raise ImageDecodeError("not a PNG file (only 8-bit non-interlaced PNG is decoded; convert other formats first)")
    cursor = len(PNG_SIGNATURE)
    header: tuple[int, ...] | None = None
    palette = b""
    transparency: bytes | None = None
    idat = bytearray()
    seen_end = False
    first = True
    while cursor + 12 <= len(data):
        length = struct.unpack(">I", data[cursor: cursor + 4])[0]
        kind = data[cursor + 4: cursor + 8]
        end = cursor + 8 + length
        if end + 4 > len(data):
            raise ImageDecodeError("PNG chunk runs past the end of the file")
        payload = data[cursor + 8: end]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != struct.unpack(">I", data[end: end + 4])[0]:
            raise ImageDecodeError(f"PNG chunk {kind!r} fails its CRC")
        if first and (kind != b"IHDR" or length != 13):
            raise ImageDecodeError("PNG does not start with a 13 byte IHDR")
        first = False
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", payload)
        elif kind == b"PLTE":
            palette = payload
        elif kind == b"tRNS":
            transparency = payload
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            seen_end = True
            break
        cursor = end + 4
    if header is None or not seen_end:
        raise ImageDecodeError("PNG is truncated (no IHDR or no IEND)")
    width, height, depth, color_type, compression, filter_method, interlace = header
    if width < 1 or height < 1 or width * height > MAX_PIXELS:
        raise ImageDecodeError(f"PNG dimensions {width}x{height} are outside the supported range")
    if depth != 8 or interlace != 0 or compression != 0 or filter_method != 0:
        raise ImageDecodeError("unsupported PNG; only 8-bit non-interlaced images are decoded")
    channels = _CHANNELS.get(color_type)
    if channels is None:
        raise ImageDecodeError(f"unsupported PNG colour type {color_type}")
    if color_type == 3 and (not palette or len(palette) % 3):
        raise ImageDecodeError("palette PNG has no usable PLTE chunk")
    transparent_color = None
    if transparency is not None:
        if color_type == 0 and len(transparency) == 2:
            transparent_color = struct.unpack(">H", transparency)
        elif color_type == 2 and len(transparency) == 6:
            transparent_color = struct.unpack(">HHH", transparency)
        elif color_type == 3 and 0 < len(transparency) <= len(palette) // 3:
            pass
        else:
            raise ImageDecodeError("invalid PNG transparency chunk")
        if transparent_color is not None and any(value > 255 for value in transparent_color):
            raise ImageDecodeError("PNG transparency key exceeds its bit depth")
    row_bytes = width * channels
    expected = height * (1 + row_bytes)
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(bytes(idat), expected + 1)
    except zlib.error as error:
        raise ImageDecodeError(f"PNG pixel stream is corrupt: {error}") from error
    if len(raw) != expected or not inflater.eof:
        raise ImageDecodeError("PNG pixel stream length does not match its dimensions")
    rows = _unfilter(raw, height, row_bytes, channels)

    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        row = rows[y]
        base = x * channels
        if color_type == 2:
            color = (row[base], row[base + 1], row[base + 2])
            return color[0], color[1], color[2], 0 if color == transparent_color else 255
        if color_type == 6:
            return row[base], row[base + 1], row[base + 2], row[base + 3]
        if color_type == 0:
            value = row[base]
            return value, value, value, 0 if (value,) == transparent_color else 255
        if color_type == 4:
            return row[base], row[base], row[base], row[base + 1]
        index = row[base]
        if index * 3 + 2 >= len(palette):
            raise ImageDecodeError("palette index is outside PLTE")
        alpha = transparency[index] if transparency is not None and index < len(transparency) else 255
        return palette[index * 3], palette[index * 3 + 1], palette[index * 3 + 2], alpha

    radius = max(3, min(width, height) // 40)
    corners: list[tuple[int, int, int, int]] = []
    for x0, x1, y0, y1 in ((0, radius, 0, radius), (width - radius, width, 0, radius),
                           (0, radius, height - radius, height), (width - radius, width, height - radius, height)):
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                corners.append(pixel(x, y))
    return Image(width, height, pixel, corners)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[int(round(max(0.0, min(1.0, fraction)) * (len(ordered) - 1)))]


def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _largest_blob(mask: list[bool]) -> list[bool]:
    seen = [False] * len(mask)
    best: list[int] = []
    for start in range(len(mask)):
        if not mask[start] or seen[start]:
            continue
        seen[start] = True
        stack = [start]
        blob: list[int] = []
        while stack:
            index = stack.pop()
            blob.append(index)
            y, x = divmod(index, GRID)
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < GRID and 0 <= ny < GRID:
                    neighbour = ny * GRID + nx
                    if mask[neighbour] and not seen[neighbour]:
                        seen[neighbour] = True
                        stack.append(neighbour)
        if len(blob) > len(best):
            best = blob
    result = [False] * len(mask)
    for index in best:
        result[index] = True
    return result


def sample_image(image: Image) -> Sampled:
    visible = [(r, g, b) for r, g, b, a in image.corners if a > 16]
    if visible:
        background = tuple(int(_percentile([float(p[c]) for p in visible], 0.5)) for c in range(3))
    else:
        background = (255, 255, 255)
    noise = _percentile([_distance(p, background) for p in visible], 0.75)
    threshold = max(24.0, noise * 2.4)
    cells = [image.pixel(min(image.width - 1, int(gx * image.width / GRID)),
                         min(image.height - 1, int(gy * image.height / GRID)))
             for gy in range(GRID) for gx in range(GRID)]
    rgb = [(r, g, b) for r, g, b, _ in cells]
    if sum(1 for _, _, _, a in cells if a < 245) / len(cells) > 0.03:
        raw = [a > 24 for _, _, _, a in cells]
    else:
        raw = []
        for r, g, b, a in cells:
            high, low = max(r, g, b), min(r, g, b)
            saturation = 0.0 if high <= 0 else (high - low) / high
            luma = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
            raw.append(a > 16 and (_distance((r, g, b), background) > threshold or (saturation > 0.16 and luma < 0.94)))
    subject = _largest_blob(raw)
    total = len(raw)
    return Sampled(image.width, image.height, rgb, subject, sum(raw) / total, sum(subject) / total)


def identical_cells(a: Sampled, b: Sampled) -> bool:
    """True when two frames are indistinguishable at measurement resolution."""
    return a.rgb == b.rgb


def _bbox(mask: list[bool]) -> tuple[int, int]:
    xs = [index % GRID for index, value in enumerate(mask) if value]
    ys = [index // GRID for index, value in enumerate(mask) if value]
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def _luma(color: tuple[int, int, int]) -> float:
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def _round(value: float) -> float:
    return round(value, DIGITS)


def _correlation(a: list[float], b: list[float]) -> float:
    """Zero-mean normalised cross-correlation clipped to [0, 1].

    Limit cases, fixed by definition rather than guessed: fewer than MIN_CORRELATION_CELLS shared
    cells is 0.0 (nothing comparable was observed); two flat patches score 1.0 when their means agree
    within one grey level and 0.0 otherwise; exactly one flat patch is 0.0."""
    count = len(a)
    if count < MIN_CORRELATION_CELLS:
        return 0.0
    mean_a, mean_b = math.fsum(a) / count, math.fsum(b) / count
    var_a = math.fsum((x - mean_a) ** 2 for x in a)
    var_b = math.fsum((y - mean_b) ** 2 for y in b)
    flat_a, flat_b = var_a <= FLAT_VARIANCE, var_b <= FLAT_VARIANCE
    if flat_a and flat_b:
        return 1.0 if abs(mean_a - mean_b) <= 1.0 else 0.0
    if flat_a or flat_b:
        return 0.0
    covariance = math.fsum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    return _clip(covariance / math.sqrt(var_a * var_b))


def silhouette_measures(reference: Sampled, capture: Sampled) -> dict[str, float]:
    """IoU of the two silhouettes, bounding-box aspect and scale deltas, and reference coverage.

    Aspect is the subject's true pixel aspect (lattice box scaled back by its frame's aspect); scale
    is the subject box's share of the frame, so it is independent of resolution."""
    ref, cap = reference.subject, capture.subject
    union = sum(1 for r, c in zip(ref, cap) if r or c)
    inter = sum(1 for r, c in zip(ref, cap) if r and c)
    rw, rh = _bbox(ref)
    cw, ch = _bbox(cap)
    ref_aspect = (rw * reference.width) / (rh * reference.height)
    cap_aspect = (cw * capture.width) / (ch * capture.height)
    return {
        "silhouetteIoU": _round(inter / union),
        "aspectRatioDelta": _round(abs(ref_aspect - cap_aspect) / ref_aspect),
        "scaleDelta": _round(abs(rw * rh - cw * ch) / (rw * rh)),
        "coverage": _round(inter / sum(ref)),
    }


def finish_colour_response(reference: Sampled, capture: Sampled) -> float:
    """Histogram intersection of the subject colour distributions (16 levels per channel).

    Range [0, 1], 1.0 for identical distributions. Pose independent; measures colour and tone
    agreement only, not specular response."""

    def histogram(sampled: Sampled) -> dict[int, float]:
        counts: dict[int, int] = {}
        for color, inside in zip(sampled.rgb, sampled.subject):
            if inside:
                key = ((color[0] >> HISTOGRAM_SHIFT) << 8) | ((color[1] >> HISTOGRAM_SHIFT) << 4) | (color[2] >> HISTOGRAM_SHIFT)
                counts[key] = counts.get(key, 0) + 1
        total = sum(counts.values())
        return {key: value / total for key, value in counts.items()}

    ref_hist, cap_hist = histogram(reference), histogram(capture)
    return _round(_clip(math.fsum(min(share, cap_hist.get(key, 0.0)) for key, share in ref_hist.items())))


def identity_detail(reference: Sampled, capture: Sampled) -> float:
    """Luminance correlation over the cells both frames depict as subject (see _correlation)."""
    shared = [index for index, (r, c) in enumerate(zip(reference.subject, capture.subject)) if r and c]
    return _round(_correlation([_luma(reference.rgb[i]) for i in shared], [_luma(capture.rgb[i]) for i in shared]))


def painted_regions(reference: Sampled, capture: Sampled) -> list[dict[str, object]]:
    """Reference colour regions and how well the render reproduces each one.

    A region is a 4-level-per-channel colour bin holding at least MIN_REGION_SHARE of the reference
    subject (largest first, ties by bin, at most MAX_PAINTED_REGIONS). `score` is the IoU of the
    reference region against the render's cells in the same colour bin; `confidence` is the share of
    the region's reference cells that the render's silhouette covers at all -- how much of the region
    the render could be compared on."""

    def bin_of(color: tuple[int, int, int]) -> int:
        return ((color[0] >> REGION_SHIFT) << 4) | ((color[1] >> REGION_SHIFT) << 2) | (color[2] >> REGION_SHIFT)

    ref_bins = [bin_of(color) if inside else -1 for color, inside in zip(reference.rgb, reference.subject)]
    cap_bins = [bin_of(color) if inside else -1 for color, inside in zip(capture.rgb, capture.subject)]
    counts: dict[int, int] = {}
    for value in ref_bins:
        if value >= 0:
            counts[value] = counts.get(value, 0) + 1
    total = sum(counts.values())
    ordered = sorted(counts, key=lambda key: (-counts[key], key))
    regions: list[dict[str, object]] = []
    for key in ordered:
        if len(regions) >= MAX_PAINTED_REGIONS or counts[key] / total < MIN_REGION_SHARE:
            break
        inter = sum(1 for r, c in zip(ref_bins, cap_bins) if r == key and c == key)
        union = sum(1 for r, c in zip(ref_bins, cap_bins) if r == key or c == key)
        covered = sum(1 for r, inside in zip(ref_bins, capture.subject) if r == key and inside)
        regions.append({
            "id": f"color-region-{(key >> 4) & 3}{(key >> 2) & 3}{key & 3}",
            "score": _round(inter / union),
            "confidence": _round(covered / counts[key]),
            "referenceCells": counts[key],
        })
    return regions


def detail_features(reference: Sampled, capture: Sampled) -> list[dict[str, object]]:
    """The reference's most detail-dense tiles and the local luminance correlation of each.

    Tiles are ranked by gradient energy over reference subject cells, then subject cell count, then
    position; only tiles with at least MIN_TILE_CELLS subject cells qualify. These are structural
    detail windows, not semantic part labels, and are named for their tile."""
    tile = GRID // TILE_COUNT
    luma = [_luma(color) for color in reference.rgb]
    ranked: list[tuple[float, int, int, int]] = []
    for row in range(TILE_COUNT):
        for column in range(TILE_COUNT):
            cells = [y * GRID + x for y in range(row * tile, (row + 1) * tile) for x in range(column * tile, (column + 1) * tile)
                     if reference.subject[y * GRID + x]]
            if len(cells) < MIN_TILE_CELLS:
                continue
            energy = 0.0
            for index in cells:
                y, x = divmod(index, GRID)
                if x + 1 < GRID:
                    energy += abs(luma[index + 1] - luma[index])
                if y + 1 < GRID:
                    energy += abs(luma[index + GRID] - luma[index])
            ranked.append((-energy, -len(cells), row, column))
    ranked.sort()
    features: list[dict[str, object]] = []
    for _, _, row, column in ranked[:MAX_DETAIL_FEATURES]:
        shared = [y * GRID + x for y in range(row * tile, (row + 1) * tile) for x in range(column * tile, (column + 1) * tile)
                  if reference.subject[y * GRID + x] and capture.subject[y * GRID + x]]
        score = _correlation([luma[i] for i in shared], [_luma(capture.rgb[i]) for i in shared])
        features.append({"id": f"detail-tile-r{row}c{column}", "score": _round(score), "sharedCells": len(shared)})
    return features
