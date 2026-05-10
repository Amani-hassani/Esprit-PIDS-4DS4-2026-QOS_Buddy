"""
QoS Buddy - Network Data Acquisition Framework
Phase A: Real-World Data Collection with Automatic Anomaly Detection

Author: QoS Buddy Team
Version: 1.2
Date: 2026-03-17
"""

import csv
import json
import os
import glob
import re
import time
import threading
import subprocess
import platform
import socket
import urllib.request
import xml.etree.ElementTree as ET
import psutil
import logging
from qos_buddy.config import TunisianNetworkConfig, setup_logging      
from qos_buddy.collector import QoSBuddyCollector

# Initialize logger for main script
logger = logging.getLogger("QoSBuddy")
def main():
    """Main entry point with CLI arguments"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='QoS Buddy - Network Data Acquisition Framework',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect data for 1 hour (WiFi metrics always collected)
  python qos_buddy_collector.py --duration 60

  # Huawei 4G/5G router at 192.168.8.1 — adds RSRP/RSRQ/SINR from the router API
  python qos_buddy_collector.py --router-gateway 192.168.8.1 --duration 60

  # ZTE router + specific router type
  python qos_buddy_collector.py --router-gateway 192.168.0.1 --router-type zte --duration 60

  # Android phone connected via USB — auto-detects authorized ADB device
  python qos_buddy_collector.py --router-gateway 192.168.8.1 --duration 60

  # Run baseline scenario
  python qos_buddy_collector.py --scenario baseline --duration 15

  # Run congestion test against remote iperf3 server (real network load)
  python qos_buddy_collector.py --scenario congestion --duration 20

  # Use a custom iperf3 server
  python qos_buddy_collector.py --scenario congestion --iperf3-server ping.online.net --duration 15

  # Specify custom zone/cell/node
  python qos_buddy_collector.py --zone Z2 --cell C3 --node N5 --duration 30
        """
    )
    
    parser.add_argument('--duration', type=int, default=60,
                       help='Collection duration in minutes (0 = unlimited, default: 60)')
    parser.add_argument('--interval', type=int, default=30,
                       help='Sampling interval in seconds (default: 30)')
    parser.add_argument('--scenario', choices=['baseline', 'congestion', 'packet_loss', 'throughput', 'normal'],
                       default='normal', help='Test scenario to run (default: normal)')
    parser.add_argument('--zone', default='Z2',
                       help='Zone ID (default: Z2)')
    parser.add_argument('--cell', default='C1',
                       help='Cell ID (default: C1)')
    parser.add_argument('--node', default='N1',
                       help='Node ID (default: N1)')
    parser.add_argument('--device-type', default='workstation',
                       help='Device type (default: workstation)')
    parser.add_argument('--iperf3-server', default=None,
                       help='Remote iperf3 server hostname (default: bouygues.iperf.fr)')
    parser.add_argument('--iperf3-port', type=int, default=None,
                       help='Remote iperf3 server port (default: 5201)')
    parser.add_argument('--with-iperf3', action='store_true',
                       help='Include periodic iperf3 tests during collection for CSSR metric')
    parser.add_argument('--choice', type=int, default=None,
                       help='Menu choice number (1-13) to organize data in separate folders')
    parser.add_argument('--all-scenarios', action='store_true',
                       help='Run all scenarios (baseline, congestion, packet_loss) sequentially with iperf3')
    parser.add_argument('--structured-pattern', action='store_true',
                       help='Run structured scenario pattern: baseline + [congestion x2 + normal x2 + packet_loss x2 + normal x2] repeat')
    parser.add_argument('--infinite', action='store_true',
                       help='Run indefinitely until manually stopped (Ctrl+C) or computer shuts down')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging (shows DEBUG level details: iperf3 tests, router login, metrics retrieval, scenarios, etc.)')

    # ---- Radio / Router / ADB options ----
    parser.add_argument('--router-gateway', default=None, metavar='IP',
                       help='4G/5G router admin IP for cellular metrics collection')
    parser.add_argument('--router-username', default=None, metavar='USERNAME',
                       help='Router admin username for API authentication')
    parser.add_argument('--router-password', default=None, metavar='PASSWORD',
                       help='Router admin password for API authentication')


    args = parser.parse_args()

    # Setup logging with verbose option
    setup_logging(log_dir="logs", verbose=args.verbose)
    logger = logging.getLogger("QoSBuddy")
    
    if args.verbose:
        logger.info("")
        logger.info("="*80)
        logger.info("[VERBOSE MODE] Showing detailed debug information")
        logger.info("="*80)
        logger.info("Tracking: iperf3 tests, scenarios, router login, metrics retrieval...")
        logger.info("="*80 + "")
    
    # Configure iperf3 remote server if specified
    config = TunisianNetworkConfig.from_yaml()  # Load from config.yaml, fall back to defaults
    if args.iperf3_server:
        config.IPERF3_REMOTE_SERVER = args.iperf3_server
    if args.iperf3_port:
        config.IPERF3_REMOTE_PORT = args.iperf3_port

    # Apply router settings if provided
    if args.router_gateway:
        config.ROUTER_GATEWAY = args.router_gateway
    if args.router_username:
        config.ROUTER_USERNAME = args.router_username
    if args.router_password:
        config.ROUTER_PASSWORD = args.router_password
    

    
    # Initialize collector
    collector = QoSBuddyCollector(
        zone_id=args.zone,
        cell_id=args.cell,
        node_id=args.node,
        device_type=args.device_type,
        config=config,
        choice=args.choice
    )
    
    # Run collection
    # If infinite mode is enabled, pass duration as 0 (infinite)
    duration = 0 if args.infinite else args.duration
    
    # Enable structured pattern if choice is 13
    if args.choice == 13:
        args.structured_pattern = True
    
    if args.structured_pattern:
        # Choice 13: Run structured scenario pattern
        collector.run_structured_scenario_pattern(num_cycles=duration if duration > 0 else 0)
    elif args.all_scenarios:
        # Choice 12: Run all scenarios with continuous iperf3
        collector.run_all_scenarios_with_iperf3(duration_per_scenario=duration)
    elif args.scenario != 'normal':
        # Choice 6: Run specific scenario with iperf3
        collector.run_scenario(args.scenario, duration_minutes=duration)
    else:
        # Default live monitoring mode (NO synthetic load).
        # Collect passive KPIs only, every `--interval` seconds (default: 30).
        #
        # IMPORTANT: Do NOT run iperf3 by default — it generates artificial traffic and
        # distorts "live network state" views. Operators can still opt-in explicitly
        # via scenarios or `--with-iperf3` when they intentionally want a load test.
        collector.run_collection(duration_minutes=duration, interval_seconds=args.interval)



if __name__ == '__main__':
    import sys
    import atexit
    
    def cleanup():
        """Ensure all background processes are terminated"""
        try:
            import subprocess
            subprocess.run(["taskkill", "/F", "/IM", "chromedriver.exe"], 
                         stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        except:
            pass
    
    atexit.register(cleanup)
    
    try:
        main()
        sys.exit(0)  # Success
    except Exception as e:
        logger.error(f"FATAL ERROR: {str(e)}", exc_info=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
