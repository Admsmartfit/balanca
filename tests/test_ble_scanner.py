"""Testes do parser BLE (RF01/RF02) — cobre a correção de bits da seção 11 do PRD."""

from app.ble_scanner import parse_v2_payload


def _payload(*, c0: int, c1: int, weight_raw: int, impedance_raw: int = 0) -> bytes:
    return bytes(
        [
            c0,
            c1,
            0, 0, 0, 0, 0, 0, 0,  # timestamp (índices 2-8), não usado no parser
            impedance_raw & 0xFF,
            (impedance_raw >> 8) & 0xFF,
            weight_raw & 0xFF,
            (weight_raw >> 8) & 0xFF,
        ]
    )


def test_stabilized_and_impedance_flags_read_from_control_byte_1():
    # bit5 (stabilized) e bit1 (impedância válida) de c1 — não de c0, que é o bug do rascunho.
    payload = _payload(c0=0x00, c1=(1 << 5) | (1 << 1), weight_raw=14100, impedance_raw=480)
    reading = parse_v2_payload(payload)

    assert reading is not None
    assert reading.stabilized is True
    assert reading.impedance_ohm == 480.0
    assert reading.unit == "kg"
    assert reading.weight_kg == 70.5  # 14100 / 200


def test_control_byte_0_only_carries_the_unit_flag():
    # is_lbs vem de c0 bit0; setar outros bits de c0 não deve afetar estabilizado/impedância.
    payload = _payload(c0=0xFF, c1=0x00, weight_raw=7000)
    reading = parse_v2_payload(payload)

    assert reading is not None
    assert reading.unit == "lbs"
    assert reading.weight_kg == 70.0  # 7000 / 100
    assert reading.stabilized is False
    assert reading.impedance_ohm is None


def test_not_stabilized_when_bit5_of_c1_is_unset():
    payload = _payload(c0=0x00, c1=(1 << 1), weight_raw=14100, impedance_raw=480)
    reading = parse_v2_payload(payload)

    assert reading is not None
    assert reading.stabilized is False


def test_impedance_ignored_when_flag_unset_even_if_bytes_nonzero():
    payload = _payload(c0=0x00, c1=(1 << 5), weight_raw=14100, impedance_raw=480)
    reading = parse_v2_payload(payload)

    assert reading is not None
    assert reading.impedance_ohm is None


def test_malformed_payload_returns_none():
    assert parse_v2_payload(b"\x00" * 10) is None
