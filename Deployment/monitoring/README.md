# Monitoring Agent

The Monitoring Agent collects network quality telemetry for QoS Buddy. It measures host, Wi-Fi, router, and traffic indicators, then writes structured samples that the integrated platform can consume.

## What It Collects

- Latency, jitter, packet loss, throughput, and connection success rate.
- Wi-Fi signal, channel, band, and link information when available.
- Router and cellular metrics such as RSRP, RSRQ, SINR, CQI, MCS, and band information when the router exposes them.
- Host metrics such as CPU, memory, active connections, and timestamped scenario context.

## Main Files

```text
monitoring/
|-- qos_buddy_collector.py       Main collector entrypoint
|-- config.yaml                  Local collector configuration
|-- qos_buddy/                   Collector library modules
|-- data/                        Packaged sample data
|-- pipeline_ui/                 Optional pipeline monitoring UI
|-- requirements.txt             Python dependencies
|-- run_collector.ps1            Windows helper
`-- ROUTER_ACCESS_GUIDE.md       Router configuration guide
```

## Run Locally

From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python qos_buddy_collector.py --duration 5
```

For the integrated demo, use the top-level deployment launcher instead:

```powershell
cd ..
.\START-HERE.ps1
```

The launcher starts the collector and the Docker Compose platform together.

## Configuration

Edit `config.yaml` for local router access and device labels. Router credentials should stay local and should not be committed.

If router metrics are unavailable, the collector can still provide useful host and Wi-Fi telemetry.

## Output

Runtime output is written as local CSV and JSONL files. These files support training, replay, live monitoring, and troubleshooting. New private telemetry captures should be reviewed before committing.

