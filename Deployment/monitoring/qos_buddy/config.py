"""
QoS Buddy - Network Data Acquisition Framework
Phase A: Real-World Data Collection with Automatic Anomaly Detection

Author: QoS Buddy Team
Version: 1.2
Date: 2026-03-17
"""

import logging
from datetime import datetime
from pathlib import Path


# ==================== IPERF3 BANDWIDTH TESTING ====================

class TunisianNetworkConfig:
    """Network baseline parameters for Tunisian providers"""
    
    LATENCY_BASELINE_MS = 50
    LATENCY_ACCEPTABLE_MS = 100
    LATENCY_WARNING_MS = 150
    LATENCY_CRITICAL_MS = 250
    LATENCY_UNACCEPTABLE_MS = 400
    
    JITTER_EXCELLENT_MS = 10
    JITTER_GOOD_MS = 30
    JITTER_ACCEPTABLE_MS = 50
    JITTER_WARNING_MS = 75
    JITTER_CRITICAL_MS = 150
    JITTER_UNACCEPTABLE_MS = 200
    
    PACKET_LOSS_EXCELLENT_PCT = 0.0
    PACKET_LOSS_GOOD_PCT = 1.0
    PACKET_LOSS_ACCEPTABLE_PCT = 2.0
    PACKET_LOSS_WARNING_PCT = 5.0
    PACKET_LOSS_CRITICAL_PCT = 10.0
    PACKET_LOSS_UNACCEPTABLE_PCT = 15.0
    
    THROUGHPUT_EXCELLENT_MBPS = 15.0
    THROUGHPUT_GOOD_MBPS = 8.0
    THROUGHPUT_ACCEPTABLE_MBPS = 4.0
    THROUGHPUT_BASELINE_MBPS = 3.0
    THROUGHPUT_WARNING_MBPS = 1.0
    THROUGHPUT_CRITICAL_MBPS = 0.5
    
    BANDWIDTH_UTIL_EXCELLENT_PCT = 20.0
    BANDWIDTH_UTIL_GOOD_PCT = 50.0
    BANDWIDTH_UTIL_WARNING_PCT = 80.0
    BANDWIDTH_UTIL_CRITICAL_PCT = 95.0
    
    QOS_EXCELLENT_SCORE = 4.2
    QOS_GOOD_SCORE = 4.0
    QOS_ACCEPTABLE_SCORE = 3.5
    QOS_POOR_SCORE = 3.0
    QOS_VERY_POOR_SCORE = 2.0
    
    PEAK_HOURS_START = 18
    PEAK_HOURS_END = 23
    SECONDARY_PEAK_START = 12
    SECONDARY_PEAK_END = 14
    
    ISP_BASELINES = {
        'OTC': {'latency_baseline': 45, 'throughput_typical': 6.0},
        'Orange': {'latency_baseline': 65, 'throughput_typical': 8.0},
        'Ooredoo': {'latency_baseline': 65, 'throughput_typical': 8.0},
        'Default': {'latency_baseline': 50, 'throughput_typical': 5.0}
    }
    
    CPU_WARNING_PCT = 75.0
    CPU_CRITICAL_PCT = 90.0
    MEMORY_WARNING_PCT = 80.0
    MEMORY_CRITICAL_PCT = 95.0
    
    CONGESTION_LATENCY_SPIKE_MS = 120
    CONGESTION_THROUGHPUT_SPIKE_PCT = 60
    LINK_FAILURE_PACKET_LOSS_PCT = 100.0
    LINK_FAILURE_DURATION_SEC = 5
    
    QUEUE_ALPHA = 0.3
    QUEUE_BETA = 0.5
    QUEUE_GAMMA = 0.2
    
    ACTIVE_ISP = 'OTC'
    THROUGHPUT_MAX_MBPS = 15.0
    
    # Remote iperf3 server for real network testing
    # Primary server + fallback pool (rotates if busy)
    # Each server has its own iperf3 instance per port, so multiple ports = more availability
    # Prioritized by proximity to Tunisia and capacity
    IPERF3_REMOTE_SERVER = 'iperf3.moji.fr'
    IPERF3_REMOTE_PORT = 5200
    IPERF3_SERVER_POOL = [
        # Paris — Moji 100Gbps (ports 5200-5240, tested 18 Mbps from Tunisia)
        ('iperf3.moji.fr', 5200),
        ('iperf3.moji.fr', 5201),
        ('iperf3.moji.fr', 5202),
        ('iperf3.moji.fr', 5203),
        # Paris — Scaleway 100Gbps (ports 5200-5209, tested 3 Mbps from Tunisia)
        ('ping.online.net', 5200),
        ('ping.online.net', 5201),
        ('ping.online.net', 5202),
        ('ping.online.net', 5203),
        # Paris — MilkyWan 40Gbps (ports 9200-9240)
        ('speedtest.milkywan.fr', 9200),
        ('speedtest.milkywan.fr', 9201),
        # Paris — Bouygues 10Gbps (ports 9200-9240)
        ('paris.bbr.iperf.bytel.fr', 9200),
        ('paris.bbr.iperf.bytel.fr', 9201),
        # Netherlands — Serverius 10Gbps
        ('speedtest.serverius.net', 5002),
        # Ukraine — Volia BBR
        ('iperf.volia.net', 5201),
    ]
    
    # WiFi interface name (set to None to auto-detect)
    # Common Windows names: 'Wi-Fi', 'WiFi', 'Wireless Network Connection'
    WIFI_INTERFACE_NAME = None

    # Throughput measurement window in seconds (longer = smoother, shorter = more live)
    THROUGHPUT_MEASURE_WINDOW = 5.0

    # ---- Radio Layer Thresholds (WiFi RSSI, analogous to LTE RSRP scale) ----
    RSSI_EXCELLENT_DBM  = -65   # Excellent coverage
    RSSI_GOOD_DBM       = -70   # Good
    RSSI_ACCEPTABLE_DBM = -75   # Acceptable
    RSSI_WARNING_DBM    = -80   # Weak — investigate
    RSSI_CRITICAL_DBM   = -85   # Coverage hole equivalent

    # Channel utilization thresholds (from BSS Load IE — PRB congestion proxy)
    CHANNEL_UTIL_WARNING_PCT  = 70
    CHANNEL_UTIL_CRITICAL_PCT = 85

    # TCP retransmission rate thresholds (BLER proxy)
    TCP_RETRANS_WARNING_PCT  = 2.0
    TCP_RETRANS_CRITICAL_PCT = 5.0

    # MOS thresholds (ITU-T G.107)
    MOS_EXCELLENT  = 4.3
    MOS_GOOD       = 4.0
    MOS_ACCEPTABLE = 3.6
    MOS_POOR       = 3.1
    MOS_BAD        = 2.6

    # LTE RSRP thresholds (from router API or Android ADB, dBm)
    RSRP_EXCELLENT_DBM = -80
    RSRP_GOOD_DBM      = -90
    RSRP_ACCEPTABLE_DBM= -100
    RSRP_WARNING_DBM   = -110
    RSRP_CRITICAL_DBM  = -120

    # LTE SINR thresholds (dB)
    SINR_EXCELLENT_DB  = 20
    SINR_GOOD_DB       = 13
    SINR_ACCEPTABLE_DB =  0
    SINR_WARNING_DB    = -3
    SINR_CRITICAL_DB   = -6

    # ---- Router API config ----
    # Set ROUTER_GATEWAY to your router IP (e.g. '192.168.8.1' for Huawei)
    # Leave None or set to "auto" to auto-detect from the routing table
    ROUTER_GATEWAY    = None     # e.g. '192.168.8.1'
    ROUTER_TYPE       = 'auto'   # 'auto', 'huawei', 'zte'
    ROUTER_USERNAME   = None     # e.g. 'admin' (if your router requires login)
    ROUTER_PASSWORD   = None     # e.g. 'admin' (if your router requires login)

    # ---- Ping target config ----
    # Local gateway for ping-fallback. None / "" / "auto" → resolved at runtime.
    PING_LOCAL_GATEWAY = None


    
    @classmethod
    def from_yaml(cls, yaml_path: str = "config.yaml") -> 'TunisianNetworkConfig':
        """Load configuration from YAML file, falling back to class defaults for missing keys"""
        config = cls()
        try:
            import yaml
        except ImportError:
            logging.getLogger("QoSBuddy").warning("PyYAML not installed, using default config")
            return config
        
        try:
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f)
            if not data:
                return config
            
            net = data.get('network', {})
            
            # Latency
            lat = net.get('latency', {})
            if 'baseline_ms' in lat:
                config.LATENCY_BASELINE_MS = lat['baseline_ms']
            if 'warning_ms' in lat:
                config.LATENCY_WARNING_MS = lat['warning_ms']
            if 'critical_ms' in lat:
                config.LATENCY_CRITICAL_MS = lat['critical_ms']
            
            # Jitter
            jit = net.get('jitter', {})
            if 'acceptable_ms' in jit:
                config.JITTER_ACCEPTABLE_MS = jit['acceptable_ms']
            if 'warning_ms' in jit:
                config.JITTER_WARNING_MS = jit['warning_ms']
            if 'critical_ms' in jit:
                config.JITTER_CRITICAL_MS = jit['critical_ms']
            
            # Packet loss
            pl = net.get('packet_loss', {})
            if 'warning_pct' in pl:
                config.PACKET_LOSS_WARNING_PCT = pl['warning_pct']
            if 'critical_pct' in pl:
                config.PACKET_LOSS_CRITICAL_PCT = pl['critical_pct']
            if 'threshold_pct' in pl:
                config.PACKET_LOSS_ACCEPTABLE_PCT = pl['threshold_pct']
            
            # Throughput
            tp = net.get('throughput', {})
            if 'baseline_mbps' in tp:
                config.THROUGHPUT_BASELINE_MBPS = tp['baseline_mbps']
            if 'max_mbps' in tp:
                config.THROUGHPUT_MAX_MBPS = tp['max_mbps']
            if 'min_mbps' in tp:
                config.THROUGHPUT_CRITICAL_MBPS = tp['min_mbps']
            
            # Ping targets (from config)
            targets = net.get('ping_targets', {})
            if 'local_gateway' in targets:
                from qos_buddy.net_utils import is_auto_sentinel
                gw_val = targets['local_gateway']
                config.PING_LOCAL_GATEWAY = None if is_auto_sentinel(gw_val) else gw_val
            
            # Resources
            res = data.get('resources', {})
            cpu = res.get('cpu', {})
            if 'warning_pct' in cpu:
                config.CPU_WARNING_PCT = cpu['warning_pct']
            if 'critical_pct' in cpu:
                config.CPU_CRITICAL_PCT = cpu['critical_pct']
            mem = res.get('memory', {})
            if 'warning_pct' in mem:
                config.MEMORY_WARNING_PCT = mem['warning_pct']
            if 'critical_pct' in mem:
                config.MEMORY_CRITICAL_PCT = mem['critical_pct']
            
            # Time context
            tc = data.get('time_context', {})
            peak = tc.get('peak_hours', {})
            if 'start' in peak:
                config.PEAK_HOURS_START = peak['start']
            if 'end' in peak:
                config.PEAK_HOURS_END = peak['end']
            spk = tc.get('secondary_peak', {})
            if 'start' in spk:
                config.SECONDARY_PEAK_START = spk['start']
            if 'end' in spk:
                config.SECONDARY_PEAK_END = spk['end']
            
            # Anomaly detection
            ad = data.get('anomaly_detection', {})
            cong = ad.get('congestion', {})
            if 'latency_spike_ms' in cong:
                config.CONGESTION_LATENCY_SPIKE_MS = cong['latency_spike_ms']
            if 'throughput_spike_pct' in cong:
                config.CONGESTION_THROUGHPUT_SPIKE_PCT = cong['throughput_spike_pct']
            lf = ad.get('link_failure', {})
            if 'duration_sec' in lf:
                config.LINK_FAILURE_DURATION_SEC = lf['duration_sec']
            
            # Feature engineering
            fe = data.get('feature_engineering', {})
            qm = fe.get('queue_modeling', {})
            if 'alpha' in qm:
                config.QUEUE_ALPHA = qm['alpha']
            if 'beta' in qm:
                config.QUEUE_BETA = qm['beta']
            if 'gamma' in qm:
                config.QUEUE_GAMMA = qm['gamma']
            
            # Router metrics configuration
            rt = data.get('router', {})
            if 'gateway' in rt:
                from qos_buddy.net_utils import is_auto_sentinel
                gw_val = rt['gateway']
                config.ROUTER_GATEWAY = None if is_auto_sentinel(gw_val) else gw_val
            if 'type' in rt:
                config.ROUTER_TYPE = rt['type']
            if 'username' in rt:
                config.ROUTER_USERNAME = rt['username']
            if 'password' in rt:
                config.ROUTER_PASSWORD = rt['password']
            
            logging.getLogger("QoSBuddy").info(f"Configuration loaded from {yaml_path}")
        except FileNotFoundError:
            logging.getLogger("QoSBuddy").info(f"No config file at {yaml_path}, using defaults")
        except Exception as e:
            logging.getLogger("QoSBuddy").warning(f"Error loading config from {yaml_path}: {e}, using defaults")
        
        return config


def setup_logging(log_dir: str = "logs", verbose: bool = False) -> logging.Logger:
    """Configure logging to file and console
    
    Args:
        log_dir: Directory for log files
        verbose: If True, console output shows DEBUG level (detailed); if False, INFO level (summary)
    """
    Path(log_dir).mkdir(exist_ok=True)
    
    logger = logging.getLogger("QoSBuddy")
    logger.setLevel(logging.DEBUG)  # Logger itself captures everything
    
    # Remove any existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # File handler - always DEBUG (full detail for later analysis)
    fh = logging.FileHandler(f"{log_dir}/qos_collector_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    fh.setLevel(logging.DEBUG)
    
    # Console handler - DEBUG if verbose, INFO otherwise
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    # Formatter with more detail for debug mode
    if verbose:
        formatter = logging.Formatter('[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s')
    else:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger


