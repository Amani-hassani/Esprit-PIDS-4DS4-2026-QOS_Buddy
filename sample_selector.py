from data_loader import to_float


def compute_interest_score(row: dict) -> float:
    score = 0.0

    anomaly_flag = str(row.get("anomaly_flag", "")).strip().lower() == "true"
    anomaly_type = str(row.get("anomaly_type", "")).strip().lower()

    anomaly_score = to_float(row.get("anomaly_score"), 0.0)
    latency = to_float(row.get("latency_ms"), 0.0)
    jitter = to_float(row.get("jitter_ms"), 0.0)
    packet_loss = to_float(row.get("packet_loss_pct"), 0.0)
    throughput = to_float(row.get("throughput_mbps"), None)
    channel_util = to_float(row.get("channel_util_pct"), 0.0)
    tcp_retx = to_float(row.get("tcp_retransmit_rate"), 0.0)
    sinr = to_float(row.get("sinr_db"), None)
    rssi = to_float(row.get("rssi_dbm"), None)

    if anomaly_flag:
        score += 50

    score += anomaly_score * 100

    if latency is not None:
        score += min(latency / 5, 40)

    if jitter is not None:
        score += min(jitter / 3, 40)

    if packet_loss is not None:
        score += min(packet_loss * 4, 40)

    if throughput is not None:
        if 0 < throughput < 1:
            score += 25
        elif throughput == 0:
            score += 10

    if channel_util is not None and channel_util > 80:
        score += 20

    if tcp_retx is not None and tcp_retx > 5:
        score += 20

    if sinr is not None and sinr < 5:
        score += 20

    if rssi is not None and rssi < -85:
        score += 20

    if anomaly_type and anomaly_type != "normal":
        score += 15

    return score


def pick_most_interesting_sample(df):
    if df.empty:
        return None

    scored = df.copy()
    scored["interest_score"] = scored.apply(lambda row: compute_interest_score(row.to_dict()), axis=1)
    scored = scored.sort_values("interest_score", ascending=False)
    return scored.iloc[0].to_dict()


def top_interesting_samples(df, n=10):
    if df.empty:
        return []

    scored = df.copy()
    scored["interest_score"] = scored.apply(lambda row: compute_interest_score(row.to_dict()), axis=1)
    scored = scored.sort_values("interest_score", ascending=False).head(n)
    return [row.to_dict() for _, row in scored.iterrows()]