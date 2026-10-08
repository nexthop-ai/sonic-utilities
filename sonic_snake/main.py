#!/usr/bin/env python3
"""
SONiC Snake CLI Tool

A traffic generation tool for SONiC network switches.

AVAILABLE COMMANDS:
    setup              Configure traffic generator and interfaces for testing
    generate-traffic   Generate traffic to achieve target TX utilization
    drain              Drain traffic from traffic generator interface
    cleanup            Remove interfaces from VLAN and restore default state
"""

import sys
import time
import click
import click_log

from sonic_snake import __version__
from sonic_snake.platforms import create_platform
from sonic_snake.logger import log
from utilities_common import sonic_snake_helper

# Global platform instance
_snake = None


@click.group()
@click.version_option(version=__version__, prog_name='sonic-snake',
                      message='%(prog)s %(version)s')
@click_log.simple_verbosity_option(
    log,
    default='INFO',
    help='Log level: CRITICAL, ERROR, WARNING, INFO or DEBUG. '
         'Default is INFO for both console and syslog.'
)
def cli():
    """SONiC Snake - Network Traffic Generation Tool"""
    global _snake

    # Create platform instance (auto-detects chip type)
    _snake = create_platform()

    log.info(f"SONiC Snake v{__version__} starting")

    # Log detected platform
    chip_name = getattr(_snake, 'CHIP_NAME', 'unknown')
    log.info(f"Platform: {chip_name}")

    # Check if platform is Broadcom before executing any commands
    if not _snake.check_platform():
        log.error("This tool requires a Broadcom platform")
        sys.exit(1)


# =============================================================================
# CLI Commands
# =============================================================================

@cli.command()
@click.option('--tx-intf', required=True, help='TX interface name (e.g., Ethernet0)')
@click.option('--rx-intf', required=False, help='RX interface name (e.g., Ethernet4)')
@click.option('--tgen-intf', required=True, help='Traffic generator interface name (e.g., Ethernet8)')
@click.option('--vlan', type=int, required=True, help='VLAN ID (must not have any interfaces)')
def setup(tx_intf, rx_intf, tgen_intf, vlan):
    """Setup traffic generator configuration"""
    log.info("SONiC Snake - Setup")
    log.info(f"TX interface: {tx_intf}")
    if rx_intf:
        log.info(f"RX interface: {rx_intf}")
    else:
        log.info("RX interface: None (not specified)")
    log.info(f"Traffic generator interface: {tgen_intf}")
    log.info(f"VLAN: {vlan}")

    try:
        # Get combined port mapping
        log.info("Getting combined port mapping...")
        combined_mapping = sonic_snake_helper.get_port_mapping(_snake)
        if not combined_mapping:
            log.error("Failed to get combined port mapping")
            sys.exit(1)

        # Validate TX interface: admin up, oper up
        log.info(f"Validating TX interface '{tx_intf}'...")
        if not _snake.validate_interface(tx_intf, combined_mapping):
            sys.exit(1)
        log.info("✓ TX interface validation passed")

        # Validate RX interface: admin up, oper up
        if rx_intf:
            log.info(f"Validating RX interface '{rx_intf}'...")
            if not _snake.validate_interface(rx_intf, combined_mapping):
                sys.exit(1)
            log.info("✓ RX interface validation passed")

        # Validate traffic generator interface: admin up, oper down, not in any VLAN, speed > both TX
        log.info(f"Validating traffic generator interface '{tgen_intf}'...")
        if not _snake.validate_tgen_interface(tgen_intf, tx_intf, combined_mapping):
            sys.exit(1)
        log.info("✓ Traffic generator interface validation passed")

        log.info("Validating QoS buffer configuration...")
        if not sonic_snake_helper.validate_buffer_config():
            sys.exit(1)

        # Validate VLAN (will be default 100 if not specified)
        log.info(f"Validating VLAN {vlan}...")

        # Check if VLAN exists and is empty (auto-create if needed)
        if not sonic_snake_helper.validate_vlan_empty(vlan, auto_create=True):
            sys.exit(1)

        # Setup traffic generator and TX interface configuration
        log.info("Setting up traffic generator and TX interface configuration...")

        # Get PBM ports for both interfaces
        tgen_info = combined_mapping[tgen_intf]
        tx_info = combined_mapping[tx_intf]

        tgen_pbm_port = tgen_info.get('Pbm', '')
        tx_pbm_port = tx_info.get('Pbm', '')

        if not tgen_pbm_port:
            log.error(f"No PBM port found for traffic generator interface '{tgen_intf}'")
            sys.exit(1)

        if not tx_pbm_port:
            log.error(f"No PBM port found for TX interface '{tx_intf}'")
            sys.exit(1)

        log.info(f"Traffic generator PBM port: {tgen_pbm_port}")
        log.info(f"TX interface PBM port: {tx_pbm_port}")

        # Detect available loopback mode
        log.info("Detecting available loopback mode...")
        loopback_mode = _snake.detect_loopback_mode()
        if loopback_mode:
            log.info(f"✓ Detected loopback mode: {loopback_mode}")
        else:
            log.error("Could not detect loopback mode from BCM hardware")
            log.error("This is required for traffic generator configuration")
            sys.exit(1)

        # Setup scheduler for rate limiting (default: 100% of TX speed)
        scheduler_success, scheduler_name = sonic_snake_helper.setup_scheduler(
            tgen_intf, tx_intf, _snake)
        if not scheduler_success:
            log.warning("Scheduler setup failed - bandwidth rate limiting unavailable")
        else:
            time.sleep(5)
            log.info(f"Scheduler '{scheduler_name}' created and bound successfully")

        # Step 1: Add traffic generator interface to VLAN (BCM command)
        log.info(f"Adding {tgen_intf} to VLAN {vlan} as untagged member...")
        if not _snake.add_to_vlan(vlan, tgen_pbm_port):
            log.error(f"Failed to add {tgen_intf} to VLAN {vlan}")
            sys.exit(1)

        # Execute platform-specific BCM setup
        mirror_attempted = False
        try:
            log.info("\n" + "="*70)
            log.info("SONIC SNAKE SETUP - BCM Configuration")
            log.info("="*70)
            log.info(f"Traffic Gen Port: {tgen_pbm_port}")
            log.info(f"TX Port: {tx_pbm_port}")
            log.info(f"VLAN ID: {vlan}")
            log.info(f"Loopback Mode: {loopback_mode}")

            # Port configuration
            log.info("\n→ Configuring traffic generator port...")
            if not _snake.enable_port(tgen_pbm_port):
                raise RuntimeError("Failed to enable port")
            if not _snake.set_loopback(tgen_pbm_port, loopback_mode):
                raise RuntimeError("Failed to set loopback mode")

            # Bridge configuration
            log.info("\n→ Configuring bridge settings...")
            if not _snake.set_bridge(tgen_pbm_port, enabled=True):
                raise RuntimeError("Failed to enable bridge")
            if not _snake.set_learning(tgen_pbm_port, _snake.BCM_PORT_LEARN_ARL_FWD):
                raise RuntimeError("Failed to set learning mode")
            if not _snake.set_discard(tgen_pbm_port, 'none'):
                raise RuntimeError("Failed to set discard mode")

            # VLAN configuration
            log.info("\n→ Configuring VLAN settings...")
            if not _snake.set_mcast_flood(vlan, _snake.BCM_VLAN_MCAST_FLOOD_NONE):
                raise RuntimeError("Failed to set multicast flood")
            if not _snake.add_to_vlan(vlan, tgen_pbm_port):
                raise RuntimeError("Failed to add to VLAN")
            if not _snake.remove_from_vlan(1, tgen_pbm_port):
                raise RuntimeError("Failed to remove from default VLAN")
            if not _snake.set_pvid(tgen_pbm_port, vlan):
                raise RuntimeError("Failed to set PVID")

            # Port mirroring configuration (Ingress mode to avoid egress control plane)
            log.info("\n→ Configuring port mirroring...")
            mirror_attempted = True
            if not _snake.setup_mirror(tgen_pbm_port, tx_pbm_port):
                raise RuntimeError("Failed to setup port mirroring")

            log.info("="*70)
            log.info("✓ BCM Setup completed successfully!")
            log.info("="*70)

            if rx_intf:
                log.info(
                    f"Configuration: TX({tx_intf}) <-> RX({rx_intf}) "
                    f"via Traffic Generator({tgen_intf}) using port mirroring")
            else:
                log.info(
                    f"Configuration: TX({tx_intf}) via Traffic "
                    f"Generator({tgen_intf}) using port mirroring")

            # Clear counters for all interfaces after successful setup
            interfaces_to_reset = [tx_intf, tgen_intf]
            if rx_intf:
                interfaces_to_reset.append(rx_intf)
            reset_success = sonic_snake_helper.reset_counters(interfaces_to_reset)
            if not reset_success:
                log.warning("Counter reset failed, but setup is complete")

        except Exception as e:
            log.error(f"Setup failed: {e}")
            log.error("Running automatic cleanup...")

            # Perform automatic cleanup on setup failure: the same BCM steps, in
            # the same order, as the `cleanup` command
            try:
                _snake.set_loopback(tgen_pbm_port, 'none')
                _snake.set_bridge(tgen_pbm_port, enabled=False)
                _snake.set_learning(tgen_pbm_port, 0)
                _snake.set_discard(tgen_pbm_port, 'all')
                _snake.set_mcast_flood(vlan, _snake.BCM_VLAN_MCAST_FLOOD_UNKNOWN)
                _snake.remove_from_vlan(vlan, tgen_pbm_port)
                _snake.set_pvid(tgen_pbm_port, 1)

                # Unbind the mirror; release the TX destination only if this run
                # got as far as configuring it
                _snake.cleanup_mirror(tgen_pbm_port, tx_pbm_port if mirror_attempted else None)

                log.info("✓ Automatic cleanup completed")
            except Exception as cleanup_error:
                log.warning(f"Automatic cleanup had errors: {cleanup_error}")

            log.error("Setup failed - exiting after cleanup")
            sys.exit(1)

    except Exception as e:
        log.error(f"Setup command failed: {str(e)}")
        sys.exit(1)


def _header_overhead_bytes(ip_version):
    """Worst-case header bytes ahead of the payload for the address family."""
    overhead = _snake.HEADER_OVERHEAD_BYTES
    if ip_version == 6:
        overhead += _snake.IPV6_HEADER_EXTRA_BYTES
    return overhead


def _generate_multistream(streams_cfg, defaults, tx_intf, tgen_intf,
                          bandwidth, vlan, tolerance, pcap_file=None):
    """Build and run multi-stream traffic in a single shared queue.

    Streams are defined as a list of objects, each with any packet fields plus
    a ``percentage``: its absolute share of the tgen bandwidth. Percentages
    must be positive and sum to exactly 100 across all streams. The per-stream
    byte budget is ``total_data_size * percentage/100`` (in wire bytes), so the
    recirculating loopback buffer carries each stream in exact proportion to
    its percentage, capped overall by the single scheduler PIR (= bandwidth).
    See run_multistream_burst_loop.
    """
    # Validate the streams definition up front.
    if not isinstance(streams_cfg, list) or len(streams_cfg) == 0:
        log.error("'streams' must be a non-empty list")
        sys.exit(1)

    # Each stream's share of the tgen bandwidth is given by 'percentage': an
    # absolute slice that must be a positive number. All streams' percentages
    # must sum to exactly 100 so the user always accounts for the full tgen
    # bandwidth (no silent over-/under-allocation).
    names = set()
    total_percentage = 0.0
    for i, stream in enumerate(streams_cfg):
        if not isinstance(stream, dict):
            log.error(f"Stream #{i} must be a JSON object")
            sys.exit(1)
        name = stream.get('name', f"stream{i}")
        if name in names:
            log.error(f"Duplicate stream name: {name}")
            sys.exit(1)
        names.add(name)
        if 'weight' in stream:
            log.error(
                f"Stream '{name}': 'weight' is not supported. Use "
                f"'percentage' instead (all streams must sum to 100).")
            sys.exit(1)
        pct = stream.get('percentage')
        if pct is None:
            log.error(f"Stream '{name}': missing 'percentage'.")
            sys.exit(1)
        if not isinstance(pct, (int, float)) or pct <= 0:
            log.error(f"Stream '{name}': percentage must be a positive number")
            sys.exit(1)
        total_percentage += pct

    # Percentages must sum to exactly 100 (small float tolerance); anything
    # more or less is rejected so the full tgen bandwidth is always accounted
    # for with no over-/under-allocation.
    if abs(total_percentage - 100.0) > 1e-6:
        log.error(
            f"Stream percentages must sum to 100, but got "
            f"{format(total_percentage, 'g')}. Please re-check the config.")
        sys.exit(1)

    log.info("\n" + "="*70)
    log.info("SONIC SNAKE - MULTI-STREAM TRAFFIC GENERATION")
    log.info("="*70)
    log.info(f"TX Interface:    {tx_intf}")
    log.info(f"TGen Interface:  {tgen_intf}")
    log.info(f"Target TX Util:  {bandwidth}% (aggregate)")
    log.info(f"Streams:         {len(streams_cfg)}")

    try:
        combined_mapping = sonic_snake_helper.get_port_mapping(_snake)
        if not combined_mapping:
            log.error("Failed to get combined port mapping")
            sys.exit(1)
        if tx_intf not in combined_mapping:
            log.error(f"TX interface '{tx_intf}' not found")
            sys.exit(1)
        if tgen_intf not in combined_mapping:
            log.error(f"Traffic generator interface '{tgen_intf}' not found")
            sys.exit(1)

        tx_info = combined_mapping[tx_intf]
        tgen_info = combined_mapping[tgen_intf]
        required_tgen_util = sonic_snake_helper.calculate_utilization_requirements(
            tx_info, tgen_info, bandwidth)

        tgen_pbm_port = tgen_info.get('Pbm', '')
        if not tgen_pbm_port:
            log.error(f"No PBM port found for traffic generator interface '{tgen_intf}'")
            sys.exit(1)

        # Build packets for each stream, merging top-level defaults.
        streams = []
        for i, stream in enumerate(streams_cfg):
            cfg = {**defaults, **stream}
            name = stream.get('name', f"stream{i}")
            ptype = str(cfg['packet_type'])
            ecn_v = cfg.get('ecn', 0)
            if ecn_v is None or not (0 <= ecn_v <= 3):
                log.error(f"Stream '{name}': invalid ECN {ecn_v} (must be 0-3)")
                sys.exit(1)
            dscp_v = cfg.get('dscp', 0)
            if dscp_v is None or not (0 <= dscp_v <= 63):
                log.error(f"Stream '{name}': invalid DSCP {dscp_v} (must be 0-63)")
                sys.exit(1)
            stream_ip_version, ip_err = sonic_snake_helper.resolve_ip_version(
                cfg['src_ip'], cfg['dst_ip'])
            if ip_err:
                log.error(f"Stream '{name}': {ip_err}")
                sys.exit(1)
            random_payload = bool(cfg.get('random_payload', False))
            random_payload_size = bool(cfg.get('random_payload_size', False))
            min_payload_size = int(cfg.get('min_payload_size', 64))
            max_payload_size = int(cfg.get('max_payload_size', 9000))
            if random_payload_size and not (0 < min_payload_size <= max_payload_size):
                log.error(
                    f"Stream '{name}': invalid random-payload-size range "
                    f"min={min_payload_size}, max={max_payload_size} (require 0 < min <= max)")
                sys.exit(1)
            if random_payload_size and tx_intf:
                mtu = _snake.get_interface_mtu(tx_intf)
                overhead = _header_overhead_bytes(stream_ip_version)
                if mtu is not None and max_payload_size > mtu - overhead:
                    log.error(
                        f"Stream '{name}': max-payload-size {max_payload_size} exceeds the "
                        f"{tx_intf} MTU ({mtu}), must be <= "
                        f"{mtu - overhead}")
                    sys.exit(1)

            try:
                psizes = [int(str(x).strip()) for x in str(cfg['payload_size']).split(',')]
            except ValueError:
                log.error(f"Stream '{name}': invalid payload_size '{cfg['payload_size']}'")
                sys.exit(1)

            if random_payload:
                ppatterns = ['58'] * len(psizes)
            else:
                ppatterns = [x.strip() for x in str(cfg['payload_pattern']).split(',')]
                if len(psizes) != len(ppatterns):
                    log.error(
                        f"Stream '{name}': payload_size count ({len(psizes)}) "
                        f"must match payload_pattern count ({len(ppatterns)})")
                    sys.exit(1)

            pkts = sonic_snake_helper.create_traffic_packet(
                ptype, cfg['dst_mac'], cfg['src_mac'], vlan, cfg['dst_ip'],
                cfg['src_ip'], cfg['dst_port'], cfg['src_port'], cfg['tcp_flags'],
                cfg['icmp_type'], cfg['icmp_code'], psizes, ppatterns,
                dscp=dscp_v, ecn=ecn_v)
            if not pkts:
                log.error(f"Stream '{name}': failed to build packets")
                sys.exit(1)

            pct = float(stream['percentage'])
            streams.append({
                'name': name,
                'percentage': pct,
                'packets': pkts,
                'payload_sizes': psizes,
                'random_payload': random_payload,
                'random_payload_size': random_payload_size,
                'min_payload_size': min_payload_size,
                'max_payload_size': max_payload_size,
            })
            size_desc = (f"random {min_payload_size}-{max_payload_size}" if random_payload_size
                         else f"{psizes}")
            log.info(
                f"  Stream '{name}': percentage={format(pct, 'g')}%, "
                f"type={ptype.upper()}, dscp={dscp_v}, ecn={ecn_v}, sizes={size_desc}, "
                f"random_payload={random_payload}")
            log.info(
                f"      MAC {cfg['src_mac']} to {cfg['dst_mac']}   "
                f"IP {cfg['src_ip']} to {cfg['dst_ip']}   "
                f"ports {cfg['src_port']} to {cfg['dst_port']}")

        # Set the single global PIR (= bandwidth). Percentages never touch it.
        if not sonic_snake_helper.update_scheduler_for_bandwidth(
                tgen_intf, tx_intf, bandwidth, _snake):
            log.warning("Scheduler rate limiting not applied")
        else:
            time.sleep(5)

        # No DSCP->queue manipulation is needed: the looped traffic is
        # unknown-unicast and floods to a single multicast queue regardless
        # of each stream's DSCP, so all streams already share one queue and
        # the single scheduler PIR caps the aggregate.
        final_stats, packets_sent = _snake.run_multistream_burst_loop(
            streams, tgen_intf, tx_intf, tgen_pbm_port,
            bandwidth, required_tgen_util, tolerance=tolerance,
            pcap_file=pcap_file)

        if not final_stats:
            log.error("Multi-stream traffic generation failed")
            sys.exit(1)

        log.info("\n" + "="*70)
        log.info("MULTI-STREAM RESULTS")
        log.info("="*70)
        log.info(f"Total Packets Sent: {format(packets_sent, ',')}")
        log.info(
            "Aggregate TX Util:  "
            f"{format(final_stats.get('tx_util', 0), '.1f')}%")
        log.info(f"Target Utilization: {bandwidth}%")
        log.info(
            "Target Reached:     "
            f"{'✓ YES' if final_stats.get('target_reached') else '✗ NO'}")
        log.info("="*70)

    except SystemExit:
        raise
    except Exception as e:
        log.error(f"Multi-stream traffic generation failed: {str(e)}")
        sys.exit(1)


@cli.command()
@click.option('--config', type=click.Path(exists=True), default=None,
              help='Path to JSON configuration file. If provided, CLI options are ignored.')
@click.option('--tx-intf', help='TX interface name (e.g., Ethernet0)')
@click.option('--tgen-intf', help='Traffic generator interface name (e.g., Ethernet8)')
@click.option('--bandwidth', type=int,
              help='Target TX utilization percentage (0-100)')
@click.option('--vlan', type=int, default=None,
              help='VLAN ID for packet tagging (optional)')
@click.option('--packet-type', type=click.Choice(['udp', 'tcp', 'icmp'], case_sensitive=False),
              default='udp', help='Packet type (default: udp)')
@click.option('--dst-mac', default='aa:bb:cc:dd:ee:ff',
              help='Destination MAC address')
@click.option('--src-mac', default='00:11:22:33:44:55',
              help='Source MAC address')
@click.option('--dst-ip', default='10.0.0.100',
              help='Destination IP address (IPv4 or IPv6)')
@click.option('--src-ip', default='10.0.0.1',
              help='Source IP address (IPv4 or IPv6, same family as --dst-ip)')
@click.option('--dst-port', default=12345, type=int,
              help='Destination port for TCP/UDP')
@click.option('--src-port', default=54321, type=int,
              help='Source port for TCP/UDP')
@click.option('--tcp-flags', default='S',
              help='TCP flags for TCP packets')
@click.option('--icmp-type', default=8, type=int,
              help='ICMP type')
@click.option('--icmp-code', default=0, type=int,
              help='ICMP code')
@click.option('--payload-size', default='18',
              help='Payload size in bytes. Can be comma-separated')
@click.option('--payload-pattern', default='58',
              help='Payload pattern as hex string')
@click.option('--random-payload', is_flag=True, default=False,
              help='Enable random payload mode')
@click.option('--random-payload-size', is_flag=True, default=False,
              help='Enable random packet size mode (payload size randomized '
                   'per packet between --min-payload-size and --max-payload-size)')
@click.option('--min-payload-size', default=64, type=int,
              help='Minimum payload size in bytes for --random-payload-size (default: 64)')
@click.option('--max-payload-size', default=9000, type=int,
              help='Maximum payload size in bytes for --random-payload-size '
                   '(default: 9000; keep frame within the interface MTU)')
@click.option('--dscp', default=0, type=click.IntRange(0, 63),
              help='DSCP value to mark in the IP header (0-63, default: 0)')
@click.option('--ecn', default=0, type=click.IntRange(0, 3),
              help='ECN codepoint in the low two bits of the IP ToS byte '
                   '(0 Not-ECT, 1 ECT(1), 2 ECT(0), 3 CE; default: 0). '
                   'A switch may only promote ECT to CE under congestion, so '
                   'Not-ECT traffic is dropped rather than ECN-marked '
                   'regardless of the WRED profile -- use 1 or 2 to test '
                   'ECN marking.')
@click.option('--tolerance', default=5, type=int,
              help='Tolerance percentage for the post-run target check')
@click.option('--save-pcap', is_flag=True, default=False,
              help='Save every packet loaded into the preload buffer to a '
                   'timestamped pcap file under ./tmp for later inspection')
def generate_traffic(config, tx_intf, tgen_intf, bandwidth, vlan, packet_type,
                     dst_mac, src_mac, dst_ip, src_ip, dst_port, src_port,
                     tcp_flags, icmp_type, icmp_code, payload_size,
                     payload_pattern, random_payload, random_payload_size, min_payload_size,
                     max_payload_size, dscp, ecn, tolerance, save_pcap):
    """Generate traffic to achieve desired TX utilization (use --config or CLI options)"""

    config_data = {}

    # Load config from JSON file if provided
    if config:
        try:
            import json

            log.info(f"Loading configuration from: {config}")
            with open(config, 'r') as f:
                if not config.endswith('.json'):
                    log.error("Config file must be .json")
                    sys.exit(1)
                config_data = json.load(f)

            # Override all parameters from config file
            tx_intf = config_data.get('tx_intf', tx_intf)
            tgen_intf = config_data.get('tgen_intf', tgen_intf)
            bandwidth = config_data.get('bandwidth', bandwidth)
            vlan = config_data.get('vlan', vlan)
            packet_type = config_data.get('packet_type', packet_type)
            dst_mac = config_data.get('dst_mac', dst_mac)
            src_mac = config_data.get('src_mac', src_mac)
            dst_ip = config_data.get('dst_ip', dst_ip)
            src_ip = config_data.get('src_ip', src_ip)
            dst_port = config_data.get('dst_port', dst_port)
            src_port = config_data.get('src_port', src_port)
            tcp_flags = config_data.get('tcp_flags', tcp_flags)
            icmp_type = config_data.get('icmp_type', icmp_type)
            icmp_code = config_data.get('icmp_code', icmp_code)
            payload_size = config_data.get('payload_size', payload_size)
            payload_pattern = config_data.get('payload_pattern', payload_pattern)
            random_payload = config_data.get('random_payload', random_payload)
            random_payload_size = config_data.get('random_payload_size', random_payload_size)
            min_payload_size = config_data.get('min_payload_size', min_payload_size)
            max_payload_size = config_data.get('max_payload_size', max_payload_size)
            dscp = config_data.get('dscp', dscp)
            ecn = config_data.get('ecn', ecn)
            tolerance = config_data.get('tolerance', tolerance)
            save_pcap = config_data.get('save_pcap', save_pcap)

        except Exception as e:
            log.error(f"Failed to load config file: {e}")
            sys.exit(1)

    # DSCP/ECN from a config file bypass click's IntRange, so validate here too
    if ecn is None or not (0 <= ecn <= 3):
        log.error(f"Invalid ECN value: {ecn}. Must be 0-3")
        sys.exit(1)
    if dscp is None or not (0 <= dscp <= 63):
        log.error(f"Invalid DSCP value: {dscp}. Must be 0-63")
        sys.exit(1)

    # Validate the IP pair early (both parse, same family) and pin the IP
    # version before anything touches the scheduler or the MTU check. In
    # multi-stream mode these are the inherited defaults; each stream is
    # re-validated with its own overrides in _generate_multistream.
    ip_version, ip_err = sonic_snake_helper.resolve_ip_version(src_ip, dst_ip)
    if ip_err:
        log.error(ip_err)
        sys.exit(1)

    # Validate random-payload-size bounds when enabled
    if random_payload_size and not (0 < min_payload_size <= max_payload_size):
        log.error(
            f"Invalid random-payload-size range: min-payload-size={min_payload_size}, "
            f"max-payload-size={max_payload_size}. Require 0 < min-payload-size <= max-payload-size")
        sys.exit(1)

    # Fail fast if max-payload-size would exceed the TX interface MTU. An oversized
    # payload otherwise blows up later in sendp(), mid-preload and after TX has
    # already been disabled on the tgen port, leaving it half-configured.
    if random_payload_size and tx_intf:
        mtu = _snake.get_interface_mtu(tx_intf)
        if mtu is not None:
            overhead = _header_overhead_bytes(ip_version)
            mtu_max_payload = mtu - overhead
            if max_payload_size > mtu_max_payload:
                log.error(
                    f"--max-payload-size {max_payload_size} exceeds the {tx_intf} MTU ({mtu}): "
                    f"payload + ~{overhead}B of headers must "
                    f"fit, so max-payload-size must be <= {mtu_max_payload}")
                sys.exit(1)

    # Validate required parameters (from either config or CLI)
    if not tx_intf or not tgen_intf or bandwidth is None:
        log.error("Required: --tx-intf, --tgen-intf, --bandwidth (or use --config)")
        sys.exit(1)

    # When --save-pcap is set, build a timestamped path under ./tmp so every
    # packet loaded into the preload buffer can be dumped there. The directory
    # is created up front (both single- and multi-stream paths reuse this path).
    pcap_file = None
    if save_pcap:
        import os

        pcap_dir = os.path.join(os.getcwd(), 'tmp')
        try:
            os.makedirs(pcap_dir, exist_ok=True)
        except OSError as e:
            log.error(f"Failed to create pcap directory '{pcap_dir}': {e}")
            sys.exit(1)
        pcap_file = os.path.join(
            pcap_dir, f"sonic_snake_{time.strftime('%Y%m%d_%H%M%S')}.pcap")
        log.info(f"PCAP capture enabled: preload buffer will be saved to {pcap_file}")

    # Multi-stream mode: a "streams" array in the config defines
    # percentage-based streams that share a single queue. The top-level packet
    # fields act as
    # inherited defaults; each stream may override any of them. When no
    # "streams" key is present we fall through to the single-stream path,
    # leaving existing behaviour unchanged.
    streams_cfg = config_data.get('streams')
    if streams_cfg:
        defaults = {
            'packet_type': packet_type, 'dst_mac': dst_mac, 'src_mac': src_mac,
            'dst_ip': dst_ip, 'src_ip': src_ip, 'dst_port': dst_port,
            'src_port': src_port, 'tcp_flags': tcp_flags,
            'icmp_type': icmp_type, 'icmp_code': icmp_code,
            'payload_size': payload_size, 'payload_pattern': payload_pattern,
            'random_payload': random_payload, 'dscp': dscp, 'ecn': ecn,
            'random_payload_size': random_payload_size, 'min_payload_size': min_payload_size,
            'max_payload_size': max_payload_size,
        }
        _generate_multistream(streams_cfg, defaults, tx_intf, tgen_intf,
                              bandwidth, vlan, tolerance, pcap_file=pcap_file)
        return

    log.info("\n" + "="*70)
    log.info("SONIC SNAKE - TRAFFIC GENERATION")
    log.info("="*70)
    log.info(f"TX Interface:    {tx_intf}")
    log.info(f"TGen Interface:  {tgen_intf}")
    log.info(f"Target TX Util:  {bandwidth}%")
    if vlan is not None:
        log.info(f"VLAN:            {vlan}")
    else:
        log.info("VLAN:            None (untagged)")

    # Parse payload_size and payload_pattern as lists
    try:
        payload_sizes = [int(x.strip()) for x in payload_size.split(',')]
    except ValueError:
        log.error(
            f"Invalid payload size format: {payload_size}. "
            "Must be comma-separated integers.")
        sys.exit(1)

    # If random_payload is enabled the content is regenerated per packet, so a
    # placeholder pattern is fine. random_payload_size keeps the real pattern (only the
    # length varies) unless random_payload is also set.
    if random_payload:
        payload_patterns = ['58'] * len(payload_sizes)  # Use '58' (ASCII 'X') as placeholder
    else:
        payload_patterns = [x.strip() for x in payload_pattern.split(',')]

        # Validate that lists have the same length
        if len(payload_sizes) != len(payload_patterns):
            log.error(
                f"Payload size list length ({len(payload_sizes)}) must match "
                f"payload pattern list length ({len(payload_patterns)})")
            sys.exit(1)

    log.info("\n→ Packet Configuration:")
    log.info(f"   Type:         {packet_type.upper()}")
    log.info(f"   Dst MAC:      {dst_mac}")
    log.info(f"   Src MAC:      {src_mac}")
    log.info(f"   Dst IP:       {dst_ip}")
    log.info(f"   Src IP:       {src_ip}")
    log.info(f"   DSCP:         {dscp}")
    log.info(f"   ECN:          {ecn}")

    if packet_type.lower() in ['tcp', 'udp']:
        log.info(f"   Dst Port:     {dst_port}")
        log.info(f"   Src Port:     {src_port}")
        if packet_type.lower() == 'tcp':
            log.info(f"   TCP Flags:    {tcp_flags}")
    elif packet_type.lower() == 'icmp':
        log.info(f"   ICMP Type:    {icmp_type}")
        log.info(f"   ICMP Code:    {icmp_code}")

    if random_payload_size:
        log.info(f"   Payload Size: Random {min_payload_size}-{max_payload_size} bytes (per packet)")
    else:
        log.info(f"   Payload Size: {payload_sizes} bytes")
    if random_payload:
        log.info("   Payload:      Random content (generated per packet)")
    else:
        log.info(f"   Payload Pat:  {payload_patterns}")
    log.info(f"   Variants:     {len(payload_sizes)}")

    log.info("\n→ Traffic Parameters:")
    log.info(f"   Tolerance:    ±{tolerance}%")

    try:
        # Get combined port mapping
        combined_mapping = sonic_snake_helper.get_port_mapping(_snake)
        if not combined_mapping:
            log.error("Failed to get combined port mapping")
            sys.exit(1)

        # Validate interfaces exist
        if tx_intf not in combined_mapping:
            log.error(f"TX interface '{tx_intf}' not found")
            sys.exit(1)

        if tgen_intf not in combined_mapping:
            log.error(f"Traffic generator interface '{tgen_intf}' not found")
            sys.exit(1)

        # Get interface information
        tx_info = combined_mapping[tx_intf]
        tgen_info = combined_mapping[tgen_intf]

        # Calculate utilization requirements
        required_tgen_util = sonic_snake_helper.calculate_utilization_requirements(tx_info, tgen_info, bandwidth)

        # Update scheduler PIR for target bandwidth (% of TX interface speed)
        if not sonic_snake_helper.update_scheduler_for_bandwidth(
                tgen_intf, tx_intf, bandwidth, _snake):
            log.warning("Scheduler rate limiting not applied")
        else:
            time.sleep(5)

        # Create traffic packets (with optional VLAN tagging)
        packets = sonic_snake_helper.create_traffic_packet(
            packet_type, dst_mac, src_mac, vlan, dst_ip, src_ip,
            dst_port, src_port, tcp_flags, icmp_type, icmp_code,
            payload_sizes, payload_patterns, dscp=dscp, ecn=ecn)
        if not packets:
            sys.exit(1)

        # Single burst-based traffic generation flow for both fixed and
        # random payloads. The tgen PBM port is required to disable/enable
        # egress while the loopback buffer is preloaded.
        tgen_pbm_port = tgen_info.get('Pbm', '')
        if not tgen_pbm_port:
            log.error(f"No PBM port found for traffic generator interface '{tgen_intf}'")
            sys.exit(1)

        log.info(f"Traffic generator PBM port: {tgen_pbm_port}")

        # random_payload / random_payload_size only change the per-packet payload bytes
        # (content and/or length); the generation flow (preload burst +
        # scheduler rate control) is identical.
        final_stats, packets_sent = _snake.run_burst_traffic_loop(
            packets, tgen_intf, tx_intf, tgen_pbm_port,
            bandwidth, required_tgen_util,
            payload_sizes, random_payload=random_payload,
            random_payload_size=random_payload_size,
            min_payload_size=min_payload_size,
            max_payload_size=max_payload_size,
            pcap_file=pcap_file)

        if final_stats:
            log.info("\n" + "="*70)
            log.info("TRAFFIC GENERATION RESULTS")
            log.info("="*70)
            log.info(f"Total Packets Sent:   {format(packets_sent, ",")}")
            log.info(
                "TX Utilization:       "
                f"{format(final_stats.get('tx_util', 0), ".1f")}%")
            log.info(f"Target Utilization:   {bandwidth}%")
            log.info(
                "Target Reached:       "
                f"{'✓ YES' if final_stats.get('target_reached') else '✗ NO'}")
            log.info("="*70)

            # Check if target was reached
            if final_stats.get('tx_util', 0) < bandwidth - tolerance:
                log.warning(
                    "\n⚠️  Target threshold not reached - "
                    "performing debugging...")

                # Dump loopback port configuration for debugging
                log.info("\n" + "-"*70)
                log.info("DIAGNOSTIC INFORMATION")
                log.info("-"*70)
                tgen_info = combined_mapping[tgen_intf]
                tx_info = combined_mapping[tx_intf]
                tgen_pbm_port = tgen_info.get('Pbm', '')
                tx_pbm_port = tx_info.get('Pbm', '')

                if tgen_pbm_port:
                    log.info(
                        f"\n→ Traffic Generator Port ({tgen_pbm_port}) "
                        "Diagnostics:")

                    ps_cmd = f"ps {tgen_pbm_port}"
                    log.info(f"Executing: {ps_cmd}")
                    ps_result = sonic_snake_helper.run_bcm_command(ps_cmd)
                    if ps_result['success']:
                        output = ps_result['stdout']
                        log.info("Port status output:\n" + output)
                    else:
                        log.error(
                            f"Failed to get port status: "
                            f"{ps_result['stderr']}")

                    portcontrol_cmd = (
                        f"portcontrol {tgen_pbm_port} bcmPortControlBridge")
                    log.info(f"Executing: {portcontrol_cmd}")
                    portcontrol_result = sonic_snake_helper.run_bcm_command(
                        portcontrol_cmd)
                    if portcontrol_result['success']:
                        log.info(
                            "Port control bridge output:\n"
                            f"{portcontrol_result['stdout']}")
                    else:
                        log.error(
                            "Failed to get port control bridge: "
                            f"{portcontrol_result['stderr']}")

                    cstat_tgen_cmd = f"cstat {tgen_pbm_port}"
                    log.info(f"Executing: {cstat_tgen_cmd}")
                    cstat_tgen_result = sonic_snake_helper.run_bcm_command(cstat_tgen_cmd)
                    if cstat_tgen_result['success']:
                        output = cstat_tgen_result['stdout']
                        log.info("Traffic generator port statistics:\n" + output)
                    else:
                        log.error(
                            "Failed to get traffic generator port "
                            f"statistics: {cstat_tgen_result['stderr']}")

                if tx_pbm_port:
                    cstat_tx_cmd = f"cstat {tx_pbm_port}"
                    log.info(f"Executing: {cstat_tx_cmd}")
                    cstat_tx_result = sonic_snake_helper.run_bcm_command(cstat_tx_cmd)
                    if cstat_tx_result['success']:
                        output = cstat_tx_result['stdout']
                        log.info("TX port statistics:\n" + output)
                    else:
                        log.error(
                            f"Failed to get TX port statistics: "
                            f"{cstat_tx_result['stderr']}")
        else:
            log.error("Traffic generation failed")
            sys.exit(1)

    except Exception as e:
        log.error(f"Traffic generation failed: {str(e)}")
        sys.exit(1)


@cli.command()
@click.option('--tgen-intf', required=True, help='Traffic generator interface name (e.g., Ethernet8)')
def drain(tgen_intf):
    """Drain traffic from traffic generator interface by setting discard=all and monitoring utilization"""
    log.info("SONiC Snake - Drain Traffic")
    log.info(f"Traffic generator interface: {tgen_intf}")

    try:
        # Get combined port mapping
        combined_mapping = sonic_snake_helper.get_port_mapping(_snake)
        if not combined_mapping:
            log.error("Failed to get combined port mapping")
            sys.exit(1)

        # Validate traffic generator interface exists
        if tgen_intf not in combined_mapping:
            log.error(f"Traffic generator interface '{tgen_intf}' not found")
            sys.exit(1)

        # Get PBM port for traffic generator interface
        tgen_info = combined_mapping[tgen_intf]
        tgen_pbm_port = tgen_info.get('Pbm')

        if not tgen_pbm_port:
            log.error(f"No PBM port found for traffic generator interface '{tgen_intf}'")
            sys.exit(1)

        log.info(f"Traffic generator PBM port: {tgen_pbm_port}")

        # Step 1: Set discard=all to drain traffic
        log.info(f"Step 1: Setting discard=all on traffic generator port {tgen_pbm_port}")
        if not _snake.set_discard(tgen_pbm_port, 'all'):
            log.error("Failed to set discard=all")
            sys.exit(1)

        log.info(f"✓ Successfully set discard=all on port {tgen_pbm_port}")

        # Step 2: Wait initial time for traffic to drain
        initial_wait = 3
        log.info(f"Step 2: Waiting {initial_wait} seconds for traffic to drain...")
        time.sleep(initial_wait)

        # Step 3: Monitor utilization until it reaches 0
        log.info("Step 3: Monitoring utilization until it reaches 0...")
        max_attempts = 10

        for attempt in range(1, max_attempts + 1):
            log.info(f"  Attempt {attempt}/{max_attempts}: Checking utilization...")

            # Get and parse utilization statistics using existing helper
            # function. Note: We use tgen_intf for both parameters since
            # we only care about the traffic generator interface
            (tgen_tx_util, tgen_rx_util,
             success) = sonic_snake_helper.get_and_parse_utilization_stats(
                 tgen_intf, tgen_intf)

            if not success:
                log.error("  Error getting utilization statistics")
                time.sleep(2)
                continue

            # Check if both TX and RX utilizations are 0 or very close to 0
            if tgen_tx_util <= 0.1 and tgen_rx_util <= 0.1:
                # Allow small tolerance
                log.info(
                    f"  ✓ Utilization reached near-zero "
                    f"(TX: {format(tgen_tx_util, ".1f")}%, RX: {format(tgen_rx_util, ".1f")}%)")
                log.info(
                    f"✓ Traffic successfully drained from {tgen_intf}")
                break
            else:
                log.info(
                    f"  Traffic still present "
                    f"(TX: {format(tgen_tx_util, ".1f")}%, RX: {format(tgen_rx_util, ".1f")}%)")

            # Wait before next attempt
            if attempt < max_attempts:
                time.sleep(2)
        else:
            # If we reach here, max attempts exceeded
            log.warning(
                f"Traffic may not be fully drained after "
                f"{max_attempts} attempts")
            log.warning(
                "Utilization monitoring was inconclusive, but proceeding "
                "with cleanup")

        # Step 4: Restore discard mode to none
        log.info(
            f"Step 4: Restoring discard mode to none on traffic generator "
            f"port {tgen_pbm_port}")
        if not _snake.set_discard(tgen_pbm_port, 'none'):
            log.warning("Failed to restore discard=none")
        else:
            log.info(
                f"✓ Successfully restored discard=none on port "
                f"{tgen_pbm_port}")

        log.info(f"✓ Drain operation completed for {tgen_intf}")
        log.info(f"Port {tgen_pbm_port} has been restored to normal operation")

    except Exception as e:
        log.error(f"Drain operation failed: {str(e)}")
        sys.exit(1)


@cli.command()
@click.option('--tgen-intf', required=True, help='Traffic generator interface name (e.g., Ethernet8)')
@click.option('--tx-intf', required=True, help='TX interface name (e.g., Ethernet0)')
@click.option('--rx-intf', required=False, help='RX interface name (e.g., Ethernet4)')
@click.option('--vlan', required=True, type=int, help='VLAN ID to clean up (e.g., 100)')
def cleanup(tgen_intf, tx_intf, rx_intf, vlan):
    """Cleanup traffic generator configuration and restore interfaces to default state"""
    log.info("SONiC Snake - Cleanup")
    log.info(f"Traffic generator interface: {tgen_intf}")
    log.info(f"TX interface: {tx_intf}")
    if rx_intf:
        log.info(f"RX interface: {rx_intf}")
    else:
        log.info("RX interface: None (not specified)")
    log.info(f"VLAN ID: {vlan}")

    try:
        # Get combined port mapping
        log.info("Getting combined port mapping...")
        combined_mapping = sonic_snake_helper.get_port_mapping(_snake)
        if not combined_mapping:
            log.error("Failed to get combined port mapping")
            sys.exit(1)

        # Validate all required interfaces exist
        required_interfaces = [(tgen_intf, 'Traffic generator'), (tx_intf, 'TX')]
        if rx_intf:
            required_interfaces.append((rx_intf, 'RX'))

        for intf_name, intf_type in required_interfaces:
            if intf_name not in combined_mapping:
                log.error(f"{intf_type} interface '{intf_name}' not found")
                sys.exit(1)

        # Get PBM ports for traffic generator and TX interfaces
        tgen_info = combined_mapping[tgen_intf]
        tx_info = combined_mapping[tx_intf]

        tgen_pbm_port = tgen_info.get('Pbm')
        tx_pbm_port = tx_info.get('Pbm')

        if not tgen_pbm_port:
            log.error(f"No PBM port found for traffic generator interface '{tgen_intf}'")
            sys.exit(1)

        if not tx_pbm_port:
            log.error(f"No PBM port found for TX interface '{tx_intf}'")
            sys.exit(1)

        log.info(f"Traffic generator PBM port: {tgen_pbm_port}")
        log.info(f"TX interface PBM port: {tx_pbm_port}")

        # Use the provided VLAN for cleanup
        log.info(f"Using VLAN {vlan} for cleanup")

        # Execute platform-specific BCM cleanup
        mirror_released = False
        try:
            log.info("\n" + "="*70)
            log.info("SONIC SNAKE CLEANUP - BCM Configuration")
            log.info("="*70)
            log.info(f"Port: {tgen_pbm_port}")
            log.info(f"VLAN ID: {vlan}")

            log.info("\n→ Cleaning up traffic generator port...")
            _snake.set_loopback(tgen_pbm_port, 'none')
            _snake.set_bridge(tgen_pbm_port, enabled=False)
            _snake.set_learning(tgen_pbm_port, 0)
            _snake.set_discard(tgen_pbm_port, 'all')
            _snake.set_mcast_flood(vlan, _snake.BCM_VLAN_MCAST_FLOOD_UNKNOWN)
            _snake.remove_from_vlan(vlan, tgen_pbm_port)
            _snake.set_pvid(tgen_pbm_port, 1)

            log.info("\n→ Cleaning up port mirroring...")
            mirror_released = _snake.cleanup_mirror(tgen_pbm_port, tx_pbm_port)

            cleanup_success = True
        except Exception as e:
            log.error(f"Cleanup failed: {e}")
            cleanup_success = False

        # Remove from VLAN using BCM command
        log.info(f"\n→ Removing {tgen_intf} from VLAN {vlan}...")
        _snake.remove_from_vlan(vlan, tgen_pbm_port)

        # Cleanup scheduler AFTER BCM cleanup
        log.info("\n→ Cleaning up scheduler...")
        if not sonic_snake_helper.cleanup_scheduler(tgen_intf, _snake):
            log.warning("Scheduler cleanup failed")
        else:
            time.sleep(2)

        # setup auto-creates this VLAN, so remove it here rather than
        # leaving an empty VLAN behind on every run.
        log.info(f"\n→ Removing VLAN {vlan}...")
        sonic_snake_helper.delete_vlan(vlan)

        if cleanup_success:
            if mirror_released:
                log.info("✓ Cleanup completed successfully!")
                log.info(
                    f"Traffic generator interface '{tgen_intf}' and TX "
                    f"interface '{tx_intf}' restored to default state")
            else:
                log.warning(
                    "Cleanup completed, but the mirror destination for TX "
                    f"interface '{tx_intf}' could not be released" "; see the "
                    "messages above")

            # Print final counter stats for verification if RX interface is specified
            if rx_intf:
                log.info("Waiting 5 seconds for counters to stabilize...")
                time.sleep(5)

                log.info("Final counter statistics:")

                # Get both interface stats in one call
                final_stats = sonic_snake_helper.get_interface_statistics([tx_intf, rx_intf])
                tx_stats = final_stats[tx_intf]
                rx_stats = final_stats[rx_intf]

                if not tx_stats.get('ERROR'):
                    tx_ok = tx_stats.get('TX_OK', 'N/A')
                    log.info(f"TX interface '{tx_intf}' TX_OK: {tx_ok}")
                else:
                    log.error(f"TX interface '{tx_intf}' TX_OK: Error getting stats")

                if not rx_stats.get('ERROR'):
                    rx_ok = rx_stats.get('RX_OK', 'N/A')
                    log.info(f"RX interface '{rx_intf}' RX_OK: {rx_ok}")
                else:
                    log.error(f"RX interface '{rx_intf}' RX_OK: Error getting stats")

                # Compare TX_OK and RX_OK
                if (not tx_stats.get('ERROR') and
                        not rx_stats.get('ERROR') and
                        tx_stats.get('TX_OK', 'N/A') != 'N/A' and
                        rx_stats.get('RX_OK', 'N/A') != 'N/A'):
                    try:
                        tx_count = int(tx_stats['TX_OK'].replace(',', ''))
                        rx_count = int(rx_stats['RX_OK'].replace(',', ''))
                        if tx_count == rx_count:
                            log.info(
                                f"✓ TX_OK and RX_OK counters match: "
                                f"{tx_count}")
                        else:
                            log.warning(
                                f"TX_OK ({tx_count}) and RX_OK ({rx_count}) "
                                f"counters do not match")
                            log.warning(
                                f"   Difference: "
                                f"{abs(tx_count - rx_count)} packets")
                    except (ValueError, AttributeError):
                        log.warning(
                            "Could not compare TX_OK and RX_OK counters "
                            "(format issue)")
                else:
                    log.warning(
                        "Could not compare TX_OK and RX_OK counters "
                        "(stats unavailable)")

        else:
            log.error("Cleanup failed - some BCM commands failed")
            sys.exit(1)

    except Exception as e:
        log.error(f"Cleanup failed: {str(e)}")
        sys.exit(1)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == '__main__':
    cli()
