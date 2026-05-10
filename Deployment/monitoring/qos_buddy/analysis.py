"""
QoS Buddy - Network Data Acquisition Framework
Phase A: Real-World Data Collection with Automatic Anomaly Detection

Author: QoS Buddy Team
Version: 1.2
Date: 2026-03-17
"""

import json
import logging
from datetime import datetime
from collections import deque
import numpy as np
from typing import Dict, List, Tuple, Optional


# ==================== IPERF3 BANDWIDTH TESTING ====================
from qos_buddy.config import TunisianNetworkConfig
from qos_buddy.traffic import AdvancedTrafficAnalyzer

# Initialize logger
logger = logging.getLogger("QoSBuddy")


class BLERTrendAnalyzer:
    """Enhanced BLER collection with delta and trend analysis"""
    
    def __init__(self, config: Optional[TunisianNetworkConfig] = None):
        self.config = config or TunisianNetworkConfig()
        self.bler_history = deque(maxlen=20)  # Last 20 samples for trend
        self.prev_tcp_stats = None
    
    def get_bler_metrics(self, tcp_retransmit_rate: float = 0.0) -> Dict:
        """
        Returns BLER metrics including delta, trend, and severity
        Uses the provided TCP retransmit rate (already calculated in NetworkMetricsCollector)
        """
        try:
            # Use provided TCP retransmit rate as BLER proxy
            # (handles encoding issues on French Windows via netstat)
            if tcp_retransmit_rate < 0:  # -1.0 means failed to measure
                bler_current = 0.0
            else:
                bler_current = tcp_retransmit_rate
            
            bler_current = round(bler_current, 2)
            
            # Calculate delta from last measurement
            bler_delta = 0.0
            if self.prev_tcp_stats:
                prev_bler = self.prev_tcp_stats.get('bler', 0.0)
                bler_delta = round(bler_current - prev_bler, 2)
            
            self.prev_tcp_stats = {'bler': bler_current}
            
            # Track history for trend
            self.bler_history.append(bler_current)
            
            # Trend: increasing, decreasing, or stable
            if len(self.bler_history) >= 3:
                recent_avg = sum(list(self.bler_history)[-3:]) / 3
                older_avg = sum(list(self.bler_history)[:-3]) / (len(self.bler_history) - 3) if len(self.bler_history) > 3 else recent_avg
                
                if recent_avg > older_avg * 1.2:
                    bler_trend = 'increasing'
                elif recent_avg < older_avg * 0.8:
                    bler_trend = 'decreasing'
                else:
                    bler_trend = 'stable'
            else:
                bler_trend = 'stable'
            
            # Severity classification
            if bler_current < 0.5:
                bler_severity = 'none'
            elif bler_current < 2.0:
                bler_severity = 'low'
            elif bler_current < 5.0:
                bler_severity = 'medium'
            elif bler_current < 10.0:
                bler_severity = 'high'
            else:
                bler_severity = 'critical'
            
            return {
                'bler_proxy_pct': bler_current,
                'bler_delta': bler_delta,
                'bler_trend': bler_trend,
                'bler_severity': bler_severity
            }
        except Exception as e:
            logger.debug(f'BLERTrendAnalyzer error: {e}')
            return {'bler_proxy_pct': 0.0, 'bler_delta': 0.0, 'bler_trend': 'stable', 'bler_severity': 'none'}


class SignalQualityAnalyzer:
    """Categorizes signal strength and calculates signal quality metrics"""
    
    def __init__(self, config: Optional[TunisianNetworkConfig] = None):
        self.config = config or TunisianNetworkConfig()
    
    def categorize_wifi_signal(self, rssi_dbm: Optional[float] = None) -> Dict:
        """Categorize WiFi RSSI into quality tiers"""
        if rssi_dbm is None or rssi_dbm == 0:
            return {'wifi_signal_category': 'unavailable', 'wifi_signal_score': 0}
        
        rssi = rssi_dbm or -999
        
        if rssi > -40:
            category = 'excellent'
            score = 95
        elif rssi > -50:
            category = 'good'
            score = 80
        elif rssi > -60:
            category = 'fair'
            score = 60
        elif rssi > -70:
            category = 'poor'
            score = 40
        else:
            category = 'very_poor'
            score = 10
        
        return {'wifi_signal_category': category, 'wifi_signal_score': score}
    
    def categorize_cellular_signal(self, rsrp_dbm: Optional[float] = None, rsrq_db: Optional[float] = None) -> Dict:
        """Categorize cellular signal (RSRP + RSRQ) into quality tiers"""
        if rsrp_dbm is None or rsrp_dbm == 0:
            return {'cellular_signal_category': 'unavailable', 'cellular_signal_score': 0}
        
        rsrp = rsrp_dbm or -999
        
        # RSRP primary indicator
        if rsrp > -85:
            category = 'excellent'
            score = 95
        elif rsrp > -95:
            category = 'good'
            score = 80
        elif rsrp > -105:
            category = 'fair'
            score = 60
        elif rsrp > -115:
            category = 'poor'
            score = 40
        else:
            category = 'very_poor'
            score = 10
        
        # RSRQ refines if available
        if rsrq_db and rsrq_db > 0:
            rsrq = rsrq_db or 0
            if rsrq > 20:
                score = min(100, score + 10)
            elif rsrq < 5:
                score = max(0, score - 20)
        
        return {'cellular_signal_category': category, 'cellular_signal_score': score}
    
    def get_combined_signal_health(self, wifi_score: int, cellular_score: int) -> Dict:
        """Combine WiFi and cellular signal scores"""
        # Prefer whichever connection is available and has better score
        if cellular_score > 0:
            combined_score = max(wifi_score, cellular_score)
            dominant = 'cellular' if cellular_score > wifi_score else 'wifi'
        else:
            combined_score = wifi_score
            dominant = 'wifi'
        
        if combined_score > 85:
            health = 'excellent'
        elif combined_score > 70:
            health = 'good'
        elif combined_score > 50:
            health = 'fair'
        elif combined_score > 30:
            health = 'poor'
        else:
            health = 'critical'
        
        return {'signal_health_overall': health, 'signal_dominant_link': dominant, 'signal_health_score': combined_score}


class DataQualityTracker:
    """Tracks completeness and quality of collected data"""
    
    def __init__(self, config: Optional[TunisianNetworkConfig] = None):
        self.config = config or TunisianNetworkConfig()
        self.required_fields = [
            'timestamp', 'latency_ms', 'jitter_ms', 'packet_loss_pct', 'throughput_mbps',
            'rssi_dbm', 'signal_quality_pct'
        ]
        self.optional_router_fields = ['rsrp_dbm', 'rsrq_db', 'sinr_db', 'cqi', 'bler_proxy_pct']
    
    def assess_record_quality(self, record: Dict) -> Dict:
        """Assess how complete and valid the record is"""
        issues = []
        
        # Check required fields
        required_present = sum(1 for f in self.required_fields if f in record and record[f] is not None)
        required_pct = (required_present / len(self.required_fields)) * 100
        
        # Check router metrics
        router_metrics_present = 0
        for f in self.optional_router_fields:
            if f in record and record[f] is not None and record[f] not in [0, '0', -1, '-1.0', '']:
                router_metrics_present += 1
        router_pct = (router_metrics_present / len(self.optional_router_fields)) * 100 if self.optional_router_fields else 0
        
        # Overall completeness
        total_pct = (required_pct + router_pct * 0.5) / 1.5  # Weight required more heavily
        
        # Quality issues
        if record.get('latency_ms', 0) > 5000:
            issues.append('extreme_latency')
        if record.get('packet_loss_pct', 0) > 50:
            issues.append('high_packet_loss')
        if record.get('throughput_mbps', 0) < 0:
            issues.append('negative_throughput')
        if record.get('cpu_pct', 0) > 95:
            issues.append('high_cpu_usage')
        
        # Flag for training
        skip_for_training = total_pct < 70 or len(issues) > 2
        
        return {
            'data_completeness_pct': round(total_pct, 1),
            'required_metrics_pct': round(required_pct, 1),
            'router_metrics_pct': round(router_pct, 1),
            'data_quality_issues': ','.join(issues) if issues else 'none',
            'skip_for_training': skip_for_training,
            'data_quality_rating': 'excellent' if total_pct > 90 else 'good' if total_pct > 80 else 'fair' if total_pct > 70 else 'poor'
        }


class TemporalFeatureGenerator:
    """Generates temporal/lag features for ML training"""
    
    def __init__(self, config: Optional[TunisianNetworkConfig] = None, window_size: int = 30):
        self.config = config or TunisianNetworkConfig()
        self.window_size = window_size
        self.history = deque(maxlen=window_size)
    
    def add_sample(self, record: Dict):
        """Add sample to rolling window"""
        self.history.append(record)
    
    def calculate_temporal_features(self) -> Dict:
        """Calculate rolling statistics from history"""
        if len(self.history) < 2:
            return {}
        
        records = list(self.history)
        features = {}
        
        # Latency statistics
        latencies = [r.get('latency_ms', 0) for r in records]
        if latencies:
            features['latency_rolling_mean'] = round(sum(latencies) / len(latencies), 2)
            features['latency_rolling_std'] = round(self._std_dev(latencies), 2)
            features['latency_trend'] = round(latencies[-1] - latencies[0], 2)
            features['latency_volatility'] = round(max(latencies) - min(latencies), 2)
        
        # Jitter statistics
        jitters = [r.get('jitter_ms', 0) for r in records]
        if jitters:
            features['jitter_rolling_mean'] = round(sum(jitters) / len(jitters), 2)
            features['jitter_rolling_std'] = round(self._std_dev(jitters), 2)
            features['jitter_increasing'] = 1 if jitters[-1] > jitters[0] else 0
        
        # Throughput statistics
        throughputs = [r.get('throughput_mbps', 0) for r in records if r.get('throughput_mbps', 0) > 0]
        if throughputs:
            features['throughput_rolling_mean'] = round(sum(throughputs) / len(throughputs), 2)
            features['throughput_rolling_std'] = round(self._std_dev(throughputs), 2)
            features['throughput_volatility'] = round(max(throughputs) - min(throughputs), 2)
        
        # Anomaly frequency in window
        anomalies = sum(1 for r in records if r.get('anomaly_flag'))
        features['anomaly_rate_recent'] = round((anomalies / len(records)) * 100, 1)
        
        # Signal degradation (filter out None values which occur during offline/no WiFi)
        signals = [r.get('rssi_dbm') for r in records if r.get('rssi_dbm') is not None]
        if len(signals) >= 2:
            features['signal_degradation_rate'] = round((signals[-1] - signals[0]) / len(signals), 2)
        else:
            features['signal_degradation_rate'] = 0.0
        
        return features
    
    def _std_dev(self, values: list) -> float:
        """Calculate standard deviation"""
        if not values:
            return 0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5


class HandoverAnalyzer:
    """Track handover success rates based on network transitions"""
    
    def __init__(self, config: Optional[TunisianNetworkConfig] = None):
        self.config = config or TunisianNetworkConfig()
        self.history = deque(maxlen=50)  # Track last 50 samples
        self.prev_record = None
        self.ho_in_progress = False
        self.ho_success_count = 0
        self.ho_total_count = 0
    
    def analyze_handover(self, curr_record: Dict) -> Tuple[bool, str, float]:
        """
        Detect handover and classify as success/failure/in_progress
        
        Returns: (ho_occurred, ho_status, ho_success_rate_pct)
        
        ho_status: 'none' | 'detected' | 'success' | 'failure'
        """
        if self.prev_record is None:
            self.prev_record = curr_record
            return False, 'none', 0.0
        
        # Detect handover: network type change or BSSID change
        network_changed = (
            (self.prev_record.get('network_type_router', '') != 
             curr_record.get('network_type_router', '')) or
            self.prev_record.get('handover_event') == True
        )
        
        if network_changed:
            self.ho_in_progress = True
            self.ho_total_count += 1
            
            # Determine success: throughput maintained >1 Mbps
            prev_throughput = self.prev_record.get('throughput_mbps', 0)
            curr_throughput = curr_record.get('throughput_mbps', 0)
            
            # Success = no significant throughput degradation after change
            throughput_degraded = (prev_throughput > 5.0 and curr_throughput < 1.0)
            
            if not throughput_degraded:
                self.ho_success_count += 1
                ho_status = 'success'
            else:
                ho_status = 'failure'
            
            self.ho_in_progress = False
        else:
            ho_status = 'none'
        
        # Calculate success rate from history
        if self.ho_total_count > 0:
            ho_success_rate = round((self.ho_success_count / self.ho_total_count) * 100, 2)
        else:
            ho_success_rate = 0.0
        
        self.prev_record = curr_record.copy()
        return network_changed, ho_status, ho_success_rate


class ConnectionSuccessTracker:
    """Track connection success rate (CSSR proxy) from iperf3 tests - SEGMENT SPECIFIC"""
    
    def __init__(self, config: Optional[TunisianNetworkConfig] = None):
        self.config = config or TunisianNetworkConfig()
        # Segment-specific counters (reset at start of each 30-second segment)
        self.segment_success_count = 0
        self.segment_total_count = 0
        # Legacy counters for backward compatibility
        self.iperf_successes = 0
        self.iperf_attempts = 0
    
    def reset_segment(self):
        """Reset counters for a new 30-second segment"""
        self.segment_success_count = 0
        self.segment_total_count = 0
        logger.debug("[CSSR] Segment tracker reset for new segment")
    
    def track_iperf3_result(self, returncode: int, transferred_bytes: int, 
                          duration_sec: float, error_msg: str = '') -> bool:
        """
        Track iperf3 connection success for CURRENT SEGMENT ONLY
        
        Returns: True if connection succeeded, False if failed
        """
        # Success criteria:
        # 1. iperf3 returned 0 (no error)
        # 2. Actually transferred >50KB (not just connection handshake)
        min_bytes = 50000  # 50 KB minimum
        
        success = (returncode == 0 and transferred_bytes > min_bytes and 
                  duration_sec > 0.5)  # At least 0.5 sec transfer
        
        if not success and error_msg:
            logger.debug(f'iperf3 failure: {error_msg[:50]}')
        
        # Track in segment
        self.segment_total_count += 1
        if success:
            self.segment_success_count += 1
        
        # Legacy counters
        self.iperf_attempts += 1
        if success:
            self.iperf_successes += 1
        
        return success
    
    def get_cssr_proxy_pct(self) -> float:
        """
        Return connection success rate % (0-100) for CURRENT 30-SECOND SEGMENT ONLY
        
        CSSR proxy = (successful connections / total attempts in segment) * 100
        
        TRUE EXTRACTION: Only counts tests that completed during current segment.
        No rolling windows - each segment gets independent CSSR calculation.
        
        Example:
        - Segment with 0 tests: 0.0%
        - Segment with 1 success, 0 failures: 100.0%
        - Segment with 2 successes, 1 failure: 66.7%
        - Segment with 1 success, 2 failures: 33.3%
        """
        if self.segment_total_count == 0:
            return 0.0
        
        cssr = (self.segment_success_count / self.segment_total_count) * 100
        
        display = f"{self.segment_success_count}/{self.segment_total_count} tests passed"
        logger.debug(f"[CSSR DEBUG] {display} = {cssr:.1f}%")
        
        return round(cssr, 2)
    
    def _check_recent_success(self) -> bool:
        """Check if iperf3 succeeded in current segment"""
        # True if at least one test succeeded in this segment
        return self.segment_success_count > 0


class AnomalyDetector:
    """Detects and classifies network anomalies"""
    
    def __init__(self, config: TunisianNetworkConfig = None): # type: ignore
        self.config = config or TunisianNetworkConfig()
        self.baseline_stats = None
        self.history = deque(maxlen=500)
        self.link_failure_tracker = {}
    
    def update_baseline(self, metrics: List[Dict]):
        """Calculate baseline statistics from initial measurements"""
        if len(metrics) < 10:
            logger.warning("Not enough samples for baseline calculation (need at least 10)")
            return
        
        latencies = [m['latency_ms'] for m in metrics if m['latency_ms'] > 0]
        jitters = [m['jitter_ms'] for m in metrics if m['jitter_ms'] > 0]
        throughputs = [m['throughput_mbps'] for m in metrics if m['throughput_mbps'] > 0]
        
        self.baseline_stats = {
            'latency_mean': np.mean(latencies),
            'latency_std': np.std(latencies),
            'jitter_mean': np.mean(jitters),
            'jitter_std': np.std(jitters),
            'throughput_mean': np.mean(throughputs),
            'throughput_std': np.std(throughputs)
        }
        
        logger.info(f"Baseline established: {json.dumps(self.baseline_stats, indent=2)}")
    
    def detect_anomaly(self, record: Dict) -> Tuple[bool, str, float]:
        """
        Detect anomalies in network metrics
        Returns: (is_anomaly, anomaly_type, anomaly_score)
        """
        anomaly_type = 'normal'
        anomaly_score = 0.0
        
        # Rule 1: Link Failure Detection
        if record['packet_loss_pct'] == 100.0:
            node_id = record.get('node_id', 'default')
            if node_id not in self.link_failure_tracker:
                self.link_failure_tracker[node_id] = datetime.now()
            elif (datetime.now() - self.link_failure_tracker[node_id]).seconds > self.config.LINK_FAILURE_DURATION_SEC:
                anomaly_type = 'link_failure'
                anomaly_score = 1.0
        else:
            self.link_failure_tracker.pop(record.get('node_id', 'default'), None)
        
        # Rule 2: Packet Loss Anomaly
        if anomaly_type == 'normal' and record['packet_loss_pct'] > self.config.PACKET_LOSS_CRITICAL_PCT:
            anomaly_type = 'severe_packet_loss'
            anomaly_score = min(1.0, record['packet_loss_pct'] / 100.0)
        
        elif anomaly_type == 'normal' and record['packet_loss_pct'] > self.config.PACKET_LOSS_WARNING_PCT:
            anomaly_type = 'packet_loss'
            anomaly_score = record['packet_loss_pct'] / self.config.PACKET_LOSS_CRITICAL_PCT
        
        # Rule 3: Congestion Detection
        if anomaly_type == 'normal':
            latency_spike = (record['latency_ms'] - self.config.LATENCY_BASELINE_MS) > self.config.CONGESTION_LATENCY_SPIKE_MS
            throughput_high = (record['throughput_mbps'] > self.config.THROUGHPUT_MAX_MBPS * 
                             self.config.CONGESTION_THROUGHPUT_SPIKE_PCT / 100)
            
            if latency_spike and throughput_high:
                anomaly_type = 'congestion'
                anomaly_score = min(1.0, (record['latency_ms'] / self.config.LATENCY_CRITICAL_MS + 
                                         record['throughput_mbps'] / self.config.THROUGHPUT_MAX_MBPS) / 2)
        
        # Rule 4: High Latency (WARNING level first, then CRITICAL)
        if anomaly_type == 'normal' and record['latency_ms'] > self.config.LATENCY_WARNING_MS:
            if record['latency_ms'] > self.config.LATENCY_CRITICAL_MS:
                anomaly_type = 'high_latency'
                anomaly_score = min(1.0, record['latency_ms'] / (self.config.LATENCY_CRITICAL_MS * 2))
            else:
                # WARNING level: degraded but not critical
                anomaly_type = 'latency_degradation'
                anomaly_score = (record['latency_ms'] - self.config.LATENCY_WARNING_MS) / (self.config.LATENCY_CRITICAL_MS - self.config.LATENCY_WARNING_MS) * 0.6
        
        # Rule 5: High Jitter (WARNING level first, then CRITICAL)
        if anomaly_type == 'normal' and record['jitter_ms'] > self.config.JITTER_WARNING_MS:
            if record['jitter_ms'] > self.config.JITTER_CRITICAL_MS:
                anomaly_type = 'high_jitter'
                anomaly_score = min(1.0, record['jitter_ms'] / (self.config.JITTER_CRITICAL_MS * 2))
            else:
                # WARNING level: degraded but not critical
                anomaly_type = 'jitter_degradation'
                anomaly_score = (record['jitter_ms'] - self.config.JITTER_WARNING_MS) / (self.config.JITTER_CRITICAL_MS - self.config.JITTER_WARNING_MS) * 0.6
        
        # Rule 6: Resource Constraint
        if anomaly_type == 'normal' and record['cpu_pct'] > self.config.CPU_CRITICAL_PCT:
            if record['latency_ms'] > self.config.LATENCY_BASELINE_MS:
                anomaly_type = 'local_resource_constraint'
                anomaly_score = min(1.0, (record['cpu_pct'] + record['memory_pct']) / 200)
        
        # Rule 7: Low Throughput
        # Only flag if throughput > 0 (active transfer) but too low
        # 0 throughput = idle network (not a problem)
        if (anomaly_type == 'normal' and record['throughput_mbps'] > 0 and 
            record['throughput_mbps'] < self.config.THROUGHPUT_CRITICAL_MBPS):
            anomaly_type = 'low_throughput'
            anomaly_score = 1.0 - (record['throughput_mbps'] / self.config.THROUGHPUT_CRITICAL_MBPS)
        
        # Statistical Deviation (if baseline available)
        if anomaly_type == 'normal' and self.baseline_stats:
            if record['latency_ms'] > (self.baseline_stats['latency_mean'] +
                                      3 * self.baseline_stats['latency_std']):
                anomaly_type = 'statistical_outlier'
                z_score = (record['latency_ms'] - self.baseline_stats['latency_mean']) / max(1, self.baseline_stats['latency_std'])
                anomaly_score = min(1.0, z_score / 5)

        # ---- Radio Layer Anomaly Rules ----

        # Rule 8: Weak WiFi signal (coverage hole equivalent)
        if anomaly_type == 'normal':
            rssi = record.get('rssi_dbm')
            if rssi is not None and rssi < self.config.RSSI_CRITICAL_DBM:
                anomaly_type = 'weak_signal'
                anomaly_score = min(1.0, (self.config.RSSI_CRITICAL_DBM - rssi) / 20.0)

        # Rule 9: Handover event (WiFi roaming / cell change detected)
        if anomaly_type == 'normal' and record.get('handover_event', False):
            anomaly_type = 'handover_event'
            anomaly_score = 0.5  # Informational — may or may not degrade QoS

        # Rule 10: High channel utilization (PRB congestion proxy — issue #7)
        if anomaly_type == 'normal':
            ch_util = record.get('channel_util_pct')
            if ch_util is not None and ch_util > self.config.CHANNEL_UTIL_CRITICAL_PCT:
                anomaly_type = 'channel_congestion'
                anomaly_score = min(
                    1.0,
                    (ch_util - self.config.CHANNEL_UTIL_WARNING_PCT) /
                    max(1, 100 - self.config.CHANNEL_UTIL_WARNING_PCT)
                )

        # Rule 11: High TCP retransmission rate (BLER proxy — issues #2, #4)
        if anomaly_type == 'normal':
            retrans = record.get('tcp_retransmit_rate', -1.0)
            if retrans >= self.config.TCP_RETRANS_CRITICAL_PCT:
                anomaly_type = 'high_retransmission'
                anomaly_score = min(1.0, retrans / 20.0)

        # Rule 12: Poor voice quality / low MOS (issue #2)
        if anomaly_type == 'normal':
            mos = record.get('mos_estimate')
            if mos is not None and mos < self.config.MOS_POOR:
                anomaly_type = 'poor_voice_quality'
                anomaly_score = min(
                    1.0,
                    (self.config.MOS_ACCEPTABLE - mos) / max(0.1, self.config.MOS_ACCEPTABLE - 1.0)
                )

        # Rule 13: Weak LTE RSRP (from router API or ADB — issues #1, #2, #5)
        if anomaly_type == 'normal':
            rsrp = record.get('rsrp_dbm')
            if rsrp is not None and rsrp < self.config.RSRP_WARNING_DBM:
                anomaly_type = 'weak_rsrp'
                anomaly_score = min(
                    1.0,
                    (self.config.RSRP_WARNING_DBM - rsrp) /
                    max(1, self.config.RSRP_WARNING_DBM - self.config.RSRP_CRITICAL_DBM)
                )

        # Rule 14: Low LTE SINR (interference-dominated link — issues #1, #3)
        if anomaly_type == 'normal':
            sinr = record.get('sinr_db')
            if sinr is not None and sinr < self.config.SINR_WARNING_DB:
                anomaly_type = 'low_sinr'
                anomaly_score = min(1.0, abs(sinr - self.config.SINR_WARNING_DB) / 20.0)

        return (anomaly_type != 'normal', anomaly_type, anomaly_score)


class FeatureEngineer:
    """Generates derived features and traffic analysis"""
    
    def __init__(self, config: TunisianNetworkConfig = None): # type: ignore
        self.config = config or TunisianNetworkConfig()
        self.traffic_analyzer = AdvancedTrafficAnalyzer(config)
    
    def engineer_features(self, record: Dict) -> Dict:
        """Calculate derived metrics and features with intelligent traffic detection"""
        
        # Queue Length Modeling
        queue_length = (self.config.QUEUE_ALPHA * record['throughput_mbps'] +
                       self.config.QUEUE_BETA * record['latency_ms'] +
                       self.config.QUEUE_GAMMA * record['packet_loss_pct'])
        
        # Bandwidth Utilization
        bandwidth_util = (record['throughput_mbps'] / self.config.THROUGHPUT_MAX_MBPS) * 100
        
        # Advanced Traffic Type Analysis (using multiple signals)
        traffic_type, confidence, detection_method = self.traffic_analyzer.analyze_traffic(record)
        
        # Peak Hour Detection (Tunisian context)
        hour = datetime.now().hour
        is_peak_hour = (
            (self.config.PEAK_HOURS_START <= hour <= self.config.PEAK_HOURS_END) or
            (self.config.SECONDARY_PEAK_START <= hour <= self.config.SECONDARY_PEAK_END)
        )
        
        return {
            'queue_length': float(queue_length),
            'bandwidth_util_pct': float(min(100, bandwidth_util)),
            'traffic_type': traffic_type,
            'traffic_confidence': round(confidence, 2),
            'detection_method': detection_method,
            'is_peak_hour': is_peak_hour,
            'active_connections': self.traffic_analyzer._last_established_count
        }


