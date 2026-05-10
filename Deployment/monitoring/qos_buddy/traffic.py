"""
QoS Buddy - Network Data Acquisition Framework
Phase A: Real-World Data Collection with Automatic Anomaly Detection

Author: QoS Buddy Team
Version: 1.2
Date: 2026-03-17
"""

import time
import threading
import socket
import psutil
import logging
from collections import Counter, defaultdict
from typing import Dict, List, Tuple, Optional


# ==================== IPERF3 BANDWIDTH TESTING ====================
from qos_buddy.config import TunisianNetworkConfig

# Initialize logger
logger = logging.getLogger("QoSBuddy")


class AdvancedTrafficAnalyzer:
    """
    Sophisticated traffic type detection using multiple signals:
    1. Process detection — which app owns each connection (most reliable)
    2. DNS hostname lookup — reverse-DNS on remote IPs to identify services
    3. Port detection — only unambiguous ports (SIP, BitTorrent, etc.)
    4. Pattern detection — throughput/latency/jitter heuristics (fallback)
    
    All signals are combined via weighted voting instead of strict priority.
    A single psutil snapshot is used per sample to avoid redundant syscalls.
    """
    
    # ---- Port mappings: ONLY unambiguous ports (removed 80, 443, 8080, 8443) ----
    PORT_MAPPINGS = {
        'voip': {5060, 5061, 4569, 1719, 1720, 5004, 5005},
        'video_call': {16384, 16385, 16386, 16387, 16388, 16389, 16390,
                       16391, 16392, 16393, 16394, 16395, 16396, 16397, 16398, 16399},
        'streaming': {1935, 8554, 6970, 6971, 6972},  # RTMP, RTSP
        'gaming': {3074, 27015, 27016, 27030, 27031, 25565,
                   4380, 6100, 6500, 7777, 7778},
        'file_transfer': {20, 21, 115, 989, 990},
        'p2p': {6881, 6882, 6883, 6884, 6885, 6886, 6887, 6888, 6889},
        'dns': {53},
        'stun': {3478, 3479},  # STUN/TURN (used by VoIP + video + gaming)
    }
    
    # ---- Process name patterns ----
    PROCESS_PATTERNS = {
        'gaming': {
            'valorant', 'valorant.exe', 'valorantclient', 'riotclient',
            'steam', 'steamwebhelper',
            'fortnite', 'epicgames', 'xbox', 'gamingservices',
            'minecraft', 'javaw',  # Minecraft Java
            'csgo', 'cs2', 'dota2', 'leagueclient', 'league of legends',
            'pubg', 'apex', 'overwatch', 'battlenet', 'battle.net',
            'genshinimpact', 'rocketleague', 'r5apex',
        },
        'video_call': {
            'zoom', 'zoomit', 'cpthost',  # Zoom processes
            'teams', 'msteams',            # Microsoft Teams
            'skype', 'skypeapp',
            'discord',                     # Discord
            'facetime', 'whatsapp', 'telegram', 'signal', 'jitsi',
            'webex', 'gotomeeting', 'googlemeetdesktop',
        },
        'streaming': {
            'netflix', 'prime video', 'youtube', 'vlc', 'mpv',
            'spotify', 'apple music', 'disney', 'hbomax',
            'twitch', 'obs64', 'obs32', 'streamlabs',  # Streaming apps
            'plex', 'jellyfin', 'kodi',
        },
        'file_transfer': {
            'dropbox', 'onedrive', 'googledrive', 'resilio', 'syncthing',
            'torrent', 'transmission', 'utorrent', 'qbittorrent', 'deluge',
            'filezilla', 'winscp', 'cyberduck',
        },
        'browsing': {
            'chrome', 'firefox', 'msedge', 'safari', 'opera', 'brave',
            'iexplore', 'vivaldi', 'chromium',
        },
    }
    
    # ---- DNS hostname patterns → traffic type (checked via substring match) ----
    # These resolve the "everything is port 443" problem
    HOSTNAME_PATTERNS = {
        'video_call': [
            'zoom.us', 'zoom.com', 'zoomgov.com',
            'teams.microsoft.com', 'teams.live.com', 'lync.com', 'skype.com',
            'discord.gg', 'discord.com', 'discordapp.com', 'discord.media',
            'whatsapp.net', 'whatsapp.com',
            'telegram.org', 'signal.org',
            'meet.google.com', 'webex.com', 'gotomeeting.com',
            'facetime.apple.com', 'jitsi.org',
        ],
        'streaming': [
            'youtube.com', 'googlevideo.com', 'ytimg.com',
            'netflix.com', 'nflxvideo.net', 'nflxso.net',
            'twitch.tv', 'twitchcdn.net', 'jtvnw.net',
            'spotify.com', 'scdn.co', 'spotifycdn.com',
            'primevideo.com', 'amazonvideo.com', 'aiv-cdn.net',
            'disneyplus.com', 'disney-plus.net', 'bamgrid.com',
            'hbomaxcdn.com', 'hbomax.com',
            'deezer.com', 'soundcloud.com',
            'plex.tv', 'plexapp.com',
            'crunchyroll.com', 'funimation.com', 'animelab.com',
            'dailymotion.com', 'vimeo.com',
        ],
        'gaming': [
            'steampowered.com', 'steamcontent.com', 'steamstatic.com',
            'epicgames.com', 'unrealengine.com', 'fortnite.com',
            'riotgames.com', 'riotcdn.net', 'leagueoflegends.com',
            'blizzard.com', 'battle.net', 'blizzard.net',
            'xbox.com', 'xboxlive.com', 'playfabapi.com',
            'playstation.com', 'playstation.net',
            'ea.com', 'origin.com',
            'ubisoft.com', 'uplay.com',
            'valvesoftware.com',
            'mojang.com', 'minecraft.net',
            'rockstargames.com',
        ],
        'file_transfer': [
            'dropbox.com', 'dropboxapi.com',
            'onedrive.live.com', 'sharepoint.com', '1drv.com',
            'drive.google.com', 'googleapis.com',
            'icloud.com', 'apple-cloudkit.com',
            'mega.nz', 'mega.co.nz',
            'mediafire.com',
        ],
        'voip': [
            'sip.', 'pbx.', 'voip.',  # Common SIP/VoIP hostname prefixes
        ],
    }
    
    # Weights for combining detection signals
    WEIGHT_PROCESS = 0.45
    WEIGHT_HOSTNAME = 0.35
    WEIGHT_PORT = 0.10
    WEIGHT_PATTERN = 0.10
    
    def __init__(self, config: 'TunisianNetworkConfig' = None):  # type: ignore
        self.config = config or TunisianNetworkConfig()
        self._dns_cache: Dict[str, Optional[str]] = {}  # IP → hostname
        self._dns_cache_ttl: Dict[str, float] = {}       # IP → cache timestamp
        self._DNS_CACHE_SECONDS = 300  # 5-minute TTL
        self._DNS_CACHE_MAX_SIZE = 500  # Max cache entries before LRU eviction
        self._last_established_count = 0  # Connection count from last snapshot
    
    # ---------- Single Connection Snapshot ----------
    def _take_connection_snapshot(self) -> List:
        """
        Take ONE snapshot of all network connections.
        Returns list of psutil connection objects. Used by all detection methods.
        Also stores the ESTABLISHED connection count for reuse.
        """
        try:
            conns = list(psutil.net_connections())
            self._last_established_count = len([c for c in conns if c.status == 'ESTABLISHED'])
            return conns
        except Exception as e:
            logger.debug(f"Connection snapshot failed: {e}")
            self._last_established_count = 0
            return []
    
    # ---------- DNS Hostname Lookup ----------
    def _resolve_ip(self, ip: str) -> Optional[str]:
        """
        Reverse-DNS lookup with caching. Returns hostname or None.
        Skips private/local IPs. Cache entries expire after 5 minutes.
        Uses a worker thread to enforce a hard timeout (gethostbyaddr ignores
        socket.setdefaulttimeout on Windows).
        """
        # Skip private/local IPs
        if ip.startswith(('127.', '10.', '192.168.', '0.', '::1', 'fe80')):
            return None
        if ip.startswith('172.'):
            try:
                second_octet = int(ip.split('.')[1])
                if 16 <= second_octet <= 31:
                    return None
            except (ValueError, IndexError):
                pass
        
        now = time.time()
        # Check cache
        if ip in self._dns_cache:
            if now - self._dns_cache_ttl.get(ip, 0) < self._DNS_CACHE_SECONDS:
                return self._dns_cache[ip]
        
        # Perform reverse lookup with hard timeout via thread
        result_holder: List[Optional[str]] = [None]  # mutable container for thread result
        
        def _do_lookup():
            try:
                hostname, _aliases, _addrs = socket.gethostbyaddr(ip)
                if hostname and hostname != ip:
                    result_holder[0] = hostname.lower()
            except (socket.herror, socket.gaierror, socket.timeout, OSError):
                pass
        
        t = threading.Thread(target=_do_lookup, daemon=True)
        t.start()
        t.join(timeout=0.5)  # Hard 500ms timeout
        
        self._dns_cache[ip] = result_holder[0]
        self._dns_cache_ttl[ip] = now
        # Evict oldest entries if cache exceeds max size
        while len(self._dns_cache) > self._DNS_CACHE_MAX_SIZE:
            oldest_ip = min(self._dns_cache_ttl, key=lambda k: self._dns_cache_ttl[k])
            del self._dns_cache[oldest_ip]
            del self._dns_cache_ttl[oldest_ip]
        return self._dns_cache[ip]
    
    def _classify_by_hostname(self, connections: List) -> Dict[str, float]:
        """
        Classify traffic by reverse-DNS of remote IPs.
        Returns: {traffic_type: total_score} where score = number of matching connections.
        Performs DNS lookups in parallel (max 10 new lookups) to avoid blocking.
        """
        scores: Dict[str, float] = defaultdict(float)
        ips_to_lookup: List[str] = []
        cached_ips: Dict[str, Optional[str]] = {}
        seen: set = set()
        
        for conn in connections:
            if conn.status != 'ESTABLISHED' or not conn.raddr:
                continue
            remote_ip = conn.raddr[0]
            if remote_ip in seen:
                continue
            seen.add(remote_ip)
            
            # Skip private IPs
            if remote_ip.startswith(('127.', '10.', '192.168.', '0.', '::1', 'fe80')):
                continue
            if remote_ip.startswith('172.'):
                try:
                    second_octet = int(remote_ip.split('.')[1])
                    if 16 <= second_octet <= 31:
                        continue
                except (ValueError, IndexError):
                    pass
            
            # Check cache first
            now = time.time()
            if remote_ip in self._dns_cache:
                if now - self._dns_cache_ttl.get(remote_ip, 0) < self._DNS_CACHE_SECONDS:
                    cached_ips[remote_ip] = self._dns_cache[remote_ip]
                    continue
            
            if len(ips_to_lookup) < 10:
                ips_to_lookup.append(remote_ip)
        
        # Parallel DNS lookups for uncached IPs
        if ips_to_lookup:
            results = self._batch_reverse_dns(ips_to_lookup)
            now = time.time()
            for ip, hostname in results.items():
                self._dns_cache[ip] = hostname
                self._dns_cache_ttl[ip] = now
                cached_ips[ip] = hostname
        
        # Score hostnames against patterns
        for ip, hostname in cached_ips.items():
            if not hostname:
                continue
            for traffic_type, patterns in self.HOSTNAME_PATTERNS.items():
                for pattern in patterns:
                    if pattern in hostname:
                        scores[traffic_type] += 1.0
                        break
        
        return dict(scores)
    
    def _batch_reverse_dns(self, ips: List[str]) -> Dict[str, Optional[str]]:
        """
        Perform reverse DNS lookups on multiple IPs in parallel.
        Each lookup has a 300ms timeout. Total batch timeout: 1 second.
        Returns: {ip: hostname_or_None}
        """
        results: Dict[str, Optional[str]] = {ip: None for ip in ips}
        
        def _lookup(ip):
            try:
                hostname, _, _ = socket.gethostbyaddr(ip)
                if hostname and hostname != ip:
                    results[ip] = hostname.lower()
            except (socket.herror, socket.gaierror, socket.timeout, OSError):
                pass
        
        threads = []
        for ip in ips:
            t = threading.Thread(target=_lookup, args=(ip,), daemon=True)
            threads.append(t)
            t.start()
        
        # Wait for all threads with a hard total timeout
        deadline = time.time() + 0.5  # 500ms max for the whole batch
        for t in threads:
            remaining = deadline - time.time()
            if remaining > 0:
                t.join(timeout=remaining)
            else:
                break  # Out of time, use whatever we have
        
        return results
    
    # ---------- Process Detection (improved) ----------
    def _classify_by_process(self, connections: List) -> Tuple[Dict[str, int], Optional[Tuple[str, float]]]:
        """
        Classify traffic by process names on established connections.
        Returns: (process_counts, best_match)
          - process_counts: {process_name: connection_count}
          - best_match: (traffic_type, confidence) or None
        
        Improvement: checks ALL recognized processes weighted by connection count,
        not just the single most-active process.
        """
        process_counts: Dict[str, int] = Counter()
        type_scores: Dict[str, float] = defaultdict(float)
        
        for conn in connections:
            if conn.status != 'ESTABLISHED' or not conn.pid:
                continue
            try:
                proc = psutil.Process(conn.pid)
                pname = proc.name().lower()
                process_counts[pname] += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        if not process_counts:
            return dict(process_counts), None
        
        # Score each traffic type by how many connections its processes have
        for pname, count in process_counts.items():
            for traffic_type, patterns in self.PROCESS_PATTERNS.items():
                for pattern in patterns:
                    if pattern in pname:
                        type_scores[traffic_type] += count
                        break
        
        if not type_scores:
            return dict(process_counts), None
        
        best_type = max(type_scores, key=lambda k: type_scores[k])
        total_recognized = sum(type_scores.values())
        total_conns = sum(process_counts.values())
        # Confidence scales with how dominant the best type is
        dominance = type_scores[best_type] / max(total_conns, 1)
        confidence = min(0.95, 0.60 + 0.35 * dominance)
        
        return dict(process_counts), (best_type, confidence)
    
    # ---------- Port Detection (unambiguous only) ----------
    def _classify_by_port(self, connections: List) -> Dict[str, float]:
        """
        Classify traffic by remote port numbers (unambiguous ports only).
        Returns: {traffic_type: count_of_matching_connections}
        """
        scores: Dict[str, float] = defaultdict(float)
        
        for conn in connections:
            if conn.status != 'ESTABLISHED' or not conn.raddr:
                continue
            remote_port = conn.raddr[1]
            # Skip the super-common ambiguous ports
            if remote_port in (80, 443, 8080, 8443):
                continue
            for traffic_type, ports in self.PORT_MAPPINGS.items():
                if remote_port in ports:
                    scores[traffic_type] += 1.0
                    break
        
        return dict(scores)
    
    # ---------- Pattern Detection (network metrics heuristics) ----------
    def _detect_by_pattern(self, throughput: float, latency: float, jitter: float,
                          packet_loss: float, active_conns: int) -> Tuple[str, float]:
        """Detect traffic type based on network characteristics (fallback heuristic)"""
        
        if throughput < 0.1 and active_conns == 0:
            return ('idle', 0.95)
        
        if throughput < 0.5 and active_conns <= 1:
            if jitter > self.config.JITTER_CRITICAL_MS:
                return ('voip_degraded', 0.85)
            if latency > self.config.LATENCY_CRITICAL_MS:
                return ('voip_lag', 0.80)
            if packet_loss > self.config.PACKET_LOSS_CRITICAL_PCT:
                return ('voip_packet_loss', 0.85)
            return ('voip', 0.90)
        
        if 0.3 < throughput < 3.0 and active_conns >= 1:
            if jitter > self.config.JITTER_CRITICAL_MS or packet_loss > self.config.PACKET_LOSS_WARNING_PCT:
                return ('video_call_degraded', 0.80)
            if latency > self.config.LATENCY_CRITICAL_MS:
                return ('video_call_lag', 0.75)
            if throughput > 1.0:
                return ('video_call', 0.85)
        
        if 0.5 < throughput < 5.0 and active_conns >= 2:
            latency_good = latency < self.config.LATENCY_ACCEPTABLE_MS
            jitter_good = jitter < self.config.JITTER_GOOD_MS
            
            if not latency_good and not jitter_good:
                return ('gaming_lag', 0.75)
            elif latency_good and jitter_good:
                return ('gaming', 0.85)
            elif latency <= self.config.LATENCY_WARNING_MS and jitter <= self.config.JITTER_WARNING_MS:
                return ('gaming', 0.75)
            elif latency > self.config.LATENCY_CRITICAL_MS or jitter > self.config.JITTER_CRITICAL_MS:
                return ('gaming_lag', 0.70)
        
        if throughput >= 8.0:
            if jitter > self.config.JITTER_CRITICAL_MS or packet_loss > self.config.PACKET_LOSS_WARNING_PCT:
                return ('streaming_hd_degraded', 0.75)
            if latency > self.config.LATENCY_WARNING_MS:
                return ('streaming_hd_lag', 0.65)
            return ('streaming_hd', 0.85)
        
        # File transfer: check BEFORE streaming so high-connection bulk transfers aren't misclassified
        if throughput >= 4.0 and active_conns >= 3:
            if packet_loss > self.config.PACKET_LOSS_WARNING_PCT:
                return ('file_transfer_lossy', 0.70)
            return ('file_transfer', 0.80)
        
        if 3.0 <= throughput < 8.0 and active_conns >= 1:
            if jitter > self.config.JITTER_WARNING_MS or packet_loss > self.config.PACKET_LOSS_CRITICAL_PCT:
                return ('streaming_degraded', 0.75)
            return ('streaming', 0.80)
        
        if 0.1 <= throughput < 3.0:
            return ('mixed_traffic', 0.45)
        
        return ('unknown', 0.30)
    
    # ---------- Weighted Multi-Signal Voting ----------
    def _combine_signals(self,
                         process_result: Optional[Tuple[str, float]],
                         hostname_scores: Dict[str, float],
                         port_scores: Dict[str, float],
                         pattern_result: Tuple[str, float]) -> Tuple[str, float, str]:
        """
        Combine all detection signals via weighted voting.
        
        Each method contributes a weighted score to each traffic type.
        The type with the highest combined score wins.
        Returns: (traffic_type, confidence, primary_detection_method)
        """
        combined: Dict[str, float] = defaultdict(float)
        methods: Dict[str, str] = {}  # type → which method contributed most
        
        # 1) Process signal
        if process_result:
            ptype, pconf = process_result
            combined[ptype] += pconf * self.WEIGHT_PROCESS
            methods[ptype] = 'process'
        
        # 2) Hostname signal — normalize scores so they sum to 1
        if hostname_scores:
            total_h = sum(hostname_scores.values())
            for htype, hscore in hostname_scores.items():
                normalized = hscore / total_h
                weighted = normalized * self.WEIGHT_HOSTNAME
                combined[htype] += weighted
                if htype not in methods:
                    methods[htype] = 'hostname'
        
        # 3) Port signal — normalize scores
        if port_scores:
            total_p = sum(port_scores.values())
            for ptype, pscore in port_scores.items():
                normalized = pscore / total_p
                weighted = normalized * self.WEIGHT_PORT
                combined[ptype] += weighted
                if ptype not in methods:
                    methods[ptype] = 'port'
        
        # 4) Pattern signal (always present)
        pat_type, pat_conf = pattern_result
        combined[pat_type] += pat_conf * self.WEIGHT_PATTERN
        if pat_type not in methods:
            methods[pat_type] = 'pattern'
        
        if not combined:
            return (pat_type, pat_conf, 'pattern')
        
        # Pick the winner
        best_type = max(combined, key=lambda k: combined[k])
        raw_score = combined[best_type]
        
        # Scale raw score to 0.0-1.0 confidence
        # Max possible raw score is ~0.95*0.45 + 1.0*0.35 + 1.0*0.10 + 0.95*0.10 = 0.9225
        confidence = min(0.99, raw_score / 0.92)
        confidence = round(max(0.10, confidence), 2)
        
        method = methods.get(best_type, 'pattern')
        
        return (best_type, confidence, method)
    
    # ---------- Main Entry Point ----------
    def analyze_traffic(self, record: Dict) -> Tuple[str, float, str]:
        """
        Comprehensive traffic analysis using all available signals.
        
        1. Takes a single connection snapshot (one psutil call)
        2. Runs process detection, DNS hostname lookup, port classification
        3. Runs pattern-based heuristics on network metrics
        4. Combines all signals via weighted voting
        5. Checks if Teams meeting is active to override traffic classification
        
        Returns: (traffic_type, confidence, detection_method)
        """
        throughput = record['throughput_mbps']
        latency = record['latency_ms']
        jitter = record['jitter_ms']
        packet_loss = record['packet_loss_pct']
        
        # Check if Teams meeting is active (NEW)
        teams_in_meeting = record.get('teams_in_meeting', False)
        
        # --- Single snapshot for all methods ---
        connections = self._take_connection_snapshot()
        active_conns = self._last_established_count  # Use count from our snapshot
        
        # 1) Process detection
        _process_counts, process_result = self._classify_by_process(connections)
        
        # 2) DNS hostname detection
        hostname_scores = self._classify_by_hostname(connections)
        
        # 3) Port detection (unambiguous ports only)
        port_scores = self._classify_by_port(connections)
        
        # 4) Pattern-based heuristics
        pattern_result = self._detect_by_pattern(
            throughput, latency, jitter, packet_loss, active_conns
        )
        
        # Combine via weighted voting
        traffic_type, confidence, method = self._combine_signals(
            process_result, hostname_scores, port_scores, pattern_result
        )
        
        # Override with Teams detection if meeting is active (PRIORITY)
        if teams_in_meeting:
            traffic_type = 'calling'
            confidence = 0.95
            method = 'teams_detection'
        
        return (traffic_type, confidence, method)


