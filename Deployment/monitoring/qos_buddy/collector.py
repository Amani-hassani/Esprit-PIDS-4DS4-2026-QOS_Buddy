"""
QoS Buddy - Network Data Acquisition Framework
Phase A: Real-World Data Collection with Automatic Anomaly Detection

Author: QoS Buddy Team
Version: 1.2
Date: 2026-03-17
"""

import time
import threading
import logging
from datetime import datetime
from typing import Dict


# ==================== IPERF3 BANDWIDTH TESTING ====================
from qos_buddy.config import TunisianNetworkConfig
from qos_buddy.network import Iperf3Manager, RadioMetricsCollector, NetworkMetricsCollector
from qos_buddy.analysis import HandoverAnalyzer, BLERTrendAnalyzer, AnomalyDetector, ConnectionSuccessTracker, SignalQualityAnalyzer, DataQualityTracker, TemporalFeatureGenerator, FeatureEngineer
from qos_buddy.router import RouterAPICollector
from qos_buddy.persistence import DataPersistence
from qos_buddy.network import Iperf3Manager, NetworkMetricsCollector, RadioMetricsCollector
from qos_buddy.router import RouterAPICollector
from qos_buddy.analysis import BLERTrendAnalyzer, SignalQualityAnalyzer, DataQualityTracker, TemporalFeatureGenerator, HandoverAnalyzer, ConnectionSuccessTracker, AnomalyDetector, FeatureEngineer
from qos_buddy.persistence import DataPersistence

# Initialize logger
logger = logging.getLogger("QoSBuddy")


class QoSBuddyCollector:
    """Main orchestrator for data collection"""
    
    def __init__(self, zone_id: str = "Z1", cell_id: str = "C1", node_id: str = "N1",
                 device_type: str = "workstation", config: TunisianNetworkConfig = None, choice: int = None): # type: ignore
        self.config = config or TunisianNetworkConfig()
        self.zone_id = zone_id
        self.cell_id = cell_id
        self.node_id = node_id
        self.device_type = device_type
        self.choice = choice
        
        self.metrics_collector = NetworkMetricsCollector(config)
        self.anomaly_detector = AnomalyDetector(config)
        self.feature_engineer = FeatureEngineer(config)
        self.data_persistence = DataPersistence(config=config, choice=choice)
        self.iperf_manager = Iperf3Manager(config)

        # Radio layer collectors
        self.radio_collector  = RadioMetricsCollector(config)
        self.router_collector = RouterAPICollector(config)
        
        # Enhanced metric collectors (NEW & IMPROVED)
        self.bler_analyzer = BLERTrendAnalyzer(config)  # Enhanced BLER with trends
        self.signal_analyzer = SignalQualityAnalyzer(config)  # Signal quality categorization
        self.data_quality_tracker = DataQualityTracker(config)  # Data completeness tracking
        self.temporal_feature_gen = TemporalFeatureGenerator(config, window_size=30)  # Temporal features
        self.handover_analyzer = HandoverAnalyzer(config)
        self.connection_tracker = ConnectionSuccessTracker(config)

        # Incident tracking: group consecutive anomalies
        self.incident_tracker = {}  # {anomaly_type: {start_time, end_time, samples, highest_score}}
        self.sampling_interval = 30  # Default, updated by run_collection/scenario
        self.running = False
        
        # Baseline phase tracking (NEW)
        self.baseline_phase_active = True
        self.baseline_start_time = datetime.now()
        self.baseline_sample_count = 0
        
        # Hour-specific anomaly context (NEW)
        self.hour_anomaly_counts = {}  # {hour: {total: count, anomaly: count}}
        self.hour_anomaly_rates = {}  # {hour: anomaly_rate_pct}
        
        # Incident lifecycle tracking (NEW)
        self.last_incident_recovery_time = {}  # {anomaly_type: seconds_since_recovery}
        
        # Collection source tracking (NEW)
        self.router_api_failures = 0
        self.iperf3_test_count = 0
        self.iperf3_success_count = 0
        
        # Throughput tracking: cache latest iperf3 bandwidth result (for accurate throughput measurement)
        self.latest_iperf3_bandwidth_mbps = None
        self.latest_iperf3_timestamp = None
        self.iperf3_bandwidth_ttl_seconds = 120  # Consider iperf3 result valid for 2 minutes
        
        # === IMPROVEMENT 1: Per-scenario CSSR tracking ===
        self.scenario_cssr_stats = {
            'baseline': {'tests': 0, 'successes': 0, 'avg_bandwidth': 0},
            'congestion': {'tests': 0, 'successes': 0, 'avg_bandwidth': 0},
            'packet_loss': {'tests': 0, 'successes': 0, 'avg_bandwidth': 0},
            'normal': {'tests': 0, 'successes': 0, 'avg_bandwidth': 0}
        }
        self.baseline_network_capacity_mbps = None  # Established during baseline phase
        
        # === IMPROVEMENT 2: Per-server performance tracking ===
        self.server_performance = {}  # {(server, port): {'successes': int, 'failures': int, 'avg_bandwidth': float, 'total_tests': int}}
        
        # === IMPROVEMENT 3: Load generator verification ===
        self.load_verification = {
            'tcp_load_active': False,
            'udp_load_active': False,
            'tcp_packets_sent': 0,
            'udp_packets_sent': 0
        }
        
        # === IMPROVEMENT 4: Adaptive test duration ===
        self.iperf3_test_duration_seconds = 10  # Adaptive based on capacity
    
    def flush_pending_incidents(self):
        """Save any open incidents that haven't been closed yet (called on shutdown)"""
        for atype, incident in list(self.incident_tracker.items()):
            if not incident.get('saved', False):
                start = incident['start_time']
                end = incident['end_time']
                duration = (end - start).total_seconds()
                
                score = incident['highest_score']
                if score >= 0.8:
                    severity = 'critical'
                elif score >= 0.6:
                    severity = 'high'
                elif score >= 0.4:
                    severity = 'medium'
                else:
                    severity = 'low'
                
                incident_record = {
                    'incident_id': f"INC_{int(start.timestamp())}_{atype[:10]}",
                    'start_timestamp': start.isoformat(),
                    'end_timestamp': end.isoformat(),
                    'node_id': self.node_id,
                    'incident_type': atype,
                    'severity': severity,
                    'time_to_detect_sec': self.sampling_interval,
                    'duration_sec': int(duration),
                    'samples': incident['samples'],
                    'max_score': round(incident['highest_score'], 3)
                }
                
                self.data_persistence.save_incident(incident_record)
                logger.info(f"[INCIDENT FLUSHED] {atype} | Duration: {int(duration)}s | "
                          f"Severity: {severity} | Score: {incident['highest_score']:.2f}")
        
        self.incident_tracker.clear()
    
    def track_incident(self, record: Dict):
        """
        Track incidents by grouping consecutive anomalies of same type.
        Only saves unique incidents when they end.
        """
        anomaly_type = record['anomaly_type']
        anomaly_score = record['anomaly_score']
        timestamp = datetime.fromisoformat(record['timestamp'])
        
        if record['anomaly_flag']:
            # Anomaly detected - update or create incident
            if anomaly_type not in self.incident_tracker:
                # New incident started
                self.incident_tracker[anomaly_type] = {
                    'start_time': timestamp,
                    'end_time': timestamp,
                    'samples': 1,
                    'highest_score': anomaly_score,
                    'saved': False
                }
            else:
                # Incident ongoing - update end time and increase score tracking
                incident = self.incident_tracker[anomaly_type]
                incident['end_time'] = timestamp
                incident['samples'] += 1
                incident['highest_score'] = max(incident['highest_score'], anomaly_score)
        
        else:
            # Normal state - save any active incidents
            for atype, incident in list(self.incident_tracker.items()):
                if not incident['saved']:
                    # Save the incident
                    start = incident['start_time']
                    end = incident['end_time']
                    duration = (end - start).total_seconds()
                    
                    # Determine severity based on anomaly score
                    score = incident['highest_score']
                    if score >= 0.8:
                        severity = 'critical'
                    elif score >= 0.6:
                        severity = 'high'
                    elif score >= 0.4:
                        severity = 'medium'
                    else:
                        severity = 'low'
                    
                    incident_record = {
                        'incident_id': f"INC_{int(start.timestamp())}_{atype[:10]}",
                        'start_timestamp': start.isoformat(),
                        'end_timestamp': end.isoformat(),
                        'node_id': self.node_id,
                        'incident_type': atype,
                        'severity': severity,
                        'time_to_detect_sec': self.sampling_interval,
                        'duration_sec': int(duration),
                        'samples': incident['samples'],
                        'max_score': round(incident['highest_score'], 3)
                    }
                    
                    self.data_persistence.save_incident(incident_record)
                    
                    logger.info(f"[INCIDENT CLOSED] {atype} | Duration: {int(duration)}s | "
                              f"Severity: {severity} | Score: {incident['highest_score']:.2f}")
                    
                    incident['saved'] = True
                    del self.incident_tracker[atype]
    
    def _check_teams_in_meeting(self) -> bool:
        """
        Detect if Microsoft Teams is actively in a meeting/call by checking network activity.
        
        Teams uses specific UDP ports for media during calls:
        - UDP: 50000-59999 (RTP/SRTP media streams)
        - UDP: 3478-3481 (STUN - NAT traversal)
        - TCP: 5223 (Signaling)
        
        Strategy: Check if Teams.exe has any network connections on these media ports.
        When in a meeting: Media ports are actively used
        When idle: No connections on these ports
        
        Returns: True if Teams has active media connections, False otherwise
        """
        try:
            import subprocess
            
            # Check if Teams.exe is running
            tasklist_result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq Teams.exe'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if 'Teams.exe' not in tasklist_result.stdout:
                logger.debug("[TEAMS] Teams not running")
                return False
            
            # Check for active network connections on Teams media ports
            # Using netstat to check for active connections
            ps_cmd = """
            # Get all established connections and check if Teams is using media ports
            $mediaActive = $false
            
            try {
                # Check for UDP connections on media port range (50000-59999)
                $udpConns = Get-NetUDPEndpoint -ErrorAction SilentlyContinue | 
                    Where-Object {
                        ([int]$_.LocalPort -ge 50000 -and [int]$_.LocalPort -le 59999) -or
                        ([int]$_.LocalPort -in @(3478, 3479, 3480, 3481, 5223))
                    }
                
                # Filter for Teams process
                $teamsProcess = Get-Process Teams -ErrorAction SilentlyContinue
                if ($teamsProcess -and $udpConns) {
                    # Teams is running and media ports are in use
                    $mediaActive = $true
                }
            } catch {}
            
            try {
                # Alternative: Check if Teams process has high memory (typical during calls)
                # Call: 150-300MB, Idle: 50-150MB
                $teams = Get-Process Teams -ErrorAction SilentlyContinue
                if ($teams) {
                    $memMB = $teams.WorkingSet / 1MB
                    if ($memMB -gt 200) {
                        $mediaActive = $true
                    }
                }
            } catch {}
            
            if ($mediaActive) {
                Write-Output "CALL_ACTIVE"
            } else {
                Write-Output "IDLE"
            }
            """
            
            result = subprocess.run(
                ['powershell', '-NoProfile', '-NoLogo', '-Command', ps_cmd],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            output = result.stdout.strip().lower()
            logger.debug(f"[TEAMS] Detection result: {output}")
            
            if 'call_active' in output:
                logger.info("[TEAMS] Active meeting detected - media ports in use or high memory")
                return True
            else:
                logger.debug("[TEAMS] Teams running but idle (no active media)")
                return False
        
        except Exception as e:
            logger.debug(f"[TEAMS] Detection error: {str(e)}")
            return False
            logger.debug(f"[TEAMS] Detection error: {str(e)}")
            return False  # Default to False on error
    
    def collect_single_sample(self, scenario_type: str = 'baseline') -> Dict:
        """Collect one complete sample of all metrics
        
        Args:
            scenario_type: 'baseline', 'congestion', 'packet_loss', 'normal' - used to override loss metrics with actual scenario impact
        """
        timestamp = datetime.now()
        
        # Collect network metrics from multiple targets
        # Try primary target (OTC Tunisia), fall back to local gateway if it times out
        isp_metrics = self.metrics_collector.ping_target(
            self.metrics_collector.ping_targets['isp_dns'],
            count=2,
            timeout=1
        )
        
        # If primary target failed (100% packet loss), try local gateway as fallback
        if isp_metrics.get('packet_loss_pct', 0) >= 100:
            logger.debug(f"Primary ping target {self.metrics_collector.ping_targets['isp_dns']} unreachable, trying fallback (local gateway)")
            fallback_metrics = self.metrics_collector.ping_target(
                self.metrics_collector.ping_targets['local_gateway'],
                count=2,
                timeout=1
            )
            # Use fallback if it's better (has any successful samples)
            if fallback_metrics.get('samples', 0) > 0:
                isp_metrics = fallback_metrics
                logger.debug("Using local gateway ping results as fallback")
            else:
                # Both pings failed - if we have recent iperf3 success, assume network is reachable
                recent_iperf_success = self.connection_tracker._check_recent_success()
                if recent_iperf_success:
                    logger.debug("Both ping targets failed, but iperf3 recently succeeded - assuming network is reachable")
                    # Use very low packet loss (assume ping issue, not network issue)
                    isp_metrics = {
                        'target': 'fallback',
                        'latency_ms': 0,
                        'jitter_ms': 0,
                        'packet_loss_pct': 0,  # Assume OK since iperf3 works
                        'samples': 0
                    }
        
        # IMPORTANT: Override packet_loss_pct with actual UDP loss if in PACKET_LOSS scenario
        if scenario_type == 'packet_loss' and hasattr(self, '_last_udp_result') and self._last_udp_result:
            actual_udp_loss = self._last_udp_result.get('packet_loss_pct', 0)
            if actual_udp_loss > 0:
                isp_metrics['packet_loss_pct'] = actual_udp_loss
                logger.debug(f"Using actual UDP flood loss ({actual_udp_loss}%) instead of ping loss")
        
        # Get network interface stats
        # Use cached iperf3 bandwidth if recent, otherwise measure passively
        if (self.latest_iperf3_bandwidth_mbps is not None and 
            self.latest_iperf3_timestamp is not None and
            (datetime.now() - self.latest_iperf3_timestamp).total_seconds() < self.iperf3_bandwidth_ttl_seconds):
            # Use recent iperf3 result (within 2 minutes)
            throughput = self.latest_iperf3_bandwidth_mbps
            logger.debug(f"Using cached iperf3 bandwidth: {throughput:.2f} Mbps")
        else:
            # Fall back to passive measurement
            throughput = self.metrics_collector.estimate_throughput()
        system_resources = self.metrics_collector.get_system_resources()
        
        # Aggregate base metrics
        base_record = {
            'timestamp': timestamp.isoformat(),
            'zone_id': self.zone_id,
            'cell_id': self.cell_id,
            'node_id': self.node_id,
            'device_type': self.device_type,
            'latency_ms': isp_metrics.get('latency_ms', 0),
            'jitter_ms': isp_metrics.get('jitter_ms', 0),
            'packet_loss_pct': isp_metrics.get('packet_loss_pct', 0),
            'throughput_mbps': throughput,
            'cpu_pct': system_resources['cpu_pct'],
            'memory_pct': system_resources['memory_pct'],
            'active_connections': 0,  # Will be set by engineer_features from connection snapshot
            'day_of_week': timestamp.strftime('%A'),
            'hour_of_day': timestamp.hour,
            'teams_in_meeting': self._check_teams_in_meeting()  # Detect if Teams is actively in a meeting
        }

        # Engineer features (traffic type, queue length, peak hour, etc.)
        engineered = self.feature_engineer.engineer_features(base_record)
        base_record.update(engineered)
        
        # Override traffic_type if scenario_type is explicitly set
        if scenario_type and scenario_type != 'baseline':
            base_record['traffic_type'] = scenario_type
            base_record['traffic_confidence'] = 1.0  # Explicitly set scenario, high confidence
            base_record['detection_method'] = 'explicit_scenario'
            logger.debug(f"Override traffic_type to '{scenario_type}' (explicit scenario)")

        # ---- Radio Layer: WiFi metrics (always collected) ----
        radio_metrics = self.radio_collector.collect_all(
            latency_ms=base_record['latency_ms'],
            jitter_ms=base_record['jitter_ms'],
            packet_loss_pct=base_record['packet_loss_pct']
        )
        base_record.update(radio_metrics)

        # ---- Radio Layer: Cellular from router API (if available) ----
        # Use thread-based timeout to prevent infinite hangs (Windows-safe)
        # Always waits for router metrics - timeout is safety net only
        if self.router_collector._available:
            router_metrics = {}
            try:
                def get_router_metrics_with_timeout():
                    nonlocal router_metrics
                    try:
                        router_metrics = self.router_collector.get_signal_metrics() or {}
                    except Exception as e:
                        logger.debug(f"Router metrics error: {str(e)}")
                        router_metrics = {}
                
                # Run in thread with 40s timeout (allows full Selenium login + extraction)
                router_thread = threading.Thread(target=get_router_metrics_with_timeout, daemon=True)
                router_thread.start()
                router_thread.join(timeout=40)  # Wait up to 40 seconds for router metrics
                
                if router_thread.is_alive():
                    logger.error("[ROUTER] CRITICAL: Metrics collection took >40s, likely Selenium hang - may need restart")
                
                # Always use whatever metrics we got (even if partial/empty)
                if router_metrics:
                    base_record.update(router_metrics)
                    base_record['data_source'] = 'wifi+router'
            except Exception as e:
                logger.warning(f"[ROUTER] Timeout handler error: {str(e)}")

        # ---- Enhanced Radio Metrics (NEW) ----
        # BLER proxy with trend analysis (using already-calculated TCP retransmit rate)
        tcp_rate = base_record.get('tcp_retransmit_rate', 0.0)
        bler_metrics = self.bler_analyzer.get_bler_metrics(tcp_retransmit_rate=tcp_rate)
        base_record.update(bler_metrics)
        
        # Signal Quality Categorization (NEW)
        rssi = base_record.get('rssi_dbm')
        wifi_quality = self.signal_analyzer.categorize_wifi_signal(rssi)
        base_record.update(wifi_quality)
        
        # Cellular signal quality (if available)
        rsrp = base_record.get('rsrp_dbm')
        rsrq = base_record.get('rsrq_db')
        cellular_quality = self.signal_analyzer.categorize_cellular_signal(rsrp, rsrq)
        base_record.update(cellular_quality)
        
        # Combined signal health
        wifi_score = wifi_quality.get('wifi_signal_score', 0)
        cellular_score = cellular_quality.get('cellular_signal_score', 0)
        signal_health = self.signal_analyzer.get_combined_signal_health(wifi_score, cellular_score)
        base_record.update(signal_health)
        
        # Handover analysis
        ho_occurred, ho_status, ho_success_rate = self.handover_analyzer.analyze_handover(base_record)
        base_record['ho_status'] = ho_status
        base_record['ho_success_rate_pct'] = ho_success_rate
        
        # Connection success (CSSR proxy) — will be updated when iperf3 runs
        base_record['cssr_proxy_pct'] = self.connection_tracker.get_cssr_proxy_pct()

        # Detect anomalies (now includes radio-layer metrics)
        is_anomaly, anomaly_type, anomaly_score = self.anomaly_detector.detect_anomaly(base_record)
        base_record['anomaly_flag'] = is_anomaly
        base_record['anomaly_type'] = anomaly_type
        base_record['anomaly_score'] = anomaly_score

        # ---- Data Quality Assessment (NEW) ----
        quality_metrics = self.data_quality_tracker.assess_record_quality(base_record)
        base_record.update(quality_metrics)
        
        # ---- Temporal Features (NEW) ----
        # Add current sample to history for rolling statistics
        self.temporal_feature_gen.add_sample(base_record)
        temporal_features = self.temporal_feature_gen.calculate_temporal_features()
        base_record.update(temporal_features)

        # ---- Baseline & Context Features (NEW) ----
        # Baseline phase indicator
        base_record['baseline_phase'] = self.baseline_phase_active
        
        # Hour-specific anomaly rate (contextual feature)
        hour = timestamp.hour
        if hour not in self.hour_anomaly_counts:
            self.hour_anomaly_counts[hour] = {'total': 0, 'anomaly': 0}
        
        self.hour_anomaly_counts[hour]['total'] += 1
        if is_anomaly:
            self.hour_anomaly_counts[hour]['anomaly'] += 1
        
        hour_anomaly_rate = (self.hour_anomaly_counts[hour]['anomaly'] / 
                             max(1, self.hour_anomaly_counts[hour]['total']) * 100)
        base_record['hour_anomaly_rate'] = round(hour_anomaly_rate, 1)
        
        # Incident recovery time (time since last recovery)
        recovery_time = -1.0  # -1 indicates never had this anomaly or still ongoing
        if not is_anomaly and anomaly_type in self.last_incident_recovery_time:
            recovery_time = self.last_incident_recovery_time[anomaly_type]
        elif is_anomaly and anomaly_type not in self.last_incident_recovery_time:
            self.last_incident_recovery_time[anomaly_type] = 0  # Just started
        base_record['incident_recovery_time'] = recovery_time
        
        # Collection completion percentage (samples collected vs expected)
        self.baseline_sample_count += 1
        if self.baseline_sample_count > 30:
            self.baseline_phase_active = False
        collection_completion_pct = 100.0  # Placeholder - will be set by collection methods
        base_record['collection_completion_pct'] = collection_completion_pct

        return base_record
    
    def _display_metrics(self, record: Dict, sample_num: int = 0):
        """Display collected metrics in formatted console output with anomaly info"""
        try:
            # Format timestamp
            ts = record.get('timestamp', '').split('T')[1][:8] if 'T' in record.get('timestamp', '') else 'N/A'
            
            # Check for anomaly
            is_anomaly = record.get('anomaly_flag', False)
            anomaly_type = record.get('anomaly_type', 'normal')
            anomaly_score = record.get('anomaly_score', 0.0)
            traffic_type = record.get('traffic_type', 'unknown')
            
            # Status indicator
            if is_anomaly:
                status = "[!] ANOMALY"
                sep = "=" * 120
            else:
                status = "[OK]"
                sep = "-" * 120
            
            # Print separator for anomalies
            if is_anomaly:
                print(f"\n{sep}")
            
            # QoS metrics line
            qos_line = f"[{ts}] Sample #{sample_num} | {status} | {anomaly_type.upper()}"
            if is_anomaly:
                qos_line += f" (Score: {anomaly_score:.2f})"
            print(qos_line)
            
            # Detailed metrics
            metrics_line = f"  QoS: "
            metrics_line += f"Latency={record.get('latency_ms', 0):.1f}ms "
            metrics_line += f"Jitter={record.get('jitter_ms', 0):.1f}ms "
            metrics_line += f"Loss={record.get('packet_loss_pct', 0):.1f}% "
            metrics_line += f"Throughput={record.get('throughput_mbps', 0):.2f}Mbps "
            metrics_line += f"CPU={record.get('cpu_pct', 0):.1f}% "
            metrics_line += f"Traffic={traffic_type} "
            
            # Add Teams meeting status if detected (NEW)
            teams_in_meeting = record.get('teams_in_meeting', False)
            if teams_in_meeting:
                metrics_line += "[TEAMS_MEETING] "
            
            print(metrics_line)
            
            # WiFi metrics
            wifi_line = "  WiFi: "
            wifi_line += f"RSSI={record.get('rssi_dbm', 'N/A')} "
            wifi_line += f"Signal={record.get('signal_quality_pct', 'N/A')}% "
            wifi_line += f"Channel={record.get('channel', 'N/A')} "
            wifi_line += f"LinkSpeed={record.get('rx_link_mbps', 'N/A')}Mbps"
            print(wifi_line)
            
            # Router metrics (cellular - if available)
            router_metrics = []
            if record.get('rsrp_dbm'):
                router_metrics.append(f"RSRP={record['rsrp_dbm']}")
            if record.get('rsrq_db'):
                router_metrics.append(f"RSRQ={record['rsrq_db']}")
            if record.get('sinr_db'):
                router_metrics.append(f"SINR={record['sinr_db']}")
            if record.get('pci'):
                router_metrics.append(f"PCI={record['pci']}")
            if record.get('cqi'):
                router_metrics.append(f"CQI={record['cqi']}")
            if record.get('mcs'):
                router_metrics.append(f"MCS={record['mcs']}")
            if record.get('network_type_router'):
                router_metrics.append(f"Type={record['network_type_router']}")
            
            if router_metrics:
                router_line = "  Router: " + " ".join(router_metrics)
                print(router_line)
            
            # ADB metrics (if available)
            adb_metrics = []

            if record.get('timing_advance'):
                adb_metrics.append(f"TA={record['timing_advance']}")
            
            if adb_metrics:
                adb_line = "  ADB: " + " ".join(adb_metrics)
                print(adb_line)
            
            # BLER metrics (error rate)
            bler_proxy = record.get('bler_proxy_pct')
            if bler_proxy is not None:
                bler_line = f"  BLER: {bler_proxy:.1f}% (TCP retransmit proxy)"
                print(bler_line)
            
            # Data source and footer
            data_source = record.get('data_source', 'unknown')
            print(f"  [{data_source}]")
            
            # Print separator for anomalies
            if is_anomaly:
                print(f"{sep}\n")
            
        except Exception as e:
            logger.debug(f"Error displaying metrics: {e}")
    
    def _initialize_router(self):
        """Initialize router metrics collection (idempotent helper)
        
        Call this at the START of any collection method to ensure router is ready
        """
        if not self.router_collector.gateway:
            logger.debug("Router initialization skipped (no gateway configured)")
            return False
        
        # Set credentials if not already set
        if not self.router_collector.username or not self.router_collector.password:
            self.router_collector.username = "admin"
            self.router_collector.password = "admin"
            logger.debug("Set default router credentials (admin/admin)")
        
        # Try to detect router type synchronously
        try:
            router_detected = self.router_collector.detect_router()
            if router_detected:
                logger.info(f"[OK] Router detected: {self.router_collector.router_type} at {self.router_collector.gateway}")
                return True
            else:
                logger.warning(f"[!] Router at {self.router_collector.gateway} not detected (may retry during collection)")
                return False
        except Exception as e:
            logger.warning(f"[!] Router initialization error: {e}")
            return False
    
    def print_improvements_summary(self):
        """Print summary of QoS improvements implemented in choice 13"""
        summary = """
================================================================================
                    CHOICE 13 IMPROVEMENTS - Enhanced QoS Testing
================================================================================

[OK] IMPROVEMENT 1: Baseline Network Capacity Establishment
  └─ Parallel iperf3 tests during baseline phase (adaptive duration)
  └─ Auto-adjust test duration: 15s (>10Mbps) | 10s (5-10Mbps) | 5s (<5Mbps)
  └─ Establishes reference network capacity for comparison

[OK] IMPROVEMENT 2: Per-Scenario CSSR Tracking
  └─ Separate CSSR statistics per scenario type:
     • Baseline CSSR: Network baseline
     • Congestion CSSR: Impact of TCP load
     • Packet Loss CSSR: Impact of UDP flood
     • Normal CSSR: Network recovery
  └─ Real-time visibility per segment

[OK] IMPROVEMENT 3: Intelligent Server Fallback & Rotation
  └─ Tracks per-server success rate & bandwidth
  └─ Selects best-performing server automatically
  └─ Falls back to alternate servers on primary failure
  └─ Score: (success_rate × 60%) + (bandwidth × 40%)

[OK] IMPROVEMENT 4: Real-time Load Generator Verification
  └─ Confirms TCP/UDP loads are actually running
  └─ Displays: "[LOAD]" or "[IDLE]" per segment
  └─ Helps verify scenario setup

[OK] IMPROVEMENT 5: Enhanced Logging & Real-time Visibility
  └─ Per-segment logs show: load | loss% | CSSR% | Throughput | Latency
  └─ Per-server performance ranking at collection end
  └─ Scenario-specific statistics summary

[OK] IMPROVEMENT 6: Per-Server Performance Tracking
  └─ Historical performance matrix: success%, avg bandwidth
  └─ Automatic best-server selection for future tests
  └─ Know which servers work best from your location

EXPECTED BENEFITS:
  • Better baseline detection → More accurate test tuning
  • Scenario-specific metrics → Clear impact measurement  
  • Reliable fallback → No failed tests from single server
  • Load verification → Confirm scenarios are running
  • Full visibility → Know exactly what's happening

RUN WITH VERBOSE MODE:
  python qos_buddy_collector.py --choice 13 --verbose --duration 10

================================================================================
        """
        logger.info(summary)
    
    def run_collection(self, duration_minutes: int = 60, interval_seconds: int = 30):
        """
        Run continuous data collection for specified duration
        
        Args:
            duration_minutes: How long to collect data (0 = infinite)
            interval_seconds: Sampling interval
        """
        self.running = True
        self.sampling_interval = interval_seconds
        start_time = datetime.now()
        baseline_samples = []
        baseline_phase_complete = False
        
        logger.info(f"Starting QoS Buddy collection for {duration_minutes} minutes...")
        logger.info(f"Configuration: Zone={self.zone_id}, Cell={self.cell_id}, Node={self.node_id}")
        
        # Initialize router metrics collection (NEW: using helper method)
        self._initialize_router()
        
        try:
            while self.running:
                cycle_started = time.monotonic()

                # Check if we should stop
                if duration_minutes > 0:
                    elapsed = (datetime.now() - start_time).total_seconds() / 60
                    if elapsed >= duration_minutes:
                        break
                
                # Collect sample
                record = self.collect_single_sample()
                
                # Baseline phase (first 30 samples ~ 15 minutes at 30sec interval)
                if not baseline_phase_complete:
                    baseline_samples.append(record)
                    if len(baseline_samples) >= 30:
                        self.anomaly_detector.update_baseline(baseline_samples)
                        baseline_phase_complete = True
                        self.baseline_phase_active = False  # Mark baseline phase as complete (NEW)
                        logger.info("Baseline phase complete, anomaly detection enabled")
                
                # Save record
                self.data_persistence.save_record(record)
                
                # Display metrics in console
                sample_num = int((datetime.now() - start_time).total_seconds() / interval_seconds)
                self._display_metrics(record, sample_num)
                
                # Track incidents (group consecutive anomalies)
                self.track_incident(record)
                
                # Update recovery times for previous incidents (NEW)
                for atype in self.last_incident_recovery_time:
                    self.last_incident_recovery_time[atype] += interval_seconds
                
                # Keep the live feed on the requested cadence; if probes run long,
                # start the next sample immediately instead of adding extra delay.
                elapsed_seconds = time.monotonic() - cycle_started
                time.sleep(max(0, interval_seconds - elapsed_seconds))
        
        except KeyboardInterrupt:
            logger.info("Collection interrupted by user")
        except Exception as e:
            logger.error(f"Error during collection: {str(e)}", exc_info=True)
        finally:
            self.flush_pending_incidents()
            self.running = False
            logger.info("Data collection stopped")
    
    def run_all_scenarios_with_iperf3(self, duration_per_scenario: int = 15):
        """
        CHOICE 12: Run ALL scenarios IN PARALLEL with continuous load generation.
        
        Each scenario runs SIMULTANEOUSLY in separate threads, allowing the network
        to experience multiple types of stress at once. This captures realistic
        interactions between different load types:
        
        1. Baseline (Thread 1): passive WiFi + router metrics
        2. Congestion (Thread 2): iperf3 TCP load injection
        3. Normal (Thread 3): passive collection (reference baseline)
        4. Packet Loss (Thread 4): UDP flood + TCP measurement
        
        All 4 scenarios generate metrics simultaneously for diverse training data.
        In unlimited mode (duration=0), cycles repeat indefinitely. Each cycle is
        followed by a 2-minute break for data stabilization.
        
        Args:
            duration_per_scenario: Duration in minutes for all scenarios running together (0 = unlimited loop)
        """
        
        logger.info("=" * 80)
        logger.info("CHOICE 12: Running ALL 4 Scenarios IN PARALLEL with Simultaneous Load Generation")
        logger.info("=" * 80)
        logger.info("NETWORK STRESS: Multiple load types affecting network SIMULTANEOUSLY")
        logger.info("PARALLELISM: Baseline | Congestion | Normal-Passive | Packet-Loss")
        logger.info("                   ^             ^              ^              ^")
        logger.info("                   |_____________|______________|______________| All running at ONCE")
        logger.info("")
        
        if duration_per_scenario <= 0:
            logger.info("Mode: UNLIMITED LOOP - all 4 scenarios run repeatedly in parallel for maximum diversity")
            logger.info("Press Ctrl+C to stop collection")
        else:
            logger.info(f"Duration: {duration_per_scenario} min per cycle + 2min break = {duration_per_scenario + 2} min per cycle")
        
        logger.info("=" * 80)
        
        # Initialize router metrics collection
        self._initialize_router()
        
        cycle = 0
        
        try:
            while True:
                cycle += 1
                
                logger.info(f"\n{'='*80}")
                logger.info(f"CYCLE [{cycle}] - All 4 scenarios running in PARALLEL")
                logger.info(f"{'='*80}")
                logger.info("Starting: BASELINE | CONGESTION | NORMAL | PACKET_LOSS")
                logger.info(f"Duration: {duration_per_scenario if duration_per_scenario > 0 else 'unlimited'} minutes")
                logger.info("-" * 80)
                
                # Create 4 scenario threads - all start at same time
                scenario_threads = []
                scenario_results = {}
                
                # Thread 1: Baseline load generator (passive)
                t1 = threading.Thread(
                    target=self._generate_baseline_load,
                    args=(duration_per_scenario,),
                    name="BASELINE_LOAD",
                    daemon=True
                )
                scenario_threads.append(t1)
                
                # Thread 2: Congestion load generator (iperf3 TCP)
                t2 = threading.Thread(
                    target=self._generate_congestion_load,
                    args=(duration_per_scenario,),
                    name="CONGESTION_LOAD",
                    daemon=True
                )
                scenario_threads.append(t2)
                
                # Thread 3: Normal load generator (passive baseline reference)
                t3 = threading.Thread(
                    target=self._generate_normal_load,
                    args=(duration_per_scenario,),
                    name="NORMAL_LOAD",
                    daemon=True
                )
                scenario_threads.append(t3)
                
                # Thread 4: Packet Loss load generator (UDP flood)
                t4 = threading.Thread(
                    target=self._generate_packet_loss_load,
                    args=(duration_per_scenario,),
                    name="PACKET_LOSS_LOAD",
                    daemon=True
                )
                scenario_threads.append(t4)
                
                # Thread 5: UNIFIED Metric Collection (while all loads are active)
                metric_thread = threading.Thread(
                    target=self._collect_metrics_parallel,
                    args=(duration_per_scenario,),
                    name="METRIC_COLLECTION",
                    daemon=True
                )
                
                # CRITICAL: Enable the running flag before starting threads
                self.running = True
                
                # Start all 4 load generators + metric collector
                logger.info("[PARALLEL] Starting 4 load generators + unified metric collection...")
                for t in scenario_threads:
                    t.start()
                    logger.info(f"[PARALLEL] Started {t.name} thread")
                
                metric_thread.start()
                logger.info("[PARALLEL] Started METRIC_COLLECTION thread")
                
                # Wait for all threads to complete
                logger.info("[PARALLEL] All 4 scenario loads + metric collection running simultaneously...")
                for t in scenario_threads:
                    t.join()
                metric_thread.join()
                
                logger.info(f"[CYCLE {cycle}] All scenarios completed simultaneously")
                
                # Exit loop if limited mode
                if duration_per_scenario > 0:
                    logger.info("Limited mode: Single cycle completed. Exiting.")
                    break
                
                # In unlimited mode, add 2-minute break before next cycle
                logger.info("\n[BREAK] 2-minute rest before next cycle...")
                for i in range(120):
                    if not self.running:
                        break
                    time.sleep(1)
                logger.info("[BREAK] Complete - starting next cycle")
        
        except KeyboardInterrupt:
            logger.info("\nAll parallel scenarios interrupted by user")
            self.running = False
        except Exception as e:
            logger.error(f"Error in parallel scenarios: {str(e)}", exc_info=True)
            self.running = False
        finally:
            logger.info("=" * 80)
            logger.info("Parallel scenario collection completed")
            logger.info("=" * 80)
    
    def run_structured_scenario_pattern(self, num_cycles: int = 0):
        """
        CHOICE 13: Structured Scenario Pattern with Parallel Data Collection
        
        Pattern (repeats until num_cycles complete or indefinitely if num_cycles=0):
        1. BASELINE PHASE: Establish normal network baseline (20 samples)
        2. CYCLE (repeats):
           - [CONGESTION_S1] Run congestion scenario 1 + collect data (30 sec)
           - [CONGESTION_S2] Run congestion scenario 2 + collect data (30 sec)
           - [NORMAL_S1] No scenario, collect data only (30 sec)
           - [NORMAL_S2] No scenario, collect data only (30 sec)
           - [PACKET_LOSS_S1] Run packet loss scenario 1 + collect data (30 sec)
           - [PACKET_LOSS_S2] Run packet loss scenario 2 + collect data (30 sec)
           - [NORMAL_S3] No scenario, collect data only (30 sec)
           - [NORMAL_S4] No scenario, collect data only (30 sec)
        
        Args:
            num_cycles (int): Number of cycles to run. 0 = infinite (press Ctrl+C to stop)
        
        All scenarios and data collection run in parallel for realistic impact measurement.
        """
        logger.info("=" * 80)
        logger.info("CHOICE 13: Structured Scenario Pattern - Parallel Load + Data Collection")
        logger.info("=" * 80)
        logger.info("Pattern: BASELINE -> [CONGESTION x2 + NORMAL x2 + PACKET_LOSS x2 + NORMAL x2] (repeat)")
        logger.info("ALL scenarios and data collection run SIMULTANEOUSLY")
        logger.info("Press Ctrl+C to stop collection")
        logger.info("=" * 80)
        
        # Initialize router metrics collection
        self._initialize_router()
        
        # Reset running flag for structured pattern
        self.running = True
        
        # Phase 1: Baseline establishment
        logger.info("\n" + "=" * 80)
        logger.info("PHASE 1: BASELINE ESTABLISHMENT (establishing normal network conditions)")
        logger.info("=" * 80)
        self._collect_baseline_phase(duration_seconds=60)  # 60 seconds = 2 samples at 30-sec interval
        
        # Reset running flag after baseline (it was set to False in _collect_baseline_phase)
        self.running = True
        
        logger.info("\n[SUCCESS] Baseline established - starting pattern cycles")
        cycle = 0
        
        try:
            while num_cycles == 0 or cycle < num_cycles:
                cycle += 1
                logger.info("\n" + "=" * 80)
                logger.info(f"CYCLE [{cycle}] - Running complete scenario pattern")
                logger.info("=" * 80)
                
                # S1 & S2: Congestion
                self._run_structured_segment(
                    segment_name="CONGESTION_S1",
                    load_type="congestion",
                    duration_seconds=30
                )
                
                self._run_structured_segment(
                    segment_name="CONGESTION_S2",
                    load_type="congestion",
                    duration_seconds=30
                )
                
                # S3 & S4: No scenario (reference)
                self._run_structured_segment(
                    segment_name="NORMAL_S1",
                    load_type="none",
                    duration_seconds=30
                )
                
                self._run_structured_segment(
                    segment_name="NORMAL_S2",
                    load_type="none",
                    duration_seconds=30
                )
                
                # S5 & S6: Packet Loss
                self._run_structured_segment(
                    segment_name="PACKET_LOSS_S1",
                    load_type="packet_loss",
                    duration_seconds=30
                )
                
                self._run_structured_segment(
                    segment_name="PACKET_LOSS_S2",
                    load_type="packet_loss",
                    duration_seconds=30
                )
                
                # S7 & S8: No scenario (recovery)
                self._run_structured_segment(
                    segment_name="NORMAL_S3",
                    load_type="none",
                    duration_seconds=30
                )
                
                self._run_structured_segment(
                    segment_name="NORMAL_S4",
                    load_type="none",
                    duration_seconds=30
                )
                
                logger.info(f"\n[CYCLE {cycle}] Pattern complete - restarting")
        
        except KeyboardInterrupt:
            logger.info("\n\nCollection interrupted by user (Ctrl+C)")
            self.running = False
        except Exception as e:
            logger.error(f"Error in structured pattern: {str(e)}", exc_info=True)
            self.running = False
        finally:
            logger.info("=" * 80)
            logger.info("Structured pattern collection completed")
            logger.info("=" * 80)
    
    def _collect_baseline_phase(self, duration_seconds: int = 60):
        """
        Collect baseline samples WITHOUT any scenario load + establish network capacity.
        
        IMPROVEMENTS:
        1. Run iperf3 tests to establish baseline network capacity
        2. Track per-server performance during baseline
        3. Use baseline capacity for adaptive test duration
        4. Provide better logging of baseline establishment
        """
        logger.info(f"[BASELINE] Collecting baseline samples for {duration_seconds} seconds...")
        logger.info("[BASELINE] === PHASE 1: Establish network capacity with iperf3 ===")
        
        self.connection_tracker.reset_segment()  # Reset CSSR for baseline
        self.running = True
        start_time = datetime.now()
        samples_collected = 0
        iperf3_thread = None
        
        try:
            # Start iperf3 tests in background to establish capacity
            iperf3_thread = threading.Thread(
                target=self._run_iperf3_baseline_capacity,
                kwargs={'duration_seconds': duration_seconds},
                name="BASELINE_IPERF3",
                daemon=True
            )
            iperf3_thread.start()
            logger.info("[BASELINE] iperf3 capacity tests started (parallel with metrics)")
            
            # Collect metrics while iperf3 runs
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= duration_seconds:
                    logger.info(f"[BASELINE] Duration reached ({elapsed:.1f}s >= {duration_seconds}s), ending baseline")
                    break
                
                # Safety timeout: force exit if baseline exceeds 2x duration
                if elapsed > (duration_seconds * 2):
                    logger.warning(f"[BASELINE] SAFETY: Exceeded 2x duration ({elapsed:.0f}s), forcing baseline exit")
                    break
                
                try:
                    logger.debug("[BASELINE] Collecting sample...")
                    record = self.collect_single_sample(scenario_type='baseline')
                    self.data_persistence.save_record(record)
                    self.track_incident(record)
                    
                    samples_collected += 1
                    self._display_metrics(record, samples_collected)
                    logger.info(f"[BASELINE] Sample {samples_collected} saved")
                    
                except Exception as e:
                    logger.error(f"[BASELINE] Error collecting sample: {str(e)}", exc_info=True)
                
                time.sleep(30)  # 30-second interval
            
            # Signal iperf3 thread to stop
            self.running = False
            # Wait for iperf3 to complete
            if iperf3_thread:
                logger.debug("[BASELINE] Waiting for iperf3 thread to stop (max 5s)...")
                iperf3_thread.join(timeout=5)
                if iperf3_thread.is_alive():
                    logger.warning("[BASELINE] iperf3 thread did not stop within timeout")

            # Log baseline results
            if self.baseline_network_capacity_mbps:
                logger.info(f"[BASELINE] === CAPACITY ESTABLISHED: {self.baseline_network_capacity_mbps:.2f} Mbps ===")
                # Adjust adaptive test duration based on capacity
                if self.baseline_network_capacity_mbps > 10:
                    self.iperf3_test_duration_seconds = 15
                    logger.info("[BASELINE] Fast connection detected - using 15s iperf3 tests")
                elif self.baseline_network_capacity_mbps > 5:
                    self.iperf3_test_duration_seconds = 10
                    logger.info("[BASELINE] Medium connection - using 10s iperf3 tests")
                else:
                    self.iperf3_test_duration_seconds = 5
                    logger.info("[BASELINE] Slow connection - using 5s iperf3 tests")
            else:
                logger.warning("[BASELINE] Capacity not established from iperf3 tests")
            
            # Log per-server performance from baseline
            if self.server_performance:
                logger.info("[BASELINE] Per-server performance during baseline:")
                for (server, port), stats in list(self.server_performance.items())[:5]:  # Top 5
                    if stats['total_tests'] > 0:
                        success_rate = (stats['successes'] / stats['total_tests']) * 100
                        logger.info(f"  {server}:{port} - {success_rate:.1f}% success, {stats['avg_bandwidth']:.2f} Mbps avg")
        
        except Exception as e:
            logger.error(f"[BASELINE] Unexpected error in baseline: {str(e)}", exc_info=True)
        finally:
            try:
                logger.info(f"[BASELINE] Phase complete - {samples_collected} samples, capacity: {self.baseline_network_capacity_mbps or 'unknown'} Mbps")
            except Exception as e:
                logger.error(f"[BASELINE] Error in finally block: {str(e)}")

    
    def _run_iperf3_baseline_capacity(self, duration_seconds: int = 60):
        """
        Run iperf3 tests during baseline to establish network capacity.
        Tests run more frequently to get good sample of available bandwidth.
        Tracks per-server performance for later server selection.
        """
        logger.debug("[BASELINE_IPERF3] Starting capacity tests...")
        start_time = datetime.now()
        total_bandwidth = 0
        test_count = 0
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= duration_seconds:
                    break
                
                # Safety timeout: force exit if exceeds 2x duration
                if elapsed > (duration_seconds * 2):
                    logger.warning(f"[BASELINE_IPERF3] SAFETY: Exceeded 2x duration ({elapsed:.0f}s), forcing exit")
                    break
                
                try:
                    # Run one iperf3 test
                    logger.debug("[BASELINE_IPERF3] Running capacity test...")
                    result = self.iperf3_manager.run_iperf3_test(duration_seconds=5)
                    
                    if result and result.get('success'):
                        bandwidth = result.get('bandwidth_mbps', 0)
                        server = result.get('server', 'unknown')
                        port = result.get('port', 'unknown')
                        
                        total_bandwidth += bandwidth
                        test_count += 1
                        
                        # Track per-server performance
                        server_key = (server, port)
                        if server_key not in self.server_performance:
                            self.server_performance[server_key] = {
                                'successes': 0, 'failures': 0, 'avg_bandwidth': 0, 'total_tests': 0
                            }
                        self.server_performance[server_key]['successes'] += 1
                        self.server_performance[server_key]['total_tests'] += 1
                        self.server_performance[server_key]['avg_bandwidth'] = (
                            (self.server_performance[server_key]['avg_bandwidth'] * 
                             (self.server_performance[server_key]['successes'] - 1) + bandwidth) / 
                            self.server_performance[server_key]['successes']
                        )
                        
                        logger.debug(f"[BASELINE_IPERF3] Test {test_count}: {bandwidth:.2f} Mbps from {server}:{port}")
                        
                    else:
                        test_count += 1
                        if result:
                            server = result.get('server', 'unknown')
                            port = result.get('port', 'unknown')
                            server_key = (server, port)
                            if server_key not in self.server_performance:
                                self.server_performance[server_key] = {
                                    'successes': 0, 'failures': 0, 'avg_bandwidth': 0, 'total_tests': 0
                                }
                            self.server_performance[server_key]['failures'] += 1
                            self.server_performance[server_key]['total_tests'] += 1
                            logger.debug(f"[BASELINE_IPERF3] Test {test_count} FAILED from {server}:{port}")
                    
                except Exception as e:
                    logger.debug(f"[BASELINE_IPERF3] Error running capacity test: {e}")
                
                # Brief pause between tests
                time.sleep(8)
        
        finally:
            if test_count > 0:
                self.baseline_network_capacity_mbps = total_bandwidth / test_count
                self.scenario_cssr_stats['baseline']['tests'] = test_count
                logger.info(f"[BASELINE_IPERF3] Completed {test_count} tests, avg capacity: {self.baseline_network_capacity_mbps:.2f} Mbps")
    
    def _run_structured_segment(self, segment_name: str, load_type: str, duration_seconds: int = 30):
        """
        Run a single segment: optional load generator + iperf3 tests + metric collection in parallel.
        
        IMPROVEMENTS:
        1. Per-scenario CSSR tracking (congestion vs normal vs packet_loss)
        2. Load generator verification logging
        3. Increased test frequency (more frequent iperf3 tests)
        4. Per-server performance tracking
        5. Better real-time visibility
        
        Args:
            segment_name: Name for logging (e.g., "CONGESTION_S1")
            load_type: "congestion", "packet_loss", or "none"
            duration_seconds: How long to run the segment
        """
        logger.info(f"\n[{segment_name}] Starting {duration_seconds}s segment")
        logger.info(f"[{segment_name}] Load: {load_type.upper()} | iperf3: ENABLED | Baseline capacity: {self.baseline_network_capacity_mbps or 'establishing'}Mbps")
        
        # Map load_type to scenario_type for metric collection override
        scenario_map = {'congestion': 'congestion', 'packet_loss': 'packet_loss', 'none': 'normal'}
        scenario_type = scenario_map.get(load_type, 'baseline')
        
        # CRITICAL: Reset CSSR tracker for this segment (true extraction - only this segment's tests)
        self.connection_tracker.reset_segment()
        self.load_verification['tcp_load_active'] = False
        self.load_verification['udp_load_active'] = False
        
        self.running = True
        start_time = datetime.now()
        samples_collected = 0
        load_thread = None
        
        try:
            # Start load generator thread based on type
            if load_type == "congestion":
                self.load_verification['tcp_load_active'] = True
                load_thread = threading.Thread(
                    target=self._run_continuous_iperf3_load,
                    args=(duration_seconds,),
                    name=f"{segment_name}_LOAD",
                    daemon=True
                )
                load_thread.start()
                logger.info(f"[{segment_name}] [LOAD] TCP load generator STARTED - spawning iperf3 tests every ~1s")
            elif load_type == "packet_loss":
                self.load_verification['udp_load_active'] = True
                load_thread = threading.Thread(
                    target=self._run_continuous_udp_load,
                    args=(duration_seconds,),
                    name=f"{segment_name}_LOAD",
                    daemon=True
                )
                load_thread.start()
                logger.info(f"[{segment_name}] [LOAD] UDP flood load generator STARTED (includes iperf3 CSSR tracking)")
            else:  # "none" - NORMAL segment
                logger.info(f"[{segment_name}] No synthetic load generator (passive metric collection)")
                # For NORMAL segments: spawn ONLY iperf3 CSSR tracking (no load)
                load_thread = threading.Thread(
                    target=self._run_continuous_iperf3_for_cssr_tracking,
                    args=(duration_seconds,),
                    name=f"{segment_name}_CSSR",
                    daemon=True
                )
                load_thread.start()
                logger.info(f"[{segment_name}] [IDLE] iperf3 CSSR tracking STARTED (passive, no synthetic load)")
            
            # Collect samples while scenarios are active
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= duration_seconds:
                    break
                
                # Safety timeout: never let a segment run more than 2x its intended duration
                if elapsed > (duration_seconds * 2):
                    logger.warning(f"[{segment_name}] SAFETY: Segment exceeded 2x duration ({elapsed:.0f}s > {duration_seconds*2}s), forcing exit")
                    break
                
                try:
                    logger.debug(f"[{segment_name}] Collecting sample...")
                    record = self.collect_single_sample(scenario_type=scenario_type)
                    self.data_persistence.save_record(record)
                    self.track_incident(record)
                    
                    samples_collected += 1
                    self._display_metrics(record, samples_collected)
                    
                    # Log per-scenario statistics
                    loss_display = record.get('packet_loss_pct', 0)
                    cssr_display = record.get('cssr_proxy_pct', '?')
                    throughput = record.get('throughput_mbps', 0)
                    latency = record.get('latency_ms', 0)
                    
                    # Update scenario statistics
                    if scenario_type in self.scenario_cssr_stats:
                        # Will be updated from CSSR tracker data
                        pass
                    
                    load_status = "[LOAD]" if self.load_verification.get(f'{load_type.split("_")[0]}_load_active') else "[IDLE]"
                    traffic_type_display = record.get('traffic_type', 'unknown')
                    logger.info(
                        f"[{segment_name}] #{samples_collected} | {load_status} | Traffic:{traffic_type_display} | "
                        f"Loss:{loss_display:.1f}% | CSSR:{cssr_display}% | "
                        f"Throughput:{throughput:.2f}Mbps | Latency:{latency:.1f}ms"
                    )
                    
                except Exception as e:
                    logger.error(f"[{segment_name}] Error collecting sample: {str(e)}", exc_info=True)
                
                time.sleep(30)  # 30-second interval
        
        except Exception as e:
            logger.error(f"[{segment_name}] Error: {str(e)}", exc_info=True)
        finally:
            # Signal load thread to stop immediately
            self.running = False
            if load_thread:
                load_thread.join(timeout=5)  # Wait max 5 seconds for thread to exit
            
            # Capture segment statistics
            segment_cssr = self.connection_tracker.get_cssr() if hasattr(self.connection_tracker, 'get_cssr') else None
            if segment_cssr is not None and scenario_type in self.scenario_cssr_stats:
                self.scenario_cssr_stats[scenario_type]['tests'] = self.connection_tracker.total_connections if hasattr(self.connection_tracker, 'total_connections') else 0
                self.scenario_cssr_stats[scenario_type]['successes'] = self.connection_tracker.successful_connections if hasattr(self.connection_tracker, 'successful_connections') else 0
            
            logger.info(f"[{segment_name}] [DONE] SEGMENT COMPLETE")
            logger.info(f"[{segment_name}]   Samples collected: {samples_collected}")
            logger.info(f"[{segment_name}]   Scenario type: {scenario_type}")
            if segment_cssr is not None:
                logger.info(f"[{segment_name}]   CSSR: {segment_cssr:.1f}%")
            
            # Show actual measured impact
            if scenario_type == 'congestion':
                logger.info(f"[{segment_name}] [NOTE] Congestion impact measured via CSSR (connection success rate)")
                logger.info(f"[{segment_name}]       If CSSR is low during congestion, network is affected")
            elif scenario_type == 'packet_loss':
                logger.info(f"[{segment_name}] [NOTE] Packet loss measured via CSSR and UDP flood statistics")
                logger.info(f"[{segment_name}]       If CSSR drops significantly, UDP flooding is affecting TCP connectivity")
    
    def _run_continuous_iperf3_for_cssr_tracking(self, duration_seconds: int = 30):
        """
        Run iperf3 tests continuously for CSSR tracking (independent of load type).
        
        This runs EVERY 30 seconds (aligned with sample collection) to track network
        connection success rate across all scenario types (congestion, normal, packet_loss).
        
        Unlike _run_continuous_iperf3_load (which spawns every second), this waits for
        sample collection interval to keep bandwidth tests aligned with metrics.
        """
        logger.info("[IPERF3_CSSR] Starting iperf3 CSSR tracking")
        start_time = datetime.now()
        test_thread = None
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= duration_seconds:
                    break
                
                # Run one iperf3 test approximately every 30 seconds (aligned with sample interval)
                if test_thread is None or not test_thread.is_alive():
                    test_thread = threading.Thread(
                        target=self._run_and_track_iperf3_for_cssr,
                        daemon=True
                    )
                    test_thread.start()
                    logger.debug("[IPERF3_CSSR] Spawned test thread")
                
                time.sleep(30)  # Wait 30 seconds before next test (aligned with sample collection)
        except Exception as e:
            logger.error(f"[IPERF3_CSSR] Error: {str(e)}")
        finally:
            if test_thread:
                test_thread.join(timeout=15)
            logger.info("[IPERF3_CSSR] Stopped")
    
    def _run_continuous_iperf3_load(self, duration_seconds: int = 30):
        """Run continuous iperf3 TCP load for specified duration - saturates local network."""
        logger.info("[IPERF3_LOAD] Starting continuous TCP load")
        start_time = datetime.now()
        test_threads = []
        
        try:
            # Spawn MULTIPLE iperf3 tests in parallel to actually saturate bandwidth
            # A single iperf3 test might not create enough local network load
            active_test_count = 0
            max_parallel_tests = 3  # Run up to 3 simultaneous iperf3 tests to saturate connection
            
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= duration_seconds:
                    break
                
                # Maintain 3 concurrent iperf3 tests by spawning new ones as old ones complete
                active_threads = [t for t in test_threads if t.is_alive()]
                
                while len(active_threads) < max_parallel_tests and self.running:
                    test_thread = threading.Thread(
                        target=self._run_and_track_iperf3_for_cssr,
                        daemon=True
                    )
                    test_thread.start()
                    test_threads.append(test_thread)
                    active_threads.append(test_thread)
                    logger.debug(f"[IPERF3_LOAD] Spawned test {len(test_threads)} (now {len(active_threads)} active)")
                
                time.sleep(2)  # Check every 2 seconds
        except Exception as e:
            logger.error(f"[IPERF3_LOAD] Error: {str(e)}")
        finally:
            # Wait for all threads to complete
            for t in test_threads:
                t.join(timeout=15)
            logger.info(f"[IPERF3_LOAD] Stopped (ran {len(test_threads)} total tests)")
    
    def _run_continuous_udp_load(self, duration_seconds: int = 30):
        """Run continuous UDP flood then measure CSSR (TCP connectivity under packet loss)."""
        logger.info("[UDP_LOAD] Starting continuous UDP flood with CSSR measurement")
        start_time = datetime.now()
        udp_threads = []
        
        try:
            # First 20 seconds: UDP flood (run parallel floods for more aggressive impact)
            logger.info("[UDP_LOAD] Flooding network with high-bandwidth UDP packets")
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds()
                # Run UDP flood for first 20 seconds
                if elapsed < 20:
                    # Run up to 2 parallel UDP floods for aggressive packet generation
                    active_floods = [t for t in udp_threads if t.is_alive()]
                    
                    while len(active_floods) < 2 and self.running:
                        udp_thread = threading.Thread(
                            target=self._run_udp_flood_and_store,
                            daemon=True
                        )
                        udp_thread.start()
                        udp_threads.append(udp_thread)
                        active_floods.append(udp_thread)
                        logger.debug(f"[UDP_LOAD] Spawned UDP flood {len(udp_threads)} (now {len(active_floods)} active)")
                    
                    time.sleep(3)
                else:
                    break
            
            # Remaining time: Run iperf3 TCP tests (measure CSSR under packet loss)
            logger.info("[UDP_LOAD] UDP flood complete, now measuring TCP connectivity under congestion (CSSR)")
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= duration_seconds:
                    break
                
                # Run 1-2 iperf3 TCP tests to measure CSSR in presence of congested network
                iperf_thread = threading.Thread(
                    target=self._run_and_track_iperf3_for_cssr,
                    daemon=True
                )
                iperf_thread.start()
                iperf_thread.join(timeout=15)  # Wait for test to complete
                
                time.sleep(2)  # 2-second interval for iperf3 tests
                
        except Exception as e:
            logger.error(f"[UDP_LOAD] Error: {str(e)}")
        finally:
            # Wait for all UDP floods to complete
            for t in udp_threads:
                t.join(timeout=5)
            logger.info(f"[UDP_LOAD] Stopped (ran {len(udp_threads)} UDP flood tests)")
    
    # ========== LOAD GENERATORS (SCENARIO LOADS ONLY - NO METRIC COLLECTION) ==========
    
    def _generate_baseline_load(self, duration_minutes: int = 15):
        """
        Baseline load generator: Passive - maintain system activity without artificial stress.
        Runs for specified duration while metric collection happens in parallel.
        """
        logger.info("[BASELINE_LOAD] Passive network state (no artificial load)")
        start_time = datetime.now()
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                if duration_minutes > 0 and elapsed >= duration_minutes:
                    break
                time.sleep(1)
        except Exception as e:
            logger.error(f"[BASELINE_LOAD] Error: {str(e)}")
        finally:
            logger.info("[BASELINE_LOAD] Completed")
    
    def _generate_congestion_load(self, duration_minutes: int = 15):
        """
        Congestion load generator: Continuous iperf3 TCP load injection.
        Runs for specified duration while metric collection happens in parallel.
        """
        if not self.iperf_manager.iperf3_available:
            logger.warning("[CONGESTION_LOAD] iperf3 not available - skipping congestion load")
            self._generate_baseline_load(duration_minutes)
            return
        
        logger.info("[CONGESTION_LOAD] Continuous iperf3 TCP load injection")
        start_time = datetime.now()
        test_thread = None
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                if duration_minutes > 0 and elapsed >= duration_minutes:
                    break
                
                # Spawn iperf3 every iteration (or when previous finishes)
                if test_thread is None or not test_thread.is_alive():
                    test_thread = threading.Thread(
                        target=self._run_and_track_iperf3_for_cssr,
                        daemon=True
                    )
                    test_thread.start()
                
                time.sleep(1)
        except Exception as e:
            logger.error(f"[CONGESTION_LOAD] Error: {str(e)}")
        finally:
            if test_thread:
                test_thread.join(timeout=5)
            logger.info("[CONGESTION_LOAD] Completed")
    
    def _generate_normal_load(self, duration_minutes: int = 15):
        """
        Normal load generator: Passive reference baseline (same as baseline load).
        Runs for specified duration while metric collection happens in parallel.
        """
        logger.info("[NORMAL_LOAD] Passive network state (reference baseline)")
        start_time = datetime.now()
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                if duration_minutes > 0 and elapsed >= duration_minutes:
                    break
                time.sleep(1)
        except Exception as e:
            logger.error(f"[NORMAL_LOAD] Error: {str(e)}")
        finally:
            logger.info("[NORMAL_LOAD] Completed")
    
    def _generate_packet_loss_load(self, duration_minutes: int = 15):
        """
        Packet Loss load generator: Continuous UDP flood for packet loss injection.
        Runs for specified duration while metric collection happens in parallel.
        """
        logger.info("[PACKET_LOSS_LOAD] Continuous UDP flood injection")
        start_time = datetime.now()
        udp_thread = None
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                if duration_minutes > 0 and elapsed >= duration_minutes:
                    break
                
                # Spawn UDP flood (continuous)
                if udp_thread is None or not udp_thread.is_alive():
                    udp_thread = threading.Thread(
                        target=self._run_udp_flood_and_store,
                        daemon=True
                    )
                    udp_thread.start()
                
                time.sleep(1)
        except Exception as e:
            logger.error(f"[PACKET_LOSS_LOAD] Error: {str(e)}")
        finally:
            if udp_thread:
                udp_thread.join(timeout=5)
            logger.info("[PACKET_LOSS_LOAD] Completed")
    
    def _collect_metrics_parallel(self, duration_minutes: int = 15):
        """
        UNIFIED Metric Collection: Collects WiFi + Router + QoS metrics continuously
        while ALL 4 scenarios are running their loads in parallel.
        
        This ensures metrics are captured with network affected by ALL load types
        simultaneously (baseline + congestion + normal + packet_loss).
        """
        logger.info("[METRIC_COLLECTION] Starting unified collection (30-second intervals)")
        logger.info("[METRIC_COLLECTION] Sampling while: BASELINE | CONGESTION | NORMAL | PACKET_LOSS active")
        
        start_time = datetime.now()
        samples_collected = 0
        baseline_samples = []
        baseline_phase_complete = False
        
        # Router already initialized in main thread - no need to initialize again
        logger.info("[METRIC_COLLECTION] Router already initialized - starting collection immediately")
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                if duration_minutes > 0 and elapsed >= duration_minutes:
                    break
                
                # Collect single sample
                try:
                    logger.debug("[METRIC_COLLECTION] Starting sample collection...")
                    record = self.collect_single_sample()
                    logger.debug("[METRIC_COLLECTION] Sample collected successfully")
                    
                    # Baseline phase for anomaly detection
                    if not baseline_phase_complete:
                        baseline_samples.append(record)
                        if len(baseline_samples) >= 20:
                            self.anomaly_detector.update_baseline(baseline_samples)
                            baseline_phase_complete = True
                            logger.info("[METRIC_COLLECTION] Baseline phase complete")
                    
                    # Save to CSV
                    logger.debug(f"[METRIC_COLLECTION] Saving record to CSV...")
                    self.data_persistence.save_record(record)
                    logger.debug(f"[METRIC_COLLECTION] Record saved successfully")
                    self.track_incident(record)
                    
                    samples_collected += 1
                    self._display_metrics(record, samples_collected)
                    logger.info(f"[METRIC_COLLECTION] Sample {samples_collected} saved (elapsed: {elapsed:.1f}min)")
                    
                except Exception as e:
                    logger.error(f"[METRIC_COLLECTION] Error collecting sample: {str(e)}", exc_info=True)
                
                # 30-second interval between samples
                time.sleep(30)
        
        except Exception as e:
            logger.error(f"[METRIC_COLLECTION] Outer error: {str(e)}", exc_info=True)
        finally:
            logger.info(f"[METRIC_COLLECTION] Completed - {samples_collected} samples collected")
    
    def _run_baseline_with_iperf3(self, duration_minutes: int = 15):
        """Baseline scenario with iperf3 tests every 60 seconds."""
        if not self.iperf_manager.iperf3_available:
            logger.warning("[BASELINE] iperf3 not available - running without tests")
            self.run_collection(duration_minutes=duration_minutes, interval_seconds=30)
            return
        
        self.running = True
        self.sampling_interval = 30
        start_time = datetime.now()
        baseline_samples = []
        baseline_phase_complete = False
        test_thread = None
        sample_count = 0
        
        logger.info("[BASELINE] 30-second intervals with iperf3 tests")
        
        # Initialize router metrics collection if credentials are available
        router_enabled = False
        if self.router_collector.gateway:
            if not self.router_collector.username or not self.router_collector.password:
                # Use defaults if not explicitly set
                self.router_collector.username = "admin"
                self.router_collector.password = "admin"
            router_enabled = True
            logger.info(f"Router metrics collection enabled: {self.router_collector.gateway}")
            # Detect router type at startup (synchronously to avoid race condition)
            router_detected = self.router_collector.detect_router()
            if router_detected:
                logger.info(f"Router type detected: {self.router_collector.router_type}")
            else:
                logger.warning(f"Could not detect router at {self.router_collector.gateway}, but will continue attempting")
        else:
            logger.info("Router metrics collection disabled (no gateway configured)")
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                # Only break if duration_minutes > 0 (limited mode). If 0, run indefinitely
                if duration_minutes > 0 and elapsed >= duration_minutes:
                    break
                
                # iperf3 every 2 samples (~60 seconds)
                if sample_count % 2 == 0:
                    if test_thread is None or not test_thread.is_alive():
                        test_thread = threading.Thread(target=self._run_and_track_iperf3_for_cssr, daemon=True)
                        test_thread.start()
                
                record = self.collect_single_sample()
                
                if not baseline_phase_complete:
                    baseline_samples.append(record)
                    if len(baseline_samples) >= 20:
                        self.anomaly_detector.update_baseline(baseline_samples)
                        baseline_phase_complete = True
                        logger.info("[BASELINE] Baseline phase complete")
                
                self.data_persistence.save_record(record)
                self.track_incident(record)
                
                sample_num = int(elapsed * 2)
                self._display_metrics(record, sample_num)
                sample_count += 1
                
                time.sleep(30)
        
        except KeyboardInterrupt:
            logger.info("[BASELINE] Stopped by user")
        finally:
            self.flush_pending_incidents()
            self.running = False
            if test_thread:
                test_thread.join(timeout=10)
            logger.info("[BASELINE] Complete")
    
    def _run_congestion_with_iperf3_measurement(self, duration_minutes: int = 15):
        """Congestion scenario: iperf3 load + bandwidth measurement."""
        if not self.iperf_manager.iperf3_available:
            logger.warning("[CONGESTION] iperf3 not available - running without load injection")
            self.run_collection(duration_minutes=duration_minutes, interval_seconds=15)
            return
        
        logger.info("[CONGESTION] iperf3 TCP traffic every 15 seconds + measurements")
        
        # Initialize router metrics collection if credentials are available
        router_enabled = False
        if self.router_collector.gateway:
            if not self.router_collector.username or not self.router_collector.password:
                # Use defaults if not explicitly set
                self.router_collector.username = "admin"
                self.router_collector.password = "admin"
            router_enabled = True
            logger.info(f"Router metrics collection enabled: {self.router_collector.gateway}")
            # Detect router type at startup (synchronously to avoid race condition)
            router_detected = self.router_collector.detect_router()
            if router_detected:
                logger.info(f"Router type detected: {self.router_collector.router_type}")
            else:
                logger.warning(f"Could not detect router at {self.router_collector.gateway}, but will continue attempting")
        else:
            logger.info("Router metrics collection disabled (no gateway configured)")
        
        self.running = True
        self.sampling_interval = 15
        start_time = datetime.now()
        baseline_samples = []
        baseline_phase_complete = False
        test_thread = None
        sample_count = 0
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                # Only break if duration_minutes > 0 (limited mode). If 0, run indefinitely
                if duration_minutes > 0 and elapsed >= duration_minutes:
                    break
                
                # Continuous iperf3 load every ~15 seconds
                if test_thread is None or not test_thread.is_alive():
                    test_thread = threading.Thread(target=self._run_and_track_iperf3_for_cssr, daemon=True)
                    test_thread.start()
                
                record = self.collect_single_sample()
                
                if not baseline_phase_complete:
                    baseline_samples.append(record)
                    if len(baseline_samples) >= 10:
                        self.anomaly_detector.update_baseline(baseline_samples)
                        baseline_phase_complete = True
                        logger.info("[CONGESTION] Baseline phase complete")
                
                self.data_persistence.save_record(record)
                self.track_incident(record)
                
                sample_num = int(elapsed * 4)
                self._display_metrics(record, sample_num)
                sample_count += 1
                
                time.sleep(15)
        
        except KeyboardInterrupt:
            logger.info("[CONGESTION] Stopped by user")
        finally:
            self.flush_pending_incidents()
            self.running = False
            if test_thread:
                test_thread.join(timeout=10)
            logger.info("[CONGESTION] Complete")
    
    def _run_packet_loss_with_iperf3_measurement(self, duration_minutes: int = 15):
        """Packet loss scenario: UDP flood for packet loss + TCP measurement."""
        if not self.iperf_manager.iperf3_available:
            logger.warning("[PACKET_LOSS] iperf3 not available - running without stress")
            self.run_collection(duration_minutes=duration_minutes, interval_seconds=15)
            return
        
        logger.info("[PACKET_LOSS] UDP flood injection + TCP bandwidth measurement")
        
        # Initialize router metrics collection if credentials are available
        router_enabled = False
        if self.router_collector.gateway:
            if not self.router_collector.username or not self.router_collector.password:
                # Use defaults if not explicitly set
                self.router_collector.username = "admin"
                self.router_collector.password = "admin"
            router_enabled = True
            logger.info(f"Router metrics collection enabled: {self.router_collector.gateway}")
            # Detect router type at startup (synchronously to avoid race condition)
            router_detected = self.router_collector.detect_router()
            if router_detected:
                logger.info(f"Router type detected: {self.router_collector.router_type}")
            else:
                logger.warning(f"Could not detect router at {self.router_collector.gateway}, but will continue attempting")
        else:
            logger.info("Router metrics collection disabled (no gateway configured)")
        
        self.running = True
        self.sampling_interval = 15
        start_time = datetime.now()
        baseline_samples = []
        baseline_phase_complete = False
        test_thread = None
        udp_thread = None
        sample_count = 0
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                # Only break if duration_minutes > 0 (limited mode). If 0, run indefinitely
                if duration_minutes > 0 and elapsed >= duration_minutes:
                    break
                
                # UDP flood for packet loss injection
                if udp_thread is None or not udp_thread.is_alive():
                    udp_thread = threading.Thread(
                        target=self._run_udp_flood_and_store,
                        daemon=True
                    )
                    udp_thread.start()
                
                # Also measure TCP bandwidth impact
                if sample_count % 2 == 0:
                    if test_thread is None or not test_thread.is_alive():
                        test_thread = threading.Thread(target=self._run_and_track_iperf3_for_cssr, daemon=True)
                        test_thread.start()
                
                record = self.collect_single_sample()
                
                if not baseline_phase_complete:
                    baseline_samples.append(record)
                    if len(baseline_samples) >= 10:
                        self.anomaly_detector.update_baseline(baseline_samples)
                        baseline_phase_complete = True
                        logger.info("[PACKET_LOSS] Baseline phase complete")
                
                self.data_persistence.save_record(record)
                self.track_incident(record)
                
                sample_num = int(elapsed * 4)
                self._display_metrics(record, sample_num)
                sample_count += 1
                
                time.sleep(15)
        
        except KeyboardInterrupt:
            logger.info("[PACKET_LOSS] Stopped by user")
        finally:
            self.flush_pending_incidents()
            self.running = False
            if test_thread:
                test_thread.join(timeout=10)
            if udp_thread:
                udp_thread.join(timeout=10)
            logger.info("[PACKET_LOSS] Complete")
    
    def _run_normal_passive_with_iperf3(self, duration_minutes: int = 15):
        """Normal scenario: Pure passive collection WITHOUT load injection, with iperf3 tests every 60 seconds.
        
        This scenario captures 'typical' network behavior without artificial stress,
        providing realistic baseline data that complements the load scenarios.
        """
        if not self.iperf_manager.iperf3_available:
            logger.warning("[NORMAL] iperf3 not available - running passive collection only")
            self.run_collection(duration_minutes=duration_minutes, interval_seconds=30)
            return
        
        logger.info("[NORMAL] Pure passive WiFi + router metrics, with iperf3 measurements every 60s")
        
        # Initialize router metrics collection if credentials are available
        router_enabled = False
        if self.router_collector.gateway:
            if not self.router_collector.username or not self.router_collector.password:
                # Use defaults if not explicitly set
                self.router_collector.username = "admin"
                self.router_collector.password = "admin"
            router_enabled = True
            logger.info(f"Router metrics collection enabled: {self.router_collector.gateway}")
            # Detect router type at startup (synchronously to avoid race condition)
            router_detected = self.router_collector.detect_router()
            if router_detected:
                logger.info(f"Router type detected: {self.router_collector.router_type}")
            else:
                logger.warning(f"Could not detect router at {self.router_collector.gateway}, but will continue attempting")
        else:
            logger.info("Router metrics collection disabled (no gateway configured)")
        
        self.running = True
        self.sampling_interval = 30
        start_time = datetime.now()
        baseline_samples = []
        baseline_phase_complete = False
        test_thread = None
        sample_count = 0
        
        logger.info("[NORMAL] 30-second intervals with iperf3 tests every ~60 seconds")
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                # Only break if duration_minutes > 0 (limited mode). If 0, run indefinitely
                if duration_minutes > 0 and elapsed >= duration_minutes:
                    break
                
                # iperf3 every 2 samples (~60 seconds) - same as baseline for consistency
                if sample_count % 2 == 0:
                    if test_thread is None or not test_thread.is_alive():
                        test_thread = threading.Thread(target=self._run_and_track_iperf3_for_cssr, daemon=True)
                        test_thread.start()
                
                record = self.collect_single_sample()
                
                if not baseline_phase_complete:
                    baseline_samples.append(record)
                    if len(baseline_samples) >= 20:
                        self.anomaly_detector.update_baseline(baseline_samples)
                        baseline_phase_complete = True
                        logger.info("[NORMAL] Baseline phase complete")
                
                self.data_persistence.save_record(record)
                self.track_incident(record)
                
                sample_num = int(elapsed * 2)
                self._display_metrics(record, sample_num)
                sample_count += 1
                
                time.sleep(30)
        
        except KeyboardInterrupt:
            logger.info("[NORMAL] Stopped by user")
        finally:
            self.flush_pending_incidents()
            self.running = False
            if test_thread:
                test_thread.join(timeout=10)
            logger.info("[NORMAL] Complete")
    
        """Helper: run UDP flood test in background for packet loss injection."""
        try:
            server_info = self.iperf_manager.get_available_server()
            if not server_info:
                logger.debug("[UDP_FLOOD] No server available")
                return
            
            server, port = server_info
            results = self.iperf_manager.run_udp_flood_with_rotation(
                duration=15,
                bandwidth='50M',
                reverse=False
            )
            
            if results:
                logger.debug(f"[UDP_FLOOD] Flood completed: {results.get('throughput_mbps', 0):.2f} Mbps")
        except Exception as e:
            logger.debug(f"[UDP_FLOOD] Error: {str(e)}")
    
    def run_collection_with_iperf3(self, duration_minutes: int = 60, interval_seconds: int = 30):
        """
        Run continuous data collection with periodic iperf3 tests
        Runs iperf3 test every 3 samples to populate CSSR metric
        
        Args:
            duration_minutes: How long to collect data (0 = infinite)
            interval_seconds: Sampling interval
        """
        """
        Run continuous data collection with periodic iperf3 tests
        Runs iperf3 test every 3 samples to populate CSSR metric
        
        Args:
            duration_minutes: How long to collect data (0 = infinite)
            interval_seconds: Sampling interval
        """
        if not self.iperf_manager.iperf3_available:
            logger.warning("iperf3 not available, falling back to standard collection")
            self.run_collection(duration_minutes=duration_minutes, interval_seconds=interval_seconds)
            return
        
        self.running = True
        self.sampling_interval = interval_seconds
        start_time = datetime.now()
        baseline_samples = []
        baseline_phase_complete = False
        test_thread = None
        sample_count = 0
        
        logger.info(f"Starting QoS collection with iperf3 tests for {duration_minutes} minutes...")
        logger.info(f"Configuration: Zone={self.zone_id}, Cell={self.cell_id}, Node={self.node_id}")
        logger.info(f"iperf3 tests will run every ~{interval_seconds * 2} seconds to measure CSSR")
        
        # Initialize router metrics collection (NEW: using helper method)
        self._initialize_router()
        
        try:
            while self.running:
                # Check if we should stop
                if duration_minutes > 0:
                    elapsed = (datetime.now() - start_time).total_seconds() / 60
                    if elapsed >= duration_minutes:
                        break
                
                # Run iperf3 test every 2 samples (non-blocking in background)
                # Only start new test if previous one finished
                if sample_count % 2 == 0:
                    if test_thread is None or not test_thread.is_alive():
                        logger.debug(f"Spawning iperf3 test thread (sample {sample_count})")
                        test_thread = threading.Thread(
                            target=self._run_and_track_iperf3_for_cssr,
                            daemon=True
                        )
                        test_thread.start()
                    else:
                        logger.debug(f"iperf3 test still running from previous cycle, skipping (sample {sample_count})")
                
                # Collect sample
                record = self.collect_single_sample()
                
                # Baseline phase (first 30 samples ~ 15 minutes at 30sec interval)
                if not baseline_phase_complete:
                    baseline_samples.append(record)
                    if len(baseline_samples) >= 30:
                        self.anomaly_detector.update_baseline(baseline_samples)
                        baseline_phase_complete = True
                        logger.info("Baseline phase complete, anomaly detection enabled")
                
                # Save record
                self.data_persistence.save_record(record)
                
                # Display metrics in console
                sample_num = int((datetime.now() - start_time).total_seconds() / interval_seconds)
                self._display_metrics(record, sample_num)
                
                # Track incidents (group consecutive anomalies)
                self.track_incident(record)
                
                sample_count += 1
                
                # Wait for next interval
                time.sleep(interval_seconds)
        
        except KeyboardInterrupt:
            logger.info("Collection interrupted by user")
        except Exception as e:
            logger.error(f"Error during collection: {str(e)}", exc_info=True)
        finally:
            self.flush_pending_incidents()
            self.running = False
            if test_thread:
                test_thread.join(timeout=10)
            logger.info("Data collection with iperf3 stopped")
    
    def _run_and_track_iperf3_for_cssr(self):
        """Helper: run iperf3 test and track result for CSSR metric with diagnostics"""
        test_start_time = datetime.now()
        logger.debug(f"[CSSR] iperf3 test thread started at {test_start_time.strftime('%H:%M:%S')}")
        
        results = self.iperf_manager.run_bandwidth_test_with_rotation(
            duration=10, reverse=False
        )
        
        test_duration = (datetime.now() - test_start_time).total_seconds()
        
        # Track the iperf3 result in CSSR tracker
        if results:
            transferred_bytes = results.get('transferred_bytes', 0)
            duration_sec = results.get('duration_sec', 0)
            throughput = results['throughput_mbps']
            server = results.get('server', 'unknown')
            port = results.get('port', 'unknown')
            logger.info(f"[CSSR] SUCCESS: {throughput:.2f} Mbps from {server}:{port} ({transferred_bytes/1024/1024:.1f} MB) | Completed in {test_duration:.1f}s")
            # Success if we got any meaningful data transfer (min 50KB)
            self.connection_tracker.track_iperf3_result(0, transferred_bytes, duration_sec)
            
            # Cache bandwidth result for throughput_mbps field (valid for 2 minutes)
            self.latest_iperf3_bandwidth_mbps = throughput
            self.latest_iperf3_timestamp = datetime.now()
        else:
            logger.warning(f"[CSSR] iperf3 test FAILED (timeout or server unavailable) after {test_duration:.1f}s")
            self.connection_tracker.track_iperf3_result(1, 0, 0, "iperf3 test failed")
    
    def run_scenario(self, scenario_name: str, duration_minutes: int = 10):
        """
        Run a predefined test scenario with network load injection
        
        Scenarios:
        - 'baseline': Light browsing, stable conditions (no load injection)
        - 'congestion': Heavy traffic simulation using iperf3
        - 'packet_loss': Packet loss simulation (throughput degradation)
        - 'throughput': Maximum throughput test
        """
        logger.info(f"Starting scenario: {scenario_name}")
        logger.info(f"Duration: {duration_minutes} minutes")
        
        try:
            if scenario_name == 'baseline':
                logger.info("Running BASELINE scenario: Light browsing, stable conditions")
                self.run_collection(duration_minutes=duration_minutes, interval_seconds=30)
            
            elif scenario_name == 'congestion':
                logger.info("Running CONGESTION scenario with iperf3 load injection...")
                self._run_congestion_scenario(duration_minutes=duration_minutes)
            
            elif scenario_name == 'packet_loss':
                logger.info("Running PACKET_LOSS scenario: Simulating degraded conditions")
                self._run_packet_loss_scenario(duration_minutes=duration_minutes)
            
            elif scenario_name == 'throughput':
                logger.info("Running THROUGHPUT scenario: Maximum bandwidth test")
                self._run_throughput_scenario(duration_minutes=duration_minutes)
            
            else:
                logger.error(f"Unknown scenario: {scenario_name}")
        
        except Exception as e:
            logger.error(f"Error running scenario: {str(e)}", exc_info=True)
    
    def _run_congestion_scenario(self, duration_minutes: int = 10):
        """
        Simulate network congestion using iperf3 against a REMOTE server.
        This generates real traffic through your WiFi/Ethernet connection.
        """
        if not self.iperf_manager.iperf3_available:
            logger.warning("iperf3 not available - running as standard collection without load injection")
            self.run_collection(duration_minutes=duration_minutes, interval_seconds=15)
            return
        
        # Find an available server from the pool
        server_info = self.iperf_manager.get_available_server()
        if not server_info:
            logger.warning("No iperf3 servers reachable, running standard collection")
            self.run_collection(duration_minutes=duration_minutes, interval_seconds=15)
            return
        
        logger.info(f"Initial iperf3 server: {server_info[0]}:{server_info[1]}")
        logger.info("All iperf3 traffic will go through your real network connection")
        logger.info("Server rotation enabled - will switch servers if one becomes busy")
        
        # Initialize router metrics collection if credentials are available
        router_enabled = False
        if self.router_collector.gateway:
            if not self.router_collector.username or not self.router_collector.password:
                # Use defaults if not explicitly set
                self.router_collector.username = "admin"
                self.router_collector.password = "admin"
            router_enabled = True
            logger.info(f"Router metrics collection enabled: {self.router_collector.gateway}")
            # Detect router type at startup (synchronously to avoid race condition)
            router_detected = self.router_collector.detect_router()
            if router_detected:
                logger.info(f"Router type detected: {self.router_collector.router_type}")
            else:
                logger.warning(f"Could not detect router at {self.router_collector.gateway}, but will continue attempting")
        else:
            logger.info("Router metrics collection disabled (no gateway configured)")
        
        # Run collection while generating real network load
        self.running = True
        self.sampling_interval = 15
        start_time = datetime.now()
        baseline_samples = []
        baseline_phase_complete = False
        test_thread = None
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                # Check duration (0 = infinite)
                if duration_minutes > 0 and elapsed >= duration_minutes:
                    break
                
                # Run iperf3 test with server rotation (tries next server if busy)
                # Only start a new test if the previous one has finished
                if duration_minutes <= 0 or elapsed < duration_minutes - 1:
                    if test_thread is None or not test_thread.is_alive():
                        test_thread = threading.Thread(
                            target=self.iperf_manager.run_bandwidth_test_with_rotation,
                            args=(15, False),
                            daemon=True
                        )
                        test_thread.start()
                
                # Collect sample under real load
                record = self.collect_single_sample()
                
                if not baseline_phase_complete:
                    baseline_samples.append(record)
                    if len(baseline_samples) >= 20:
                        self.anomaly_detector.update_baseline(baseline_samples)
                        baseline_phase_complete = True
                        logger.info("Baseline phase complete, anomaly detection enabled")
                
                self.data_persistence.save_record(record)
                self.track_incident(record)
                
                # Display metrics in console
                sample_num = int((datetime.now() - start_time).total_seconds() / 15)
                self._display_metrics(record, sample_num)
                
                time.sleep(15)
        
        except KeyboardInterrupt:
            logger.info("Congestion scenario interrupted by user")
        finally:
            self.flush_pending_incidents()
            self.running = False
            if test_thread:
                test_thread.join(timeout=10)
            logger.info("Congestion scenario completed")
    
    def _run_packet_loss_scenario(self, duration_minutes: int = 10):
        """
        Induce real packet loss by saturating the connection with iperf3 UDP traffic
        to a remote server. This floods your real WiFi/ISP link, causing genuine
        queuing, latency spikes, and packet drops.
        """
        if not self.iperf_manager.iperf3_available:
            logger.warning("iperf3 not available - running as standard collection")
            self.run_collection(duration_minutes=duration_minutes, interval_seconds=15)
            return
        
        # Find an available server from the pool
        server_info = self.iperf_manager.get_available_server()
        if not server_info:
            logger.warning("No iperf3 servers reachable, running standard collection")
            self.run_collection(duration_minutes=duration_minutes, interval_seconds=15)
            return
        
        logger.info(f"Initial iperf3 server: {server_info[0]}:{server_info[1]}")
        logger.info("UDP flood will saturate your real connection to induce packet loss")
        logger.info("Server rotation enabled - will switch servers if one becomes busy")
        
        # Initialize router metrics collection if credentials are available
        router_enabled = False
        if self.router_collector.gateway:
            if not self.router_collector.username or not self.router_collector.password:
                # Use defaults if not explicitly set
                self.router_collector.username = "admin"
                self.router_collector.password = "admin"
            router_enabled = True
            logger.info(f"Router metrics collection enabled: {self.router_collector.gateway}")
            # Detect router type at startup (synchronously to avoid race condition)
            router_detected = self.router_collector.detect_router()
            if router_detected:
                logger.info(f"Router type detected: {self.router_collector.router_type}")
            else:
                logger.warning(f"Could not detect router at {self.router_collector.gateway}, but will continue attempting")
        else:
            logger.info("Router metrics collection disabled (no gateway configured)")
        
        self.running = True
        self.sampling_interval = 15
        start_time = datetime.now()
        test_thread = None
        self._last_udp_result = {}  # Shared state for UDP test results
        
        try:
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                # Check duration (0 = infinite)
                if duration_minutes > 0 and elapsed >= duration_minutes:
                    break
                
                # Run UDP flood with high bandwidth to saturate the link
                # This causes real queuing and packet drops at the bottleneck
                if duration_minutes <= 0 or elapsed < duration_minutes - 1:
                    if test_thread is None or not test_thread.is_alive():
                        test_thread = threading.Thread(
                            target=self._run_udp_flood_and_store,
                            daemon=True
                        )
                        test_thread.start()
                
                # Collect sample during real network stress
                record = self.collect_single_sample()
                
                # If iperf3 UDP test reported packet loss, use that (more accurate than ping)
                if self._last_udp_result:
                    udp_loss = self._last_udp_result.get('packet_loss_pct', 0)
                    udp_jitter = self._last_udp_result.get('jitter_ms', 0)
                    metrics_updated = False
                    if udp_loss > record['packet_loss_pct']:
                        record['packet_loss_pct'] = udp_loss
                        metrics_updated = True
                    if udp_jitter > record['jitter_ms']:
                        record['jitter_ms'] = udp_jitter
                        metrics_updated = True
                    # Re-run anomaly detection with corrected UDP metrics
                    if metrics_updated:
                        is_anomaly, anomaly_type, anomaly_score = self.anomaly_detector.detect_anomaly(record)
                        record['anomaly_flag'] = is_anomaly
                        record['anomaly_type'] = anomaly_type
                        record['anomaly_score'] = anomaly_score
                
                self.data_persistence.save_record(record)
                self.track_incident(record)
                
                # Display metrics in console
                sample_num = int((datetime.now() - start_time).total_seconds() / 15)
                self._display_metrics(record, sample_num)
                
                time.sleep(15)
        
        except KeyboardInterrupt:
            logger.info("Packet loss scenario interrupted")
        finally:
            self.flush_pending_incidents()
            self.running = False
            if test_thread:
                test_thread.join(timeout=10)
            logger.info("Packet loss scenario completed")
    
    def _run_udp_flood_and_store(self):
        """Run UDP flood test and store the result for the packet_loss scenario to use"""
        result = self.iperf_manager.run_udp_flood_with_rotation(
            duration=15, bandwidth='100M', reverse=True
        )
        self._last_udp_result = result
        if result:
            logger.info(f"UDP flood: {result['throughput_mbps']:.2f} Mbps | "
                       f"Loss={result['packet_loss_pct']:.1f}% ({result.get('lost_packets', 0)}/{result.get('total_packets', 0)} pkts) | "
                       f"Jitter={result.get('jitter_ms', 0):.1f}ms")
    
    def _run_throughput_scenario(self, duration_minutes: int = 5):
        """
        Run maximum throughput test against a REMOTE iperf3 server.
        Measures your real sustained WiFi/ISP bandwidth under full load.
        """
        if not self.iperf_manager.iperf3_available:
            logger.warning("iperf3 not available - using standard collection")
            self.run_collection(duration_minutes=duration_minutes, interval_seconds=10)
            return
        
        # Find an available server from the pool
        server_info = self.iperf_manager.get_available_server()
        if not server_info:
            logger.warning("No iperf3 servers reachable")
            self.run_collection(duration_minutes=duration_minutes, interval_seconds=10)
            return
        
        logger.info(f"Initial iperf3 server: {server_info[0]}:{server_info[1]}")
        logger.info("Measuring your real network bandwidth")
        logger.info("Server rotation enabled - will switch servers if one becomes busy")
        
        # Initialize router metrics collection if credentials are available
        router_enabled = False
        if self.router_collector.gateway:
            if not self.router_collector.username or not self.router_collector.password:
                # Use defaults if not explicitly set
                self.router_collector.username = "admin"
                self.router_collector.password = "admin"
            router_enabled = True
            logger.info(f"Router metrics collection enabled: {self.router_collector.gateway}")
            # Detect router type at startup (synchronously to avoid race condition)
            router_detected = self.router_collector.detect_router()
            if router_detected:
                logger.info(f"Router type detected: {self.router_collector.router_type}")
            else:
                logger.warning(f"Could not detect router at {self.router_collector.gateway}, but will continue attempting")
        else:
            logger.info("Router metrics collection disabled (no gateway configured)")
        
        self.running = True
        start_time = datetime.now()
        test_thread = None
        
        try:
            logger.info(f"Running {duration_minutes if duration_minutes > 0 else 'infinite'}-minute real throughput test...")
            
            while self.running:
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                # Check duration (0 = infinite)
                if duration_minutes > 0 and elapsed >= duration_minutes:
                    break
                
                # Run iperf3 with server rotation for sustained throughput
                if test_thread is None or not test_thread.is_alive():
                    test_thread = threading.Thread(
                        target=self._run_and_log_throughput_test,
                        daemon=True
                    )
                    test_thread.start()
                
                # Collect system & network metrics during the test
                record = self.collect_single_sample()
                self.data_persistence.save_record(record)
                
                # Display metrics in console
                sample_num = int((datetime.now() - start_time).total_seconds() / 10)
                self._display_metrics(record, sample_num)
                
                time.sleep(10)
        
        except KeyboardInterrupt:
            logger.info("Throughput scenario interrupted")
        except Exception as e:
            logger.error(f"Error in throughput scenario: {str(e)}")
        finally:
            self.flush_pending_incidents()
            self.running = False
            if test_thread:
                test_thread.join(timeout=10)
            logger.info("Throughput scenario completed")
    
    def _run_and_log_throughput_test(self):
        """Helper: run a single iperf3 test with server rotation and log the result"""
        results = self.iperf_manager.run_bandwidth_test_with_rotation(
            duration=30, reverse=False
        )
        
        # Track iperf3 result in CSSR tracker (for connection success rate proxy)
        if results:
            transferred_bytes = results.get('transferred_bytes', 0)
            duration_sec = results.get('duration_sec', 0)
            logger.info(f"iperf3 real throughput: {results['throughput_mbps']:.2f} Mbps ({results['test_type']})")
            # Success if we got any meaningful data transfer (min 50KB)
            self.connection_tracker.track_iperf3_result(0, transferred_bytes, duration_sec)
        else:
            # iperf3 failure - log it
            logger.warning("iperf3 test failed or timed out")
            self.connection_tracker.track_iperf3_result(1, 0, 0, "iperf3 test failed")


