#!/usr/bin/env python3
"""
SONiC Snake Helper Functions

This module contains helper functions for the SONiC Snake traffic generator utility.

Function Categories:
1. Platform Detection
2. Utility Functions
3. BCM Command Execution
4. Interface Status and Information
5. VLAN Information and Validation
6. BCM Port Mapping
7. Interface Validation
8. BCM Hardware Detection
9. Traffic Generation and Statistics
10. Traffic Control and Algorithms
"""
import time
import subprocess
import json
from sonic_snake.logger import log

# Import database access for VLAN information
try:
    from utilities_common.db import Db
except ImportError:
    Db = None

# Global variable for total data size to send in random payload mode
# Set this value to control how much data is sent (in bytes)
# The function will calculate how many packets to send based on packet size
RANDOM_PAYLOAD_TOTAL_DATA_SIZE = 2097152  # Default: 2 MB (2 * 1024 * 1024 bytes)


def log_info(message):
    """Log info message to syslog and console (based on verbosity)"""
    log.info(message)


def log_error(message):
    """Log error message to syslog and console (based on verbosity)"""
    log.error(message)


def log_warning(message):
    """Log warning message to syslog and console (based on verbosity)"""
    log.warning(message)


# =============================================================================
# Platform Detection
# =============================================================================

# =============================================================================
# Utility Functions
# =============================================================================

def parse_speed_to_gbps(speed_str):
    """
    Parse speed string to Gbps value.

    Supports all common speed formats and converts to Gbps:
    - Mbps: '1000M', '10000M' -> converted to Gbps (1000M = 1G)
    - Gbps: '100G', '40G', '25G' -> returned as-is
    - Tbps: '1T', '10T' -> converted to Gbps (1T = 1000G)
    - Raw numbers: '100000', '40000' -> assumed Mbps, converted to Gbps
    - Special: 'N/A', empty strings -> 0

    Args:
        speed_str (str): Speed string (e.g., "100G", "1000M", "1T", "40000", "N/A")

    Returns:
        int: Speed in Gbps, or 0 if cannot parse
    """
    try:
        if not speed_str or speed_str == 'N/A':
            return 0

        # Convert to uppercase for consistent processing
        speed_str = str(speed_str).upper().strip()

        # Handle different suffixes
        if speed_str.endswith('T'):
            # Terabits per second -> Gigabits per second (multiply by 1000)
            return int(speed_str[:-1]) * 1000
        elif speed_str.endswith('G'):
            # Gigabits per second -> return as-is
            return int(speed_str[:-1])
        elif speed_str.endswith('M'):
            # Megabits per second -> Gigabits per second (divide by 1000)
            return int(speed_str[:-1]) // 1000
        else:
            # No suffix - assume raw Mbps value, convert to Gbps
            return int(speed_str) // 1000

    except (ValueError, TypeError, AttributeError):
        return 0


def parse_lanes_string(lanes_str):
    """Parse lanes string to extract lane numbers"""
    try:
        if ',' in lanes_str:
            return [int(x.strip()) for x in lanes_str.split(',')]
        elif '-' in lanes_str:
            start, end = lanes_str.split('-')
            return list(range(int(start.strip()), int(end.strip()) + 1))
        else:
            return [int(lanes_str.strip())]
    except (ValueError, AttributeError):
        return []


def reset_counters(interfaces):
    """
    Reset interface counters using portstat command.

    Args:
        interfaces (list): List of interface names to reset counters for

    Returns:
        bool: True if successful, False if failed
    """
    try:
        import subprocess
        # Ensure interfaces is a list
        if not isinstance(interfaces, list):
            raise TypeError("interfaces must be a list of interface names")

        # Create comma-separated interface names
        interface_names = ','.join(interfaces)

        # Use portstat -c -i to clear counters for specified interfaces
        result = subprocess.run(
            ['portstat', '-c', '-i', interface_names],
            capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            return True
        else:
            log_error(f"Error resetting counters: {result.stderr}")
            return False

    except Exception as e:
        log_error(f"Error resetting interface counters: {str(e)}")
        return False


# =============================================================================
# BCM Command Execution
# =============================================================================

def run_bcm_command(bcm_command, timeout=30):
    """
    Execute a BCM command using bcmcmd.

    Note: This uses hardcoded 'bcmcmd' command which works on TH5/TH6 platforms.
          For TD3 platforms that require 'docker exec syncd bcmcmd',
          use the platform-specific version in base.py instead.

    Args:
        bcm_command (str): BCM command string (e.g., "show portmap", "ps")
        timeout (int): Seconds before the command is killed. Defaults to 30
                       (XGS callers unchanged); DNX cint/diag can be slow and
                       passes a longer value.

    Returns:
        dict: Result with success, stdout, stderr
              {
                  'success': bool,
                  'stdout': str,
                  'stderr': str
              }
    """
    try:
        import subprocess
        # Execute bcmcmd with the provided command
        cmd = ['bcmcmd', bcm_command]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'stdout': '',
            'stderr': f'Command timed out after {timeout} seconds'
        }
    except Exception as e:
        return {
            'success': False,
            'stdout': '',
            'stderr': f'Command execution failed: {str(e)}'
        }


# =============================================================================
# SONiC Command Execution
# =============================================================================

def run_sonic_command(sonic_command_args):
    """
    Execute a SONiC CLI command

    Args:
        sonic_command_args: List of command arguments (e.g., ['config', 'vlan', 'member', 'add', '100', 'Ethernet0'])

    Returns:
        dict: Result with success, stdout, stderr
              {
                  'success': bool,
                  'stdout': str,
                  'stderr': str
              }
    """
    try:
        # Execute SONiC command with sudo if it's a config command
        if sonic_command_args and sonic_command_args[0] == 'config':
            cmd = ['sudo'] + sonic_command_args
        else:
            cmd = sonic_command_args

        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=30)
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'stdout': '',
            'stderr': 'Command timed out after 30 seconds'
        }
    except Exception as e:
        return {
            'success': False,
            'stdout': '',
            'stderr': f'Command execution failed: {str(e)}'
        }


# =============================================================================
# Interface Status and Information
# =============================================================================

def get_interface_status():
    """
    Get interface status information using SONiC's intfutil command.

    Returns:
        dict: Interface status data with interface names as keys
    """
    try:
        # Run intfutil status --json command for better parsing
        result = subprocess.run(['intfutil', '-c', 'status', '--json'], capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            log_error(f"Error running intfutil status: {result.stderr}")
            return {}

        # Parse JSON output
        interface_data = json.loads(result.stdout)

        # Convert to our expected format
        interface_dict = {}
        for interface_name, interface_info in interface_data.items():
            # Parse lanes string to list of integers
            lanes_str = interface_info.get('Lanes', '')
            lanes_list = parse_lanes_string(lanes_str)

            interface_dict[interface_name] = {
                "Lanes": lanes_list,
                "Speed": interface_info.get('Speed') if interface_info.get('Speed') != 'N/A' else None,
                "MTU": interface_info.get('MTU') if interface_info.get('MTU') != 'N/A' else None,
                "FEC": interface_info.get('FEC') if interface_info.get('FEC') != 'N/A' else None,
                "Alias": interface_info.get('Alias') if interface_info.get('Alias') != 'N/A' else None,
                "Vlan": interface_info.get('Vlan') if interface_info.get('Vlan') != 'N/A' else None,
                "Oper": interface_info.get('Oper') if interface_info.get('Oper') != 'N/A' else None,
                "Admin": interface_info.get('Admin') if interface_info.get('Admin') != 'N/A' else None,
                "Type": interface_info.get('Type') if interface_info.get('Type') != 'N/A' else None,
                "Asym PFC": interface_info.get('Asym PFC') if interface_info.get('Asym PFC') != 'N/A' else None
            }

        return interface_dict

    except subprocess.CalledProcessError as e:
        log_error(f"Error running intfutil command: {e}")
        return {}
    except json.JSONDecodeError as e:
        log_error(f"Error parsing JSON output: {e}")
        return {}
    except Exception as e:
        log_error(f"Error getting interface status: {e}")
        return {}


# =============================================================================
# VLAN Information
# =============================================================================

def get_vlan_facts():
    """
    Get VLAN facts in both interface-centric and VLAN-centric formats.

    Returns:
        dict: Dictionary containing both VLAN data formats:
              {
                  "interface_centric": {
                      "Ethernet0": {
                          "vlan_names": ["vlan1000", "vlan2000"],
                          "vlan_ids": ["1000", "2000"],
                          "tagging_modes": ["untagged", "tagged"]
                      },
                      "Ethernet2": {
                          "vlan_names": ["vlan1000"],
                          "vlan_ids": ["1000"],
                          "tagging_modes": ["untagged"]
                      }
                  },
                  "vlan_centric": {
                      "1000": {
                          "members": ["Ethernet0", "Ethernet2"],
                          "tagged_members": ["Ethernet0"],
                          "untagged_members": ["Ethernet2"]
                      },
                      "2000": {
                          "members": ["Ethernet0"],
                          "tagged_members": [],
                          "untagged_members": ["Ethernet0"]
                      }
                  }
              }
    """
    try:
        if Db is None:
            log_error("Database access not available - utilities_common.db could not be imported")
            return {"interface_centric": {}, "vlan_centric": {}}

        db = Db()

        # Try multiple database sources to get current VLAN state
        # First try APPL_DB which has running state, then fall back to CONFIG_DB
        vlan_data = {}
        vlan_member_data = {}

        db.cfgdb.connect()
        vlan_data = db.cfgdb.get_table('VLAN')
        vlan_member_data = db.cfgdb.get_table('VLAN_MEMBER')

        interface_vlan_map = {}
        vlan_centric_map = {}

        # First, initialize all VLANs from vlan_data in the vlan_centric_map
        # This ensures that even empty VLANs (with no members) are included
        for vlan_name, vlan_config in vlan_data.items():
            vlan_id = vlan_config.get('vlanid', vlan_name.replace('Vlan', ''))
            if vlan_id not in vlan_centric_map:
                vlan_centric_map[vlan_id] = {
                    "members": [],
                    "tagged_members": [],
                    "untagged_members": []
                }

        # Create mapping from interface to VLANs (interface can have multiple VLANs)
        for (vlan_name, interface), member_config in vlan_member_data.items():
            vlan_config = vlan_data.get(vlan_name, {})
            vlan_id = vlan_config.get('vlanid', vlan_name.replace('Vlan', ''))
            tagging_mode = member_config.get('tagging_mode', 'untagged')

            # Initialize interface entry if not exists
            if interface not in interface_vlan_map:
                interface_vlan_map[interface] = {
                    "vlan_names": [],
                    "vlan_ids": [],
                    "tagging_modes": []
                }

            # Add VLAN to the interface's VLAN list
            interface_vlan_map[interface]["vlan_names"].append(vlan_name.lower())
            interface_vlan_map[interface]["vlan_ids"].append(vlan_id)
            interface_vlan_map[interface]["tagging_modes"].append(tagging_mode)

            # Build VLAN-centric view (VLAN already initialized above)
            vlan_centric_map[vlan_id]["members"].append(interface)
            if tagging_mode.lower() == 'tagged':
                vlan_centric_map[vlan_id]["tagged_members"].append(interface)
            else:
                vlan_centric_map[vlan_id]["untagged_members"].append(interface)

        # Return both formats in a single dict
        return {
            "interface_centric": interface_vlan_map,
            "vlan_centric": vlan_centric_map
        }

    except Exception as e:
        log_error(f"Error getting VLAN facts: {str(e)}")
        return {"interface_centric": {}, "vlan_centric": {}}


# =============================================================================
# BCM Port Mapping
# =============================================================================


def get_port_mapping(platform):
    """
    Combine interface status, VLAN facts, and portmap data for complete port information

    The BCM port ('Pbm') is derived by the platform: the base class implements
    the XGS 'show portmap' lane-matching, and chip families that map ports
    differently (e.g. DNX) override get_pbm_lookup()/get_pbm().

    Args:
        platform: Platform object providing get_pbm_lookup()/get_pbm().

    Returns:
        dict: Combined mapping with interface names as keys and detailed info as values
              Format: {
                  "Ethernet0": {
                      "Lanes": [192, 193, 194, 195],
                      "Speed": "40G",
                      "Admin": "up",
                      "Oper": "down",
                      "Pbm": "xe0",
                      "Vlan_ids": [1000]
                  }
              }
    """
    try:
        # Get all data sources
        interface_status = get_interface_status()
        vlan_facts = get_vlan_facts()

        # Per-platform BCM-port lookup (XGS: the 'show portmap' lane map)
        pbm_lookup = platform.get_pbm_lookup()

        combined_mapping = {}

        # Process each interface from interface_status (primary source)
        for interface_name, interface_data in interface_status.items():
            # Extract basic interface information
            combined_info = {
                'Lanes': interface_data.get('Lanes', []),
                'Speed': interface_data.get('Speed'),
                'Admin': interface_data.get('Admin'),
                'Oper': interface_data.get('Oper'),
                'Pbm': None,
                'Vlan_ids': []
            }

            # Derive the BCM port. Platform override point (DNX derives it
            # from the interface index; XGS matches lanes to the PBM map).
            combined_info['Pbm'] = platform.get_pbm(
                interface_name, interface_data, pbm_lookup)

            # Add VLAN information using our existing vlan_facts function
            interface_vlan_map = vlan_facts.get('interface_centric', {})
            if interface_name in interface_vlan_map:
                vlan_info = interface_vlan_map[interface_name]
                # Convert string VLAN IDs to integers
                combined_info['Vlan_ids'] = [int(vid) for vid in vlan_info.get('vlan_ids', [])]

            combined_mapping[interface_name] = combined_info

        return combined_mapping

    except Exception as e:
        log_error(f"Error creating combined port mapping: {e}")
        return {}


# =============================================================================
# Interface Validation Functions
# =============================================================================

# =============================================================================
# VLAN Validation Functions
# =============================================================================

def create_vlan(vlan_id):
    """
    Create a VLAN using native SONiC command.

    Args:
        vlan_id (int): VLAN ID to create

    Returns:
        bool: True if successful or if VLAN already exists, False otherwise
    """
    try:
        cmd = ['config', 'vlan', 'add', str(vlan_id)]

        log_info(f"Creating VLAN {vlan_id}...")
        result = run_sonic_command(cmd)

        if result['success']:
            log_info(f"✓ Successfully created VLAN {vlan_id}")
            return True
        else:
            # Check if error is because VLAN already exists (this is OK)
            error_msg = result['stderr'].lower()
            if 'already exist' in error_msg or 'already created' in error_msg:
                log_info(f"  VLAN {vlan_id} already exists (skipping)")
                return True  # Return True since this is not a failure condition
            else:
                log_error(f"Failed to create VLAN {vlan_id}: {result['stderr']}")
                return False

    except Exception as e:
        log_error(f"Error creating VLAN {vlan_id}: {str(e)}")
        return False


def delete_vlan(vlan_id):
    """
    Delete a VLAN using native SONiC command.

    Args:
        vlan_id (int): VLAN ID to delete

    Returns:
        bool: True if the VLAN is gone (deleted, or was already absent),
              False if it is still present.
    """
    try:
        cmd = ['config', 'vlan', 'del', str(vlan_id)]

        log_info(f"Deleting VLAN {vlan_id}...")
        result = run_sonic_command(cmd)

        if result['success']:
            log_info(f"✓ Successfully deleted VLAN {vlan_id}")
            return True

        error_msg = result['stderr'].lower()
        if 'does not exist' in error_msg:
            log_info(f"  VLAN {vlan_id} does not exist (skipping)")
            return True  # Return True since this is not a failure condition
        if 'not be removed' in error_msg:
            # SONiC refuses the delete while the VLAN still has members, an IP,
            # a VXLAN mapping or a DHCP relay binding - none of which are ours.
            log_warning(
                f"VLAN {vlan_id} is still referenced by other config, "
                f"leaving it in place. {result['stderr'].strip()}")
            return False
        log_error(f"Failed to delete VLAN {vlan_id}: {result['stderr']}")
        return False

    except Exception as e:
        log_error(f"Error deleting VLAN {vlan_id}: {str(e)}")
        return False


def validate_vlan_empty(vlan_id, auto_create=False):
    """
    Validate that a VLAN exists and is empty (contains no interfaces).

    Args:
        vlan_id (int): VLAN ID to check
        auto_create (bool): If True, automatically create VLAN if it doesn't exist.
                           If False, return False if VLAN doesn't exist.
                           Default: False (VLAN must exist)

    Returns:
        bool: True if VLAN exists and is empty, False otherwise
    """
    try:
        # Get VLAN facts to check if VLAN exists and has any interfaces
        vlan_facts = get_vlan_facts()
        vlan_centric_map = vlan_facts.get('vlan_centric', {})

        # First check if VLAN exists
        if str(vlan_id) not in vlan_centric_map:
            if auto_create:
                # Auto-create VLAN if enabled
                log_warning(f"VLAN {vlan_id} does not exist")
                log_info(f"Attempting to create VLAN {vlan_id}...")

                if not create_vlan(vlan_id):
                    log_error(f"Failed to create VLAN {vlan_id}")
                    return False

                # Wait for VLAN to be created
                import time
                time.sleep(2)

                # Re-fetch VLAN facts to verify creation
                log_info("Re-checking VLAN status after creation...")
                vlan_facts = get_vlan_facts()
                vlan_centric_map = vlan_facts.get('vlan_centric', {})

                if str(vlan_id) not in vlan_centric_map:
                    log_error(f"VLAN {vlan_id} still not found after creation")
                    return False

                log_info(f"✓ VLAN {vlan_id} created successfully")
            else:
                # Auto-create disabled, VLAN must exist
                log_error(f"VLAN {vlan_id} does not exist")
                return False
        else:
            log_info(f"✓ VLAN {vlan_id} exists")

        # Check if VLAN has any members using vlan_centric_map
        vlan_info = vlan_centric_map[str(vlan_id)]
        vlan_members = vlan_info.get("members", [])

        if vlan_members:
            log_error(f"VLAN {vlan_id} is not empty. Current interfaces: {vlan_members}")
            log_error(f"       Please choose an empty VLAN or remove interfaces from VLAN {vlan_id}")
            return False
        else:
            log_info(f"✓ VLAN {vlan_id} is empty")
            return True

    except Exception as e:
        log_error(f"Error checking VLAN {vlan_id}: {str(e)}")
        return False


def validate_buffer_config():
    """
    Validate that the switch has a QoS buffer configuration.

    Without BUFFER_POOL the egress queues run on SDK defaults that are far too
    small to hold the preloaded burst, so generate-traffic drops it and never
    reaches its target. A device initialized from factory default has none
    until `config qos reload` renders the platform templates.

    Returns:
        bool: False only when CONFIG_DB is readable and has no BUFFER_POOL
    """
    result = run_sonic_db_cli("CONFIG_DB", "KEYS", "BUFFER_POOL|*")
    if not result['success']:
        log_warning(f"Could not read BUFFER_POOL from CONFIG_DB, skipping buffer check: {result['error']}")
        return True
    if result['output']:
        log_info("✓ QoS buffer configuration present")
        return True

    log_error("CONFIG_DB has no BUFFER_POOL: this switch has no QoS buffer configuration.")
    log_error("       The traffic generator port cannot buffer the preloaded burst, so traffic would not flow.")
    log_error("       Run 'sudo config qos reload' (and 'sudo config save -y' to persist it), then rerun setup.")
    return False


def startup_interface(interface):
    """
    Bring up an interface using native SONiC command.

    Args:
        interface (str): Interface name (e.g., 'Ethernet0')

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        cmd = ['config', 'interface', 'startup', interface]

        log_info(f"Bringing up interface {interface}...")
        result = run_sonic_command(cmd)

        if result['success']:
            log_info(f"✓ Successfully brought up interface {interface}")
            return True
        else:
            log_error(f"Failed to bring up interface {interface}: {result['stderr']}")
            return False

    except Exception as e:
        log_error(f"Error bringing up interface {interface}: {str(e)}")
        return False


# =============================================================================
# BCM Port Control Functions
# =============================================================================

def check_port_drops(pbm_port):
    """
    Check if there are packet drops on a port using BCM commands.

    Args:
        pbm_port (str): PBM port number (e.g., 'xe0', 'd3c0')

    Returns:
        tuple: (has_drops, drop_count)
    """
    try:
        # Use BCM 'show c' command to get detailed counters including drops
        result = run_bcm_command(f"show c {pbm_port}")

        if not result['success']:
            log_warning(f"Could not get counters for port {pbm_port}: {result['stderr']}")
            return False, 0

        output = result['stdout']

        # Parse output for drop-related counters
        # Looking for lines like:
        # RDBGC0            :              123    +123        Ingress Drop
        # or other drop counters
        drop_count = 0

        for line in output.split('\n'):
            line_lower = line.lower()
            # Look for drop indicators
            if 'drop' in line_lower or 'discard' in line_lower:
                # Try to extract the counter value
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        # The counter value is usually the second field
                        counter_str = parts[1].replace(',', '').replace('+', '')
                        counter_value = int(counter_str)
                        if counter_value > 0:
                            drop_count += counter_value
                            log_info(f"  Found drop counter: {line.strip()}")
                    except (ValueError, IndexError):
                        continue

        has_drops = drop_count > 0
        return has_drops, drop_count

    except Exception as e:
        log_error(f"Error checking drops on port {pbm_port}: {str(e)}")
        return False, 0


# =============================================================================
# BCM Hardware Detection and Configuration
# =============================================================================

# =============================================================================
# Traffic Generation and Statistics
# =============================================================================

def calculate_utilization_requirements(tx_info, tgen_info, bandwidth):
    """
    Calculate required traffic generator utilization to achieve target TX utilization.

    Args:
        tx_info (dict): TX interface information
        tgen_info (dict): Traffic generator interface information
        bandwidth (int): Target TX utilization percentage

    Returns:
        float: Required traffic generator utilization percentage
    """
    tx_speed = parse_speed_to_gbps(tx_info.get('Speed', ''))
    tgen_speed = parse_speed_to_gbps(tgen_info.get('Speed', ''))

    speed_ratio = tgen_speed / tx_speed if tx_speed > 0 else 1
    required_tgen_util = bandwidth / speed_ratio

    log_info("\nUtilization calculation:")
    log_info(f"  TX speed: {tx_speed}G")
    log_info(f"  Traffic generator speed: {tgen_speed}G")
    log_info(f"  Speed ratio: {speed_ratio:.2f}x")
    log_info(f"  Target TX utilization: {bandwidth}%")
    log_info(f"  Required traffic generator utilization: "
             f"{required_tgen_util:.1f}%")

    return required_tgen_util


def resolve_ip_version(src_ip, dst_ip):
    """
    Determine the IP version shared by a src/dst address pair.

    Args:
        src_ip (str): Source IP address
        dst_ip (str): Destination IP address

    Returns:
        tuple: (version, error) where version is 4 or 6 and error is None on
        success, or version is None and error is a message when either address
        is invalid or the two addresses are of different families.
    """
    import ipaddress

    try:
        src = ipaddress.ip_address(src_ip)
    except ValueError:
        return None, f"Invalid source IP address: '{src_ip}'"
    try:
        dst = ipaddress.ip_address(dst_ip)
    except ValueError:
        return None, f"Invalid destination IP address: '{dst_ip}'"
    if src.version != dst.version:
        return None, (f"IP version mismatch: source '{src_ip}' is IPv{src.version} "
                      f"but destination '{dst_ip}' is IPv{dst.version}")
    return src.version, None


def create_traffic_packet(packet_type, dst_mac, src_mac, vlan_id, dst_ip,
                          src_ip, dst_port, src_port, tcp_flags, icmp_type,
                          icmp_code, payload_sizes, payload_patterns, dscp=0,
                          ecn=0):
    """
    Create traffic packets based on specified type and parameters.

    Args:
        packet_type (str): Type of packet ('udp', 'tcp', 'icmp')
        dst_mac (str): Destination MAC address
        src_mac (str): Source MAC address
        vlan_id (int): VLAN ID
        dst_ip (str): Destination IP address (IPv4 or IPv6)
        src_ip (str): Source IP address (same family as dst_ip)
        dst_port (int): Destination port (TCP/UDP)
        src_port (int): Source port (TCP/UDP)
        tcp_flags (str): TCP flags (TCP only)
        icmp_type (int): ICMP type (ICMP only; for IPv6 the default v4 echo
                         type 8 maps to ICMPv6 Echo Request, type 128)
        icmp_code (int): ICMP code (ICMP only)
        payload_sizes (list): List of payload sizes in bytes
        payload_patterns (list): List of payload pattern hex strings
        dscp (int): DSCP value (0-63) marked in the IPv4 ToS byte or the IPv6
                    Traffic Class byte
        ecn (int): ECN codepoint (0-3) in the low two bits of the same byte --
                   0 Not-ECT, 1 ECT(1), 2 ECT(0), 3 CE. A switch may only
                   promote ECT to CE under congestion (RFC 3168), so traffic
                   sent as Not-ECT is dropped rather than ECN-marked no matter
                   how the WRED profile is configured. Set 1 or 2 to make the
                   flow markable.

    Returns:
        List of Scapy packet objects or None if creation fails
    """
    try:
        from scapy.all import (Ether, Dot1Q, IP, IPv6, TCP, UDP, ICMP, Raw,
                               ICMPv6EchoRequest, ICMPv6Unknown)
        import binascii

        # Build the IP ToS byte: DSCP in the upper 6 bits, ECN in the low 2.
        if not (0 <= dscp <= 63):
            log_error(f"Invalid DSCP value: {dscp}. Must be 0-63")
            return None
        if not (0 <= ecn <= 3):
            log_error(f"Invalid ECN value: {ecn}. Must be 0-3")
            return None
        tos = (dscp << 2) | ecn

        ip_version, err = resolve_ip_version(src_ip, dst_ip)
        if err:
            log_error(err)
            return None

        packets = []

        # Create a packet for each payload_size and payload_pattern combination
        for payload_size, payload_pattern in zip(payload_sizes, payload_patterns):
            # Convert hex pattern to bytes
            try:
                # Remove any spaces from the hex string
                hex_pattern = ''.join(c for c in payload_pattern if c not in ' ')
                # Convert hex string to bytes
                pattern_bytes = binascii.unhexlify(hex_pattern)
            except (ValueError, binascii.Error) as e:
                log_error(f"Invalid hex pattern '{payload_pattern}': {e}")
                return None

            if len(pattern_bytes) == 0:
                log_error("Payload pattern cannot be empty")
                return None

            # Create payload by repeating the pattern to reach the desired size
            if len(pattern_bytes) > payload_size:
                # If pattern is longer than payload size, truncate it
                payload = pattern_bytes[:payload_size]
            else:
                # Repeat the pattern to fill the payload size
                repetitions = (payload_size // len(pattern_bytes)) + 1
                payload = (pattern_bytes * repetitions)[:payload_size]

            # Build base Ethernet frame
            eth = Ether(src=src_mac, dst=dst_mac)

            # Add VLAN tag if specified
            if vlan_id:
                eth = eth / Dot1Q(vlan=int(vlan_id))

            # L3 header: DSCP rides in the ToS byte (IPv4) or the Traffic
            # Class byte (IPv6); both place DSCP in the upper 6 bits.
            if ip_version == 6:
                l3 = IPv6(src=src_ip, dst=dst_ip, tc=tos)
            else:
                l3 = IP(src=src_ip, dst=dst_ip, tos=tos)

            # Build packet based on type. Every variant ends in a Raw layer:
            # the burst loop rewrites packet[Raw] in the random-payload modes.
            if packet_type.lower() == 'tcp':
                packet = (eth / l3 /
                          TCP(sport=src_port, dport=dst_port, flags=tcp_flags) /
                          Raw(load=payload))
            elif packet_type.lower() == 'udp':
                packet = (eth / l3 /
                          UDP(sport=src_port, dport=dst_port) /
                          Raw(load=payload))
            elif packet_type.lower() == 'icmp':
                if ip_version == 6:
                    # ICMPv6 Echo Request is type 128; accept the v4 echo
                    # default (8) as meaning "echo request" so plain
                    # --packet-type icmp works for both families.
                    if icmp_type in (8, 128):
                        icmp = ICMPv6EchoRequest(code=icmp_code)
                    else:
                        icmp = ICMPv6Unknown(type=icmp_type, code=icmp_code)
                else:
                    icmp = ICMP(type=icmp_type, code=icmp_code)
                packet = eth / l3 / icmp / Raw(load=payload)
            else:
                log_error(f"Unsupported packet type: {packet_type}")
                return None

            log_info(f"✓ Created IPv{ip_version} {packet_type.upper()} packet "
                     f"with payload size {payload_size}, pattern "
                     f"'{payload_pattern}', DSCP {dscp} ({len(packet)} bytes)")

            packets.append(packet)

        log_info(f"✓ Created {len(packets)} packet variant(s)")
        return packets

    except ImportError:
        log_error("scapy library not available for packet creation")
        return None
    except Exception as e:
        log_error(f"Failed to create packet: {e}")
        return None


def get_interface_statistics(interfaces):
    """
    Get interface statistics for multiple interfaces.

    Args:
        interfaces (list): List of interface names

    Returns:
        dict: Statistics for each interface
    """
    try:
        # Get statistics for all interfaces
        result = subprocess.run(['portstat', '-j'], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {intf: {'ERROR': 'Failed to get stats'} for intf in interfaces}

        import json
        all_stats = json.loads(result.stdout)

        # Extract stats for requested interfaces
        interface_stats = {}
        for intf in interfaces:
            if intf in all_stats:
                stats = all_stats[intf]
                interface_stats[intf] = {
                    'TX_UTIL': stats.get('TX_UTIL', 'N/A'),
                    'RX_UTIL': stats.get('RX_UTIL', 'N/A'),
                    'TX_OK': stats.get('TX_OK', 'N/A'),
                    'RX_OK': stats.get('RX_OK', 'N/A'),
                    'ERROR': None
                }
            else:
                interface_stats[intf] = {'ERROR': f'Interface {intf} not found'}

        return interface_stats

    except Exception as e:
        return {intf: {'ERROR': str(e)} for intf in interfaces}


def get_and_parse_utilization_stats(tgen_intf, tx_intf):
    """
    Get and parse utilization statistics for traffic generator and TX interfaces.

    Args:
        tgen_intf (str): Traffic generator interface name
        tx_intf (str): TX interface name

    Returns:
        tuple: (tgen_util, tx_util, success)
    """
    try:
        # Get stats for both interfaces
        all_stats = get_interface_statistics([tgen_intf, tx_intf])
        tgen_stats = all_stats[tgen_intf]
        tx_stats = all_stats[tx_intf]

        if tgen_stats.get('ERROR') or tx_stats.get('ERROR'):
            return 0.0, 0.0, False

        # Parse utilization values
        tgen_util_str = tgen_stats.get('TX_UTIL', 'N/A')
        tx_util_str = tx_stats.get('TX_UTIL', 'N/A')

        # Convert to float values
        current_tgen_util = 0.0
        current_tx_util = 0.0

        if tgen_util_str != 'N/A':
            try:
                current_tgen_util = float(tgen_util_str.replace('%', ''))
            except (ValueError, TypeError):
                current_tgen_util = 0.0

        if tx_util_str != 'N/A':
            try:
                current_tx_util = float(tx_util_str.replace('%', ''))
            except (ValueError, TypeError):
                current_tx_util = 0.0

        return current_tgen_util, current_tx_util, True

    except Exception as e:
        log_error(f"Error getting utilization stats: {e}")
        return 0.0, 0.0, False


def parse_utilization_value(util_str):
    """
    Parse utilization string to float value.

    Args:
        util_str: Utilization string (e.g., "0.00%", "N/A", "1.23%")

    Returns:
        float: Utilization value as percentage, or None if cannot parse
    """
    try:
        if util_str == 'N/A' or not util_str:
            return None

        # Remove % sign and convert to float
        if isinstance(util_str, str) and util_str.endswith('%'):
            return float(util_str[:-1])
        elif isinstance(util_str, (int, float)):
            return float(util_str)
        else:
            return float(util_str)
    except (ValueError, TypeError):
        return None


# =============================================================================
# SCHEDULER HELPER FUNCTIONS
# =============================================================================

def run_sonic_db_cli(db_name, *args):
    """Execute a sonic-db-cli command."""
    try:
        cmd = ["sonic-db-cli", db_name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = result.stdout.strip()

        if result.returncode != 0:
            return {'success': False, 'output': '', 'error': result.stderr.strip()}
        if output.startswith("ERR") or output.startswith("WRONGTYPE"):
            return {'success': False, 'output': '', 'error': output}

        return {'success': True, 'output': output, 'error': ''}
    except subprocess.TimeoutExpired:
        return {'success': False, 'output': '', 'error': 'Command timed out'}
    except Exception as e:
        return {'success': False, 'output': '', 'error': str(e)}


def get_queue_count_for_interface(interface_name):
    """Get queue count from COUNTERS_DB."""
    try:
        result = run_sonic_db_cli("COUNTERS_DB", "HKEYS", "COUNTERS_QUEUE_NAME_MAP")
        if not result['success']:
            raise Exception(f"Failed to get queue map: {result['error']}")

        all_keys = result['output'].split('\n') if result['output'] else []
        prefix = interface_name + ":"
        queue_count = sum(1 for key in all_keys if key.startswith(prefix))

        if queue_count == 0:
            raise Exception(f"No queues found for {interface_name}")
        return queue_count

    except Exception as e:
        raise Exception(f"Queue count failed for {interface_name}: {str(e)}")


def get_interface_speed_mbps(interface_name):
    """Get interface speed in Mbps from CONFIG_DB.

    Args:
        interface_name: Interface name (e.g., "Ethernet448")

    Returns:
        int: Speed in Mbps (e.g., 800000 for 800G)

    Raises:
        Exception: If speed cannot be retrieved
    """
    result = run_sonic_db_cli("CONFIG_DB", "HGET", f"PORT|{interface_name}", "speed")
    if not result['success'] or not result['output'] or result['output'] == "(nil)":
        raise Exception(f"Speed not found for {interface_name}")
    return int(result['output'])


# =============================================================================
# MAIN FUNCTIONS
# =============================================================================

def _scheduler_name(tgen_intf):
    """CONFIG_DB SCHEDULER profile name sonic-snake owns for a tgen port."""
    return f"sonic_snake_{tgen_intf.replace('/', '_').replace(':', '_')}"


def _rate_variant_keys(scheduler_name):
    """SCHEDULER keys of the per-rate variants (<name>_bw<N>) that the rebind
    path of update_scheduler_for_bandwidth leaves behind."""
    res = run_sonic_db_cli("CONFIG_DB", "KEYS", f"SCHEDULER|{scheduler_name}_bw*")
    if res['success'] and res['output']:
        return [k for k in res['output'].split('\n') if k]
    return []


def setup_scheduler(tgen_intf, tx_intf, platform):
    """Setup scheduler at 100% of TX interface speed as default.

    PIR is sized to TX line rate so the tgen port can never overdrive TX.
    The QUEUE key the profile is bound with comes from the platform: flat on
    XGS, chassis-keyed on VOQ platforms such as Q3D.
    """
    try:
        scheduler_name = _scheduler_name(tgen_intf)
        queue_count = get_queue_count_for_interface(tgen_intf)

        tx_speed_mbps = get_interface_speed_mbps(tx_intf)

        pir = int((tx_speed_mbps * 1_000_000 * 100 / 100) / 8)

        # Create scheduler
        for field, value in [("type", "STRICT"), ("pir", str(pir))]:
            result = run_sonic_db_cli("CONFIG_DB", "HSET", f"SCHEDULER|{scheduler_name}", field, value)
            if not result['success']:
                raise Exception(f"Failed to set {field}: {result['error']}")
        time.sleep(5)

        # Bind scheduler to all queues (platform-specific QUEUE key)
        for q in range(queue_count):
            key = platform.scheduler_queue_key(tgen_intf, q)
            result = run_sonic_db_cli("CONFIG_DB", "HSET", key, "scheduler", scheduler_name)
            if not result['success']:
                raise Exception(f"Failed to bind queue {q}: {result['error']}")
        time.sleep(5)

        pir_gbps = (pir * 8) / 1_000_000_000
        log_info("Scheduler '{}' created (PIR: {:.2f} Gbps, 100% of TX {}, {} queues)".format(
            scheduler_name, pir_gbps, tx_intf, queue_count))
        return True, scheduler_name

    except Exception as e:
        log_error(f"Scheduler setup failed: {str(e)}")
        return False, None


def update_scheduler_for_bandwidth(tgen_intf, tx_intf, bandwidth_percent, platform):
    """Set the scheduler PIR to bandwidth_percent of TX line rate.

    PIR is computed against the TX interface speed so that bandwidth_percent
    expresses target TX utilization, independent of tgen port speed.

    XGS rewrites 'pir' on the bound profile in place and SAI re-applies it.
    Platforms that set SCHEDULER_REBIND_ON_UPDATE (VOQ SAI on Q3D ignores an
    in-place PIR change on a bound profile) instead get a fresh profile named
    for the rate, a queue rebind to it, and the previous profile deleted.
    """
    try:
        scheduler_name = _scheduler_name(tgen_intf)
        tx_speed_mbps = get_interface_speed_mbps(tx_intf)
        pir = int((tx_speed_mbps * 1_000_000 * bandwidth_percent / 100) / 8)

        if platform.SCHEDULER_REBIND_ON_UPDATE:
            _rebind_scheduler(tgen_intf, scheduler_name, bandwidth_percent, pir, platform)
        else:
            result = run_sonic_db_cli("CONFIG_DB", "HSET", f"SCHEDULER|{scheduler_name}", "pir", str(pir))
            if not result['success']:
                raise Exception(f"Failed to update pir: {result['error']}")
            time.sleep(5)

        pir_gbps = (pir * 8) / 1_000_000_000
        log_info("Scheduler rate limit: {}% of TX ({}) ({:.2f} Gbps)".format(
            bandwidth_percent, tx_intf, pir_gbps))
        return True

    except Exception as e:
        log_error(f"Failed to update scheduler: {str(e)}")
        return False


def _rebind_scheduler(tgen_intf, scheduler_name, bandwidth_percent, pir, platform):
    """Rebind path of update_scheduler_for_bandwidth: create <name>_bw<N> with
    the new PIR, point every tgen queue at it, then delete the setup default
    and any older rate variant so only the active profile remains."""
    new_name = f"{scheduler_name}_bw{bandwidth_percent}"
    queue_count = get_queue_count_for_interface(tgen_intf)

    for field, value in [("type", "STRICT"), ("pir", str(pir))]:
        result = run_sonic_db_cli("CONFIG_DB", "HSET", f"SCHEDULER|{new_name}", field, value)
        if not result['success']:
            raise Exception(f"Failed to set {field}: {result['error']}")
    time.sleep(5)

    for q in range(queue_count):
        key = platform.scheduler_queue_key(tgen_intf, q)
        result = run_sonic_db_cli("CONFIG_DB", "HSET", key, "scheduler", new_name)
        if not result['success']:
            raise Exception(f"Failed to bind queue {q}: {result['error']}")
    time.sleep(5)

    for k in [f"SCHEDULER|{scheduler_name}"] + _rate_variant_keys(scheduler_name):
        if k != f"SCHEDULER|{new_name}":
            run_sonic_db_cli("CONFIG_DB", "DEL", k)


def cleanup_scheduler(tgen_intf, platform):
    """Cleanup scheduler from interface."""
    try:
        scheduler_name = _scheduler_name(tgen_intf)
        queue_count = get_queue_count_for_interface(tgen_intf)

        # Unbind scheduler from all queues (platform-specific QUEUE key)
        for q in range(queue_count):
            run_sonic_db_cli("CONFIG_DB", "HDEL", platform.scheduler_queue_key(tgen_intf, q), "scheduler")
        time.sleep(5)

        # Delete the profile; on rebind platforms also every rate variant left behind.
        names = [f"SCHEDULER|{scheduler_name}"]
        if platform.SCHEDULER_REBIND_ON_UPDATE:
            names += _rate_variant_keys(scheduler_name)
        for k in names:
            run_sonic_db_cli("CONFIG_DB", "DEL", k)
        log_info(f"Scheduler '{scheduler_name}' deleted")

        return True

    except Exception as e:
        log_error(f"Scheduler cleanup failed: {str(e)}")
        return False
