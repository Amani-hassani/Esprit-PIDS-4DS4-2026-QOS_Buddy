"""
QoS Buddy - Network Data Acquisition Framework
Phase A: Real-World Data Collection with Automatic Anomaly Detection

Author: QoS Buddy Team
Version: 1.2
Date: 2026-03-17
"""

import json
import os
import glob
import re
import time
import subprocess
import platform
import socket
import psutil
import logging
from datetime import datetime
from collections import deque
import numpy as np
from typing import Dict, Tuple, Optional


# ==================== IPERF3 BANDWIDTH TESTING ====================
from qos_buddy.config import TunisianNetworkConfig
from qos_buddy.net_utils import find_default_gateway, is_auto_sentinel

# Initialize logger
logger = logging.getLogger("QoSBuddy")


class Iperf3Manager:
    """Manages iperf3 bandwidth testing for network scenarios"""
    
    def __init__(self, config: 'TunisianNetworkConfig' = None):  # type: ignore
        self.config = config or TunisianNetworkConfig()
        self.server_proc = None
        self.server_running = False
        self.iperf3_cmd = self._find_iperf3_cmd()
        self.iperf3_available = self._check_iperf3_available()
        self._current_server_index = 0  # For server rotation
    
    def _find_iperf3_cmd(self) -> str:
        """Find the iperf3 executable - check local directory, subdirs, then PATH"""
        # Check if iperf3.exe exists in the script's directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        local_iperf3 = os.path.join(script_dir, 'iperf3.exe')
        if os.path.isfile(local_iperf3):
            return local_iperf3
        
        # Check subdirectories (e.g., iperf3.20/iperf3.exe)
        for match in glob.glob(os.path.join(script_dir, '*', 'iperf3.exe')):
            if os.path.isfile(match):
                return match
        
        # Check parent directory (workspace root) subdirectories
        parent_dir = os.path.dirname(script_dir)
        for match in glob.glob(os.path.join(parent_dir, '*', 'iperf3.exe')):
            if os.path.isfile(match):
                return match
        
        # Check current working directory
        cwd_iperf3 = os.path.join(os.getcwd(), 'iperf3.exe')
        if os.path.isfile(cwd_iperf3):
            return cwd_iperf3
        
        # Fallback to PATH
        return 'iperf3'
        
    def _check_iperf3_available(self) -> bool:
        """Check if iperf3 is installed and available"""
        try:
            result = subprocess.run([self.iperf3_cmd, '--version'], 
                                  capture_output=True, timeout=2)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            logger.warning("iperf3 not found. Some scenarios will run with reduced functionality.")
            return False
    
    def _kill_existing_iperf3(self):
        """Kill any existing iperf3 processes to free the port"""
        try:
            if platform.system() == 'Windows':
                subprocess.run(['taskkill', '/F', '/IM', 'iperf3.exe'],
                             capture_output=True, timeout=5)
            else:
                subprocess.run(['pkill', '-f', 'iperf3'],
                             capture_output=True, timeout=5)
            time.sleep(2)  # Wait for port to be released from TIME_WAIT
        except Exception:
            pass

    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available for binding"""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return True
        except OSError:
            return False

    def start_server(self, port: int = 5201, daemon: bool = True) -> bool:
        """
        Start iperf3 server in background
        Returns: True if successful, False otherwise
        """
        if not self.iperf3_available:
            logger.warning("iperf3 not available, skipping server start")
            return False
        
        try:
            # Kill any existing iperf3 processes first
            if not self._is_port_available(port):
                logger.info(f"Port {port} in use, killing existing iperf3 processes...")
                self._kill_existing_iperf3()
                # Wait for port to become available (TIME_WAIT cleanup)
                for _ in range(5):
                    if self._is_port_available(port):
                        break
                    time.sleep(2)
                else:
                    logger.error(f"Port {port} still in use after cleanup")
                    return False

            logger.info(f"Starting iperf3 server on port {port}...")
            
            if platform.system() == 'Windows':
                cmd = f"\"{self.iperf3_cmd}\" -s -p {port}"
                self.server_proc = subprocess.Popen(
                    cmd, 
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=True
                )
            else:
                cmd = f"{self.iperf3_cmd} -s -p {port} -D"
                self.server_proc = subprocess.Popen(
                    cmd.split(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            
            time.sleep(3)  # Give server enough time to start and bind
            self.server_running = True
            logger.info(f"iperf3 server started successfully")
            return True
        except Exception as e:
            logger.error(f"Error starting iperf3 server: {str(e)}")
            self.server_running = False
            return False
    
    def stop_server(self) -> bool:
        """Stop iperf3 server gracefully"""
        try:
            if self.server_proc:
                if platform.system() == 'Windows':
                    subprocess.run(['taskkill', '/F', '/IM', 'iperf3.exe'],
                                 capture_output=True, timeout=5)
                else:
                    self.server_proc.terminate()
                    self.server_proc.wait(timeout=3)
                
                self.server_running = False
                logger.info("iperf3 server stopped")
                return True
        except Exception as e:
            logger.error(f"Error stopping iperf3 server: {str(e)}")
        
        return False
    
    def run_bandwidth_test(self, target: str = 'localhost', port: int = 5201,
                          duration: int = 10, reverse: bool = False,
                          retries: int = 3, retry_delay: int = 5) -> Dict:
        """
        Run iperf3 client test with automatic retries and detailed diagnostics
        Args:
            target: Target server IP/hostname
            port: Target iperf3 server port
            duration: Test duration in seconds
            reverse: If True, measure reverse direction (server→client)
            retries: Number of retry attempts if test fails
            retry_delay: Seconds to wait between retries
        
        Returns: Dictionary with test results or empty dict if failed
        """
        if not self.iperf3_available:
            logger.warning("iperf3 not available, cannot run bandwidth test")
            return {}
        
        for attempt in range(1, retries + 1):
            try:
                test_start = datetime.now()
                logger.info(f"[iperf3] Attempt {attempt}/{retries}: {target}:{port} for {duration}s ({'reverse' if reverse else 'forward'})")
                
                cmd = [self.iperf3_cmd, '-c', target, '-p', str(port), '-t', str(duration), '-J']
                
                if reverse:
                    cmd.append('-R')
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    errors='replace',
                    timeout=duration + 15
                )
                
                test_elapsed = (datetime.now() - test_start).total_seconds()
                
                if result.returncode != 0:
                    error_msg = (result.stderr.strip() or result.stdout.strip())
                    # Server busy = reachable but occupied, worth retrying
                    if 'busy' in error_msg.lower():
                        logger.info(f"[iperf3] Server busy at {target}:{port} (attempt {attempt}/{retries}), will retry in {retry_delay}s")
                    else:
                        logger.error(f"[iperf3] Test failed after {test_elapsed:.1f}s (attempt {attempt}/{retries}): {error_msg[:100]}")
                    if attempt < retries:
                        time.sleep(retry_delay)
                        continue
                    logger.error(f"[iperf3] All {retries} attempts failed for {target}:{port}")
                    return {}
                
                # Parse JSON output
                try:
                    output = json.loads(result.stdout)
                    
                    # Extract throughput
                    if 'end' in output and 'sum_received' in output['end']:
                        bits_per_second = output['end']['sum_received'].get('bits_per_second', 0)
                        mbps = bits_per_second / 1_000_000
                        transferred_bytes = output['end']['sum_received'].get('bytes', 0)
                        
                        results = {
                            'throughput_bps': bits_per_second,
                            'throughput_mbps': mbps,
                            'duration_sec': duration,
                            'transferred_bytes': transferred_bytes,
                            'test_type': 'reverse' if reverse else 'forward'
                        }
                        
                        logger.info(f"[iperf3] SUCCESS: {mbps:.2f} Mbps ({transferred_bytes/1024/1024:.1f} MB transferred) in {test_elapsed:.1f}s")
                        return results
                    else:
                        logger.error(f"[iperf3] Invalid JSON structure: missing 'end' or 'sum_received' in output")
                        if attempt < retries:
                            time.sleep(retry_delay)
                            continue
                        return {}
                except json.JSONDecodeError as e:
                    logger.error(f"[iperf3] JSON decode error on attempt {attempt}: {str(e)[:60]}")
                    if attempt < retries:
                        time.sleep(retry_delay)
                        continue
                    return {}
            
            except subprocess.TimeoutExpired:
                logger.error(f"[iperf3] Test timeout after {duration + 15}s (attempt {attempt}/{retries})")
                if attempt < retries:
                    time.sleep(retry_delay)
                    continue
            except Exception as e:
                logger.error(f"[iperf3] Unexpected error on attempt {attempt}/{retries}: {str(e)}")
                if attempt < retries:
                    time.sleep(retry_delay)
                    continue
        
        logger.error(f"[iperf3] All retry attempts exhausted for {target}:{port}")
        return {}

    def test_remote_server(self, server: str, port: int, max_attempts: int = 5, timeout: int = 15) -> bool:
        """
        Quick test to verify a remote iperf3 server is reachable.
        Retries a few times since public servers can be busy.
        """
        if not self.iperf3_available:
            return False
        
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Testing remote iperf3 server {server}:{port} (attempt {attempt}/{max_attempts})...")
                cmd = [self.iperf3_cmd, '-c', server, '-p', str(port), '-t', '2', '-J']
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    errors='replace',
                    timeout=timeout
                )
                
                if result.returncode == 0:
                    logger.info(f"Remote server {server}:{port} is reachable")
                    return True
                
                stderr = result.stderr.strip()
                stdout = result.stdout.strip()
                error_text = stderr or stdout
                
                # "server is busy" means it IS reachable, just occupied — retry
                if 'busy' in error_text.lower():
                    logger.info(f"Server {server}:{port} is busy, retrying in 5s...")
                    time.sleep(5)
                    continue
                
                logger.warning(f"Remote server test failed (attempt {attempt}): {error_text}")
                if attempt < max_attempts:
                    time.sleep(3)
                    continue
                    
            except subprocess.TimeoutExpired:
                logger.warning(f"Remote server {server}:{port} connection timed out (attempt {attempt})")
                if attempt < max_attempts:
                    time.sleep(3)
                    continue
            except Exception as e:
                logger.warning(f"Remote server test error (attempt {attempt}): {str(e)}")
                if attempt < max_attempts:
                    time.sleep(3)
                    continue
        
        logger.warning(f"Remote server {server}:{port} not available after {max_attempts} attempts")
        return False

    def _quick_tcp_check(self, server: str, port: int, timeout: float = 5.0) -> bool:
        """
        Fast TCP socket connect to check if the server port is open.
        Much faster than running a full iperf3 test.
        Returns True if the TCP port is open (server is listening).
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((server, port))
            sock.close()
            if result == 0:
                logger.info(f"TCP port open: {server}:{port}")
                return True
            else:
                logger.debug(f"TCP port closed: {server}:{port} (code={result})")
                return False
        except socket.timeout:
            logger.debug(f"TCP connect timeout: {server}:{port}")
            return False
        except socket.gaierror:
            logger.debug(f"DNS resolution failed: {server}")
            return False
        except Exception as e:
            logger.debug(f"TCP check error for {server}:{port}: {e}")
            return False
    
    def select_best_server(self, server_performance: Dict = None, server_pool: list = None) -> tuple:
        """
        IMPROVEMENT #2: Intelligent server selection based on historical performance.
        
        Selects the best-performing server from the pool based on:
        1. Success rate (higher is better)
        2. Average bandwidth (higher is better)
        3. Falls back to servers by quality
        
        Args:
            server_performance: Dict of {(server, port): {'successes': int, 'failures': int, 'avg_bandwidth': float}}
            server_pool: List of (server, port) tuples to choose from
        
        Returns:
            (server, port) tuple of best server, or first in pool if no history
        """
        if not server_pool:
            server_pool = self.config.IPERF3_SERVER_POOL
        
        if not server_performance or not server_pool:
            # No performance history, use first server
            return server_pool[0] if server_pool else (self.config.IPERF3_REMOTE_SERVER, self.config.IPERF3_REMOTE_PORT)
        
        # Score each server: (success_rate * 0.6) + (normalized_bandwidth * 0.4)
        scores = {}
        for server, port in server_pool:
            key = (server, port)
            if key in server_performance:
                stats = server_performance[key]
                total = stats['total_tests']
                if total > 0:
                    success_rate = stats['successes'] / total
                    bandwidth = stats['avg_bandwidth']
                    # Normalize bandwidth to 0-1 scale (assuming max 50 Mbps)
                    bandwidth_norm = min(1.0, bandwidth / 50.0)
                    score = (success_rate * 0.6) + (bandwidth_norm * 0.4)
                    scores[key] = score
                    logger.debug(f"[SERVER_SELECT] {server}:{port} - score: {score:.3f} (success: {success_rate:.1%}, bw: {bandwidth:.1f}Mbps)")
            else:
                # No history, neutral score
                scores[key] = 0.5
                logger.debug(f"[SERVER_SELECT] {server}:{port} - no history yet, neutral score")
        
        # Sort by score (highest first) and return best
        if scores:
            best_server = max(scores.items(), key=lambda x: x[1])[0]
            logger.info(f"[SERVER_SELECT] Selected {best_server[0]}:{best_server[1]} (score: {scores[best_server]:.3f})")
            return best_server
        
        return server_pool[0] if server_pool else (self.config.IPERF3_REMOTE_SERVER, self.config.IPERF3_REMOTE_PORT)
    
    def run_bandwidth_test_with_fallback(self, duration: int = 10, reverse: bool = False,
                                        server_performance: Dict = None, server_pool: list = None) -> Dict:
        """
        IMPROVEMENT #3: Run bandwidth test with intelligent server fallback.
        
        1. Selects best server based on history
        2. If that fails, tries fallback servers
        3. Returns result with server info for tracking
        
        Args:
            duration: Test duration in seconds
            reverse: Test direction
            server_performance: Performance tracking dict
            server_pool: List of (server, port) tuples
        
        Returns:
            Dict with 'success', 'bandwidth_mbps', 'server', 'port', etc.
        """
        if not server_pool:
            server_pool = self.config.IPERF3_SERVER_POOL
        
        # Select best server first
        best_server, best_port = self.select_best_server(server_performance, server_pool)
        
        # Try best server first, then fallback to others
        servers_to_try = [(best_server, best_port)]
        # Add fallback servers (all others)
        for server, port in server_pool:
            if (server, port) != (best_server, best_port):
                servers_to_try.append((server, port))
        
        for server, port in servers_to_try:
            logger.debug(f"[FALLBACK] Attempting {server}:{port}")
            result = self.run_bandwidth_test(target=server, port=port, duration=duration, 
                                           reverse=reverse, retries=2, retry_delay=2)
            
            if result and result.get('throughput_mbps', 0) > 0:
                result['server'] = server
                result['port'] = port
                result['success'] = True
                logger.info(f"[FALLBACK] SUCCESS on {server}:{port}")
                
                # Update performance tracking if provided
                if server_performance is not None:
                    key = (server, port)
                    if key not in server_performance:
                        server_performance[key] = {'successes': 0, 'failures': 0, 'avg_bandwidth': 0, 'total_tests': 0}
                    server_performance[key]['successes'] += 1
                    server_performance[key]['total_tests'] += 1
                    server_performance[key]['avg_bandwidth'] = (
                        (server_performance[key]['avg_bandwidth'] * (server_performance[key]['successes'] - 1) + 
                         result['throughput_mbps']) / server_performance[key]['successes']
                    )
                
                return result
            else:
                # Track failure
                if server_performance is not None:
                    key = (server, port)
                    if key not in server_performance:
                        server_performance[key] = {'successes': 0, 'failures': 0, 'avg_bandwidth': 0, 'total_tests': 0}
                    server_performance[key]['failures'] += 1
                    server_performance[key]['total_tests'] += 1
                logger.debug(f"[FALLBACK] FAILED on {server}:{port}, trying next...")
        
        logger.error(f"[FALLBACK] All servers exhausted, returning empty result")
        return {'success': False, 'server': 'none', 'port': 0}

    def get_available_server(self) -> Optional[Tuple[str, int]]:
        """
        Find an available iperf3 server from the pool.
        Uses fast TCP pre-check to skip unreachable servers quickly,
        then does a brief iperf3 handshake to verify it works.
        Returns: (server, port) tuple or None if all servers are unreachable.
        """
        if not self.iperf3_available:
            return None
        
        server_pool = getattr(self.config, 'IPERF3_SERVER_POOL', [])
        if not server_pool:
            server = getattr(self.config, 'IPERF3_REMOTE_SERVER', 'iperf.he.net')
            port = getattr(self.config, 'IPERF3_REMOTE_PORT', 5201)
            return (server, port) if self.test_remote_server(server, port, max_attempts=2, timeout=10) else None
        
        # Phase 1: Fast TCP check to find servers with open ports (skips unreachable ones in ~5s)
        reachable = []
        for i in range(len(server_pool)):
            idx = (self._current_server_index + i) % len(server_pool)
            server, port = server_pool[idx]
            logger.info(f"Quick check: {server}:{port}...")
            if self._quick_tcp_check(server, port, timeout=5.0):
                reachable.append((idx, server, port))
        
        if not reachable:
            logger.warning("No iperf3 servers have open ports")
            return None
        
        logger.info(f"Found {len(reachable)} reachable server(s), testing iperf3 handshake...")
        
        # Phase 2: Quick iperf3 test on reachable servers only (1 attempt, 8s timeout)
        for idx, server, port in reachable:
            if self.test_remote_server(server, port, max_attempts=1, timeout=8):
                self._current_server_index = (idx + 1) % len(server_pool)
                return (server, port)
            logger.info(f"{server}:{port} TCP open but iperf3 handshake failed (busy/version), skipping")
        
        # Phase 3: Try busy servers with a second attempt (they may free up)
        for idx, server, port in reachable:
            logger.info(f"Retrying {server}:{port}...")
            time.sleep(3)
            if self.test_remote_server(server, port, max_attempts=1, timeout=8):
                self._current_server_index = (idx + 1) % len(server_pool)
                return (server, port)
        
        logger.warning("No iperf3 servers available from the pool (all busy or incompatible)")
        return None

    def run_bandwidth_test_with_rotation(self, duration: int = 10, reverse: bool = False) -> Dict:
        """
        Run iperf3 test, rotating through servers if one is busy.
        Uses 3-phase approach: TCP check → iperf3 handshake → retry busy servers.
        Returns: Dictionary with test results or empty dict if all failed.
        """
        if not self.iperf3_available:
            logger.warning("iperf3 not available, cannot run bandwidth test")
            return {}
        
        logger.info(f"Starting iperf3 bandwidth test ({duration}s, {'reverse' if reverse else 'forward'})")
        
        server_pool = getattr(self.config, 'IPERF3_SERVER_POOL', [])
        if not server_pool:
            server = getattr(self.config, 'IPERF3_REMOTE_SERVER', 'iperf3.moji.fr')
            port = getattr(self.config, 'IPERF3_REMOTE_PORT', 5200)
            logger.info(f"Using single server: {server}:{port}")
            return self.run_bandwidth_test(server, port, duration, reverse, retries=3, retry_delay=5)
        
        # Phase 1: Fast TCP check to find reachable servers
        logger.info(f"Phase 1: Checking {len(server_pool)} server(s) availability...")
        reachable = []
        for i in range(len(server_pool)):
            idx = (self._current_server_index + i) % len(server_pool)
            server, port = server_pool[idx]
            
            if self._quick_tcp_check(server, port, timeout=5.0):
                reachable.append((idx, server, port))
                logger.info(f"  [OK] {server}:{port} is reachable")
            else:
                logger.debug(f"  [SKIP] {server}:{port} (port not open)")
        
        if not reachable:
            logger.error("No iperf3 servers have open ports, returning empty result")
            return {}
        
        logger.info(f"Phase 2: Testing iperf3 on {len(reachable)} reachable server(s)...")
        
        # Phase 2: Test reachable servers
        for idx, server, port in reachable:
            logger.info(f"Attempting {server}:{port}...")
            result = self.run_bandwidth_test(server, port, duration, reverse, retries=2, retry_delay=3)
            if result:
                self._current_server_index = (idx + 1) % len(server_pool)
                logger.info(f"[OK] Success on {server}:{port}: {result.get('throughput_mbps', 0):.2f} Mbps")
                return result
            else:
                logger.debug(f"Server {server}:{port} TCP open but iperf3 test failed")
        
        logger.warning(f"All {len(reachable)} reachable server(s) failed iperf3 test, no bandwidth data available")
        return {}

    def run_udp_flood_test(self, target: str, port: int, duration: int = 10,
                          bandwidth: str = '50M', reverse: bool = True,
                          retries: int = 2, retry_delay: int = 3) -> Dict:
        """
        Run iperf3 UDP flood test to induce and measure real packet loss.
        
        Args:
            target: Target server IP/hostname
            port: Target iperf3 server port  
            duration: Test duration in seconds
            bandwidth: Target UDP bandwidth (e.g. '50M', '100M') - set higher than link speed
            reverse: If True, flood download direction (server→client)
            retries: Number of retry attempts
            retry_delay: Seconds between retries
        
        Returns: Dict with throughput, packet_loss_pct, jitter, etc. or empty dict if failed
        """
        if not self.iperf3_available:
            return {}
        
        for attempt in range(1, retries + 1):
            try:
                logger.info(f"Running iperf3 UDP flood: {target}:{port} -b {bandwidth} for {duration}s (attempt {attempt}/{retries})")
                
                cmd = [self.iperf3_cmd, '-c', target, '-p', str(port), '-t', str(duration),
                       '-u', '-b', bandwidth, '-J']
                
                if reverse:
                    cmd.append('-R')
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    errors='replace',
                    timeout=duration + 15
                )
                
                if result.returncode != 0:
                    error_msg = (result.stderr.strip() or result.stdout.strip())
                    if 'busy' in error_msg.lower():
                        logger.info(f"iperf3 server busy (attempt {attempt}), retrying in {retry_delay}s...")
                    else:
                        logger.warning(f"iperf3 UDP test failed (attempt {attempt}): {error_msg}")
                    if attempt < retries:
                        time.sleep(retry_delay)
                        continue
                    return {}
                
                try:
                    output = json.loads(result.stdout)
                    
                    if 'end' in output and 'sum' in output['end']:
                        summary = output['end']['sum']
                        bits_per_second = summary.get('bits_per_second', 0)
                        mbps = bits_per_second / 1_000_000
                        lost = summary.get('lost_packets', 0)
                        total = summary.get('packets', 0)
                        loss_pct = summary.get('lost_percent', 0.0)
                        jitter_ms = summary.get('jitter_ms', 0.0)
                        
                        # If lost_percent not available, calculate it
                        if loss_pct == 0 and total > 0 and lost > 0:
                            loss_pct = (lost / total) * 100.0
                        
                        results = {
                            'throughput_bps': bits_per_second,
                            'throughput_mbps': mbps,
                            'packet_loss_pct': loss_pct,
                            'lost_packets': lost,
                            'total_packets': total,
                            'jitter_ms': jitter_ms,
                            'duration_sec': duration,
                            'test_type': 'udp_reverse' if reverse else 'udp_forward'
                        }
                        
                        logger.info(f"iperf3 UDP result: {mbps:.2f} Mbps | Loss={loss_pct:.1f}% ({lost}/{total} packets) | Jitter={jitter_ms:.1f}ms")
                        return results
                        
                except json.JSONDecodeError:
                    logger.warning("Could not parse iperf3 UDP JSON output")
                    if attempt < retries:
                        time.sleep(retry_delay)
                        continue
                    return {}
            
            except subprocess.TimeoutExpired:
                logger.error(f"iperf3 UDP test timed out (attempt {attempt})")
                if attempt < retries:
                    time.sleep(retry_delay)
                    continue
            except Exception as e:
                logger.error(f"Error running iperf3 UDP test (attempt {attempt}): {str(e)}")
                if attempt < retries:
                    time.sleep(retry_delay)
                    continue
        
        return {}

    def run_udp_flood_with_rotation(self, duration: int = 10, bandwidth: str = '50M',
                                    reverse: bool = True) -> Dict:
        """
        Run UDP flood test, rotating through servers if one is busy.
        Returns: Dictionary with UDP test results or empty dict if all failed.
        """
        if not self.iperf3_available:
            return {}
        
        server_pool = getattr(self.config, 'IPERF3_SERVER_POOL', [])
        if not server_pool:
            server = getattr(self.config, 'IPERF3_REMOTE_SERVER', 'iperf3.moji.fr')
            port = getattr(self.config, 'IPERF3_REMOTE_PORT', 5200)
            return self.run_udp_flood_test(server, port, duration, bandwidth, reverse)
        
        for i in range(len(server_pool)):
            idx = (self._current_server_index + i) % len(server_pool)
            server, port = server_pool[idx]
            
            if not self._quick_tcp_check(server, port, timeout=5.0):
                continue
            
            result = self.run_udp_flood_test(server, port, duration, bandwidth, reverse)
            if result:
                self._current_server_index = (idx + 1) % len(server_pool)
                return result
            
            logger.info(f"Server {server}:{port} unavailable for UDP, trying next...")
        
        logger.warning("All iperf3 servers unavailable for UDP flood")
        return {}


class NetworkMetricsCollector:
    """Collects real-time network performance metrics"""
    
    def __init__(self, config: TunisianNetworkConfig = None): # type: ignore
        self.config = config or TunisianNetworkConfig()
        self.history = deque(maxlen=1000)  # Keep last 1000 measurements for statistics
        configured_gw = getattr(self.config, 'PING_LOCAL_GATEWAY', None)
        if is_auto_sentinel(configured_gw):
            resolved_gw = find_default_gateway()
            local_gateway = resolved_gw or '192.168.1.1'
        else:
            local_gateway = configured_gw
        self.ping_targets = {
            'local_gateway': local_gateway,
            'isp_dns': '8.8.8.8',  # Google DNS (internet path)
            'regional_server': '8.8.8.8'  # Google DNS
        }
    
    def ping_target(self, target: str, count: int = 4, timeout: int = 3) -> Dict:
        """Ping a target and extract RTT, packet loss, jitter (supports English & French locales)
        
        Falls back to local gateway if primary target times out.
        Timeout reduced to 3 seconds for faster failure detection on offline networks.
        """
        try:
            if platform.system() == 'Windows':
                cmd = f"ping -n {count} -w {timeout*1000} {target}"
            else:  # Linux/macOS — -W takes seconds, not milliseconds
                cmd = f"ping -c {count} -W {timeout} {target}"
            
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                errors='replace',
                timeout=timeout+2
            )
            output = result.stdout
            
            rtt_values = []
            
            if platform.system() == 'Windows':
                # Handle both English ('time=45ms', 'time<1ms') and French ('temps=45ms')
                for line in output.split('\n'):
                    m = re.search(r'(?:time|temps)[=<](\d+(?:\.\d+)?)\s*ms', line, re.IGNORECASE)
                    if m:
                        try:
                            rtt_values.append(float(m.group(1)))
                        except ValueError:
                            continue
                
                # Parse packet loss — English: "Packets: Sent = 4" / French: "Paquets : envoyés = 4"
                loss_match = re.search(
                    r'(?:Packets|Paquets)\s*[:：]\s*(?:Sent|envoy[eé]s)\s*=\s*(\d+).*?'
                    r'(?:Received|re[cç]us)\s*=\s*(\d+)',
                    output, re.IGNORECASE | re.DOTALL
                )
                if loss_match:
                    sent = int(loss_match.group(1))
                    received = int(loss_match.group(2))
                    packet_loss = ((sent - received) / sent * 100) if sent > 0 else 0
                else:
                    packet_loss = 0
            
            else:  # Linux/macOS
                for line in output.split('\n'):
                    m = re.search(r'time[=<](\d+(?:\.\d+)?)\s*ms', line, re.IGNORECASE)
                    if m:
                        try:
                            rtt_values.append(float(m.group(1)))
                        except ValueError:
                            continue
                
                packet_loss = 0
                if '% packet loss' in output:
                    packet_loss = float(output.split('% packet loss')[0].split()[-1])
            
            if rtt_values:
                latency_avg = np.mean(rtt_values)
                # RFC 3550 jitter: mean absolute difference between consecutive samples
                if len(rtt_values) >= 2:
                    diffs = [abs(rtt_values[i] - rtt_values[i-1]) for i in range(1, len(rtt_values))]
                    jitter = float(np.mean(diffs))
                else:
                    jitter = 0.0
                return {
                    'target': target,
                    'latency_ms': float(latency_avg),
                    'jitter_ms': jitter,
                    'packet_loss_pct': float(packet_loss),
                    'samples': len(rtt_values)
                }
            
            logger.warning(f"No valid ping responses from {target}")
            # Return timeout value (not 0) to indicate ping timed out
            return {'target': target, 'latency_ms': timeout * 1000, 'jitter_ms': 0, 'packet_loss_pct': 100.0, 'samples': 0}
        
        except Exception as e:
            logger.error(f"Error pinging {target}: {str(e)}")
            # Return timeout value to indicate error/timeout
            return {'target': target, 'latency_ms': timeout * 1000, 'jitter_ms': 0, 'packet_loss_pct': 100.0, 'samples': 0}
    
    
    def _detect_wifi_interface(self) -> Optional[str]:
        """Auto-detect the active WiFi/Ethernet interface name (skip loopback/virtual)"""
        try:
            stats = psutil.net_if_stats()
            counters = psutil.net_io_counters(pernic=True)
            
            # Known WiFi interface name patterns
            wifi_patterns = ['wi-fi', 'wifi', 'wlan', 'wireless', 'ethernet', 'eth']
            # Known virtual/loopback patterns to exclude
            skip_patterns = ['loopback', 'lo', 'vethernet', 'vmnet', 'vbox', 
                           'docker', 'virtualbox', 'hyper-v', 'bluetooth',
                           'isatap', 'teredo', 'vpn']
            
            best_iface = None
            best_bytes = 0
            
            for iface_name, stat in stats.items():
                if not stat.isup:
                    continue
                    
                name_lower = iface_name.lower()
                
                # Skip virtual/loopback interfaces
                if any(skip in name_lower for skip in skip_patterns):
                    continue
                
                # Prefer WiFi-named interfaces
                if iface_name in counters:
                    iface_counters = counters[iface_name]
                    total_bytes = iface_counters.bytes_sent + iface_counters.bytes_recv
                    
                    # Check if it's a WiFi interface by name
                    is_wifi = any(pat in name_lower for pat in wifi_patterns)
                    
                    if is_wifi:
                        if total_bytes > best_bytes:
                            best_iface = iface_name
                            best_bytes = total_bytes
                    elif best_iface is None and total_bytes > best_bytes:
                        # Fallback: use most active non-loopback interface
                        best_iface = iface_name
                        best_bytes = total_bytes
            
            if best_iface:
                logger.debug(f"Detected network interface: {best_iface}")
            return best_iface
        except Exception:
            return None

    def estimate_throughput(self) -> float:
        """
        Estimate real download throughput on the WiFi/Ethernet interface.
        
        Uses a 10-second measurement window for stable readings (increased from 5s for better accuracy).
        Measures download only (bytes_recv) — more meaningful for QoS than
        upload+download combined, and avoids inflated values.
        Uses 1,000,000 (SI) for Mbps conversion (networking standard).
        """
        try:
            measure_window = getattr(self.config, 'THROUGHPUT_MEASURE_WINDOW', 10.0)
            
            # Determine which interface to measure
            iface_name = getattr(self.config, 'WIFI_INTERFACE_NAME', None)
            if iface_name is None:
                iface_name = self._detect_wifi_interface()
            
            if iface_name:
                # Measure specific interface (real WiFi/Ethernet only)
                counters1 = psutil.net_io_counters(pernic=True)
                if iface_name not in counters1:
                    logger.warning(f"Interface '{iface_name}' not found, falling back to all interfaces")
                    iface_name = None
                else:
                    before_recv = counters1[iface_name].bytes_recv
                    before_time = time.time()
                    
                    time.sleep(measure_window)
                    
                    counters2 = psutil.net_io_counters(pernic=True)
                    after_recv = counters2[iface_name].bytes_recv
                    elapsed = time.time() - before_time
                    
                    if elapsed <= 0:
                        return 0.0
                    
                    download_bytes = after_recv - before_recv
                    mbps = (download_bytes * 8) / elapsed / 1_000_000
                    return round(max(0.0, mbps), 2)
            
            # Fallback: all interfaces, download only
            counter1 = psutil.net_io_counters()
            before_recv = counter1.bytes_recv
            before_time = time.time()
            
            time.sleep(measure_window)
            
            counter2 = psutil.net_io_counters()
            after_recv = counter2.bytes_recv
            elapsed = time.time() - before_time
            
            if elapsed <= 0:
                return 0.0
            
            download_bytes = after_recv - before_recv
            mbps = (download_bytes * 8) / elapsed / 1_000_000
            
            return round(max(0.0, mbps), 2)
        except Exception as e:
            logger.error(f"Error estimating throughput: {str(e)}")
            return 0.0
    
    def get_active_connections(self) -> int:
        """Count active network connections"""
        try:
            connections = psutil.net_connections()
            return len([c for c in connections if c.status == 'ESTABLISHED'])
        except Exception as e:
            logger.error(f"Error getting active connections: {str(e)}")
            return 0
    
    def get_system_resources(self) -> Dict:
        """Get CPU and memory usage"""
        return {
            'cpu_pct': psutil.cpu_percent(interval=0.5),
            'memory_pct': psutil.virtual_memory().percent,
            'memory_available_mb': psutil.virtual_memory().available / (1024 * 1024)
        }


class RadioMetricsCollector:
    """
    Collects radio-layer metrics from available sources on a Windows laptop:

    1. WiFi interface (netsh wlan show interfaces)
       → RSSI (dBm), signal quality %, BSSID, channel, band, Rx/Tx link speed
    2. Neighbor AP scan (netsh wlan show networks mode=bssid)
       → Visible APs, BSS Load (channel utilization %), connected stations
    3. TCP retransmissions (netstat -s delta)
       → BLER proxy: high retransmit rate indicates radio link quality issues
    4. MOS estimation (ITU-T G.107 E-model)
       → Estimated voice quality score (1.0–5.0) from latency/jitter/loss
    5. Handover detection
       → Tracks BSSID changes to detect WiFi roaming events

    Maps to radio issues:
      #1 Call Drop    : rssi_dbm, handover_event, handover_count
      #2 Voice MOS    : mos_estimate, tcp_retransmit_rate (BLER proxy)
      #3 Throughput   : rssi_dbm, rx_link_mbps, channel_util_pct
      #5 Session Drop : handover_event, neighbor_count
      #6 HO Failure   : handover_event, bssid, neighbor_count
      #7 Capacity     : channel_util_pct, connected_stations
    """

    def __init__(self, config: 'TunisianNetworkConfig' = None):  # type: ignore
        self.config = config or TunisianNetworkConfig()
        self._prev_bssid: Optional[str] = None
        self._prev_tcp_retrans: int = 0
        self._prev_tcp_sent: int = 0
        self._handover_count: int = 0

    # ---- WiFi Interface Metrics ----
    def get_wifi_radio_metrics(self) -> Dict:
        """
        Parses 'netsh wlan show interfaces' (supports French & English Windows locale).
        Returns: rssi_dbm, signal_quality_pct, bssid, channel, band_ghz,
                 rx_link_mbps, tx_link_mbps, radio_type, ssid
        """
        result = {}
        try:
            proc = subprocess.run(
                ['netsh', 'wlan', 'show', 'interfaces'],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=5
            )
            output = proc.stdout
            
            # Log raw netsh output for debugging WiFi metrics extraction
            logger.debug(f'netsh wlan show interfaces raw output (first 500 chars):\n{output[:500]}')

            def _extract(pattern: str) -> Optional[str]:
                m = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
                if not m:
                    return None
                # Return first non-None capturing group
                return next((g for g in m.groups() if g is not None), m.group(0)).strip()

            ssid = _extract(r'^\s+SSID\s*:\s*(.+)$')
            if ssid:
                result['ssid'] = ssid

            rssi = _extract(r'Rssi\s*:\s*(-?\d+)')
            if rssi:
                result['rssi_dbm'] = int(rssi)

            sig = _extract(r'Signal\s*:\s*(\d+)\s*%')
            if sig:
                result['signal_quality_pct'] = int(sig)

            # French: 'Canal', English: 'Channel'
            ch = _extract(r'(?:Canal|Channel)\s*:\s*(\d+)')
            if ch:
                result['channel'] = int(ch)

            # French: 'Bande', English: 'Band'
            band = _extract(r'(?:Bande|Band)\s*:\s*([\d.]+\s*GHz)')
            if band:
                # Normalize to remove any spaces (including non-breaking spaces)
                result['band_ghz'] = band.replace(' ', '').replace('\u00A0', '')

            tx = _extract(r'Transmission.*?:\s*([\d.]+)\s*Mbits?/s')
            if not tx:
                tx = _extract(r'Transmission.*?:\s*([\d.]+)\s*Mbps')
            if not tx:
                tx = _extract(r'Transmission\s*:\s*([\d.]+)')
            if tx:
                try:
                    result['tx_link_mbps'] = float(tx)
                except ValueError:
                    pass

            logger.debug(f'WiFi metrics: {result}')

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug(f'WiFi radio metrics unavailable: {e}')

        return result

    # ---- Neighbor AP Scan ----
    def get_neighbor_aps(self) -> Dict:
        """
        Parses 'netsh wlan show networks mode=bssid'.
        Returns: neighbor_count, channel_util_pct (BSS Load), connected_stations.
        """
        result = {}
        try:
            proc = subprocess.run(
                ['netsh', 'wlan', 'show', 'networks', 'mode=bssid'],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=10
            )
            output = proc.stdout

            bssid_count = len(re.findall(
                r'BSSID\s+\d+\s*:\s*[0-9a-fA-F:]{17}', output, re.IGNORECASE
            ))
            result['neighbor_count'] = bssid_count

            util_m = re.search(
                r'(?:Utilisation du canal|Channel\s+[Uu]tilization)'
                r'\s*:\s*\d+\s*\((\d+)\s*%\)',
                output, re.IGNORECASE
            )
            if util_m:
                result['channel_util_pct'] = int(util_m.group(1))

            sta_m = re.search(
                r'(?:Stations\s+connect[eé]es|Connected\s+[Ss]tations)\s*:\s*(\d+)',
                output, re.IGNORECASE
            )
            if sta_m:
                result['connected_stations'] = int(sta_m.group(1))

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug(f'Neighbor AP scan unavailable: {e}')

        return result

    # ---- TCP Retransmission Rate (BLER proxy) ----
    def get_tcp_retransmission_rate(self) -> float:
        """
        Measures TCP retransmission rate as % of segments sent (delta between calls).
        Acts as BLER proxy — high rate indicates radio link quality problems.
        Returns retransmit rate %, or -1.0 on failure.
        """
        try:
            proc = subprocess.run(
                ['netstat', '-s'],
                capture_output=True,
                text=True,
                errors='replace',
                timeout=5
            )
            output = proc.stdout

            # IPv4 TCP stats - more flexible regex to handle encoding issues
            # Look for "Segments" lines in TCP section and count them
            tcp_section = re.search(
                r'Statistiques TCP pour IPv4(.*?)(?:Statistiques|$)',
                output, re.IGNORECASE | re.DOTALL
            )
            
            if not tcp_section:
                return -1.0
            
            tcp_text = tcp_section.group(1)
            
            # Find sent and retransmitted segments (first two occurrences in TCP IPv4)
            segments_lines = re.findall(r'Segments\s+\S+\s+=\s+([\d,]+)', tcp_text)
            
            if len(segments_lines) < 3:  # Need at least: reçus, envoyés, retransmis
                return -1.0
            
            # Typically: Segments reçus, Segments envoyés, Segments retransmis
            sent_now = int(segments_lines[1].replace(',', ''))  # 2nd one is usually "envoyés"
            retrans_now = int(segments_lines[2].replace(',', ''))  # 3rd one is "retransmis"

            delta_sent = max(0, sent_now - self._prev_tcp_sent)
            delta_retrans = max(0, retrans_now - self._prev_tcp_retrans)

            self._prev_tcp_sent = sent_now
            self._prev_tcp_retrans = retrans_now

            if delta_sent > 0:
                return round(min(100.0, (delta_retrans / delta_sent) * 100), 3)
            return 0.0

        except Exception as e:
            logger.debug(f'TCP retransmission stats unavailable: {e}')

        return -1.0

    # ---- Handover Detection ----
    def detect_handover(self, current_bssid: Optional[str]) -> bool:
        """
        Returns True if BSSID changed since last call (WiFi roaming event).
        Increments cumulative handover_count on each event.
        """
        if current_bssid is None:
            return False
        if self._prev_bssid is not None and self._prev_bssid != current_bssid:
            self._handover_count += 1
            logger.info(
                f'[HANDOVER] BSSID: {self._prev_bssid} → {current_bssid} '
                f'(total: {self._handover_count})'
            )
            self._prev_bssid = current_bssid
            return True
        self._prev_bssid = current_bssid
        return False

    # ---- MOS Estimation (ITU-T G.107 E-model, simplified) ----
    @staticmethod
    def estimate_mos(latency_ms: float, jitter_ms: float, packet_loss_pct: float) -> float:
        """
        Estimates MOS (Mean Opinion Score, 1.0–5.0) using the ITU-T G.107 E-model.

        Formula:
          one_way_delay   = RTT/2 + 2*jitter  (jitter buffer estimate)
          Id              = delay impairment factor
          Ie              = equipment/loss impairment factor
          R               = 93.2 - Id - Ie   (quality factor, 0-100)
          MOS             = 1 + 0.035*R + R*(R-60)*(100-R)*7e-6

        Returns MOS in [1.0, 5.0]. Values below 3.6 indicate unacceptable quality.
        """
        one_way_ms = latency_ms / 2.0 + jitter_ms * 2.0

        # Delay impairment (G.107 Ta factor)
        if one_way_ms < 177.3:
            Id = 0.024 * one_way_ms
        else:
            Id = 0.024 * one_way_ms + 0.11 * (one_way_ms - 177.3)

        # Equipment/loss impairment (simplified G.107 Table B.1 for G.711)
        loss = packet_loss_pct / 100.0
        Ie = 30.0 * loss / (loss + 0.1) if loss > 0 else 0.0

        R = max(0.0, min(100.0, 93.2 - Id - Ie))
        mos = 1.0 + 0.035 * R + R * (R - 60.0) * (100.0 - R) * 7e-6
        return round(max(1.0, min(5.0, mos)), 2)

    # ---- Main Collection Entry Point ----
    def collect_all(self, latency_ms: float, jitter_ms: float, packet_loss_pct: float) -> Dict:
        """Collect all radio metrics and return a dict ready to merge into the main record."""
        radio: Dict = {}

        wifi = self.get_wifi_radio_metrics()
        radio['rssi_dbm']          = wifi.get('rssi_dbm')
        radio['signal_quality_pct']= wifi.get('signal_quality_pct')
        radio['channel']           = wifi.get('channel')
        radio['band_ghz']          = wifi.get('band_ghz', '')

        radio['handover_event']    = self.detect_handover(None)  # Cannot detect without BSSID
        radio['handover_count']    = self._handover_count

        neighbors = self.get_neighbor_aps()
        radio['neighbor_count']    = neighbors.get('neighbor_count', 0)
        radio['channel_util_pct']  = neighbors.get('channel_util_pct')
        radio['connected_stations']= neighbors.get('connected_stations')

        radio['tcp_retransmit_rate'] = self.get_tcp_retransmission_rate()
        radio['mos_estimate']        = self.estimate_mos(latency_ms, jitter_ms, packet_loss_pct)
        radio['data_source']         = 'wifi'

        # Placeholders for cellular fields (filled by RouterAPICollector)
        for field in ('rsrp_dbm', 'rsrq_db', 'sinr_db', 'cqi', 'timing_advance',
                      'pci', 'cell_id_router', 'network_type_router', 'earfcn',
                      'enodeb_id', 'mcs'):
            radio.setdefault(field, None)

        return radio


