import os
import sys

test_path = os.path.dirname(os.path.abspath(__file__))
modules_path = os.path.dirname(test_path)
sys.path.insert(0, modules_path)

from utilities_common.psu_status import classify_psu_power, ABSENT, UNPOWERED, FAULTED, OK  # noqa: E402


def test_absent():
    assert classify_psu_power({'presence': 'false'}) == ABSENT
    assert classify_psu_power({}) == ABSENT


def test_ok():
    assert classify_psu_power(
        {'presence': 'true', 'status': 'true', 'voltage': '12.0', 'input_voltage': '208'}) == OK
    # No voltage field is fine when power-good is asserted.
    assert classify_psu_power({'presence': 'true', 'status': 'true'}) == OK


def test_unpowered_requires_positive_no_input_evidence():
    # power-good false / no output AND input_voltage ~ 0 -> unpowered.
    assert classify_psu_power(
        {'presence': 'true', 'status': 'false', 'voltage': '0.0', 'input_voltage': '0.0'}) == UNPOWERED
    # power-good true but output ~0 with no input is still unpowered.
    assert classify_psu_power(
        {'presence': 'true', 'status': 'true', 'voltage': '0.0', 'input_voltage': '0.0'}) == UNPOWERED


def test_faulted_when_input_present_or_unknown():
    # Input present but no good output -> faulted (must NOT be called unpowered).
    assert classify_psu_power(
        {'presence': 'true', 'status': 'false', 'voltage': '0.0', 'input_voltage': '208'}) == FAULTED
    # Missing input_voltage -> never assume unpowered -> faulted.
    assert classify_psu_power(
        {'presence': 'true', 'status': 'false', 'voltage': '0.0'}) == FAULTED
    # Unparseable values are treated as unknown, not as evidence of no power.
    assert classify_psu_power(
        {'presence': 'true', 'status': 'false', 'voltage': 'N/A', 'input_voltage': 'N/A'}) == FAULTED
