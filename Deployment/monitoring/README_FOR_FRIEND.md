# QOS Buddy - Network Quality Monitoring Tool

Welcome! This tool automatically collects and analyzes cellular and WiFi network quality data, including special "stress test" scenarios to see how your network performs under load.

---

## **What Does It Do?**

QOS Buddy monitors your network continuously and:
- ✅ Measures **latency, jitter, packet loss, throughput**
- ✅ Collects **cellular metrics** (signal strength, MCS, CQI) from your router
- ✅ Collects **WiFi metrics** (signal, channel, link speed)
- ✅ Runs **stress tests** (congestion & packet loss scenarios)
- ✅ **Detects anomalies** and network problems automatically
- ✅ Saves everything to **CSV files** for analysis

All data is collected every 30 seconds and saved locally.

---

## **System Requirements**

- **Windows 10/11** (PowerShell installed)
- **Python 3.11+** (from https://www.python.org/downloads/)
- **4G/5G Router** with LuCI admin interface (OpenWrt, ZTE, Huawei, etc.)
- **Internet connection** for iperf3 bandwidth tests
- **~200 MB** disk space for 1 hour of collection

---

## **Quick Start (5 Minutes)**

### **Step 1: Install Python**
1. Download Python 3.11+ from https://www.python.org/downloads/
2. Install it (✅ Check "Add Python to PATH" during installation)
3. Verify: Open PowerShell and run:
   ```powershell
   python --version
   ```
   Should show: `Python 3.11.x` or higher

### **Step 2: Create Virtual Environment**
```powershell
cd "C:\path\to\QOS_BUDDY_PROJECT"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### **Step 3: Install Dependencies**
```powershell
pip install -r requirements.txt
```

### **Step 4: Configure Router Access**
Open `config.yaml` in Notepad and update:

```yaml
# Find your router's IP address:
# Windows: Open PowerShell, run: route print | findstr "0.0.0.0.*0.0.0.0"
# Look for the "Gateway" column

ROUTER_GATEWAY: "192.168.1.1"        # Your router IP address
ROUTER_USERNAME: "admin"              # Usually 'admin'
ROUTER_PASSWORD: "your_password"      # Your router admin password

# Your device location (optional, for data organization)
ZONE_ID: "Home"
CELL_ID: "Living_Room"
NODE_ID: "Desktop"
```

**How to find router password?**
- Check the router sticker/label (usually on the back)
- Default is often `admin` or blank
- If unsure, contact your ISP

### **Step 5: Run Data Collection**
```powershell
python qos_buddy_collector.py --choice 13 --duration 5
```

**What this does:**
- Runs **5 cycles** of network stress tests (~20 minutes total)
- Each cycle:
  - **Baseline** (60 sec) - normal network
  - **Congestion x2** (30 sec each) - simulates heavy downloading
  - **Normal x2** (30 sec each) - reference measurements
  - **Packet Loss x2** (30 sec each) - simulates poor network
  - **Normal x2** (30 sec each) - recovery period

---

## **Understanding Your Data**

### **Where is my data?**
```
data/choice_13/
├── qos_timeseries_choice_13_20260405.csv    ← All samples (30-sec intervals)
└── incidents_choice_13_20260405.csv         ← Only detected problems
```

### **Key Columns Explained**

| Column | Meaning | Good Value |
|--------|---------|-----------|
| `timestamp` | When sample was collected | — |
| `traffic_type` | Test scenario running | "normal", "congestion", "packet_loss" |
| `latency_ms` | Response time | < 50 ms |
| `jitter_ms` | Latency variation | < 10 ms |
| `packet_loss_pct` | % of lost packets | < 1% |
| `throughput_mbps` | Download speed | > 5 Mbps |
| `rssi_dbm` | WiFi signal strength | > -70 dBm |
| `rsrp_dbm` | Cellular signal strength | > -120 dBm |
| `rsrq_db` | Cellular signal quality | > -12 dB |
| `mcs` | Cellular modulation | > 15 |
| `cssr_proxy_pct` | Connection success rate | 95-100% during "normal" |
| `anomaly_flag` | Problem detected? | "True" = problem found |
| `anomaly_type` | What problem? | "high_latency", "weak_signal", etc. |

### **Interpreting Results**

**During NORMAL segment:**
- CSSR should be ~95-100% (connections succeed)
- Latency stable ~10-50ms
- Packet loss near 0%

**During CONGESTION segment:**
- CSSR might drop to 50-80% (some connections fail)
- Latency increases (50-200ms)
- Throughput drops

**During PACKET_LOSS segment:**
- CSSR might drop to 20-70% (many failures)
- High packet loss % (20-90%)
- Latency spikes

**Example CSV line:**
```
2026-04-05T10:30:15,Home,Living_Room,Desktop,workstation,45.2,12.5,0.5,
8.3,55.2,3.1,...,-85,70,44,5GHz,...,-105,-15,-2.0,8,361,b20301,5G,
647332,b203,26,1.2,0.0,stable,low,...,96.5,normal,False,high_latency,0.0
```

**Means:** Signal is weak (-105 dBm), latency is high (45ms), but connection quality is good (96.5% CSSR), no anomalies detected during normal test.

---

## **Advanced Usage**

### **Run Indefinitely (Until You Stop)**
```powershell
python qos_buddy_collector.py --choice 13 --infinite
```
Press **Ctrl+C** to stop whenever you want.

### **Run Longer Collection**
```powershell
python qos_buddy_collector.py --choice 13 --duration 10
```
Runs 10 cycles (~40 minutes).

### **Enable Verbose Logging** (See detailed debug info)
```powershell
python qos_buddy_collector.py --choice 13 --duration 3 --verbose
```

### **View Real-Time Logs**
```powershell
Get-Content logs/qos_collector_*.log -Wait
```

---

## **Troubleshooting**

### **"Router not detected"**
- ✅ Check router IP in config.yaml is correct
- ✅ Router must be powered on and accessible
- ✅ Run `ping 192.168.1.1` to verify connectivity
- ✅ Ensure you're on same WiFi/network as router

### **"Cannot authenticate to router"**
- ✅ Verify username and password in config.yaml
- ✅ For LuCI (OpenWrt): Default is usually `root` + blank password
- ✅ Check router web admin page (http://192.168.1.1) - can you log in manually?

### **"iperf3 servers not reachable"**
- ✅ Normal! Some remote servers may be busy or blocked
- ✅ Data collection continues even if iperf3 fails
- ✅ Connection success rate (CSSR) will show 0% for that segment
- ✅ Try again later or increase `--duration`

### **"KeyError" or "AttributeError" errors**
- ✅ Make sure `config.yaml` is in the main folder
- ✅ Make sure `qos_buddy/` folder exists and has all files
- ✅ Delete `__pycache__/` folder and try again

### **"ModuleNotFoundError: No module named..."**
```powershell
pip install -r requirements.txt --upgrade
```

### **Unicode/Encoding Errors**
- ✅ This is already fixed in this version
- ✅ If you still see encoding errors, run:
  ```powershell
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
  ```

---

## **File Structure**

```
QOS_BUDDY_PROJECT/
│
├── qos_buddy_collector.py         Main script (run this!)
├── qos_buddy/                     Core library
│   ├── collector.py               Central data collection
│   ├── router.py                  Router API integration
│   ├── wifi_metrics.py            WiFi quality measurement
│   ├── traffic_analyzer.py        Network traffic detection
│   ├── anomaly_detector.py        Problem detection
│   └── persistence.py             CSV data saving
│
├── config.yaml                    Configuration (EDIT THIS!)
├── requirements.txt               Python dependencies
├── iperf3.20/                     Bandwidth test executable
├── run_collector.ps1              Windows helper script
├── README.md                      (This file)
│
├── data/                          Collected data (auto-created)
│   └── choice_13/
│       ├── qos_timeseries_*.csv   All samples
│       └── incidents_*.csv        Problems only
│
└── logs/                          Debug logs (auto-created)
    └── qos_collector_*.log        Detailed logs
```

---

## **What Data is Collected?**

### **From Router (Cellular):**
- Signal strength (RSRP, RSSI, RSRQ)
- Signal-to-noise ratio (SINR)
- Channel quality (CQI)
- Modulation coding scheme (MCS)
- Network type (4G LTE / 5G NSA)
- Cell ID, eNodeB, PCI
- Bandwidth info

### **From WiFi:**
- WiFi signal strength (RSSI)
- Channel number
- Band (2.4 GHz / 5 GHz)
- Connected stations
- Link speed

### **Network Metrics:**
- Latency (ping response time)
- Jitter (latency variation)
- Throughput (download speed)
- Packet loss percentage
- Connection success rate (CSSR)
- Bit error rate (BLER)

### **System Info:**
- CPU usage
- Memory usage
- Active connections
- Teams meeting status
- Timestamp

---

## **FAQs**

**Q: Is my data private?**
A: Yes! All data stays LOCAL on your computer in the `data/` folder. Nothing is uploaded anywhere.

**Q: Can I run this 24/7?**
A: Yes! Use `--infinite` flag. It will create new CSV files daily and continue indefinitely.

**Q: What if I close the window?**
A: All data collected so far is saved. Just restart to continue.

**Q: How much disk space for 24 hours?**
A: ~500 MB for continuous collection (2880 samples at 30-sec intervals).

**Q: Can I modify the stress test duration?**
A: Edit the values in `qos_buddy/collector.py` around line 1050 (search for `duration_seconds=30`).

**Q: Do I need the router password?**
A: Only if you want cellular metrics (signal strength, MCS, etc.). WiFi-only collection works without it.

**Q: Can this harm my network?**
A: No. It only reads data and runs harmless iperf3 bandwidth tests. No configuration changes are made.

---

## **Next Steps**

1. ✅ Update `config.yaml` with your router credentials
2. ✅ Run: `python qos_buddy_collector.py --choice 13 --duration 2`
3. ✅ Wait 8 minutes for data to collect
4. ✅ Open `data/choice_13/qos_timeseries_choice_13_*.csv` in Excel
5. ✅ Look for patterns in your network during stress tests

---

## **Need Help?**

Check the log files:
```powershell
Get-Content logs/qos_collector_20260405_*.log -Tail 50
```

This shows the last 50 lines of the log file with any errors or details.

---

**Happy collecting! 📊**

*Created with ❤️ for QOS Buddy Network Monitoring*
