#!/usr/bin/env python3
#
# main.py
#
# Command-line utility for interacting with SFP transceivers within SONiC
#

import copy
import os
import sys
import natsort
import ast
import time
import datetime
import re
import concurrent.futures
import threading

import subprocess
import click
import enlighten
import sonic_platform
import sonic_platform_base.sonic_sfp.sfputilhelper
from sfputil.debug import debug
from sonic_platform_base.sfp_base import SfpBase
from swsscommon.swsscommon import SonicV2Connector, ConfigDBConnector
from natsort import natsorted
from sonic_py_common import device_info, logger, multi_asic
from utilities_common import platform_sfputil_helper
from utilities_common.platform_sfputil_helper import (
    get_first_subport
)
from utilities_common.sfp_helper import covert_application_advertisement_to_output_string
from utilities_common.sfp_helper import QSFP_DATA_MAP
from utilities_common.sfp_helper import is_transceiver_cmis, get_data_map_sort_key
from tabulate import tabulate
from utilities_common.general import load_db_config

VERSION = '3.0'

SYSLOG_IDENTIFIER = "sfputil"

PLATFORM_JSON = 'platform.json'
PORT_CONFIG_INI = 'port_config.ini'

EXIT_FAIL = -1
EXIT_SUCCESS = 0
ERROR_PERMISSIONS = 1
ERROR_CHASSIS_LOAD = 2
ERROR_SFPUTILHELPER_LOAD = 3
ERROR_PORT_CONFIG_LOAD = 4
ERROR_NOT_IMPLEMENTED = 5
ERROR_INVALID_PORT = 6
ERROR_INVALID_PAGE = 7
ERROR_INVALID_ARGUMENTS = 8
SMBUS_BLOCK_WRITE_SIZE = 32
# Default host password as per CMIS spec:
# http://www.qsfp-dd.com/wp-content/uploads/2021/05/CMIS5p0.pdf
CDB_DEFAULT_HOST_PASSWORD = 0x00001011

MAX_LPL_FIRMWARE_BLOCK_SIZE = 116 #Bytes

PAGE_SIZE = 128
PAGE_OFFSET = 128

SFF8472_A0_SIZE = 256
MAX_EEPROM_PAGE = 255
MAX_EEPROM_OFFSET = 255
MIN_OFFSET_FOR_NON_PAGE0  = 128
MAX_OFFSET_FOR_A0H_UPPER_PAGE = 255
MAX_OFFSET_FOR_A0H_LOWER_PAGE = 127
MAX_OFFSET_FOR_A2H = 255
PAGE_SIZE_FOR_A0H = 256
SFF8636_MODULE_PAGES = [0, 1, 2, 3]
SFF8472_MODULE_PAGES = [0, 1, 2]
CMIS_MODULE_PAGES = [0, 1, 2, 16, 17]
CMIS_COHERENT_MODULE_PAGES = [0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x38, 0x39, 0x3a, 0x3b]

EEPROM_DUMP_INDENT = ' ' * 8

# TODO: We should share these maps and the formatting functions between sfputil and sfpshow
QSFP_DD_DATA_MAP = {
    'model': 'Vendor PN',
    'vendor_oui': 'Vendor OUI',
    'vendor_date': 'Vendor Date Code(YYYY-MM-DD Lot)',
    'manufacturer': 'Vendor Name',
    'vendor_rev': 'Vendor Rev',
    'serial': 'Vendor SN',
    'type': 'Identifier',
    'ext_identifier': 'Extended Identifier',
    'ext_rateselect_compliance': 'Extended RateSelect Compliance',
    'cable_length': 'cable_length',
    'cable_type': 'Length',
    'nominal_bit_rate': 'Nominal Bit Rate(100Mbs)',
    'specification_compliance': 'Specification compliance',
    'encoding': 'Encoding',
    'connector': 'Connector',
    'application_advertisement': 'Application Advertisement',
    'hardware_rev': 'Hardware Revision',
    'media_interface_code': 'Media Interface Code',
    'host_electrical_interface': 'Host Electrical Interface',
    'host_lane_count': 'Host Lane Count',
    'media_lane_count': 'Media Lane Count',
    'host_lane_assignment_option': 'Host Lane Assignment Options',
    'media_lane_assignment_option': 'Media Lane Assignment Options',
    'active_apsel_hostlane1': 'Active App Selection Host Lane 1',
    'active_apsel_hostlane2': 'Active App Selection Host Lane 2',
    'active_apsel_hostlane3': 'Active App Selection Host Lane 3',
    'active_apsel_hostlane4': 'Active App Selection Host Lane 4',
    'active_apsel_hostlane5': 'Active App Selection Host Lane 5',
    'active_apsel_hostlane6': 'Active App Selection Host Lane 6',
    'active_apsel_hostlane7': 'Active App Selection Host Lane 7',
    'active_apsel_hostlane8': 'Active App Selection Host Lane 8',
    'media_interface_technology': 'Media Interface Technology',
    'cmis_rev': 'CMIS Revision',
    'supported_max_tx_power': 'Supported Max TX Power',
    'supported_min_tx_power': 'Supported Min TX Power',
    'supported_max_laser_freq': 'Supported Max Laser Frequency',
    'supported_min_laser_freq': 'Supported Min Laser Frequency',
    'els_identifier': 'ELS Identifier',
    'els_revision': 'ELS Revision',
    'els_laser_count': 'ELS Laser Count',
    'els_vendor_name': 'ELS Vendor Name',
    'els_vendor_oui': 'ELS Vendor OUI',
    'els_vendor_pn': 'ELS Vendor PN',
    'els_vendor_rev': 'ELS Vendor Rev',
    'els_vendor_sn': 'ELS Vendor SN',
    'els_date_code': 'ELS Vendor Date Code(YYYY-MM-DD Lot)',
    'els_max_power': 'ELS Maximum Power Consumption',
    'rlm_laser_lpmode_control': 'RLM Laser Lpower Mode Control',
    'rlm_laser_wavelength_grid': 'RLM Laser Wavelength Grid',
}

SFP_DOM_CHANNEL_MONITOR_MAP = {
    'rx1power': 'RXPower',
    'tx1bias': 'TXBias',
    'tx1power': 'TXPower'
}

SFP_DOM_CHANNEL_THRESHOLD_MAP = {
    'txpowerhighalarm':   'TxPowerHighAlarm',
    'txpowerlowalarm':    'TxPowerLowAlarm',
    'txpowerhighwarning': 'TxPowerHighWarning',
    'txpowerlowwarning':  'TxPowerLowWarning',
    'rxpowerhighalarm':   'RxPowerHighAlarm',
    'rxpowerlowalarm':    'RxPowerLowAlarm',
    'rxpowerhighwarning': 'RxPowerHighWarning',
    'rxpowerlowwarning':  'RxPowerLowWarning',
    'txbiashighalarm':    'TxBiasHighAlarm',
    'txbiaslowalarm':     'TxBiasLowAlarm',
    'txbiashighwarning':  'TxBiasHighWarning',
    'txbiaslowwarning':   'TxBiasLowWarning'
}

QSFP_DOM_CHANNEL_THRESHOLD_MAP = {
    'rxpowerhighalarm':   'RxPowerHighAlarm',
    'rxpowerlowalarm':    'RxPowerLowAlarm',
    'rxpowerhighwarning': 'RxPowerHighWarning',
    'rxpowerlowwarning':  'RxPowerLowWarning',
    'txbiashighalarm':    'TxBiasHighAlarm',
    'txbiaslowalarm':     'TxBiasLowAlarm',
    'txbiashighwarning':  'TxBiasHighWarning',
    'txbiaslowwarning':   'TxBiasLowWarning'
}

DOM_MODULE_THRESHOLD_MAP = {
    'temphighalarm':  'TempHighAlarm',
    'templowalarm':   'TempLowAlarm',
    'temphighwarning': 'TempHighWarning',
    'templowwarning': 'TempLowWarning',
    'vcchighalarm':   'VccHighAlarm',
    'vcclowalarm':    'VccLowAlarm',
    'vcchighwarning': 'VccHighWarning',
    'vcclowwarning':  'VccLowWarning'
}

QSFP_DOM_CHANNEL_MONITOR_MAP = {
    'rx1power': 'RX1Power',
    'rx2power': 'RX2Power',
    'rx3power': 'RX3Power',
    'rx4power': 'RX4Power',
    'tx1bias':  'TX1Bias',
    'tx2bias':  'TX2Bias',
    'tx3bias':  'TX3Bias',
    'tx4bias':  'TX4Bias',
    'tx1power': 'TX1Power',
    'tx2power': 'TX2Power',
    'tx3power': 'TX3Power',
    'tx4power': 'TX4Power'
}

CMIS_DOM_CHANNEL_MONITOR_MAP = {
    'rx1power': 'RX1Power',
    'rx2power': 'RX2Power',
    'rx3power': 'RX3Power',
    'rx4power': 'RX4Power',
    'rx5power': 'RX5Power',
    'rx6power': 'RX6Power',
    'rx7power': 'RX7Power',
    'rx8power': 'RX8Power',
    'tx1bias':  'TX1Bias',
    'tx2bias':  'TX2Bias',
    'tx3bias':  'TX3Bias',
    'tx4bias':  'TX4Bias',
    'tx5bias':  'TX5Bias',
    'tx6bias':  'TX6Bias',
    'tx7bias':  'TX7Bias',
    'tx8bias':  'TX8Bias',
    'tx1power': 'TX1Power',
    'tx2power': 'TX2Power',
    'tx3power': 'TX3Power',
    'tx4power': 'TX4Power',
    'tx5power': 'TX5Power',
    'tx6power': 'TX6Power',
    'tx7power': 'TX7Power',
    'tx8power': 'TX8Power'
}

DOM_MODULE_MONITOR_MAP = {
    'temperature': 'Temperature',
    'voltage': 'Vcc'
}

ELS_DOM_MONITOR_MAP = {
    'els_temperature': 'ELS Temperature',
    'els_voltage': 'ELS Vcc',
}

ELS_THRESHOLD_MAP = {
    'els_temphighalarm': 'ELS TempHighAlarm',
    'els_templowalarm': 'ELS TempLowAlarm',
    'els_temphighwarning': 'ELS TempHighWarning',
    'els_templowwarning': 'ELS TempLowWarning',
    'els_vcchighalarm': 'ELS VccHighAlarm',
    'els_vcclowalarm': 'ELS VccLowAlarm',
    'els_vcchighwarning': 'ELS VccHighWarning',
    'els_vcclowwarning': 'ELS VccLowWarning',
    'els_txpowerhighalarm': 'ELS TxPowerHighAlarm',
    'els_txpowerlowalarm': 'ELS TxPowerLowAlarm',
    'els_txpowerhighwarning': 'ELS TxPowerHighWarning',
    'els_txpowerlowwarning': 'ELS TxPowerLowWarning',
    'els_txbiashighalarm': 'ELS TxBiasHighAlarm',
    'els_txbiashighwarning': 'ELS TxBiasHighWarning'
}

DOM_CHANNEL_THRESHOLD_UNIT_MAP = {
    'txpowerhighalarm':   'dBm',
    'txpowerlowalarm':    'dBm',
    'txpowerhighwarning': 'dBm',
    'txpowerlowwarning':  'dBm',
    'rxpowerhighalarm':   'dBm',
    'rxpowerlowalarm':    'dBm',
    'rxpowerhighwarning': 'dBm',
    'rxpowerlowwarning':  'dBm',
    'txbiashighalarm':    'mA',
    'txbiaslowalarm':     'mA',
    'txbiashighwarning':  'mA',
    'txbiaslowwarning':   'mA'
}

DOM_MODULE_THRESHOLD_UNIT_MAP = {
    'temphighalarm':   'C',
    'templowalarm':    'C',
    'temphighwarning': 'C',
    'templowwarning':  'C',
    'vcchighalarm':    'Volts',
    'vcclowalarm':     'Volts',
    'vcchighwarning':  'Volts',
    'vcclowwarning':   'Volts'
}

ELS_DOM_MONITOR_UNIT_MAP = {
    'els_temperature': 'C',
    'els_voltage': 'Volts',
}

ELS_THRESHOLD_UNIT_MAP = {
    'els_temphighalarm': 'C',
    'els_templowalarm': 'C',
    'els_temphighwarning': 'C',
    'els_templowwarning': 'C',
    'els_vcchighalarm': 'Volts',
    'els_vcclowalarm': 'Volts',
    'els_vcchighwarning': 'Volts',
    'els_vcclowwarning': 'Volts',
    'els_txpowerhighalarm': 'mW',
    'els_txpowerlowalarm': 'mW',
    'els_txpowerhighwarning': 'mW',
    'els_txpowerlowwarning': 'mW',
    'els_txbiashighalarm': 'mA',
    'els_txbiashighwarning': 'mA'
}

DOM_VALUE_UNIT_MAP = {
    'rx1power': 'dBm',
    'rx2power': 'dBm',
    'rx3power': 'dBm',
    'rx4power': 'dBm',
    'tx1bias': 'mA',
    'tx2bias': 'mA',
    'tx3bias': 'mA',
    'tx4bias': 'mA',
    'tx1power': 'dBm',
    'tx2power': 'dBm',
    'tx3power': 'dBm',
    'tx4power': 'dBm',
    'temperature': 'C',
    'voltage': 'Volts'
}

QSFP_DD_DOM_VALUE_UNIT_MAP = {
    'rx1power': 'dBm',
    'rx2power': 'dBm',
    'rx3power': 'dBm',
    'rx4power': 'dBm',
    'rx5power': 'dBm',
    'rx6power': 'dBm',
    'rx7power': 'dBm',
    'rx8power': 'dBm',
    'tx1bias': 'mA',
    'tx2bias': 'mA',
    'tx3bias': 'mA',
    'tx4bias': 'mA',
    'tx5bias': 'mA',
    'tx6bias': 'mA',
    'tx7bias': 'mA',
    'tx8bias': 'mA',
    'tx1power': 'dBm',
    'tx2power': 'dBm',
    'tx3power': 'dBm',
    'tx4power': 'dBm',
    'tx5power': 'dBm',
    'tx6power': 'dBm',
    'tx7power': 'dBm',
    'tx8power': 'dBm',
    'temperature': 'C',
    'voltage': 'Volts'
}

RJ45_PORT_TYPE = 'RJ45'

# Global platform-specific Chassis class instance
platform_chassis = None

# Global platform-specific sfputil class instance
platform_sfputil = None

# Global logger instance
log = logger.Logger(SYSLOG_IDENTIFIER)

def is_sfp_present(port_name):
    physical_port = logical_port_to_physical_port_index(port_name)
    sfp = platform_chassis.get_sfp(physical_port)

    try:
        presence = sfp.get_presence()
    except NotImplementedError:
        click.echo("sfp get_presence() NOT implemented!", err=True)
        sys.exit(ERROR_NOT_IMPLEMENTED)

    return bool(presence)


def is_port_type_rj45(port_name):
    physical_port = logical_port_to_physical_port_index(port_name)

    try:
        port_types = platform_chassis.get_port_or_cage_type(physical_port)
        return SfpBase.SFP_PORT_TYPE_BIT_RJ45 == port_types
    except NotImplementedError:
        pass

    return False
# ========================== Methods for formatting output ==========================

# Convert dict values to cli output string
def format_dict_value_to_string(sorted_key_table,
                                dom_info_dict, dom_value_map,
                                dom_unit_map, alignment=0):
    output = ''
    indent = ' ' * 8
    separator = ": "
    for key in sorted_key_table:
        if dom_info_dict is not None and key in dom_info_dict and dom_info_dict[key] != 'N/A':
            value = dom_info_dict[key]
            units = ''
            if type(value) != str or (value != 'Unknown' and not value.endswith(dom_unit_map[key])):
                units = dom_unit_map[key]
            output += '{}{}{}{}{}\n'.format((indent * 2),
                                            dom_value_map[key],
                                            separator.rjust(len(separator) + alignment - len(dom_value_map[key])),
                                            value,
                                            units)
    return output


def convert_sfp_info_to_output_string(sfp_info_dict):
    indent = ' ' * 8
    output = ''
    # Gracefully handle missing/invalid info dicts
    if sfp_info_dict is None or not isinstance(sfp_info_dict, dict):
        output += '{}EEPROM info: N/A\n'.format(indent)
        return output
    is_sfp_cmis = is_transceiver_cmis(sfp_info_dict)
    if is_sfp_cmis:
        # Use the utility function with the local QSFP_DD_DATA_MAP for CMIS transceivers
        get_sort_key = get_data_map_sort_key(sfp_info_dict, QSFP_DD_DATA_MAP)
        sorted_qsfp_dd_info_keys = sorted(sfp_info_dict.keys(), key=get_sort_key)
        for key in sorted_qsfp_dd_info_keys:
            if key == 'cable_type':
                output += '{}{}: {}\n'.format(indent, sfp_info_dict['cable_type'], sfp_info_dict['cable_length'])
            elif key == 'cable_length':
                pass
            elif key == 'specification_compliance':
                output += '{}{}: {}\n'.format(indent, QSFP_DD_DATA_MAP[key], sfp_info_dict[key])
            elif key == 'supported_max_tx_power' or key == 'supported_min_tx_power':
                if key in sfp_info_dict:  # C-CMIS compliant / coherent modules
                    output += '{}{}: {}dBm\n'.format(indent, QSFP_DD_DATA_MAP[key], sfp_info_dict[key])
            elif key == 'supported_max_laser_freq' or key == 'supported_min_laser_freq':
                if key in sfp_info_dict:  # C-CMIS compliant / coherent modules
                    output += '{}{}: {}GHz\n'.format(indent, QSFP_DD_DATA_MAP[key], sfp_info_dict[key])
            elif key == 'application_advertisement':
                output += covert_application_advertisement_to_output_string(indent, sfp_info_dict)
            else:
                # For both known and unknown keys, use the data map display name if available
                display_name = QSFP_DD_DATA_MAP.get(key, key)  # Use data_map name if available, otherwise use key
                output += '{}{}: {}\n'.format(indent, display_name, sfp_info_dict.get(key, 'N/A'))

    else:
        # Use the utility function with QSFP_DATA_MAP for non-CMIS transceivers
        get_sort_key = get_data_map_sort_key(sfp_info_dict, QSFP_DATA_MAP)
        sorted_qsfp_info_keys = sorted(sfp_info_dict.keys(), key=get_sort_key)
        for key in sorted_qsfp_info_keys:
            if key == 'cable_type':
                output += '{}{}: {}\n'.format(indent, sfp_info_dict['cable_type'], sfp_info_dict['cable_length'])
            elif key == 'cable_length':
                pass
            elif key == 'specification_compliance':
                output += '{}{}:\n'.format(indent, QSFP_DATA_MAP['specification_compliance'])

                spec_compliance_dict = {}
                try:
                    spec_compliance_dict = ast.literal_eval(sfp_info_dict['specification_compliance'])
                    sorted_compliance_key_table = natsorted(spec_compliance_dict)
                    for compliance_key in sorted_compliance_key_table:
                        output += '{}{}: {}\n'.format((indent * 2), compliance_key, spec_compliance_dict[compliance_key])
                except ValueError as e:
                    output += '{}N/A\n'.format((indent * 2))
            else:
                # For both known and unknown keys, use the data map display name if available
                display_name = QSFP_DATA_MAP.get(key, key)  # Use data_map name if available, otherwise use key
                output += '{}{}: {}\n'.format(indent, display_name, sfp_info_dict.get(key, 'N/A'))

    return output


# Convert DOM sensor info in DB to CLI output string
def convert_dom_to_output_string(sfp_type, is_sfp_cmis, dom_info_dict):
    indent = ' ' * 8
    output_dom = ''
    channel_threshold_align = 18
    module_threshold_align = 15

    if sfp_type.startswith('QSFP') or is_sfp_cmis:
        # Channel Monitor
        if is_sfp_cmis:
            output_dom += (indent + 'ChannelMonitorValues:\n')
            sorted_key_table = natsorted(CMIS_DOM_CHANNEL_MONITOR_MAP)
            output_channel = format_dict_value_to_string(
                sorted_key_table, dom_info_dict,
                CMIS_DOM_CHANNEL_MONITOR_MAP,
                QSFP_DD_DOM_VALUE_UNIT_MAP)
            output_dom += output_channel
        else:
            output_dom += (indent + 'ChannelMonitorValues:\n')
            sorted_key_table = natsorted(QSFP_DOM_CHANNEL_MONITOR_MAP)
            output_channel = format_dict_value_to_string(
                sorted_key_table, dom_info_dict,
                QSFP_DOM_CHANNEL_MONITOR_MAP,
                DOM_VALUE_UNIT_MAP)
            output_dom += output_channel

        # Channel Threshold
        if is_sfp_cmis:
            dom_map = SFP_DOM_CHANNEL_THRESHOLD_MAP
        else:
            dom_map = QSFP_DOM_CHANNEL_THRESHOLD_MAP

        output_dom += (indent + 'ChannelThresholdValues:\n')
        sorted_key_table = natsorted(dom_map)
        output_channel_threshold = format_dict_value_to_string(
            sorted_key_table, dom_info_dict,
            dom_map,
            DOM_CHANNEL_THRESHOLD_UNIT_MAP,
            channel_threshold_align)
        output_dom += output_channel_threshold

        # Module Monitor
        output_dom += (indent + 'ModuleMonitorValues:\n')
        sorted_key_table = natsorted(DOM_MODULE_MONITOR_MAP)
        output_module = format_dict_value_to_string(
            sorted_key_table, dom_info_dict,
            DOM_MODULE_MONITOR_MAP,
            DOM_VALUE_UNIT_MAP)
        output_dom += output_module

        # Module Threshold
        output_dom += (indent + 'ModuleThresholdValues:\n')
        sorted_key_table = natsorted(DOM_MODULE_THRESHOLD_MAP)
        output_module_threshold = format_dict_value_to_string(
            sorted_key_table, dom_info_dict,
            DOM_MODULE_THRESHOLD_MAP,
            DOM_MODULE_THRESHOLD_UNIT_MAP,
            module_threshold_align)
        output_dom += output_module_threshold

        # This is specific for CPO DOM value parsing.
        is_cpo = sfp_type.startswith('CPO')
        if is_cpo:
            laser_keys = [key for key in dom_info_dict if key.startswith('RLM') and 'Laser' in key]
            dom_monitor_map = ELS_DOM_MONITOR_MAP.copy()
            dom_monitor_map.update({key: key for key in laser_keys})
            dom_monitor_unit_map = ELS_DOM_MONITOR_UNIT_MAP.copy()
            dom_monitor_unit_map.update({key: '' for key in laser_keys})  # laser monitor values include units
            output_dom += (indent + 'ELSMonitorValues:\n')
            sorted_key_table = natsorted(dom_monitor_map)
            output_els_monitor = format_dict_value_to_string(
                sorted_key_table, dom_info_dict,
                dom_monitor_map,
                dom_monitor_unit_map)
            output_dom += output_els_monitor

            # Threshold
            output_dom += (indent + 'ELSThresholdValues:\n')
            sorted_key_table = natsorted(ELS_THRESHOLD_MAP)
            output_els_threshold = format_dict_value_to_string(
                sorted_key_table, dom_info_dict,
                ELS_THRESHOLD_MAP,
                ELS_THRESHOLD_UNIT_MAP)
            output_dom += output_els_threshold
    else:
        output_dom += (indent + 'MonitorData:\n')
        sorted_key_table = natsorted(SFP_DOM_CHANNEL_MONITOR_MAP)
        output_channel = format_dict_value_to_string(
            sorted_key_table, dom_info_dict,
            SFP_DOM_CHANNEL_MONITOR_MAP,
            DOM_VALUE_UNIT_MAP)
        output_dom += output_channel

        sorted_key_table = natsorted(DOM_MODULE_MONITOR_MAP)
        output_module = format_dict_value_to_string(
            sorted_key_table, dom_info_dict,
            DOM_MODULE_MONITOR_MAP,
            DOM_VALUE_UNIT_MAP)
        output_dom += output_module

        output_dom += (indent + 'ThresholdData:\n')

        # Module Threshold
        sorted_key_table = natsorted(DOM_MODULE_THRESHOLD_MAP)
        output_module_threshold = format_dict_value_to_string(
            sorted_key_table, dom_info_dict,
            DOM_MODULE_THRESHOLD_MAP,
            DOM_MODULE_THRESHOLD_UNIT_MAP,
            module_threshold_align)
        output_dom += output_module_threshold

        # Channel Threshold
        sorted_key_table = natsorted(SFP_DOM_CHANNEL_THRESHOLD_MAP)
        output_channel_threshold = format_dict_value_to_string(
            sorted_key_table, dom_info_dict,
            SFP_DOM_CHANNEL_THRESHOLD_MAP,
            DOM_CHANNEL_THRESHOLD_UNIT_MAP,
            channel_threshold_align)
        output_dom += output_channel_threshold

    return output_dom


# =============== Getting and printing SFP data ===============


#
def get_physical_port_name(logical_port, physical_port, ganged):
    """
        Returns:
          port_num if physical
          logical_port:port_num if logical port and is a ganged port
          logical_port if logical and not ganged
    """
    if logical_port == physical_port:
        return str(logical_port)
    elif ganged:
        return "{}:{} (ganged)".format(logical_port, physical_port)
    else:
        return logical_port


def logical_port_name_to_physical_port_list(port_name):
    if port_name.startswith("Ethernet"):
        if platform_sfputil.is_logical_port(port_name):
            return platform_sfputil.get_logical_to_physical(port_name)
        else:
            click.echo("Error: Invalid port '{}'".format(port_name))
            return None
    else:
        return [int(port_name)]

def logical_port_to_physical_port_index(port_name):
    if not platform_sfputil.is_logical_port(port_name):
        click.echo("Error: invalid port '{}'\n".format(port_name))
        print_all_valid_port_values()
        sys.exit(ERROR_INVALID_PORT)

    physical_port = logical_port_name_to_physical_port_list(port_name)[0]
    if physical_port is None:
        click.echo("Error: No physical port found for logical port '{}'".format(port_name))
        sys.exit(EXIT_FAIL)

    return physical_port


def print_all_valid_port_values():
    click.echo("Valid values for port: {}\n".format(str(platform_sfputil.logical)))


# ==================== Methods for initialization ====================


# Instantiate platform-specific Chassis class
def load_platform_chassis():
    global platform_chassis

    # Load new platform api class
    try:
        platform_chassis = sonic_platform.platform.Platform().get_chassis()
    except Exception as e:
        log.log_error("Failed to instantiate Chassis due to {}".format(repr(e)))

    if not platform_chassis:
        return False

    return True


# Instantiate SfpUtilHelper class
def load_sfputilhelper():
    global platform_sfputil

    # we have to make use of sfputil for some features
    # even though when new platform api is used for all vendors.
    # in this sense, we treat it as a part of new platform api.
    # we have already moved sfputil to sonic_platform_base
    # which is the root of new platform api.
    platform_sfputil = sonic_platform_base.sonic_sfp.sfputilhelper.SfpUtilHelper()

    if not platform_sfputil:
        return False

    return True


def load_port_config():
    load_db_config()
    try:
        if multi_asic.is_multi_asic():
            # For multi ASIC platforms we pass DIR of port_config_file_path and the number of asics
            (platform_path, hwsku_path) = device_info.get_paths_to_platform_and_hwsku_dirs()

            # Load platform module from source
            platform_sfputil.read_all_porttab_mappings(hwsku_path, multi_asic.get_num_asics())
        else:
            # For single ASIC platforms we pass port_config_file_path and the asic_inst as 0
            port_config_file_path = device_info.get_path_to_port_config_file()
            platform_sfputil.read_porttab_mappings(port_config_file_path, 0)
    except Exception as e:
        log.log_error("Error reading port info ({})".format(str(e)), True)
        return False

    return True

# ==================== CLI commands and groups ====================


# This is our main entrypoint - the main 'sfputil' command
@click.group()
def cli():
    """sfputil - Command line utility for managing SFP transceivers"""

    if os.geteuid() != 0:
        click.echo("Root privileges are required for this operation")
        sys.exit(ERROR_PERMISSIONS)

    # Load platform-specific Chassis class
    if not load_platform_chassis():
        sys.exit(ERROR_CHASSIS_LOAD)

    # Load SfpUtilHelper class
    if not load_sfputilhelper():
        sys.exit(ERROR_SFPUTILHELPER_LOAD)

    # Load port info
    if not load_port_config():
        sys.exit(ERROR_PORT_CONFIG_LOAD)

    # Generic way to load platform-specific sfputil
    # and chassis classes
    platform_sfputil_helper.load_platform_sfputil()
    platform_sfputil_helper.load_chassis()
    platform_sfputil_helper.platform_sfputil_read_porttab_mappings()

cli.add_command(debug)

# 'show' subgroup
@cli.group()
def show():
    """Display status of SFP transceivers"""
    pass


# 'eeprom' subcommand
@show.command()
@click.option('-p', '--port', metavar='<port_name>', help="Display SFP EEPROM data for port <port_name> only")
@click.option('-d', '--dom', 'dump_dom', is_flag=True, help="Also display Digital Optical Monitoring (DOM) data")
@click.option('-n', '--namespace', default=None, help="Display interfaces for specific namespace")
def eeprom(port, dump_dom, namespace):
    """Display EEPROM data of SFP transceiver(s)"""
    logical_port_list = []
    output = ""

    # Create a list containing the logical port names of all ports we're interested in
    if port is None:
        logical_port_list = platform_sfputil.logical
    else:
        if platform_sfputil.is_logical_port(port) == 0:
            click.echo("Error: invalid port '{}'\n".format(port))
            print_all_valid_port_values()
            sys.exit(ERROR_INVALID_PORT)

        logical_port_list = [port]

    for logical_port_name in logical_port_list:
        ganged = False
        i = 1

        physical_port_list = logical_port_name_to_physical_port_list(logical_port_name)
        if physical_port_list is None:
            click.echo("Error: No physical ports found for logical port '{}'".format(logical_port_name))
            return

        if len(physical_port_list) > 1:
            ganged = True

        for physical_port in physical_port_list:
            port_name = get_physical_port_name(logical_port_name, i, ganged)

            if is_port_type_rj45(port_name):
                output += "{}: SFP EEPROM is not applicable for RJ45 port\n".format(port_name)
                output += '\n'
                continue

            try:
                presence = platform_chassis.get_sfp(physical_port).get_presence()
            except NotImplementedError:
                click.echo("Sfp.get_presence() is currently not implemented for this platform")
                sys.exit(ERROR_NOT_IMPLEMENTED)

            if not presence:
                output += "{}: SFP EEPROM not detected\n".format(port_name)
            else:
                output += "{}: SFP EEPROM detected\n".format(port_name)

                try:
                    xcvr_info = platform_chassis.get_sfp(physical_port).get_transceiver_info()
                    is_sfp_cmis = is_transceiver_cmis(xcvr_info)
                except NotImplementedError:
                    click.echo("Sfp.get_transceiver_info() is currently not implemented for this platform")
                    sys.exit(ERROR_NOT_IMPLEMENTED)

                output += convert_sfp_info_to_output_string(xcvr_info)

                if dump_dom:
                    try:
                        api = platform_chassis.get_sfp(physical_port).get_xcvr_api()
                    except NotImplementedError:
                        output += "API is currently not implemented for this platform\n"
                        click.echo(output)
                        sys.exit(ERROR_NOT_IMPLEMENTED)
                    if api is None:
                        output += "API is none while getting DOM info!\n"
                        click.echo(output)
                        sys.exit(ERROR_NOT_IMPLEMENTED)
                    try:
                        xcvr_dom_info = platform_chassis.get_sfp(physical_port).get_transceiver_dom_real_value()
                    except NotImplementedError:
                        click.echo("Sfp.get_transceiver_dom_real_value() is currently not implemented "
                                   "for this platform")
                        sys.exit(ERROR_NOT_IMPLEMENTED)

                    try:
                        xcvr_dom_threshold_info = platform_chassis.get_sfp(physical_port).get_transceiver_threshold_info()
                        if xcvr_dom_threshold_info:
                            xcvr_dom_info.update(xcvr_dom_threshold_info)
                    except NotImplementedError:
                        click.echo("Sfp.get_transceiver_threshold_info() is currently not implemented for this platform")
                        sys.exit(ERROR_NOT_IMPLEMENTED)

                    output += convert_dom_to_output_string(xcvr_info['type'],
                                                           is_sfp_cmis, xcvr_dom_info)

            output += '\n'

    click.echo(output)


# 'eeprom-hexdump' subcommand
@show.command()
@click.option('-p', '--port', metavar='<port_name>', help="Display SFP EEPROM hexdump for port <port_name>")
@click.option('-n', '--page', metavar='<page_number>',
              help="Display SFP EEPROM hexdump for <page_number> "
                   "(decimal, hex (with 0x prefix) or octal (with 0o prefix))")
def eeprom_hexdump(port, page):
    """Display EEPROM hexdump of SFP transceiver(s)"""
    if port:
        if page is None:
            page = 0
        else:
            page = validate_eeprom_page(page)
        return_code, output = eeprom_hexdump_single_port(port, page)
        click.echo(output)
        sys.exit(return_code)
    else:
        if page is not None:
            page = validate_eeprom_page(page)
        logical_port_list = natsorted(platform_sfputil.logical)
        lines = []
        for logical_port_name in logical_port_list:
            return_code, output = eeprom_hexdump_single_port(logical_port_name, page)
            if return_code != 0:
                lines.append(f'EEPROM hexdump for port {logical_port_name}')
                lines.append(f'{EEPROM_DUMP_INDENT}{output}\n')
                continue
            lines.append(output)
        click.echo('\n'.join(lines))


def validate_eeprom_page(page: str) -> int:
    """
    Validate input page module EEPROM
    Args:
        page: str page input by user (supports decimal, hex with 0x prefix, and octal with 0o prefix)
    Returns:
        int page
    """
    try:
        validated_page = int(page, base=0)
    except ValueError:
        click.echo(f'Please enter a numeric page number (decimal, hex with 0x prefix and octal with '
                   f'0o prefix). Got: "{page}"')
        sys.exit(ERROR_NOT_IMPLEMENTED)
    if validated_page < 0 or validated_page > MAX_EEPROM_PAGE:
        click.echo(f'Error: Invalid page number {page}. Must be between 0 and {MAX_EEPROM_PAGE}')
        sys.exit(ERROR_INVALID_PAGE)
    return validated_page

def eeprom_hexdump_single_port(logical_port_name, page):
    """
    Dump EEPROM for a single logical port in hex format.
    Args:
        logical_port_name: logical port name
        page: page to be dumped

    Returns:
        tuple(0, dump string) if success else tuple(error_code, error_message)
    """
    if platform_sfputil.is_logical_port(logical_port_name) == 0:
        print_all_valid_port_values()
        return ERROR_INVALID_PORT, f'Error: invalid port {logical_port_name}'

    if is_port_type_rj45(logical_port_name):
        return ERROR_INVALID_PORT, f'{logical_port_name}: SFP EEPROM Hexdump is not applicable for RJ45 port'

    physical_port = logical_port_to_physical_port_index(logical_port_name)
    try:
        sfp = platform_chassis.get_sfp(physical_port)
        presence = sfp.get_presence()
    except NotImplementedError:
        return ERROR_NOT_IMPLEMENTED, 'Sfp.get_presence() is currently not implemented for this platform'

    if not presence:
        return ERROR_NOT_IMPLEMENTED, 'SFP EEPROM not detected'

    try:
        api = sfp.get_xcvr_api()
        if not api:
            return ERROR_NOT_IMPLEMENTED, 'Error: Failed to read EEPROM for offset 0!'

        from sonic_platform_base.sonic_xcvr.api.public import sff8636, sff8436, cmis, sff8472
        from sonic_platform_base.sonic_xcvr.fields import consts
        if isinstance(api, cmis.CmisApi):
            if page is None: # print all possible pages
                if api.is_flat_memory():
                    pages = [0]
                else:
                    pages = copy.deepcopy(CMIS_MODULE_PAGES)
                    if api.is_coherent_module():
                        pages.extend(CMIS_COHERENT_MODULE_PAGES)
                    cdb_support = api.xcvr_eeprom.read(consts.CDB_SUPPORT)
                    if cdb_support != 0:
                        pages.append(0x9f)
            else:
                pages = [0]
                if page not in pages:
                    pages.append(page)
            return eeprom_hexdump_pages_general(logical_port_name, pages, page)
        elif isinstance(api, sff8636.Sff8636Api) or isinstance(api, sff8436.Sff8436Api):
            if page is None:
                if api.is_flat_memory():
                    pages = [0]
                else:
                    pages = copy.deepcopy(SFF8636_MODULE_PAGES)
            else:
                pages = [0]
                if page not in pages:
                    pages.append(page)
            return eeprom_hexdump_pages_general(logical_port_name, pages, page)
        elif isinstance(api, sff8472.Sff8472Api):
            if page is None:
                if not api.is_copper():
                    pages = copy.deepcopy(SFF8472_MODULE_PAGES)
                else:
                    pages = [0]
            else:
                pages = copy.deepcopy(SFF8472_MODULE_PAGES) if not api.is_copper() else [0]
                if page not in pages:
                    pages.append(page)
            return eeprom_hexdump_pages_sff8472(logical_port_name, pages, page)
        else:
            return ERROR_NOT_IMPLEMENTED, 'Cable type is not supported'
    except NotImplementedError:
        return ERROR_NOT_IMPLEMENTED, 'Sfp.read_eeprom() is currently not implemented for this platform'


def eeprom_hexdump_pages_general(logical_port_name, pages, target_page):
    """
    Dump module EEPROM for given pages in hex format. This function is designed for cable type other than SFF8472.
    Args:
        logical_port_name: logical port name
        pages: a list of pages to be dumped. The list always include a default page list and the target_page input by
               user
        target_page: user input page number, optional. target_page is only for display purpose

    Returns:
        tuple(0, dump string) if success else tuple(error_code, error_message)
    """
    if target_page is not None:
        lines = [f'EEPROM hexdump for port {logical_port_name} page {target_page:x}h']
    else:
        lines = [f'EEPROM hexdump for port {logical_port_name}']
    physical_port = logical_port_to_physical_port_index(logical_port_name)
    for page in pages:
        if page == 0:
            lines.append(f'{EEPROM_DUMP_INDENT}Lower page 0h')
            return_code, output = eeprom_dump_general(physical_port, page, 0, PAGE_SIZE, 0)
            lines.append(output)

            lines.append(f'\n{EEPROM_DUMP_INDENT}Upper page 0h')
            return_code, output = eeprom_dump_general(physical_port, page, PAGE_OFFSET, PAGE_SIZE, PAGE_OFFSET)
            lines.append(output)
        else:
            lines.append(f'\n{EEPROM_DUMP_INDENT}Upper page {page:x}h')
            return_code, output = eeprom_dump_general(physical_port, page, page * PAGE_SIZE + PAGE_OFFSET, PAGE_SIZE, PAGE_OFFSET)
            lines.append(output)

    lines.append('') # add a new line
    return 0, '\n'.join(lines)


def eeprom_hexdump_pages_sff8472(logical_port_name, pages, target_page):
    """
    Dump module EEPROM for given pages in hex format. This function is designed for SFF8472 only.
    Args:
        logical_port_name: logical port name
        pages: a list of pages to be dumped. The list always include a default page list and the target_page input by
               user
        target_page: user input page number, optional. target_page is only for display purpose

    Returns:
        tuple(0, dump string) if success else tuple(error_code, error_message)
    """
    if target_page is not None:
        lines = [f'EEPROM hexdump for port {logical_port_name} page {target_page:x}h']
    else:
        lines = [f'EEPROM hexdump for port {logical_port_name}']
    physical_port = logical_port_to_physical_port_index(logical_port_name)
    api = platform_chassis.get_sfp(physical_port).get_xcvr_api()
    is_flat_memory = api.is_flat_memory()
    for page in pages:
        if page == 0:
            lines.append(f'{EEPROM_DUMP_INDENT}A0h dump')
            if not is_flat_memory:
                return_code, output = eeprom_dump_general(physical_port, page, 0, SFF8472_A0_SIZE, 0)
            else:
                return_code, output = eeprom_dump_general(physical_port, page, 0, PAGE_SIZE, 0)
            lines.append(output)
        elif page == 1:
            lines.append(f'\n{EEPROM_DUMP_INDENT}A2h dump (lower 128 bytes)')
            return_code, output = eeprom_dump_general(physical_port, page, SFF8472_A0_SIZE, PAGE_SIZE, 0)
            lines.append(output)
        else:
            lines.append(f'\n{EEPROM_DUMP_INDENT}A2h dump (upper 128 bytes) page {page - 2:x}h')
            return_code, output = eeprom_dump_general(physical_port, page, SFF8472_A0_SIZE + PAGE_OFFSET + page * PAGE_SIZE, PAGE_SIZE, PAGE_SIZE)
            lines.append(output)

    lines.append('') # add a new line
    return 0, '\n'.join(lines)


def eeprom_dump_general(physical_port, page, flat_offset, size, page_offset, no_format=False):
    """
    Dump module EEPROM.
    Args:
        physical_port: physical port index
        page: module EEPROM page number
        flat_offset: overall offset in flat memory
        size: size of bytes to be dumped
        page_offset: offset within a page, only for print purpose
        no_format: False if dump with hex format else dump with flat hex string. Default False.

    Returns:
        tuple(0, dump string) if success else tuple(error_code, error_message)
    """
    sfp = platform_chassis.get_sfp(physical_port)
    page_dump = sfp.read_eeprom(flat_offset, size)
    if page_dump is None:
        return ERROR_NOT_IMPLEMENTED, f'Error: Failed to read EEPROM for page {page:x}h, flat_offset {flat_offset}, page_offset {page_offset}, size {size}!'
    if not no_format:
        return 0, hexdump(EEPROM_DUMP_INDENT, page_dump, page_offset, start_newline=False)
    else:
        return 0, ''.join('{:02x}'.format(x) for x in page_dump)


def convert_byte_to_valid_ascii_char(byte):
    if byte < 32 or 126 < byte:
        return '.'
    else:
        return chr(byte)


def hexdump(indent, data, mem_address, start_newline=True):
    size = len(data)
    offset = 0
    lines = [''] if start_newline else []
    while size > 0:
        offset_str = "{}{:08x}".format(indent, mem_address)
        if size >= 16:
            first_half = ' '.join("{:02x}".format(x) for x in data[offset:offset + 8])
            second_half = ' '.join("{:02x}".format(x) for x in data[offset + 8:offset + 16])
            ascii_str = ''.join(convert_byte_to_valid_ascii_char(x) for x in data[offset:offset + 16])
            lines.append(f'{offset_str} {first_half}  {second_half} |{ascii_str}|')
        elif size > 8:
            first_half = ' '.join("{:02x}".format(x) for x in data[offset:offset + 8])
            second_half = ' '.join("{:02x}".format(x) for x in data[offset + 8:offset + size])
            padding = '   ' * (16 - size)
            ascii_str = ''.join(convert_byte_to_valid_ascii_char(x) for x in data[offset:offset + size])
            lines.append(f'{offset_str} {first_half}  {second_half}{padding} |{ascii_str}|')
            break
        else:
            hex_part = ' '.join("{:02x}".format(x) for x in data[offset:offset + size])
            padding = '   ' * (16 - size)
            ascii_str = ''.join(convert_byte_to_valid_ascii_char(x) for x in data[offset:offset + size])
            lines.append(f'{offset_str} {hex_part} {padding} |{ascii_str}|')
            break
        size -= 16
        offset += 16
        mem_address += 16
    return '\n'.join(lines)


# 'presence' subcommand
@show.command()
@click.option('-p', '--port', metavar='<port_name>', help="Display SFP presence for port <port_name> only")
def presence(port):
    """Display presence of SFP transceiver(s)"""
    logical_port_list = []
    output_table = []
    table_header = ["Port", "Presence"]

    # Create a list containing the logical port names of all ports we're interested in
    if port is None:
        logical_port_list = platform_sfputil.logical
    else:
        if platform_sfputil.is_logical_port(port) == 0:
            click.echo("Error: invalid port '{}'\n".format(port))
            print_all_valid_port_values()
            sys.exit(ERROR_INVALID_PORT)

        logical_port_list = [port]

    logical_port_list = natsort.natsorted(logical_port_list)
    for logical_port_name in logical_port_list:
        ganged = False
        i = 1

        physical_port_list = logical_port_name_to_physical_port_list(logical_port_name)
        if physical_port_list is None:
            click.echo("Error: No physical ports found for logical port '{}'".format(logical_port_name))
            return

        if len(physical_port_list) > 1:
            ganged = True

        for physical_port in physical_port_list:
            port_name = get_physical_port_name(logical_port_name, i, ganged)

            try:
                presence = platform_chassis.get_sfp(physical_port).get_presence()
            except NotImplementedError:
                click.echo("This functionality is currently not implemented for this platform")
                sys.exit(ERROR_NOT_IMPLEMENTED)

            status_string = "Present" if presence else "Not present"
            output_table.append([port_name, status_string])

            i += 1

    click.echo(tabulate(output_table, table_header, tablefmt="simple"))


# 'error-status' subcommand
def fetch_error_status_from_platform_api(port):
    """Fetch the error status from platform API and return the output as a string
    Args:
        port: the port whose error status will be fetched.
              None represents for all ports.
    Returns:
        A string consisting of the error status of each port.
    """
    if port is None:
        logical_port_list = natsort.natsorted(platform_sfputil.logical)
    else:
        logical_port_list = [port]

    output = []
    for logical_port_name in logical_port_list:
        physical_port = logical_port_to_physical_port_index(logical_port_name)

        if is_port_type_rj45(logical_port_name):
            output.append([logical_port_name, "N/A"])
        else:
            try:
                error_description = platform_chassis.get_sfp(physical_port).get_error_description()
                output.append([logical_port_name, error_description])
            except NotImplementedError:
                click.echo("get_error_description NOT implemented for port {}".format(logical_port_name))
                sys.exit(ERROR_NOT_IMPLEMENTED)

    return output

def fetch_error_status_from_state_db(port, state_db):
    """Fetch the error status from STATE_DB and return them in a list.
    Args:
        port: the port whose error status will be fetched.
              None represents for all ports.
    Returns:
        A list consisting of tuples (port, description) and sorted by port.
    """
    status = {}
    if port:
        status[port] = state_db.get_all(state_db.STATE_DB, 'TRANSCEIVER_STATUS_SW|{}'.format(port))
    else:
        ports = state_db.keys(state_db.STATE_DB, 'TRANSCEIVER_STATUS_SW|*')
        for key in ports:
            status[key.split('|')[1]] = state_db.get_all(state_db.STATE_DB, key)

    sorted_ports = natsort.natsorted(status)
    output = []
    for port in sorted_ports:
        if is_port_type_rj45(port):
            description = "N/A"
        else:
            statestring = status[port].get('status')
            description = status[port].get('error')
            if statestring == '1':
                description = 'OK'
            elif statestring == '0':
                description = 'Unplugged'
            elif description == 'N/A':
                log.log_error("Inconsistent state found for port {}: state is {} but error description is N/A".format(port, statestring))
                description = 'Unknown state: {}'.format(statestring)

        output.append([port, description])

    return output

@show.command()
@click.option('-p', '--port', metavar='<port_name>', help="Display SFP error status for port <port_name> only")
@click.option('-hw', '--fetch-from-hardware', 'fetch_from_hardware', is_flag=True, default=False, help="Fetch the error status from hardware directly")
def error_status(port, fetch_from_hardware):
    """Display error status of SFP transceiver(s)"""
    output_table = []
    table_header = ["Port", "Error Status"]

    # Create a list containing the logical port names of all ports we're interested in
    if port and platform_sfputil.is_logical_port(port) == 0:
        click.echo("Error: invalid port '{}'\n".format(port))
        click.echo("Valid values for port: {}\n".format(str(platform_sfputil.logical)))
        sys.exit(ERROR_INVALID_PORT)

    if fetch_from_hardware:
        output_table = fetch_error_status_from_platform_api(port)
    else:
        namespaces = multi_asic.get_front_end_namespaces()
        for namespace in namespaces:
            state_db = SonicV2Connector(use_unix_socket_path=False, namespace=namespace)
            if state_db is not None:
                state_db.connect(state_db.STATE_DB)
                output_table.extend(fetch_error_status_from_state_db(port, state_db))
            else:
                click.echo("Failed to connect to STATE_DB")
                return

    click.echo(tabulate(output_table, table_header, tablefmt='simple'))


# 'lpmode' subcommand
@show.command()
@click.option('-p', '--port', metavar='<port_name>', help="Display SFP low-power mode status for port <port_name> only")
@click.option('--use-lpmode-pin', is_flag=True, default=False, help='Use Xcvr LPMode pin instead of EEPROM')
def lpmode(port, use_lpmode_pin):
    """Display low-power mode status of SFP transceiver(s)"""
    logical_port_list = []
    output_table = []
    table_header = ["Port", "Low-power Mode"]

    # Create a list containing the logical port names of all ports we're interested in
    if port is None:
        logical_port_list = platform_sfputil.logical
    else:
        if platform_sfputil.is_logical_port(port) == 0:
            click.echo("Error: invalid port '{}'\n".format(port))
            print_all_valid_port_values()
            sys.exit(ERROR_INVALID_PORT)

        logical_port_list = [port]

    for logical_port_name in logical_port_list:
        ganged = False
        i = 1

        physical_port_list = logical_port_name_to_physical_port_list(logical_port_name)
        if physical_port_list is None:
            click.echo("Error: No physical ports found for logical port '{}'".format(logical_port_name))
            return

        if is_port_type_rj45(logical_port_name):
            output_table.append([logical_port_name, "N/A"])
        else:
            if len(physical_port_list) > 1:
                ganged = True

            for physical_port in physical_port_list:
                port_name = get_physical_port_name(logical_port_name, i, ganged)
                i += 1

                sfp = platform_chassis.get_sfp(physical_port)
                try:
                    if not sfp.get_presence():
                        output_table.append([port_name, "Not Present"])
                        continue
                    if use_lpmode_pin:
                        lpmode = sfp.get_lpmode_via_pin()
                    else:
                        lpmode = sfp.get_lpmode()
                except (NotImplementedError, AttributeError) as e:
                    click.echo("This functionality is currently not implemented for this platform "
                               "({}: {})".format(type(e).__name__, e))
                    sys.exit(ERROR_NOT_IMPLEMENTED)

                if lpmode:
                    output_table.append([port_name, "On"])
                else:
                    output_table.append([port_name, "Off"])

    click.echo(tabulate(output_table, table_header, tablefmt='simple'))


def show_firmware_version(port_name, interface_filter=None, vendor_pn_filter=None,
                          tabulate_output=False, verbose=False):
    ports = get_present_sfp_ports_names_list()
    if port_name:
        if port_name not in ports:
            click.echo("Error: SFP not present on port '{}'".format(port_name))
            sys.exit(ERROR_INVALID_PORT)
        ports = [port_name]

    present_ports = ports
    transceiver_info_map, _, duplicate_ports = get_transceiver_info_for_ports(ports, unique=False)
    ports = get_interface_names_sorted_by_interface_number(
        [port for port in present_ports if port not in duplicate_ports])

    if interface_filter:
        ports = list(set(ports) & set(interface_filter))
        if not ports:
            click.echo("No matching ports")
            return

    if vendor_pn_filter:
        ports = [port for port in ports
                 if (transceiver_info_map.get(port) or {}).get('model') in vendor_pn_filter]
        if not ports:
            click.echo("No matching ports")
            return

    fw_query_ports = [port for port in ports if port in transceiver_info_map]
    module_firmware_info_map, ports_failed_to_get_module_firmware_info = \
        get_module_firmware_info_for_ports(fw_query_ports, verbose=verbose)

    if tabulate_output:
        header = [
            'Interface', 'Vendor Name', 'Vendor PN', 'Vendor SN',
            'Image A', 'Image B', 'Active', 'Running', 'Committed'
        ]
        table_data = []

    # Sort the ports by interface number
    ports = get_interface_names_sorted_by_interface_number(ports)

    for port in ports:
        transceiver_info = transceiver_info_map.get(port)
        fw_info = module_firmware_info_map.get(port)
        (vendor_name, vendor_pn, vendor_sn, image_a, image_b,
         active_fw, inactive_fw, factory_image, running_image,
         committed_image) = get_fwversion_fields(
            transceiver_info, fw_info)

        if tabulate_output:
            table_data.append([
                port,
                vendor_name,
                vendor_pn,
                vendor_sn,
                image_a,
                image_b,
                active_fw,
                running_image,
                committed_image
            ])
        else:
            click.echo("Interface: {}".format(port))
            click.echo("Vendor Name: {}".format(vendor_name))
            click.echo("Vendor PN: {}".format(vendor_pn))
            click.echo("Vendor SN: {}".format(vendor_sn))
            click.echo("Image A Version: {}".format(image_a))
            click.echo("Image B Version: {}".format(image_b))
            click.echo("Factory Image Version: {}".format(factory_image))
            click.echo("Running Image: {}".format(running_image))
            click.echo("Committed Image: {}".format(committed_image))
            click.echo("Active Firmware: {}".format(active_fw))
            click.echo("Inactive Firmware: {}".format(inactive_fw))
            click.echo()

    if tabulate_output:
        click.echo(tabulate(table_data, header, tablefmt='simple'))

# 'fwversion' subcommand


@show.command()
@click.argument('port_name', metavar='<port_name>', required=False, default=None)
@click.option('-t', '--tabulate', is_flag=True, default=False, help="Display firmware version in tabular format")
@click.option('-i', 'interfaces', metavar='<INTERFACE_LIST>',
              help="Comma-separated list of interfaces. Each entity may be a "
                   "single interface (Ethernet0) or an inclusive interface "
                   "range (Ethernet16-80).")
@click.option('-p', 'vendor_pn', metavar='<PART_NUMBER_LIST>', help="Comma-separated list of vendor part numbers")
def fwversion(port_name, tabulate, interfaces, vendor_pn):
    """Show firmware version of the transceiver(s) (all ports if no port specified)"""

    # Check if single port is RJ45
    if port_name and is_port_type_rj45(port_name):
        click.echo("Show firmware version is not applicable for RJ45 port {}.".format(port_name))
        sys.exit(EXIT_FAIL)

    interface_filter = None
    if interfaces:
        present_sfp_ports = get_present_sfp_ports_names_list()
        interface_filter = expand_interface_tokens(interfaces, present_sfp_ports)
        if not interface_filter:
            # All tokens were ranges and none matched a present port. The
            # per-range "No matching ports for range" notice has already
            # been printed by expand_interface_tokens; just exit cleanly.
            sys.exit(EXIT_SUCCESS)
    if vendor_pn:
        vendor_pn = [p.strip() for p in vendor_pn.split(',')]
    show_firmware_version(
        port_name, interface_filter=interface_filter,
        vendor_pn_filter=vendor_pn, tabulate_output=tabulate)
    sys.exit(EXIT_SUCCESS)


def get_interface_names_sorted_by_interface_number(ports):
    return natsorted(ports, key=lambda y: int(re.search(r'\d+', y).group()))

# 'lpmode' subgroup
@cli.group()
def lpmode():
    """Enable or disable low-power mode for SFP transceiver"""
    pass


# Helper method for setting low-power mode
def set_lpmode(logical_port, enable, use_lpmode_pin=False):
    ganged = False
    i = 1

    if platform_sfputil.is_logical_port(logical_port) == 0:
        click.echo("Error: invalid port '{}'\n".format(logical_port))
        print_all_valid_port_values()
        sys.exit(ERROR_INVALID_PORT)

    physical_port_list = logical_port_name_to_physical_port_list(logical_port)
    if physical_port_list is None:
        click.echo("Error: No physical ports found for logical port '{}'".format(logical_port))
        return

    if is_port_type_rj45(logical_port):
        click.echo("{} low-power mode is not applicable for RJ45 port {}.".format("Enabling" if enable else "Disabling", logical_port))
        sys.exit(EXIT_FAIL)

    if len(physical_port_list) > 1:
        ganged = True

    for physical_port in physical_port_list:
        port_name = get_physical_port_name(logical_port, i, ganged)
        i += 1
        try:
            sfp = platform_chassis.get_sfp(physical_port)
            if not sfp.get_presence():
                click.echo(f"{logical_port}: module {physical_port} is not present, skipping")
                continue
            click.echo("{} low-power mode for port {} ... ".format(
                "Enabling" if enable else "Disabling",
                get_physical_port_name(logical_port, i, ganged)), nl=False)
            if use_lpmode_pin:
                result = sfp.set_lpmode_via_pin(enable)
            else:
                result = sfp.set_lpmode(enable)
        except (NotImplementedError, AttributeError) as e:
            click.echo("This functionality is currently not implemented for this platform "
                       "({}: {})".format(type(e).__name__, e))
            sys.exit(ERROR_NOT_IMPLEMENTED)

        if result:
            click.echo("OK")
        else:
            click.echo("Failed")


# 'show' subcommand — alias of `sfputil show lpmode`
lpmode.add_command(show.commands['lpmode'], name='show')

# 'off' subcommand
@lpmode.command()
@click.argument('port_name', metavar='<port_name>')
@click.option('--use-lpmode-pin', is_flag=True, default=False, help='Use Xcvr LPMode pin instead of EEPROM')
def off(port_name, use_lpmode_pin):
    """Disable low-power mode for SFP transceiver"""
    set_lpmode(port_name, False, use_lpmode_pin=use_lpmode_pin)


# 'on' subcommand
@lpmode.command()
@click.argument('port_name', metavar='<port_name>')
@click.option('--use-lpmode-pin', is_flag=True, default=False, help='Use Xcvr LPMode pin instead of EEPROM')
def on(port_name, use_lpmode_pin):
    """Enable low-power mode for SFP transceiver"""
    set_lpmode(port_name, True, use_lpmode_pin=use_lpmode_pin)


# 'reset' subcommand
@cli.command()
@click.argument('port_name', metavar='<port_name>')
def reset(port_name):
    """Reset SFP transceiver"""
    ganged = False
    i = 1

    if platform_sfputil.is_logical_port(port_name) == 0:
        click.echo("Error: invalid port '{}'\n".format(port_name))
        print_all_valid_port_values()
        sys.exit(ERROR_INVALID_PORT)

    physical_port_list = logical_port_name_to_physical_port_list(port_name)
    if physical_port_list is None:
        click.echo("Error: No physical ports found for logical port '{}'".format(port_name))
        return

    if is_port_type_rj45(port_name):
        click.echo("Reset is not applicable for RJ45 port {}.".format(port_name))
        sys.exit(EXIT_FAIL)

    if len(physical_port_list) > 1:
        ganged = True

    for physical_port in physical_port_list:
        physical_port_name = get_physical_port_name(port_name, i, ganged)
        i += 1
        try:
            sfp = platform_chassis.get_sfp(physical_port)
            if not sfp.get_presence():
                click.echo(f"{port_name}: module {physical_port} is not present, skipping")
                continue
            click.echo("Resetting port {} ... ".format(physical_port_name), nl=False)
            result = sfp.reset()
        except NotImplementedError:
            click.echo("This functionality is currently not implemented for this platform")
            sys.exit(ERROR_NOT_IMPLEMENTED)

        if result:
            click.echo("OK")
        else:
            click.echo("Failed")


# 'power' subgroup
@cli.group()
def power():
    """Enable or disable power of SFP transceiver"""
    pass


# Helper method for setting low-power mode
def set_power(port_name, enable):
    physical_port = logical_port_to_physical_port_index(port_name)
    sfp = platform_chassis.get_sfp(physical_port)

    if is_port_type_rj45(port_name):
        click.echo("Power disable/enable is not available for RJ45 port {}.".format(port_name))
        sys.exit(EXIT_FAIL)

    try:
        presence = sfp.get_presence()
    except NotImplementedError:
        click.echo("sfp get_presence() NOT implemented!")
        sys.exit(EXIT_FAIL)

    if not presence:
        click.echo("{}: SFP EEPROM not detected\n".format(port_name))
        sys.exit(EXIT_FAIL)

    try:
        result = platform_chassis.get_sfp(physical_port).set_power(enable)
    except (NotImplementedError, AttributeError):
        click.echo("This functionality is currently not implemented for this platform")
        sys.exit(ERROR_NOT_IMPLEMENTED)

    if result:
        click.echo("OK")
    else:
        click.echo("Failed")
        sys.exit(EXIT_FAIL)


# 'disable' subcommand
@power.command()
@click.argument('port_name', metavar='<port_name>')
def disable(port_name):
    """Disable power of SFP transceiver"""
    set_power(port_name, False)


# 'enable' subcommand
@power.command()
@click.argument('port_name', metavar='<port_name>')
def enable(port_name):
    """Enable power of SFP transceiver"""
    set_power(port_name, True)


def update_firmware_info_to_state_db(port_name):
    first_subport = get_first_subport(port_name)
    if first_subport is None:
        click.echo("Error: Unable to get first subport for {} while updating FW info to DB".format(port_name))
        return
    physical_port = logical_port_to_physical_port_index(first_subport)

    namespaces = multi_asic.get_front_end_namespaces()
    for namespace in namespaces:
        state_db = SonicV2Connector(use_unix_socket_path=False, namespace=namespace)
        if state_db is not None:
            state_db.connect(state_db.STATE_DB)
            transceiver_firmware_info_dict = platform_chassis.get_sfp(physical_port).get_transceiver_info_firmware_versions()
            if transceiver_firmware_info_dict is not None:
                for key, value in transceiver_firmware_info_dict.items():
                    state_db.set(state_db.STATE_DB, 'TRANSCEIVER_FIRMWARE_INFO|{}'.format(first_subport), key, value)


def get_transceiver_api_helper(port_name, exit_on_error=True):
    api = None
    physical_port = logical_port_to_physical_port_index(port_name)
    sfp = platform_chassis.get_sfp(physical_port)
    try:
        api = sfp.get_xcvr_api()
    except NotImplementedError:
        click.echo(f"This functionality is currently not implemented for this platform for {port_name}")
        if exit_on_error:
            sys.exit(ERROR_NOT_IMPLEMENTED)
    return api

# 'firmware' subgroup
@cli.group()
def firmware():
    """Download/Upgrade firmware on the transceiver"""
    pass


# 'show' subcommand — alias of `sfputil show fwversion`
firmware.add_command(show.commands['fwversion'], name='show')


def run_firmware(port_name, mode, exit_on_error=True, verbose=True):
    """
        Make the inactive firmware as the current running firmware
        @port_name:
        @mode: 0, 1, 2, 3 different modes to run the firmware
        Returns 1 on success, and exit_code = -1 on failure
    """
    status = 0
    api = get_transceiver_api_helper(port_name, exit_on_error=exit_on_error)
    if not api:
        return status

    if verbose:
        if mode == 0:
            click.echo("Running firmware: Non-hitless Reset to Inactive Image")
        elif mode == 1:
            click.echo("Running firmware: Hitless Reset to Inactive Image")
        elif mode == 2:
            click.echo("Running firmware: Attempt non-hitless Reset to Running Image")
        elif mode == 3:
            click.echo("Running firmware: Attempt Hitless Reset to Running Image")
        else:
            click.echo("Running firmware: Unknown mode {}".format(mode))

    if mode in [0, 1, 2, 3]:
        try:
            status = api.cdb_run_firmware(mode)
        except NotImplementedError:
            click.echo(f"This functionality is not applicable for this transceiver for {port_name}")
            if exit_on_error:
                sys.exit(EXIT_FAIL)
    else:
        if exit_on_error:
            sys.exit(EXIT_FAIL)

    return status


def is_fw_switch_done(port_name, exit_on_error=True, verbose=True):
    """
        Make sure the run_firmware cmd is done
        @port_name:
        Returns 1 on success, and exit_code = -1 on failure
    """
    status = 0
    api = get_transceiver_api_helper(port_name, exit_on_error=exit_on_error)
    if not api:
        return status

    try:
        MAX_WAIT = 60
        timeout_time = time.time() + MAX_WAIT
        while time.time() < timeout_time:
            fw_info = api.get_module_fw_info()
            if fw_info['status'] is True and fw_info['result'] is not None:
                (ImageA, ImageARunning, ImageACommitted, ImageAInvalid,
                 ImageB, ImageBRunning, ImageBCommitted, ImageBInvalid, _, _) = fw_info['result']

                if (ImageARunning == 1) and (ImageAInvalid == 1):
                    click.echo("FW info error : ImageA shows running, but also shows invalid!")
                    return -1
                elif (ImageBRunning == 1) and (ImageBInvalid == 1):
                    click.echo("FW info error : ImageB shows running, but also shows invalid!")
                    return -1
                elif (ImageARunning == 1) and (ImageACommitted == 0):
                    click.echo("FW images switch successful : ImageA is running")
                    return 1
                elif (ImageBRunning == 1) and (ImageBCommitted == 0):
                    click.echo("FW images switch successful : ImageB is running")
                    return 1
                # Switch not done yet — module may have returned stale pre-reset data, keep polling

            time.sleep(2)
        click.echo("FW switch : Timeout!")
        status = -1

    except NotImplementedError:
        if verbose:
            click.echo("This functionality is not applicable for this transceiver")

    return status


def commit_firmware(port_name, exit_on_error=True, verbose=True):
    status = 0
    api = get_transceiver_api_helper(port_name, exit_on_error=exit_on_error)
    if not api:
        return status

    try:
        status = api.cdb_commit_firmware()
    except NotImplementedError:
        if verbose:
            click.echo(f"This functionality is not applicable for the {port_name} transceiver")

    return status


def download_firmware(
        port_name, filepath, exit_on_error=True, verbose=True,
        show_progress=True, progress_counter=None, download_progress=None,
        update_summary_callback=None):
    """Download firmware on the transceiver

    Args:
        port_name: Name of the port
        filepath: Path to firmware file
        exit_on_error: Whether to exit on error
        verbose: Whether to print verbose messages
        show_progress: Whether to show progress bar (for single port, uses click.progressbar)
        progress_counter: Optional enlighten counter for multi-port progress tracking
    """
    status = 0
    try:
        fd = open(filepath, 'rb')
        fd.seek(0, 2)
        file_size = fd.tell()
        fd.seek(0, 0)
    except FileNotFoundError:
        click.echo(f"Firmware file {filepath} NOT found")
        if exit_on_error:
            sys.exit(EXIT_FAIL)
        else:
            return status

    api = None
    sfp = None
    try:
        physical_port = logical_port_to_physical_port_index(port_name)
        api = get_transceiver_api_helper(port_name, exit_on_error=exit_on_error)
        sfp = platform_chassis.get_sfp(physical_port)
        fwinfo = api.get_module_fw_mgmt_feature()
        if fwinfo and fwinfo.get('status') is True and fwinfo.get('feature'):
            startLPLsize, maxblocksize, lplonly_flag, autopaging_flag, writelength = fwinfo['feature']
        else:
            if verbose:
                click.echo(f"Failed to fetch CDB Firmware management features for {port_name}")
            if exit_on_error:
                sys.exit(EXIT_FAIL)
            else:
                return status
    except NotImplementedError:
        click.echo(f"This functionality is NOT applicable for the {port_name} transceiver")
        if exit_on_error:
            sys.exit(ERROR_NOT_IMPLEMENTED)
        else:
            return status
    except Exception as e:
        if verbose:
            click.echo(f"Error getting firmware management features for {port_name}: {str(e)}")
        if exit_on_error:
            sys.exit(EXIT_FAIL)
        else:
            return status

    if verbose:
        click.echo('CDB: Starting firmware download')
    startdata = fd.read(startLPLsize)
    status = api.cdb_start_firmware_download(startLPLsize, startdata, file_size)
    if status != 1:
        if verbose:
            click.echo(f'CDB: Start firmware download failed for {port_name} - status {status}')
        # Return module to idle so subsequent retries don't see a stuck
        # download-in-progress state.
        abort_firmware_download(port_name, verbose=verbose)
        if exit_on_error:
            sys.exit(EXIT_FAIL)
        else:
            return status

    # Increase the optoe driver's write max to speed up firmware download
    try:
        sfp.set_optoe_write_max(SMBUS_BLOCK_WRITE_SIZE)
    except NotImplementedError:
        click.echo("Platform doesn't implement optoe write max change. Skipping value increase.")

    address = 0
    if lplonly_flag:
        BLOCK_SIZE = min(MAX_LPL_FIRMWARE_BLOCK_SIZE, maxblocksize)
    else:
        BLOCK_SIZE = maxblocksize
    remaining = file_size - startLPLsize
    _dl_start_time = time.time()
    _last_summary_update = _dl_start_time
    if download_progress is not None:
        download_progress[port_name] = (startLPLsize, file_size, _dl_start_time)

    # Use progress_counter if provided, otherwise create one for single port
    manager = None
    if progress_counter:
        # Use the provided counter
        counter = progress_counter
        counter.total = file_size
        counter.count = 0
    elif show_progress:
        # Create a new enlighten counter for single port operation
        manager = enlighten.get_manager()
        # Use a fixed width to accommodate port names like "Ethernet1152: Downloading"
        desc_min_width = 27
        counter = manager.counter(
            total=file_size,
            desc=f"{port_name}: Downloading",
            unit='B',
            leave=True,
            min_delta=0.1,
            series=[' ', '-', '#'],  # ASCII characters similar to click.progressbar
            bar_format='{desc:<%d}{percentage:3.0f}%%|{bar}| {count:.2f}/{total:.2f} {unit} [{eta}]' % desc_min_width
        )
    else:
        counter = None

    try:
        while remaining > 0:
            count = BLOCK_SIZE if remaining >= BLOCK_SIZE else remaining
            data = fd.read(count)
            if len(data) != count:
                click.echo(f"Firmware file read failed for {port_name}!")
                abort_firmware_download(port_name, verbose=verbose)
                if exit_on_error:
                    sys.exit(EXIT_FAIL)
                else:
                    return status

            if lplonly_flag:
                status = api.cdb_lpl_block_write(address, data)
            else:
                status = api.cdb_epl_block_write(address, data)
            if (status != 1):
                if verbose:
                    click.echo(f"CDB: firmware download failed for {port_name}! - status {status}")
                abort_firmware_download(port_name, verbose=verbose)
                if exit_on_error:
                    sys.exit(EXIT_FAIL)
                else:
                    return status

            if counter:
                counter.update(count)
            address += count
            remaining -= count
            if download_progress is not None:
                download_progress[port_name] = (startLPLsize + address, file_size, _dl_start_time)
                now = time.time()
                if update_summary_callback and now - _last_summary_update >= 2:
                    update_summary_callback()
                    _last_summary_update = now
    finally:
        if manager:
            manager.stop()

    # Restore the optoe driver's write max to '1' (default value)
    try:
        sfp.set_optoe_write_max(1)
    except NotImplementedError:
        click.echo("Platform doesn't implement optoe write max change. Skipping value restore!")

    status = api.cdb_firmware_download_complete()
    if status != 1:
        if verbose:
            click.echo(
                f"CDB: firmware download complete check failed for "
                f"{port_name} - status {status}")
        abort_firmware_download(port_name, verbose=verbose)
        if exit_on_error:
            sys.exit(EXIT_FAIL)
        else:
            return status
    update_firmware_info_to_state_db(port_name)
    if verbose:
        click.echo('CDB: firmware download complete')
    return status


# 'run' subcommand
@firmware.command()
@click.argument('port_name', required=True, default=None)
@click.option('--mode', default="0", type=click.Choice(["0", "1", "2", "3"]), show_default=True,
                                                         help="0 = Non-hitless Reset to Inactive Image\n \
                                                               1 = Hitless Reset to Inactive Image (Default)\n \
                                                               2 = Attempt non-hitless Reset to Running Image\n \
                                                               3 = Attempt Hitless Reset to Running Image\n")
@click.option('--delay', metavar='<delay>', type=click.IntRange(0, 10), default=5,
              help="Delay time before updating firmware information to STATE_DB")
def run(port_name, mode, delay, verbose=True):
    """Run the firmware with default mode=0"""

    if is_port_type_rj45(port_name):
        click.echo("This functionality is not applicable for RJ45 port {}.".format(port_name))
        sys.exit(EXIT_FAIL)

    if not is_sfp_present(port_name):
        click.echo("{}: SFP EEPROM not detected\n".format(port_name))
        sys.exit(EXIT_FAIL)

    status = run_firmware(port_name, int(mode), exit_on_error=True, verbose=verbose)
    if status == 1:
        time.sleep(delay)
        update_firmware_info_to_state_db(port_name)
        click.echo("Firmware run in mode={} success".format(mode))
    else:
        click.echo("Firmware run failed")
        sys.exit(EXIT_FAIL)


# 'commit' subcommand


@firmware.command()
@click.argument('port_name', required=True, default=None)
def commit(port_name):
    """Commit the running firmware"""

    if is_port_type_rj45(port_name):
        click.echo("This functionality is not applicable for RJ45 port {}.".format(port_name))
        sys.exit(EXIT_FAIL)

    if not is_sfp_present(port_name):
        click.echo("{}: SFP EEPROM not detected\n".format(port_name))
        sys.exit(EXIT_FAIL)

    status = commit_firmware(port_name, exit_on_error=True, verbose=True)
    if status == 1:
        update_firmware_info_to_state_db(port_name)
        click.echo("Firmware commit successful")
    else:
        click.echo('Failed to commit firmware! CDB status: {}'.format(status))
        sys.exit(EXIT_FAIL)


def get_transceiver_info_for_one_port(port):
    """Helper function to fetch transceiver info for a single port"""
    try:
        api = get_transceiver_api_helper(port, exit_on_error=False)
        if api is None:
            return port, None, "Transceiver API not available"
        transceiver_info = api.get_transceiver_info()
        return port, transceiver_info, None
    except Exception as e:
        return port, None, str(e)


def get_transceiver_info_for_ports(ports, unique=False):
    """Fetch transceiver info for multiple ports in parallel.

    Returns a tuple of (transceiver_info_map, ports_failed, duplicate_ports). When
    unique=True, ports sharing a 'serial' with another port are removed from the
    info map and returned in duplicate_ports rather than ports_failed.
    """
    transceiver_info_map = {}
    ports_failed_to_get_transceiver_info = []
    duplicate_ports = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=128) as executor:
        futures = {executor.submit(get_transceiver_info_for_one_port, port): port for port in ports}
        for future in concurrent.futures.as_completed(futures):
            port, transceiver_info, error = future.result()
            if transceiver_info is not None:
                transceiver_info_map[port] = transceiver_info
            else:
                ports_failed_to_get_transceiver_info.append(port)

    if unique:
        # If multiple ports have same 'serial' number, keep only the one with lowest port number
        seen = set()
        for port in get_interface_names_sorted_by_interface_number(list(transceiver_info_map.keys())):
            serial = transceiver_info_map[port].get('serial')
            if serial is not None and serial not in seen:
                seen.add(serial)
            else:
                duplicate_ports.append(port)
                del transceiver_info_map[port]
    return transceiver_info_map, ports_failed_to_get_transceiver_info, duplicate_ports


def get_module_firmware_info_for_one_port(port, verbose=False):
    """Helper function to fetch module firmware info for a single port"""
    try:
        api = get_transceiver_api_helper(port, exit_on_error=False)
        if api is None:
            if verbose:
                click.echo(f"{port}: transceiver API not available")
            return port, None, "Transceiver API not available"
        fw_info = api.get_module_fw_info()
        return port, fw_info, None
    except NotImplementedError:
        if verbose:
            click.echo(f"{port}: get_module_fw_info not implemented for this transceiver")
        return port, None, "NotImplementedError"
    except Exception as e:
        if verbose:
            click.echo(f"{port}: failed to get module firmware info: {e}")
        return port, None, str(e)


def get_module_firmware_info_for_ports(ports, verbose=False):
    """Fetch module firmware info for multiple ports in parallel"""
    module_firmware_info_map = {}
    ports_failed_to_get_module_firmware_info = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=128) as executor:
        futures = {executor.submit(get_module_firmware_info_for_one_port, port, verbose): port for port in ports}
        for future in concurrent.futures.as_completed(futures):
            port, fw_info, error = future.result()
            if fw_info is not None:
                module_firmware_info_map[port] = fw_info
            else:
                ports_failed_to_get_module_firmware_info.append(port)
    return module_firmware_info_map, ports_failed_to_get_module_firmware_info


def get_fwversion_fields(transceiver_info, fw_info):
    vendor_name = transceiver_info.get('manufacturer', 'N/A') if transceiver_info else 'N/A'
    vendor_pn = transceiver_info.get('model', 'N/A') if transceiver_info else 'N/A'
    vendor_sn = transceiver_info.get('serial', 'N/A') if transceiver_info else 'N/A'

    image_a = image_b = active_fw = inactive_fw = 'N/A'
    factory_image = running_image = committed_image = 'N/A'

    if fw_info and fw_info.get('status'):
        # Prefer the structured tuple over parsing the human-readable 'info' string;
        # the tuple layout is fixed by the lower-layer API contract.
        result = fw_info.get('result')
        if isinstance(result, tuple) and len(result) >= 10:
            (image_a, image_a_running, image_a_committed, _image_a_valid,
             image_b, image_b_running, image_b_committed, _image_b_valid,
             active_fw, inactive_fw) = result[:10]
            if image_a_running == 1:
                running_image = 'A'
            elif image_b_running == 1:
                running_image = 'B'
            if image_a_committed == 1:
                committed_image = 'A'
            elif image_b_committed == 1:
                committed_image = 'B'

        # 'Factory Image Version' is not part of the structured tuple,
        # so it must still be read from the info text.
        info = fw_info.get('info', '') or ''
        for line in info.strip().split('\n'):
            if 'Factory Image Version:' in line:
                factory_image = line.split(':', 1)[1].strip()
                break

    return (vendor_name, vendor_pn, vendor_sn, image_a, image_b,
            active_fw, inactive_fw, factory_image, running_image,
            committed_image)


def get_present_sfp_ports_names_list():
    ports = []
    logical_port_list = natsorted(platform_sfputil.logical)
    for logical_port_name in logical_port_list:
        if is_port_type_rj45(logical_port_name):
            continue
        physical_port = logical_port_to_physical_port_index(logical_port_name)
        sfp = platform_chassis.get_sfp(physical_port)
        if not sfp.get_presence():
            continue
        ports.append(logical_port_name)
    return ports


INTERFACE_RANGE_RE = re.compile(r'^([A-Za-z]+)(\d+)-(?:([A-Za-z]+))?(\d+)$')
INTERFACE_SINGLE_RE = re.compile(r'^([A-Za-z]+)(\d+)$')


def parse_interface_token(token):
    """Parse a single token from an INTERFACE_LIST argument.

    Returns one of:
        ('single', port_name)
        ('range', prefix, start_idx, end_idx)

    Raises ValueError for malformed tokens (e.g. missing bound, mismatched
    prefixes, reversed range).
    """
    token = token.strip()
    if not token:
        raise ValueError("Empty interface token")

    if '-' in token:
        m = INTERFACE_RANGE_RE.match(token)
        if not m:
            raise ValueError(f"Malformed interface range: '{token}'")
        prefix_left, start_str, prefix_right, end_str = m.groups()
        if prefix_right and prefix_right != prefix_left:
            raise ValueError(
                f"Mismatched prefixes in range '{token}': "
                f"'{prefix_left}' vs '{prefix_right}'")
        start_idx = int(start_str)
        end_idx = int(end_str)
        if end_idx < start_idx:
            raise ValueError(
                f"Reversed interface range '{token}': end ({end_idx}) is "
                f"less than start ({start_idx})")
        return ('range', prefix_left, start_idx, end_idx)

    m = INTERFACE_SINGLE_RE.match(token)
    if not m:
        raise ValueError(f"Malformed interface name: '{token}'")
    return ('single', token)


def expand_interface_tokens(tokens_csv, present_ports):
    """Expand a comma-separated INTERFACE_LIST argument into a list of
    present port names.

    - Single tokens (e.g. 'Ethernet0') must resolve to a present port. If
      any explicitly named interface is not present, the CLI exits with
      ERROR_INVALID_PORT.
    - Range tokens (e.g. 'Ethernet16-80' or 'Ethernet16-Ethernet80') are
      expanded inclusively and intersected with present ports. Ports inside
      the range that are not configured/present are silently dropped.
    - Malformed or reversed ranges cause the CLI to exit with
      ERROR_INVALID_PORT.
    - A range that matches zero present ports emits an informational
      message but does not abort the CLI; the caller can detect the empty
      result.
    """
    present_set = set(present_ports)
    expanded = []
    seen = set()

    for token in tokens_csv.split(','):
        try:
            parsed = parse_interface_token(token)
        except ValueError as e:
            click.echo(f"Error: {e}")
            sys.exit(ERROR_INVALID_PORT)

        if parsed[0] == 'single':
            port = parsed[1]
            if port not in present_set:
                click.echo(f"Error: port '{port}' is not present")
                sys.exit(ERROR_INVALID_PORT)
            if port not in seen:
                expanded.append(port)
                seen.add(port)
        else:
            _, prefix, start_idx, end_idx = parsed
            range_hits = 0
            for idx in range(start_idx, end_idx + 1):
                candidate = f"{prefix}{idx}"
                if candidate in present_set:
                    range_hits += 1
                    if candidate not in seen:
                        expanded.append(candidate)
                        seen.add(candidate)
            if range_hits == 0:
                click.echo(
                    f"No matching ports for range '{token.strip()}'")

    return expanded


# Decoded reasons/recovery hints for known CDB status codes.
# Sourced from the CMIS spec plus a small set of sfputil-internal modes.
CDB_FAILURE_REASONS = {
    1: ("Operation succeeded", ""),
    2: ("Image rejected by transceiver; image incompatible",
        "Use a firmware image matching the module PN/revision."),
    3: ("Invalid firmware image format",
        "Verify the firmware image and retry."),
    64: ("Transfer timed out; module unresponsive",
         "Wait for the module to become idle, then retry."),
    69: ("Firmware rejected by transceiver; incompatible",
         "Use a firmware image matching the module PN/revision."),
    70: ("Password required to access CDB feature",
         "Run 'sfputil firmware unlock <port>' and retry."),
}


def decode_cdb_failure(status_code):
    """Decode a CDB/platform status code into (reason, recovery_hint).

    status_code may be a numeric code or a free-form string (exception
    text). Unknown codes get a generic fallback so the failure table
    always renders a populated row.
    """
    if isinstance(status_code, int):
        if status_code in CDB_FAILURE_REASONS:
            return CDB_FAILURE_REASONS[status_code]
        return (
            f"Unknown CDB error (code={status_code})",
            "Collect sfputil debug output and consult vendor",
        )
    code_str = str(status_code)
    if code_str.startswith("status="):
        try:
            numeric = int(code_str.split("=", 1)[1])
            return decode_cdb_failure(numeric)
        except ValueError:
            pass
    return (
        code_str if code_str else "Operation failed",
        "Collect sfputil debug output and consult vendor",
    )


def normalize_status_code(raw):
    """Coerce a raw status value (int, 'status=N' string, or arbitrary
    exception text) into the canonical 'status code' shown in the failure
    table. Numeric codes are returned as ints; other strings are returned
    as-is.
    """
    if isinstance(raw, int):
        return raw
    s = str(raw)
    if s.startswith("status="):
        try:
            return int(s.split("=", 1)[1])
        except ValueError:
            return s
    try:
        return int(s)
    except ValueError:
        return s


def make_failure_entry(stage, raw_status):
    """Build the canonical failure-info dict for a single port."""
    status_code = normalize_status_code(raw_status)
    reason, recovery_hint = decode_cdb_failure(status_code)
    return {
        'stage': stage,
        'status_code': status_code,
        'reason': reason,
        'recovery_hint': recovery_hint,
    }


def check_fw_mgmt_capability(port_name, verbose=False):
    """Verify a port advertises CMIS firmware-management capability.

    Returns (True, None) when the module exposes a usable fw-mgmt feature
    set, otherwise (False, reason) describing why the port is excluded.
    """
    try:
        api = get_transceiver_api_helper(port_name, exit_on_error=False)
        if api is None:
            return False, "No transceiver API available"
        fwinfo = api.get_module_fw_mgmt_feature()
    except NotImplementedError:
        return False, "Firmware management not implemented for this transceiver"
    except Exception as e:
        if verbose:
            click.echo(
                f"Error querying fw mgmt feature for {port_name}: {e}")
        return False, f"Error querying fw mgmt feature: {e}"

    if not fwinfo or fwinfo.get('status') is not True or not fwinfo.get('feature'):
        return False, "CDB firmware management capability not supported"
    return True, None


def filter_fw_mgmt_capable_ports(ports, verbose=False):
    """Partition ports into (capable, incapable_failure_info).

    incapable_failure_info is a dict in the same shape as the per-port
    failure entries used elsewhere so the caller can fold these into the
    final failure table directly.
    """
    capable = []
    incapable = {}
    for port in ports:
        ok, reason = check_fw_mgmt_capability(port, verbose=verbose)
        if ok:
            capable.append(port)
        else:
            incapable[port] = {
                'stage': 'Capability',
                'status_code': 'N/A',
                'reason': reason or "Firmware management not supported",
                'recovery_hint': "Verify module supports CMIS CDB firmware management.",
            }
    return capable, incapable


def abort_firmware_download(port_name, verbose=False):
    """Best-effort CDB Abort to return a module to idle after a failed
    download step. Any errors here are swallowed: the original failure is
    what the caller cares about.
    """
    try:
        api = get_transceiver_api_helper(port_name, exit_on_error=False)
        if api is None:
            return
        cdb = getattr(api, 'cdb', None)
        if cdb is None:
            return
        abort_fn = getattr(cdb, 'abort_fw_download', None)
        if abort_fn is None:
            return
        abort_fn()
        if verbose:
            click.echo(f"CDB: Issued firmware-download abort for {port_name}")
    except Exception as e:
        if verbose:
            click.echo(
                f"CDB: Abort firmware-download failed for {port_name}: {e}")


def _normalize_firmware_path(path):
    """Normalize a firmware path for overlap comparison only.

    realpath() resolves '.', '..', and symlinks but does not require the
    file to exist, so callers can pre-validate overlap before any I/O.
    The original path is preserved separately for display.
    """
    try:
        return os.path.realpath(path)
    except Exception:
        return path


def build_port_to_firmware_map(interface_list, vendor_pn_list,
                               present_sfp_ports, transceiver_info_map):
    """Expand and merge -i/-p groups into a single port-to-firmware map.

    Implements the overlap rules from doc/sfputil/fw-mgmt-enhancement.md
    section 7.5.1:

    1. Cross-type overlap between -i and -p is ALWAYS rejected (regardless
       of whether the firmware paths match).
    2. Same firmware in multiple groups of the same type: deduplicated.
    3. Conflicting firmware paths across groups of the same type: rejected
       with ERROR_INVALID_PORT.
    4. Returns an empty mapping silently for callers to handle the
       "nothing to do" case.

    Exits with ERROR_INVALID_PORT on any overlap conflict, printing a
    conflict table before exiting.
    """
    i_map = {}          # port -> normalized realpath
    i_display = {}      # port -> original path (for display)
    i_groups = {}       # port -> selector token (for conflict table)
    p_map = {}
    p_display = {}
    p_groups = {}

    # -- Expand -i groups (interface tokens, with range support) --
    for interfaces_csv, fw_filepath in interface_list:
        ports = expand_interface_tokens(interfaces_csv, present_sfp_ports)
        norm_path = _normalize_firmware_path(fw_filepath)
        for port in ports:
            if port in i_map and i_map[port] != norm_path:
                _print_conflict_table([
                    (port, i_groups[port], i_display[port],
                     interfaces_csv, fw_filepath),
                ])
                sys.exit(ERROR_INVALID_PORT)
            i_map[port] = norm_path
            i_display[port] = fw_filepath
            i_groups[port] = interfaces_csv

    # -- Expand -p groups (vendor PN match) --
    for vendor_pn, fw_filepath in vendor_pn_list:
        matched_any = False
        norm_path = _normalize_firmware_path(fw_filepath)
        for port, info in transceiver_info_map.items():
            if info.get('model') == vendor_pn:
                matched_any = True
                if port in p_map and p_map[port] != norm_path:
                    _print_conflict_table([
                        (port, p_groups[port], p_display[port],
                         vendor_pn, fw_filepath),
                    ])
                    sys.exit(ERROR_INVALID_PORT)
                p_map[port] = norm_path
                p_display[port] = fw_filepath
                p_groups[port] = vendor_pn
        if not matched_any:
            click.echo(
                f"No ports found with vendor part number: {vendor_pn}")

    # -- Cross-type overlap: ANY port in both is a hard error --
    cross_conflicts = []
    for port in i_map:
        if port in p_map:
            cross_conflicts.append((
                port, i_groups[port], i_display[port],
                p_groups[port], p_display[port],
            ))
    if cross_conflicts:
        _print_conflict_table(cross_conflicts)
        sys.exit(ERROR_INVALID_PORT)

    # -- Merge: -i wins where it appears, -p covers the rest --
    merged = {}
    merged_display = {}
    for port, norm_path in i_map.items():
        merged[port] = norm_path
        merged_display[port] = i_display[port]
    for port, norm_path in p_map.items():
        merged[port] = norm_path
        merged_display[port] = p_display[port]

    # Hand back the original (un-normalized) paths so display and file I/O
    # operate on the user-supplied string.
    return merged_display


def _print_conflict_table(conflicts):
    """Render the firmware-path conflict table for overlap errors.

    Each row in conflicts is (port, selector_a, fw_a, selector_b, fw_b).
    """
    rows = [
        [port, sel_a, fw_a, sel_b, fw_b]
        for (port, sel_a, fw_a, sel_b, fw_b) in conflicts
    ]
    click.secho(
        "Conflict: the following port(s) are selected by overlapping "
        "groups with incompatible firmware:",
        fg='red')
    click.echo(tabulate(
        rows,
        headers=["Interface", "Group A", "Firmware A",
                 "Group B", "Firmware B"]))
    click.echo()


def display_fw_mgmt_failure_cause(ports_failed_status_info):
    ports_failed = get_interface_names_sorted_by_interface_number(list(ports_failed_status_info.keys()))
    table = []
    for port in ports_failed:
        entry = ports_failed_status_info[port]

        if isinstance(entry, dict):
            stage = entry.get('stage', 'Download')
            status_code = entry.get('status_code', '')
            reason = entry.get('reason', '')
            recovery_hint = entry.get('recovery_hint', '')
        else:
            # Backwards-compat for any caller still emitting the legacy
            # tuple shape; decode it on the fly.
            if isinstance(entry, tuple) and len(entry) == 4:
                dl_ok, run_ok, _commit_ok, raw = entry
                if not dl_ok:
                    stage = "Download"
                elif not run_ok:
                    stage = "Activate"
                else:
                    stage = "Commit"
            else:
                stage = "Download"
                raw = str(entry)
            built = make_failure_entry(stage, raw)
            stage = built['stage']
            status_code = built['status_code']
            reason = built['reason']
            recovery_hint = built['recovery_hint']

        table.append([port, stage, status_code, reason, recovery_hint])
    output = "Failed ports:\n" + tabulate(
        table,
        headers=["Interface", "Stage Failed", "Status Code",
                 "Reason", "Recovery Hint"])
    click.secho(output, fg='yellow')
    click.echo()


def run_helper(ports, run_delay, verbose):
    """Run/activate firmware on multiple ports in parallel

    Args:
        ports: List of port names to activate firmware on
        run_delay: Delay in seconds after run before checking fw switch status
        verbose: Whether to print verbose messages

    Returns:
        Tuple of (ports_succeeded, ports_failed) where ports_failed is {port: error_msg}
    """
    ports_succeeded = []
    ports_failed = {}

    def run_one_port(port):
        try:
            default_mode = 0
            status = run_firmware(port, default_mode, exit_on_error=False, verbose=verbose)
            if status != 1:
                return False, f"status={status}"

            time.sleep(run_delay)

            status = is_fw_switch_done(port, exit_on_error=False, verbose=verbose)
            if status != 1:
                return False, f"status={status}"

            return True, ""
        except Exception as e:
            return False, str(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=128) as executor:
        futures = {executor.submit(run_one_port, port): port for port in ports}
        for future in concurrent.futures.as_completed(futures):
            port = futures[future]
            try:
                success, error_msg = future.result()
                if success:
                    ports_succeeded.append(port)
                else:
                    ports_failed[port] = error_msg
            except Exception as e:
                if verbose:
                    click.echo("Error activating firmware for port {}: {}".format(port, str(e)))
                ports_failed[port] = str(e)

    return ports_succeeded, ports_failed


def commit_helper(ports, verbose):
    """Commit firmware on multiple ports in parallel

    Args:
        ports: List of port names to commit firmware on
        verbose: Whether to print verbose messages

    Returns:
        Tuple of (ports_succeeded, ports_failed) where ports_failed is {port: error_msg}
    """
    ports_succeeded = []
    ports_failed = {}

    def commit_one_port(port):
        try:
            status = commit_firmware(port, exit_on_error=False, verbose=verbose)
            if status != 1:
                return False, f"status={status}"
            return True, ""
        except Exception as e:
            return False, str(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=128) as executor:
        futures = {executor.submit(commit_one_port, port): port for port in ports}
        for future in concurrent.futures.as_completed(futures):
            port = futures[future]
            try:
                success, error_msg = future.result()
                if success:
                    ports_succeeded.append(port)
                else:
                    ports_failed[port] = error_msg
            except Exception as e:
                if verbose:
                    click.echo("Error committing firmware for port {}: {}".format(port, str(e)))
                ports_failed[port] = str(e)

    return ports_succeeded, ports_failed


def upgrade_helper(ports, port_to_firmware_map, run_delay, verbose, show_progress):
    """Helper function to upgrade firmware on multiple ports in three sequential phases:
       1. Download firmware on all ports in parallel
       2. Activate firmware on all ports in parallel
       3. Commit firmware on all ports in parallel

    Ports that fail in one phase are excluded from subsequent phases.

    Args:
        ports: List of port names to upgrade
        port_to_firmware_map: Dictionary mapping port names to firmware file paths
        run_delay: Delay after run before checking fw switch status
        verbose: Whether to print verbose messages
        show_progress: Whether to show individual progress bars

    Returns:
        Tuple of (ports_succeeded, ports_failed_status_info)
    """
    start_time = datetime.datetime.now()
    click.echo(f"CDB: Starting firmware upgrade: {start_time.strftime('%H:%M:%S')}")

    ports_succeeded = []
    ports_failed_status_info = {}

    # Phase 1: Download firmware on all ports in parallel
    click.echo(f"\n--- Phase 1/3: Downloading firmware for {len(ports)} port(s) ---")
    dl_succeeded, dl_failed_status_info = download_helper(ports, port_to_firmware_map, verbose, show_progress)
    # download_helper now emits dict failure entries; merge them directly.
    ports_failed_status_info.update(dl_failed_status_info)

    # Phase 2: Activate firmware on all successfully downloaded ports in parallel
    ports_to_run = get_interface_names_sorted_by_interface_number(dl_succeeded)
    if ports_to_run:
        click.echo(f"\n--- Phase 2/3: Activating firmware for {len(ports_to_run)} port(s) ---")
        run_succeeded, run_failed = run_helper(ports_to_run, run_delay, verbose)
        for port, error_msg in run_failed.items():
            ports_failed_status_info[port] = make_failure_entry('Activate', error_msg)
    else:
        run_succeeded = []
        click.echo("\n--- Phase 2/3: Skipped (no ports to activate) ---")

    # Phase 3: Commit firmware on all activated ports in parallel
    ports_to_commit = get_interface_names_sorted_by_interface_number(run_succeeded)
    if ports_to_commit:
        click.echo(f"\n--- Phase 3/3: Committing firmware for {len(ports_to_commit)} port(s) ---")
        commit_succeeded, commit_failed = commit_helper(ports_to_commit, verbose)
        for port, error_msg in commit_failed.items():
            ports_failed_status_info[port] = make_failure_entry('Commit', error_msg)
        ports_succeeded = commit_succeeded
    else:
        click.echo("\n--- Phase 3/3: Skipped (no ports to commit) ---")

    end_time = datetime.datetime.now()
    delta = end_time - start_time
    delta_seconds = int(delta.total_seconds())
    click.echo(
        f"\nCDB: Finished firmware upgrade: {end_time.strftime('%H:%M:%S')}. "
        f"Time taken: {delta_seconds} seconds")

    success_count = len(ports_succeeded)
    fail_count = len(ports_failed_status_info)
    click.echo("\nSucceeded: {}, Failed: {}\n".format(success_count, fail_count))
    return ports_succeeded, ports_failed_status_info


# 'upgrade' subcommand


@firmware.command()
@click.argument('port_name', required=False, default=None)
@click.argument('filepath', required=False, default=None)
@click.option(
    '-i', 'interface_list', multiple=True, type=(str, str),
    metavar='<INTERFACE_LIST> <FILEPATH>',
    help='Upgrade firmware for comma-separated interface list with specified '
         'firmware file. Each entity may be a single interface or an inclusive '
         'interface range (e.g., Ethernet16-80); tokens may be mixed. '
         'Example: -i Ethernet0,Ethernet4,Ethernet16-80 /path/to/firmware.bin')
@click.option('-p', 'vendor_pn_list', multiple=True, type=(str, str), metavar='<PART_NUMBER_LIST> <FILEPATH>',
              help='Upgrade firmware for all ports with specified vendor part number using specified firmware file')
def upgrade(port_name, filepath, interface_list, vendor_pn_list):
    """Upgrade firmware on the transceiver"""

    verbose = port_name is not None
    show_progress = port_name is not None

    # Check if single port is RJ45
    if port_name and is_port_type_rj45(port_name):
        click.echo("This functionality is not applicable for RJ45 port {}.".format(port_name))
        sys.exit(EXIT_FAIL)

    # Dictionary to map port to filepath
    present_sfp_ports = get_present_sfp_ports_names_list()
    port_to_firmware_map = {}

    # validate arguments
    if (port_name and not filepath) or (filepath and not port_name):
        click.echo("Error: port name and filepath are required together")
        sys.exit(ERROR_INVALID_ARGUMENTS)

    incapable_info = {}
    if port_name and filepath:
        if port_name not in present_sfp_ports:
            click.echo("Error: port '{}' is not present".format(port_name))
            sys.exit(ERROR_INVALID_PORT)
        port_to_firmware_map[port_name] = filepath
    else:
        transceiver_info_map, _, _ = get_transceiver_info_for_ports(present_sfp_ports, unique=True)
        port_to_firmware_map = build_port_to_firmware_map(
            interface_list, vendor_pn_list,
            present_sfp_ports, transceiver_info_map)

        if port_to_firmware_map:
            # Capability pre-check (bulk path only): exclude ports that
            # don't expose CMIS firmware management. Their failure
            # entries get folded into the final table so the operator
            # can still see why they were skipped.
            ports_matched_raw = get_interface_names_sorted_by_interface_number(
                list(port_to_firmware_map.keys()))
            capable_ports, incapable_info = filter_fw_mgmt_capable_ports(
                ports_matched_raw, verbose=verbose)
            for skipped in incapable_info:
                port_to_firmware_map.pop(skipped, None)

            if not capable_ports:
                click.echo("No ports support firmware management; nothing to upgrade.")
                display_fw_mgmt_failure_cause(incapable_info)
                sys.exit(EXIT_FAIL)

    if not port_to_firmware_map:
        click.echo("No ports to upgrade")
        sys.exit(EXIT_FAIL)

    ports_matched = get_interface_names_sorted_by_interface_number(list(port_to_firmware_map.keys()))
    click.echo(f"Upgrading image for {len(ports_matched)} transceiver(s)\n")

    click.echo("CDB: Firmware status before upgrade:")
    show_firmware_version(
        port_name, interface_filter=ports_matched,
        vendor_pn_filter=None, tabulate_output=True, verbose=verbose)
    click.echo()
    _, ports_failed_status_info = upgrade_helper(
        ports_matched, port_to_firmware_map, 5, verbose, show_progress)
    # Fold capability-skipped ports into the failure table.
    ports_failed_status_info.update(incapable_info)
    if len(ports_failed_status_info) > 0:
        display_fw_mgmt_failure_cause(ports_failed_status_info)
    click.echo("CDB: Firmware status after upgrade:")
    show_firmware_version(
        None, interface_filter=ports_matched, tabulate_output=True, verbose=verbose)

    if len(ports_failed_status_info) > 0:
        sys.exit(EXIT_FAIL)
    else:
        sys.exit(EXIT_SUCCESS)


def download_helper(ports, port_to_firmware_map, verbose, show_progress):
    """Helper function to download firmware on multiple ports in parallel

    Args:
        ports: List of port names to download firmware to
        port_to_firmware_map: Dictionary mapping port names to firmware file paths
        verbose: Whether to print verbose messages
        show_progress: Whether to show individual progress bars

    Returns:
        Tuple of (ports_succeeded, ports_failed_status_info)
    """
    start_time = datetime.datetime.now()
    click.echo(f"CDB: Starting firmware download: {start_time.strftime('%H:%M:%S')}")

    ports_succeeded = []
    ports_failed_status_info = {}

    progress_counters = {}
    manager = None

    # Status tracking for multi-port downloads
    port_status = {port: "Pending" for port in ports}
    status_lock = threading.Lock()
    download_progress = {}  # port -> (bytes_done, total_bytes, start_time)

    if show_progress:
        # Create enlighten manager for multiple progress bars
        manager = enlighten.get_manager()

        max_port_len = max(len(port) for port in ports) if ports else 0
        desc_min_width = max(max_port_len + 15, 27)

        for port in ports:
            bar_fmt = ('{desc:<%d}{percentage:3.0f}%%|{bar}| '
                       '{count:.2f}/{total:.2f} {unit} [{eta}]' % desc_min_width)
            counter = manager.counter(
                total=100,
                desc=f"{port}: Initializing",
                unit='B',
                leave=True,
                min_delta=0.1,
                series=[' ', '-', '#'],
                bar_format=bar_fmt
            )
            progress_counters[port] = counter
    else:
        if len(ports) > 1:
            manager = enlighten.get_manager()
            summary_counter = manager.counter(
                total=0,
                desc='',
                unit='',
                leave=True,
                bar_format='{desc}'
            )
            time_counter = manager.counter(
                total=0,
                desc='',
                unit='',
                leave=True,
                bar_format='{desc}'
            )

            _last_time_update = [0]
            _smoothed_remaining = [0]  # EMA of remaining time estimate
            _rate_snapshots = {}  # port -> (time, bytes_done) for windowed rate calc

            def update_summary():
                with status_lock:
                    pending = sum(1 for s in port_status.values() if s == "Pending")
                    downloading = sum(1 for s in port_status.values() if s == "Downloading Firmware")
                    succeeded = sum(1 for s in port_status.values() if s == "Succeeded")
                    failed = sum(1 for s in port_status.values() if s == "Failed")

                    summary_counter.desc = (
                        f"Progress: Not Started({pending}), "
                        f"Downloading FW({downloading}), "
                        f"Succeeded({succeeded}), Failed({failed})")
                    summary_counter.update(0, force=True)

                    now = time.time()
                    # Only throttle updates if there are still active downloads
                    # Always update when downloads complete (downloading == 0)
                    if downloading > 0 and now - _last_time_update[0] < 5:
                        return
                    _last_time_update[0] = now

                    max_remaining = 0
                    for port in list(download_progress.keys()):
                        if port_status.get(port) == "Downloading Firmware":
                            done, total, start = download_progress[port]
                            elapsed = now - start
                            if done > 0 and total > 0 and elapsed >= 15:
                                # Use windowed rate: compare against a snapshot from ~30s ago
                                # to avoid including CDB setup time in the rate
                                snap_time, snap_done = _rate_snapshots.get(port, (start, 0))
                                window = now - snap_time
                                window_bytes = done - snap_done
                                if window >= 30 and window_bytes > 0:
                                    rate = window_bytes / window
                                else:
                                    # Not enough window history yet, use overall rate
                                    rate = done / elapsed
                                remaining_secs = (total - done) / rate
                                max_remaining = max(max_remaining, remaining_secs)

                                # Update snapshot if it's older than 30s
                                if window >= 30:
                                    _rate_snapshots[port] = (now, done)
                            elif done > 0 and port not in _rate_snapshots:
                                # Seed the snapshot once data starts flowing
                                _rate_snapshots[port] = (now, done)

                    # Clean up snapshots for ports no longer downloading
                    for port in list(_rate_snapshots.keys()):
                        if port_status.get(port) != "Downloading Firmware":
                            del _rate_snapshots[port]

                    if downloading > 0 and max_remaining > 0:
                        # Exponential smoothing to reduce variance
                        if _smoothed_remaining[0] > 0:
                            # Asymmetric alpha: converge faster downward than upward
                            alpha = 0.4 if max_remaining < _smoothed_remaining[0] else 0.15
                            _smoothed_remaining[0] = alpha * max_remaining + (1 - alpha) * _smoothed_remaining[0]
                        else:
                            _smoothed_remaining[0] = max_remaining

                        display_remaining = _smoothed_remaining[0]
                        minutes, seconds = divmod(int(display_remaining), 60)
                        if minutes > 0:
                            time_counter.desc = f"Remaining Time: {minutes} minutes {seconds} seconds"
                        else:
                            time_counter.desc = f"Remaining Time: {seconds} seconds"
                    elif downloading > 0:
                        # Still downloading but can't estimate yet
                        time_counter.desc = "Remaining Time: estimating..."
                    else:
                        # All downloads completed or none in progress
                        if succeeded > 0 or failed > 0:
                            time_counter.desc = "Remaining Time: 0 seconds"
                        else:
                            time_counter.desc = ""
                        _smoothed_remaining[0] = 0
                    time_counter.update(0, force=True)

    def download_one_port(port, filepath):
        """Download firmware for a single port, returning (success, error)"""
        use_summary = not show_progress and len(ports) > 1
        try:
            if use_summary:
                with status_lock:
                    port_status[port] = "Downloading Firmware"
                update_summary()

            status = download_firmware(
                port, filepath,
                exit_on_error=False,
                verbose=verbose,
                show_progress=show_progress,
                progress_counter=progress_counters.get(port),
                download_progress=download_progress if use_summary else None,
                update_summary_callback=update_summary if use_summary else None,
            )

            if status == 1:
                if use_summary:
                    with status_lock:
                        port_status[port] = "Succeeded"
                    update_summary()
                return True, ""
            else:
                if use_summary:
                    with status_lock:
                        port_status[port] = "Failed"
                    update_summary()
                return False, f"status={status}"
        except Exception as e:
            if use_summary:
                with status_lock:
                    port_status[port] = "Failed"
                update_summary()
            return False, str(e)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=128) as executor:
            futures = {
                executor.submit(download_one_port, port, port_to_firmware_map[port]): port
                for port in ports
            }

            for future in concurrent.futures.as_completed(futures):
                port = futures[future]
                try:
                    success, error_msg = future.result()
                    if success:
                        ports_succeeded.append(port)
                    else:
                        ports_failed_status_info[port] = make_failure_entry('Download', error_msg)
                except Exception as e:
                    if verbose:
                        click.echo("Error downloading firmware for port {}: {}".format(port, str(e)))
                    ports_failed_status_info[port] = make_failure_entry('Download', str(e))
                    if port in progress_counters:
                        progress_counters[port].desc = f"{port}: Error - {str(e)}"
    finally:
        if manager:
            manager.stop()

    end_time = datetime.datetime.now()
    delta = end_time - start_time
    delta_seconds = int(delta.total_seconds())
    click.echo(f"CDB: Finished firmware download: {end_time.strftime('%H:%M:%S')}. Time taken: {delta_seconds} seconds")

    success_count = len(ports_succeeded)
    fail_count = len(ports_failed_status_info)
    click.echo("\nSucceeded: {}, Failed: {}\n".format(success_count, fail_count))
    return ports_succeeded, ports_failed_status_info


# 'download' subcommand
@firmware.command()
@click.argument('port_name', required=False, default=None)
@click.argument('filepath', required=False, default=None)
@click.option(
    '-i', 'interface_list', multiple=True, type=(str, str),
    metavar='<INTERFACE_LIST> <FILEPATH>',
    help='Download firmware for comma-separated interface list with specified '
         'firmware file. Each entity may be a single interface or an inclusive '
         'interface range (e.g., Ethernet16-80); tokens may be mixed. '
         'Example: -i Ethernet0,Ethernet4,Ethernet16-80 /path/to/firmware.bin')
@click.option('-p', 'vendor_pn_list', multiple=True, type=(str, str), metavar='<PART_NUMBER_LIST> <FILEPATH>',
              help='Download firmware for all ports with specified vendor part number using specified firmware file')
def download(port_name, filepath, interface_list, vendor_pn_list):
    """Download firmware on the transceiver"""

    verbose = port_name is not None
    show_progress = port_name is not None

    # Check if single port is RJ45
    if port_name and is_port_type_rj45(port_name):
        click.echo("This functionality is not applicable for RJ45 port {}.".format(port_name))
        sys.exit(EXIT_FAIL)

    present_sfp_ports = get_present_sfp_ports_names_list()
    port_to_firmware_map = {}

    # validate arguments
    if (port_name and not filepath) or (filepath and not port_name):
        click.echo("Error: port name and filepath are required together")
        sys.exit(ERROR_INVALID_ARGUMENTS)

    if port_name and filepath:
        if port_name not in present_sfp_ports:
            click.echo("Error: port '{}' is not present".format(port_name))
            sys.exit(ERROR_INVALID_PORT)
        port_to_firmware_map[port_name] = filepath
    else:
        transceiver_info_map, _, _ = get_transceiver_info_for_ports(present_sfp_ports, unique=True)
        port_to_firmware_map = build_port_to_firmware_map(
            interface_list, vendor_pn_list,
            present_sfp_ports, transceiver_info_map)

    if not port_to_firmware_map:
        click.echo("No ports to download firmware to")
        sys.exit(EXIT_FAIL)

    if len(port_to_firmware_map) == 1 and port_name:
        # Single port legacy path
        single_port = list(port_to_firmware_map.keys())[0]

        if is_port_type_rj45(single_port):
            click.echo("This functionality is not applicable for RJ45 port {}.".format(single_port))
            sys.exit(EXIT_FAIL)

        if not is_sfp_present(single_port):
            click.echo("{}: SFP EEPROM not detected\n".format(single_port))
            sys.exit(EXIT_FAIL)

        start = time.time()
        status = download_firmware(single_port, port_to_firmware_map[single_port])
        if status == 1:
            click.echo("Firmware download complete success")
        else:
            click.echo("Firmware download complete failed! status = {}".format(status))
            sys.exit(EXIT_FAIL)
        end = time.time()
        click.echo("Total download Time: {}".format(str(datetime.timedelta(seconds=end-start))))
    else:
        # Multi-port parallel path
        ports_matched_raw = get_interface_names_sorted_by_interface_number(list(port_to_firmware_map.keys()))

        # Capability pre-check: exclude ports that don't expose CMIS
        # firmware management. Their reasons get folded into the final
        # failure table so the operator sees why they were skipped.
        capable_ports, incapable_info = filter_fw_mgmt_capable_ports(
            ports_matched_raw, verbose=verbose)
        for skipped in incapable_info:
            port_to_firmware_map.pop(skipped, None)

        if not capable_ports:
            click.echo("No ports support firmware management; nothing to download.")
            if incapable_info:
                display_fw_mgmt_failure_cause(incapable_info)
            sys.exit(EXIT_FAIL)

        ports_matched = get_interface_names_sorted_by_interface_number(capable_ports)
        click.echo(f"Downloading firmware for {len(ports_matched)} transceiver(s)\n")

        click.echo("CDB: Firmware status before download:")
        show_firmware_version(
            None, interface_filter=ports_matched,
            vendor_pn_filter=None, tabulate_output=True, verbose=verbose)
        click.echo()

        _, ports_failed_status_info = download_helper(ports_matched, port_to_firmware_map, verbose, show_progress)
        ports_failed_status_info.update(incapable_info)
        if len(ports_failed_status_info) > 0:
            display_fw_mgmt_failure_cause(ports_failed_status_info)

        click.echo("CDB: Firmware status after download:")
        show_firmware_version(
            None, interface_filter=ports_matched,
            vendor_pn_filter=None, tabulate_output=True, verbose=verbose)

        if len(ports_failed_status_info) > 0:
            sys.exit(EXIT_FAIL)
        else:
            sys.exit(EXIT_SUCCESS)


# 'unlock' subcommand
@firmware.command()
@click.argument('port_name', required=True, default=None)
@click.option('--password', type=click.INT, help="Password in integer\n")
def unlock(port_name, password):
    """Unlock the firmware download feature via CDB host password"""
    physical_port = logical_port_to_physical_port_index(port_name)
    sfp = platform_chassis.get_sfp(physical_port)

    if is_port_type_rj45(port_name):
        click.echo("This functionality is not applicable for RJ45 port {}.".format(port_name))
        sys.exit(EXIT_FAIL)

    if not is_sfp_present(port_name):
       click.echo("{}: SFP EEPROM not detected\n".format(port_name))
       sys.exit(EXIT_FAIL)

    try:
        api = sfp.get_xcvr_api()
    except NotImplementedError:
        click.echo("This functionality is currently not implemented for this platform")
        sys.exit(ERROR_NOT_IMPLEMENTED)

    if password is None:
        password = CDB_DEFAULT_HOST_PASSWORD
    try:
        status = api.cdb_enter_host_password(int(password))
    except NotImplementedError:
        click.echo("This functionality is not applicable for this transceiver")
        sys.exit(EXIT_FAIL)

    if status == 1:
        click.echo("CDB: Host password accepted")
    else:
        click.echo("CDB: Host password NOT accepted! status = {}".format(status))

# 'version' subcommand
@cli.command()
def version():
    """Display version info"""
    click.echo("sfputil version {0}".format(VERSION))

# 'target' subcommand
@firmware.command()
@click.argument('port_name', required=True, default=None)
@click.argument('target', type=click.IntRange(0, 2), required=True, default=None)
def target(port_name, target):
    """Select target end for firmware download 0-(local) \n
                                               1-(remote-A) \n
                                               2-(remote-B)
    """
    physical_port = logical_port_to_physical_port_index(port_name)
    sfp = platform_chassis.get_sfp(physical_port)

    if is_port_type_rj45(port_name):
        click.echo("{}: This functionality is not applicable for RJ45 port".format(port_name))
        sys.exit(EXIT_FAIL)

    if not is_sfp_present(port_name):
       click.echo("{}: SFP EEPROM not detected\n".format(port_name))
       sys.exit(EXIT_FAIL)

    try:
        api = sfp.get_xcvr_api()
    except NotImplementedError:
        click.echo("{}: This functionality is currently not implemented for this module".format(port_name))
        sys.exit(ERROR_NOT_IMPLEMENTED)

    try:
        status = api.set_firmware_download_target_end(target)
    except AttributeError:
        click.echo("{}: This functionality is not applicable for this module".format(port_name))
        sys.exit(ERROR_NOT_IMPLEMENTED)

    if status:
        click.echo("Target Mode set to {}". format(target))
    else:
        click.echo("Target Mode set failed!")
        sys.exit(EXIT_FAIL)


# 'read-eeprom' subcommand
@cli.command()
@click.option('-p', '--port', metavar='<logical_port_name>', help="Logical port name", required=True)
@click.option('-n', '--page', metavar='<page>',
              help="EEPROM page number in decimal, hex (with 0x prefix) or octal (with 0o prefix)",
              required=True)
@click.option('-o', '--offset', metavar='<offset>', type=click.IntRange(0, MAX_EEPROM_OFFSET), help="EEPROM offset within the page", required=True)
@click.option('-s', '--size', metavar='<size>', type=click.IntRange(1, MAX_EEPROM_OFFSET + 1), help="Size of byte to be read", required=True)
@click.option('--no-format', is_flag=True, help="Display non formatted data")
@click.option('--wire-addr', help="Wire address of sff8472")
def read_eeprom(port, page, offset, size, no_format, wire_addr):
    """Read SFP EEPROM data
    """
    try:
        if platform_sfputil.is_logical_port(port) == 0:
            click.echo("Error: invalid port {}".format(port))
            print_all_valid_port_values()
            sys.exit(ERROR_INVALID_PORT)

        if is_port_type_rj45(port):
            click.echo("This functionality is not applicable for RJ45 port {}.".format(port))
            sys.exit(EXIT_FAIL)

        physical_port = logical_port_to_physical_port_index(port)
        sfp = platform_chassis.get_sfp(physical_port)
        if not sfp.get_presence():
            click.echo("{}: SFP EEPROM not detected\n".format(port))
            sys.exit(EXIT_FAIL)

        from sonic_platform_base.sonic_xcvr.api.public import sff8472
        api = sfp.get_xcvr_api()
        if api is None:
            click.echo('Error: SFP EEPROM not detected!')
        if page is not None:
            page = validate_eeprom_page(page)
        if not isinstance(api, sff8472.Sff8472Api):
            overall_offset = get_overall_offset_general(api, page, offset, size)
        else:
            overall_offset = get_overall_offset_sff8472(api, page, offset, size, wire_addr)
        return_code, output = eeprom_dump_general(physical_port, page, overall_offset, size, offset, no_format)
        if return_code != 0:
            click.echo("Error: Failed to read EEPROM!")
            sys.exit(return_code)
        click.echo(output)
    except NotImplementedError:
        click.echo("This functionality is currently not implemented for this platform")
        sys.exit(ERROR_NOT_IMPLEMENTED)
    except ValueError as e:
        click.echo(f"Error: {e}")
        sys.exit(EXIT_FAIL)


# 'write-eeprom' subcommand
@cli.command()
@click.option('-p', '--port', metavar='<logical_port_name>', help="Logical port name", required=True)
@click.option('-n', '--page', metavar='<page>',
              help="EEPROM page number in decimal, hex (with 0x prefix) or octal (with 0o prefix)",
              required=True)
@click.option('-o', '--offset', metavar='<offset>', type=click.IntRange(0, MAX_EEPROM_OFFSET), help="EEPROM offset within the page", required=True)
@click.option('-d', '--data', metavar='<data>', help="Hex string EEPROM data", required=True)
@click.option('--wire-addr', help="Wire address of sff8472")
@click.option('--verify', is_flag=True, help="Verify the data by reading back")
def write_eeprom(port, page, offset, data, wire_addr, verify):
    """Write SFP EEPROM data"""
    try:
        if platform_sfputil.is_logical_port(port) == 0:
            click.echo("Error: invalid port {}".format(port))
            print_all_valid_port_values()
            sys.exit(ERROR_INVALID_PORT)

        if is_port_type_rj45(port):
            click.echo("This functionality is not applicable for RJ45 port {}.".format(port))
            sys.exit(EXIT_FAIL)

        physical_port = logical_port_to_physical_port_index(port)
        sfp = platform_chassis.get_sfp(physical_port)
        if not sfp.get_presence():
            click.echo("{}: SFP EEPROM not detected\n".format(port))
            sys.exit(EXIT_FAIL)

        try:
            bytes = bytearray.fromhex(data)
        except ValueError:
            click.echo("Error: Data must be a hex string of even length!")
            sys.exit(EXIT_FAIL)

        from sonic_platform_base.sonic_xcvr.api.public import sff8472
        api = sfp.get_xcvr_api()
        if api is None:
            click.echo('Error: SFP EEPROM not detected!')
            sys.exit(EXIT_FAIL)
        if page is not None:
            page = validate_eeprom_page(page)
        if not isinstance(api, sff8472.Sff8472Api):
            overall_offset = get_overall_offset_general(api, page, offset, len(bytes))
        else:
            overall_offset = get_overall_offset_sff8472(api, page, offset, len(bytes), wire_addr)
        success = sfp.write_eeprom(overall_offset, len(bytes), bytes)
        if not success:
            click.echo("Error: Failed to write EEPROM!")
            sys.exit(ERROR_NOT_IMPLEMENTED)
        if verify:
            read_data = sfp.read_eeprom(overall_offset, len(bytes))
            if read_data != bytes:
                click.echo(f"Error: Write data failed! Write: {''.join('{:02x}'.format(x) for x in bytes)}, read: {''.join('{:02x}'.format(x) for x in read_data)}")
                sys.exit(EXIT_FAIL)
    except NotImplementedError:
        click.echo("This functionality is currently not implemented for this platform")
        sys.exit(ERROR_NOT_IMPLEMENTED)
    except ValueError as e:
        click.echo("Error: {}".format(e))
        sys.exit(EXIT_FAIL)


def get_overall_offset_general(api, page, offset, size):
    """
    Validate input parameter page, offset, size and translate them to overall offset
    Args:
        api: cable API object
        page: module EEPROM page number.
        offset: module EEPROM page offset.
        size: number bytes of the data to be read/write

    Returns:
        The overall offset
    """
    if api.is_flat_memory():
        if page != 0:
            raise ValueError(f'Invalid page number {page:x}h, only page 0 is supported')

    if page != 0:
        if offset < MIN_OFFSET_FOR_NON_PAGE0:
            raise ValueError(f'Invalid offset {offset} for page {page:x}h, valid range: [80h, FFh]')

    if size + offset - 1 > MAX_EEPROM_OFFSET:
        raise ValueError(f'Invalid size {size}, valid range: [1, {255 - offset + 1}]')

    return page * PAGE_SIZE + offset


def get_overall_offset_sff8472(api, page, offset, size, wire_addr):
    """
        Validate input parameter page, offset, size, wire_addr and translate them to overall offset
        Args:
            api: cable API object
            page: module EEPROM page number.
            offset: module EEPROM page offset.
            size: number bytes of the data to be read/write
            wire_addr: case-insensitive wire address string. Only valid for sff8472, a0h or a2h.

        Returns:
            The overall offset
        """
    if not wire_addr:
        raise ValueError("Invalid wire address for sff8472, must a0h or a2h")

    is_active_cable = not api.is_copper()
    valid_wire_address = ('a0h', 'a2h') if is_active_cable else ('a0h',)
    wire_addr = wire_addr.lower()
    if wire_addr not in valid_wire_address:
        raise ValueError(f"Invalid wire address {wire_addr} for sff8472, must be {' or '.join(valid_wire_address)}")

    if wire_addr == 'a0h':
        if page != 0:
            raise ValueError(f'Invalid page number {page} for wire address {wire_addr}, only page 0 is supported')
        max_offset = MAX_OFFSET_FOR_A0H_UPPER_PAGE if is_active_cable else MAX_OFFSET_FOR_A0H_LOWER_PAGE
        if offset > max_offset:
            raise ValueError(f'Invalid offset {offset} for wire address {wire_addr}, valid range: [0, {max_offset}]')
        if size + offset - 1 > max_offset:
            raise ValueError(
                f'Invalid size {size} for wire address {wire_addr}, valid range: [1, {max_offset - offset + 1}]')
        return offset
    else:
        if size + offset - 1 > MAX_OFFSET_FOR_A2H:
            raise ValueError(f'Invalid size {size} for wire address {wire_addr}, valid range: [1, {255 - offset + 1}]')
        return page * PAGE_SIZE + offset + PAGE_SIZE_FOR_A0H


if __name__ == '__main__':
    cli()
