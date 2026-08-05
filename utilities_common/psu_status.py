"""Shared PSU power-state classification used by `psushow` and `fanshow`.

Both commands need to answer the same question from a `PSU_INFO` row: is the PSU
absent, present-but-unpowered (no input), faulted, or healthy. Keep that logic here
so the two surfaces stay consistent; each command maps the state to its own labels.
"""

# Output voltage (volts) at or below this is treated as "no good output". Well below
# any valid rail minimum (rails are ~12V).
PSU_OUTPUT_DEAD_VOLTAGE = 1.0
# Input voltage (volts) at or below this is positive evidence of "no input present"
# (e.g. AC cord unplugged). Only used to tell an un-powered PSU from a faulted one;
# a missing input_voltage is NOT taken to mean "un-powered".
PSU_NO_INPUT_VOLTAGE = 10.0

# Power states returned by classify_psu_power().
ABSENT = 'absent'
UNPOWERED = 'unpowered'
FAULTED = 'faulted'
OK = 'ok'


def _as_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_psu_power(psu_info):
    """Classify a PSU_INFO field dict (as returned by SonicV2Connector.get_all) using
    only the evidence present in STATE_DB:

        ABSENT     - not present (presence false)
        OK         - present and delivering good output (power-good and output voltage)
        UNPOWERED  - present, no good output, AND positive evidence of no input
                     (input_voltage at/below PSU_NO_INPUT_VOLTAGE)
        FAULTED    - present, no good output, but input is present OR input is unknown

    "Un-powered" is never inferred from a deasserted power-good alone, so a real fault
    is not masked as a missing power feed.
    """
    psu_info = psu_info or {}

    if (psu_info.get('presence') or 'false').lower() != 'true':
        return ABSENT

    output_bad = (psu_info.get('status') or 'false').lower() != 'true'
    if not output_bad:
        output_voltage = _as_float(psu_info.get('voltage'))
        if output_voltage is not None:
            output_bad = output_voltage <= PSU_OUTPUT_DEAD_VOLTAGE
    if not output_bad:
        return OK

    input_voltage = _as_float(psu_info.get('input_voltage'))
    if input_voltage is not None and input_voltage <= PSU_NO_INPUT_VOLTAGE:
        return UNPOWERED
    return FAULTED
