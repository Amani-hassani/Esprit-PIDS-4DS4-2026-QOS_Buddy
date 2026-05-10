"""
QoS Buddy - Network Data Acquisition Framework
Phase A: Real-World Data Collection with Automatic Anomaly Detection

Author: QoS Buddy Team
Version: 1.2
Date: 2026-03-17
"""

import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List


# ==================== IPERF3 BANDWIDTH TESTING ====================
from qos_buddy.config import TunisianNetworkConfig

# Initialize logger
logger = logging.getLogger("QoSBuddy")

# JSONL bus path consumed by the QOS-Buddy monitoring-bridge container.
# The bridge mounts `monitoring/` as /data:ro and tails this file. Override
# with QOS_NETWORK_STREAM_PATH if you need to redirect the bus elsewhere.
_DEFAULT_JSONL_BUS_PATH = Path(__file__).resolve().parents[1] / "network_stream.jsonl"


class DataPersistence:
    """Handles CSV storage and data management"""
    
    # Define canonical field order for time-series CSV
    TIMESERIES_FIELDS = [
        # --- Identification ---
        'timestamp', 'zone_id', 'cell_id', 'node_id', 'device_type',
        # --- QoS Layer (transport / application) ---
        'latency_ms', 'jitter_ms', 'packet_loss_pct', 'throughput_mbps',
        'bandwidth_util_pct', 'cpu_pct', 'memory_pct', 'active_connections',
        'queue_length', 'traffic_type', 'traffic_confidence', 'detection_method',
        'is_peak_hour', 'day_of_week', 'hour_of_day',
        # --- Radio Layer: WiFi (always collected via netsh wlan) ---
        'rssi_dbm',            # WiFi RSSI in dBm (analogous to LTE RSRP)
        'signal_quality_pct',  # Windows signal quality % (0-100)
        'channel',             # WiFi channel number
        'band_ghz',            # WiFi band ('2.4GHz' / '5GHz')
        'handover_event',      # True = BSSID changed since last sample
        'handover_count',      # Cumulative handovers this session
        'neighbor_count',      # Visible APs (neighbor list size)
        'channel_util_pct',    # BSS Load channel utilization % (PRB proxy)
        'connected_stations',  # Devices on same AP (capacity indicator)
        'tcp_retransmit_rate', # TCP retransmit rate % since last sample (BLER proxy)
        'mos_estimate',        # ITU-T G.107 E-model MOS (1.0-5.0)
        # --- Signal Quality Categories (NEW) ---
        'wifi_signal_category',     # excellent | good | fair | poor | very_poor
        'wifi_signal_score',        # 10-95 (quality score)
        'cellular_signal_category', # excellent | good | fair | poor | very_poor | unavailable
        'cellular_signal_score',    # 0-100 (quality score)
        'signal_health_overall',    # excellent | good | fair | poor | critical
        'signal_dominant_link',     # wifi | cellular
        'signal_health_score',      # 0-100 (combined score)
        # --- Radio Layer: Cellular (from 4G/5G router API — Huawei/ZTE) ---
        'rsrp_dbm',            # LTE RSRP from router API (dBm)
        'rsrq_db',             # LTE RSRQ from router API (dB)
        'sinr_db',             # LTE SINR from router API (dB)
        'cqi',                 # Channel Quality Indicator (0-15)
        'pci',                 # Physical Cell ID
        'cell_id_router',      # Cell ID from router API
        'network_type_router', # LTE / LTE_CA / 5G from router
        'earfcn',              # E-UTRA Absolute Radio Frequency Channel Number
        'enodeb_id',           # Base Station ID (EnodeB)
        'mcs',                 # Modulation and Coding Scheme
        # --- Enhanced Radio Metrics (NEW) ---
        'bler_proxy_pct',      # Bit Error Rate proxy from TCP retransmits (0-100%)
        'bler_delta',          # Change in BLER from last sample (NEW)
        'bler_trend',          # increasing | decreasing | stable (NEW)
        'bler_severity',       # none | low | medium | high | critical (NEW)
        'ho_status',           # Handover status: 'none' | 'success' | 'failure'
        'ho_success_rate_pct', # Handover success rate % (rolling 50-sample window)
        'cssr_proxy_pct',      # Connection Success Rate proxy from iperf3 (0-100%)
        # --- Temporal Features (NEW) ---
        'latency_rolling_mean',    # 30-sample rolling average (NEW)
        'latency_rolling_std',     # 30-sample standard deviation (NEW)
        'latency_trend',           # Change from oldest to newest in window (NEW)
        'latency_volatility',      # Max-min variance in window (NEW)
        'jitter_rolling_mean',     # Rolling average (NEW)
        'jitter_rolling_std',      # Rolling std dev (NEW)
        'jitter_increasing',       # 1 if increasing, 0 if decreasing (NEW)
        'throughput_rolling_mean', # Rolling average for throughput >0 (NEW)
        'throughput_rolling_std',  # Rolling std dev (NEW)
        'throughput_volatility',   # Max-min range (NEW)
        'anomaly_rate_recent',     # % of recent samples with anomalies (NEW)
        'signal_degradation_rate', # dBm change per sample (NEW)
        # --- Data Quality Metadata (NEW) ---
        'data_completeness_pct',   # % of expected fields present (NEW)
        'required_metrics_pct',    # % of required fields present (NEW)
        'router_metrics_pct',      # % of router fields present (NEW)
        'data_quality_issues',     # Comma-separated list of issues (NEW)
        'skip_for_training',       # Boolean: true if data quality < 70% (NEW)
        'data_quality_rating',     # excellent | good | fair | poor (NEW)
        # --- Baseline & Context (NEW) ---
        'baseline_phase',          # Boolean: true if in baseline collection phase (NEW)
        'hour_anomaly_rate',       # % of anomalies in this hour historically (NEW)
        'incident_recovery_time',  # Seconds since last incident of this type recovered (NEW)
        'collection_completion_pct',  # % of samples successfully collected this session (NEW)
        # --- Collection context ---
        'teams_in_meeting',    # Boolean: Teams.exe active with audio (NEW)
        # --- Collection metadata ---
        'data_source',         # 'wifi' | 'wifi+router'
        # --- Anomaly ---
        'anomaly_flag', 'anomaly_type', 'anomaly_score'
    ]
    
    INCIDENT_FIELDS = [
        'incident_id', 'start_timestamp', 'end_timestamp', 'node_id',
        'incident_type', 'severity', 'time_to_detect_sec', 'duration_sec', 'samples', 'max_score'
    ]
    
    def __init__(self, output_dir: str = "data", config: TunisianNetworkConfig = None, choice: int = None): # type: ignore
        # Create choice-specific subfolder if provided
        if choice is not None:
            self.output_dir = f"{output_dir}/choice_{choice}"
        else:
            self.output_dir = output_dir
        
        self.choice = choice  # Store choice for use in date rollover
        self.config = config or TunisianNetworkConfig()
        Path(self.output_dir).mkdir(exist_ok=True, parents=True)
        
        # Include choice in CSV filename if provided
        date_str = datetime.now().strftime('%Y%m%d')
        if choice is not None:
            self.timeseries_file = f"{self.output_dir}/qos_timeseries_choice_{choice}_{date_str}.csv"
            self.incident_file = f"{self.output_dir}/incidents_choice_{choice}_{date_str}.csv"
        else:
            self.timeseries_file = f"{self.output_dir}/qos_timeseries_{date_str}.csv"
            self.incident_file = f"{self.output_dir}/incidents_{date_str}.csv"
        
        self._init_csv_files()

        # JSONL bus — every saved record is also appended here so the
        # qos-buddy monitoring-bridge can stream live samples to Redis.
        bus_path_override = os.getenv("QOS_NETWORK_STREAM_PATH")
        self.jsonl_bus_path = Path(bus_path_override) if bus_path_override else _DEFAULT_JSONL_BUS_PATH
        try:
            self.jsonl_bus_path.parent.mkdir(parents=True, exist_ok=True)
            self.jsonl_bus_path.touch(exist_ok=True)
        except OSError as e:
            logger.warning(f"Could not initialize JSONL bus at {self.jsonl_bus_path}: {e}")

    def _check_date_rollover(self):
        """Check if the date has changed and rotate filenames if needed"""
        current_date = datetime.now().strftime('%Y%m%d')
        if self.choice is not None:
            expected_ts = f"{self.output_dir}/qos_timeseries_choice_{self.choice}_{current_date}.csv"
            expected_inc = f"{self.output_dir}/incidents_choice_{self.choice}_{current_date}.csv"
        else:
            expected_ts = f"{self.output_dir}/qos_timeseries_{current_date}.csv"
            expected_inc = f"{self.output_dir}/incidents_{current_date}.csv"
        
        if self.timeseries_file != expected_ts:
            self.timeseries_file = expected_ts
            self.incident_file = expected_inc
            self._init_csv_files()
            logger.info(f"Date rollover: new files {self.timeseries_file}, {self.incident_file}")
    
    def _init_csv_files(self):
        """Initialize CSV files with headers"""
        
        # Time-series file - use canonical field order
        timeseries_header = self.TIMESERIES_FIELDS
        
        if not Path(self.timeseries_file).exists():
            with open(self.timeseries_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=timeseries_header)
                writer.writeheader()
        
        # Incident file - use canonical field order
        incident_header = self.INCIDENT_FIELDS
        
        if not Path(self.incident_file).exists():
            with open(self.incident_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=incident_header)
                writer.writeheader()
    
    def _sanitize_record(self, record: Dict) -> Dict:
        """Sanitize and validate record data types to ensure consistency"""
        sanitized = {}
        
        for field in self.TIMESERIES_FIELDS:
            value = record.get(field)
            
            # Handle missing fields with sensible defaults
            if value is None:
                if field in ('anomaly_type',):
                    value = 'normal'
                elif field in ('anomaly_flag', 'is_peak_hour', 'handover_event'):
                    value = False
                elif field in ('traffic_type', 'detection_method', 'ho_status'):
                    value = 'unknown'
                elif field in ('bssid', 'band_ghz', 'cell_id_router', 'network_type_router',
                               'data_source'):
                    value = ''  # Optional string: no data collected
                elif field in ('rssi_dbm', 'signal_quality_pct', 'channel', 'rx_link_mbps',
                               'handover_count', 'neighbor_count', 'channel_util_pct',
                               'connected_stations', 'tcp_retransmit_rate', 'mos_estimate',
                               'rsrp_dbm', 'rsrq_db', 'sinr_db', 'pci', 'cqi', 'mcs', 'enodeb_id'):
                    value = ''  # Optional numeric: empty cell = no measurement collected
                elif field in ('bler_proxy_pct', 'ho_success_rate_pct', 'cssr_proxy_pct'):
                    value = 0.0  # New metrics: always numeric, default to 0
                else:
                    value = 0  # Core QoS numeric fields (latency, throughput, etc.)
            
            # Type coercion for specific fields
            if field == 'active_connections':
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    value = 0
            elif field == 'is_peak_hour':
                # Ensure boolean output as True/False
                if isinstance(value, bool):
                    pass
                elif isinstance(value, str):
                    value = value.lower() in ('true', '1', 'yes')
                else:
                    value = bool(value)
            elif field == 'anomaly_flag':
                if isinstance(value, bool):
                    pass
                elif isinstance(value, str):
                    value = value.lower() in ('true', '1', 'yes')
                else:
                    value = bool(value)
            elif field == 'handover_event':
                if isinstance(value, bool):
                    pass
                elif isinstance(value, str):
                    value = value.lower() in ('true', '1', 'yes')
                else:
                    value = bool(value)
            elif field == 'hour_of_day':
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    value = 0
            elif field in ('latency_ms', 'jitter_ms', 'packet_loss_pct', 'throughput_mbps',
                          'bandwidth_util_pct', 'cpu_pct', 'memory_pct', 'queue_length',
                          'traffic_confidence', 'anomaly_score'):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    value = 0.0
            elif field in ('traffic_type', 'detection_method', 'day_of_week', 'anomaly_type', 'ho_status'):
                value = str(value) if value else 'unknown'
            elif field in ('bssid', 'band_ghz', 'cell_id_router', 'network_type_router',
                           'data_source'):
                value = str(value) if value not in (None, '', 0) else ''
            elif field in ('rssi_dbm', 'signal_quality_pct', 'channel', 'handover_count',
                           'neighbor_count', 'channel_util_pct', 'connected_stations',
                           'rsrp_dbm', 'rsrq_db', 'pci', 'cqi',
                           'earfcn', 'mcs'):
                if value != '':
                    try:
                        value = int(float(value))
                    except (ValueError, TypeError):
                        value = ''
            elif field in ('tcp_retransmit_rate', 'mos_estimate', 'sinr_db', 'bler_proxy_pct',
                           'ho_success_rate_pct', 'cssr_proxy_pct'):
                if value != '':
                    try:
                        value = round(float(value), 3)
                    except (ValueError, TypeError):
                        value = ''
            
            sanitized[field] = value
        
        return sanitized
    
    def save_record(self, record: Dict):
        """Save a single record to CSV with proper field order and data validation"""
        try:
            self._check_date_rollover()
            # Sanitize record to ensure consistent data types
            sanitized_record = self._sanitize_record(record)

            with open(self.timeseries_file, 'a', newline='') as f:
                # Use canonical field order to prevent column misalignment
                writer = csv.DictWriter(f, fieldnames=self.TIMESERIES_FIELDS)
                writer.writerow(sanitized_record)
        except Exception as e:
            logger.error(f"Error saving record: {str(e)}")
        # Mirror to the JSONL live bus consumed by the monitoring-bridge.
        # Best-effort: a failed JSONL write must never block CSV persistence.
        try:
            self._publish_jsonl(record)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"JSONL bus publish failed: {e}")

    def _publish_jsonl(self, record: Dict) -> None:
        """Append one normalized sample to the live JSONL bus."""
        envelope = dict(record)
        envelope.setdefault("timestamp", datetime.utcnow().isoformat())
        envelope["published_at"] = datetime.utcnow().isoformat()
        with self.jsonl_bus_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(envelope, ensure_ascii=False, default=str) + "\n")
            f.flush()
    
    def save_incident(self, incident: Dict):
        """Save an incident to CSV with proper field order"""
        try:
            self._check_date_rollover()
            with open(self.incident_file, 'a', newline='') as f:
                # Use canonical field order
                writer = csv.DictWriter(f, fieldnames=self.INCIDENT_FIELDS, extrasaction='ignore')
                writer.writerow(incident)
        except Exception as e:
            logger.error(f"Error saving incident: {str(e)}")
    
    def get_latest_records(self, count: int = 10) -> List[Dict]:
        """Retrieve the latest N records from CSV"""
        try:
            records = []
            with open(self.timeseries_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(row)
            return records[-count:]
        except Exception as e:
            logger.error(f"Error reading records: {str(e)}")
            return []


