# Router Access Guide

This guide explains how to configure router access for the Monitoring Agent. Router access is optional: QoS Buddy can still collect host and Wi-Fi metrics when router or cellular metrics are unavailable.

## Required Information

To collect router and cellular metrics, we need:

- Router IP address, usually `192.168.1.1`, `192.168.0.1`, or `10.0.0.1`.
- Admin username, usually `admin` or `root`.
- Admin password from the router label, ISP documentation, or local administrator.
- A router interface that exposes status or LuCI-compatible metrics.

Do not commit real router credentials.

## Find The Router IP

On Windows:

```powershell
ipconfig
```

Look for `Default Gateway` on the active network adapter.

You can also use:

```powershell
route print | findstr "0.0.0.0"
```

On macOS or Linux:

```bash
netstat -nr | grep default
```

## Confirm Web Access

Open the router IP in a browser:

```text
http://192.168.1.1
```

If the router uses HTTPS:

```text
https://192.168.1.1
```

Log in with the local admin credentials. If the credentials are unknown, check the router label, ISP documentation, or the person responsible for the network.

## Common Metric Locations

Different routers organize metrics differently. Useful pages are often under:

- Status.
- Network status.
- Internet status.
- Cellular or mobile status.
- Advanced network information.
- Signal information.

Useful cellular fields include:

| Field | Meaning |
| --- | --- |
| RSRP | Cellular signal strength |
| RSRQ | Cellular signal quality |
| SINR | Signal-to-noise ratio |
| CQI | Channel quality indicator |
| MCS | Modulation and coding scheme |
| Band | LTE or 5G band |
| Cell ID | Connected cell or tower identifier |

## Configure `config.yaml`

Update the local monitoring configuration:

```yaml
ROUTER_GATEWAY: "192.168.1.1"
ROUTER_USERNAME: "admin"
ROUTER_PASSWORD: "change-this-locally"

ZONE_ID: "Lab"
CELL_ID: "Cell-01"
NODE_ID: "Node-01"
DEVICE_TYPE: "workstation"
```

Use local values only. Do not commit a real password.

## Test Connectivity

Ping the router:

```powershell
ping 192.168.1.1
```

Test the web interface:

```powershell
Invoke-WebRequest -Uri "http://192.168.1.1" -TimeoutSec 5
```

If the router uses a self-signed HTTPS certificate:

```powershell
Invoke-WebRequest -Uri "https://192.168.1.1" -SkipCertificateCheck -TimeoutSec 5
```

## Run A Short Collection

From `Deployment/monitoring`:

```powershell
python qos_buddy_collector.py --duration 1
```

Then inspect the generated CSV files under `data/`. If router fields are empty but host and Wi-Fi fields are populated, the collector is still usable.

## Troubleshooting

| Problem | Likely Cause | What To Check |
| --- | --- | --- |
| Router does not respond | Wrong IP or disconnected network | Confirm `Default Gateway` and Wi-Fi connection |
| Login fails | Wrong credentials | Check router label, ISP docs, or local admin |
| Cellular fields are empty | Router does not expose metrics | Use host and Wi-Fi metrics, or try another router endpoint |
| HTTP request fails | Router uses HTTPS or blocks API access | Try HTTPS or inspect the web UI manually |
| Collection continues with missing router values | Expected fallback behavior | Review logs and CSV output |

## Privacy

Router credentials and private network captures must remain local. The repository includes only demo configuration examples and sample data.
