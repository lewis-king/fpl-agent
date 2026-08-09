import numpy as np

from fplagent_data.solio import _i24, _u24


def test_unsigned_24_bit_decode() -> None:
    value = np.array([[0x56, 0x34, 0x12]], dtype=np.uint8)
    assert _u24(value).tolist() == [0x123456]


def test_signed_24_bit_decode() -> None:
    value = np.array([[0xFF, 0xFF, 0xFF], [0x01, 0x00, 0x00]], dtype=np.uint8)
    assert _i24(value).tolist() == [-1, 1]

