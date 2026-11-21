"""Pixel decoding regressions; synthetic fixtures do not authenticate a capture."""
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from cs2_pixels import ImageDecodeError, decode_png, sample_image


def png(color_type, pixels, transparency):
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    header = struct.pack(">IIBBBBB", 2, 1, 8, color_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"tRNS", transparency) + chunk(b"IDAT", zlib.compress(b"\0" + pixels))
            + chunk(b"IEND", b""))


class PixelTransparencyTests(unittest.TestCase):
    def test_rgb_transparency_key_controls_alpha_and_subject(self):
        image = decode_png(png(2, bytes([20, 30, 40, 200, 100, 80]), struct.pack(">HHH", 20, 30, 40)))
        self.assertEqual(image.pixel(0, 0), (20, 30, 40, 0))
        self.assertEqual(image.pixel(1, 0), (200, 100, 80, 255))
        self.assertEqual(sample_image(image).subject_fraction, 0.5)

    def test_grayscale_transparency_key_controls_alpha(self):
        image = decode_png(png(0, bytes([17, 80]), struct.pack(">H", 17)))
        self.assertEqual(image.pixel(0, 0), (17, 17, 17, 0))
        self.assertEqual(image.pixel(1, 0), (80, 80, 80, 255))

    def test_invalid_transparency_key_is_refused(self):
        with self.assertRaises(ImageDecodeError):
            decode_png(png(2, bytes([0, 0, 0, 1, 2, 3]), struct.pack(">HHH", 256, 0, 0)))
        with self.assertRaises(ImageDecodeError):
            decode_png(png(6, bytes([0] * 8), b"\0\0"))
