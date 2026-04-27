from data_loader import safe_value


def timeseries_row_to_context(row: dict) -> str:
    return f"""
Mesure réseau :
- Timestamp : {safe_value(row, "timestamp")}
- Latency ms : {safe_value(row, "latency_ms")}
- Jitter ms : {safe_value(row, "jitter_ms")}
- Packet loss pct : {safe_value(row, "packet_loss_pct")}
- Throughput mbps : {safe_value(row, "throughput_mbps")}
- Bandwidth util pct : {safe_value(row, "bandwidth_util_pct")}
- Traffic type : {safe_value(row, "traffic_type")}
- Traffic confidence : {safe_value(row, "traffic_confidence")}
- RSSI dBm : {safe_value(row, "rssi_dbm")}
- Signal quality pct : {safe_value(row, "signal_quality_pct")}
- Channel util pct : {safe_value(row, "channel_util_pct")}
- TCP retransmit rate : {safe_value(row, "tcp_retransmit_rate")}
- MOS estimate : {safe_value(row, "mos_estimate")}
- RSRP dBm : {safe_value(row, "rsrp_dbm")}
- RSRQ dB : {safe_value(row, "rsrq_db")}
- SINR dB : {safe_value(row, "sinr_db")}
- CQI : {safe_value(row, "cqi")}
- Anomaly flag : {safe_value(row, "anomaly_flag")}
- Anomaly type : {safe_value(row, "anomaly_type")}
- Anomaly score : {safe_value(row, "anomaly_score")}
- Source file : {safe_value(row, "source_file")}
""".strip()


def incident_row_to_context(row: dict) -> str:
    return f"""
Incident :
- Start timestamp : {safe_value(row, "start_timestamp")}
- End timestamp : {safe_value(row, "end_timestamp")}
- Incident type : {safe_value(row, "incident_type")}
- Severity : {safe_value(row, "severity")}
- Max score : {safe_value(row, "max_score")}
- Duration sec : {safe_value(row, "duration_sec")}
- Samples : {safe_value(row, "samples")}
- Node ID : {safe_value(row, "node_id")}
- Source file : {safe_value(row, "source_file")}
""".strip()