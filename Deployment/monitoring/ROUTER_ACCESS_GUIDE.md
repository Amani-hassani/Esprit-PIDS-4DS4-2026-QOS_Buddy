# Router Data Access Guide

This guide explains how to access your router's web interface and find the data needed to configure `config.yaml` for network data collection.

---

## **Quick Summary**

To collect cellular metrics from your router, you need:
- **Router IP Address** (usually 192.168.1.1)
- **Admin Username** (usually "admin" or "root")
- **Admin Password** (on router sticker or default)
- **LuCI API support** (most modern routers have this)

---

## **Step 1: Find Your Router IP Address**

### **On Windows (PowerShell):**
```powershell
route print | findstr "0.0.0.0.*0.0.0.0"
```

Look for the "Gateway" column in the output - that's your router IP.

**Typical result:** `192.168.1.1` or `192.168.0.1` or `10.0.0.1`

### **On Mac/Linux:**
```bash
netstat -nr | grep default
```

---

## **Step 2: Access Router Web Interface**

1. Open your web browser (Chrome, Firefox, Edge, Safari)
2. Type your router IP in the address bar: `http://192.168.1.1`
3. Press Enter

If you see a login page, proceed to Step 3.
If you get "connection refused", try Step 4.

---

## **Step 3: Find Your Router Login Credentials**

### **Check Physical Router**
1. Look on the **back or bottom** of the router
2. Find the sticker with:
   - Default IP: `192.168.1.1` (or similar)
   - Username: Usually `admin` or `root`
   - Password: Often blank, or printed as `admin`, `password`, model number

### **Common Default Credentials**

| Router Type | Username | Password |
|-------------|----------|----------|
| ZTE (5G) | admin | admin |
| Huawei | admin | admin |
| OpenWrt/LuCI | root | (blank) |
| TP-Link | admin | admin |
| D-Link | admin | (blank) |
| Asus | admin | admin |
| Xiaomi | admin | admin |

### **If You Changed Password**
- Contact your ISP (they may have a record)
- Factory reset (usually button on back, hold 10+ seconds)
- Check your email for setup documentation

---

## **Step 4: Test Router Connection**

Use PowerShell to verify your router is accessible:

```powershell
# Check if router responds to ping
ping 192.168.1.1

# Expected result: Pings successfully (0-5ms latency)
# If no response: Router is OFF or IP is wrong
```

**If ping fails:**
- ✅ Check router is powered on
- ✅ Try different IP: 192.168.0.1, 10.0.0.1
- ✅ Check WiFi connection (not cellular only)
- ✅ Router might be in bridge mode (call ISP)

---

## **Step 5: Login to Router Web Interface**

1. Go to `http://192.168.1.1` (your router IP)
2. Enter username and password
3. Click Login

You should see the router admin dashboard.

---

## **Step 6: Find Cellular Metrics in Router Interface**

Different router types organize information differently. Here's where to look:

### **ZTE/Huawei 5G Routers**

**Path:** Admin → Status → Network/Signal

Look for:
- **Signal Strength (RSRP):** Usually shown as -XXX dBm
- **Signal Quality (RSRQ):** Shown as -XX dB
- **Signal-to-Noise (SINR):** Shown as X dB
- **MCS (Modulation):** 0-28 value
- **Band:** "Band 78" (5G) or "Band 20" (4G)
- **Network Type:** "5G NSA" or "4G LTE"
- **Cell ID:** Shows current tower

**Common Locations:**
- Status → Network → 5G Information
- Network → Internet Status
- System → Network Status
- Signal → Current Signal

### **OpenWrt/LuCI Routers** (Most Common for Custom)

**Path:** Status → Overview or Cellular/Mobile Status

Look for:
- Connection status
- Signal metrics
- Network selection
- Data usage

---

## **Step 7: Test API Endpoints (Advanced)**

If your router supports LuCI API (OpenWrt), you can test it directly:

### **Test Connection in PowerShell:**

```powershell
# Basic request to router status page
Invoke-WebRequest -Uri "http://192.168.1.1" -Method GET

# If you get a response, router has HTTP access
# (May require credentials)
```

### **Test LuCI Login (if OpenWrt)**

```powershell
# PowerShell script to test LuCI auth
$router = "192.168.1.1"
$username = "admin"
$password = "admin"

# Try to login to LuCI
$loginUrl = "https://$router/cgi-bin/luci"
$response = Invoke-WebRequest -Uri $loginUrl -SkipCertificateCheck

if ($response.StatusCode -eq 200) {
    Write-Host "✅ LuCI API is accessible"
} else {
    Write-Host "❌ LuCI API not found"
}
```

---

## **Step 8: Configure config.yaml**

Once you've found your router info, edit `config.yaml`:

```yaml
# Router Configuration
ROUTER_GATEWAY: "192.168.1.1"        # Your router IP from step 1
ROUTER_USERNAME: "admin"              # Username from router sticker
ROUTER_PASSWORD: "your_password"      # Password from router sticker

# Your device location (optional)
ZONE_ID: "Home"
CELL_ID: "Living_Room"
NODE_ID: "Desktop"
DEVICE_TYPE: "workstation"
```

---

## **Step 9: Test Configuration Before Running**

Create a test script to verify router access works:

**test_router_connection.ps1:**
```powershell
$config = @{
    gateway = "192.168.1.1"
    username = "admin"
    password = "admin"
}

# Test if we can ping the router
Write-Host "Testing ping to $($config.gateway)..."
$ping = Test-Connection -ComputerName $config.gateway -Count 1
if ($ping) {
    Write-Host "✅ Router is reachable"
} else {
    Write-Host "❌ Router not reachable"
    exit
}

# Test HTTP access
Write-Host "Testing HTTP access..."
try {
    $response = Invoke-WebRequest -Uri "http://$($config.gateway)" -TimeoutSec 5
    Write-Host "✅ Router HTTP interface is accessible"
} catch {
    Write-Host "❌ Cannot access router web interface"
    Write-Host "Error: $_"
}
```

Run it:
```powershell
.\test_router_connection.ps1
```

---

## **Router Types & Special Notes**

### **ZTE 5G CPE (Most Common)**

**Access URL:** `http://192.168.1.1`  
**Default Creds:** admin / admin  
**Signal Location:** System → Network Status → Signal Strength

To see detailed cellular info:
1. System → Network Status
2. Look for RSRP, RSRQ, SINR values
3. Band info shows 5G or 4G

**Known Issue:** Password sometimes changed by ISP
- Default factory: `admin/admin`
- Try: `admin/zte` if default doesn't work

### **Huawei 5G CPE**

**Access URL:** `http://192.168.1.1`  
**Default Creds:** admin / admin  
**Signal Location:** Administration → System → Network

Look for these tabs:
- Network Status (shows current signal)
- Connection Log (shows detailed metrics)

### **OpenWrt/Custom Linux**

**Access URL:** `https://192.168.1.1` (note: HTTPS)  
**Default Creds:** root / (blank password)  
**Signal Location:** Status → Overview

May show:
- LAN/WAN status
- WiFi status
- Cellular status (if modem connected)

**Note:** No direct 4G/5G metrics visible (requires API access)

### **TP-Link/D-Link/ASUS Home Routers**

These usually DON'T have cellular metrics:
- ❌ Won't show RSRP, RSRQ, MCS
- ❌ Only show WiFi metrics
- ✅ Can still use WiFi-only collection

---

## **Special Cases**

### **"Router Not Responding"**

**Check router is turned ON:**
- Look for lights on the device
- Try unplugging/replugging power

**Check you have the right IP:**
```powershell
ipconfig
# Find "Default Gateway" in output
# That's your router IP
```

**Check WiFi connection:**
- Are you connected to the right WiFi?
- Some routers have 2.4GHz + 5GHz networks
- Try both

### **"Admin Interface Shows No Signal Metrics"**

Your router might not support cellular metrics display:
- ✅ Some routers hide these in "Advanced" mode
- ✅ Some require specific menus/tabs
- ✅ Check documentation for your model
- Try: System → Advanced → Network Status

### **"Can't Remember Password"**

**Factory Reset (will erase all settings):**
1. Unplug router
2. Wait 30 seconds
3. Press reset button (small hole) while plugging in
4. Hold 10+ seconds until lights flash
5. Router will reboot with defaults

Then use default password from sticker.

### **"Password Different from Sticker"**

ISP or previous owner may have changed it:
- ✅ Try default passwords (admin/admin, admin/password, etc.)
- ✅ Check emails for setup documentation
- ✅ Call your ISP - they may reset it
- ✅ Factory reset (see above)

---

## **Verifying Cellular Metrics Available**

### **Checklist:**

Before running the collection tool, verify:

```
☐ Can access router web interface HTTP://192.168.1.1
☐ Found RSRP value (signal strength)
☐ Found RSRQ value (signal quality)
☐ Found MCS value (modulation)
☐ Found band info (4G/5G)
☐ Router shows network type (LTE or 5G)
```

If you can see all these in the web interface, config.yaml will work!

If NOT:
- ⚠️ Your router might not support these metrics
- ✅ Collection can still run with WiFi metrics only
- ✅ Will skip cellular metrics, no errors

---

## **Example Complete Router Check**

### **ZTE Router Check (5 minutes):**

1. **Ping router:**
   ```powershell
   ping 192.168.1.1
   # Should get replies
   ```

2. **Visit web interface:**
   - Open browser
   - Go to `http://192.168.1.1`
   - Login with `admin/admin`

3. **Find signal metrics:**
   - Click "System"
   - Click "Network Status"
   - Write down:
     - RSRP (e.g., -115)
     - RSRQ (e.g., -12)
     - Band (e.g., Band 78)
     - MCS (e.g., 26)

4. **Update config.yaml:**
   ```yaml
   ROUTER_GATEWAY: "192.168.1.1"
   ROUTER_USERNAME: "admin"
   ROUTER_PASSWORD: "admin"
   ```

5. **Run test:**
   ```powershell
   python qos_buddy_collector.py --choice 13 --duration 1
   ```

6. **Check data:**
   - Open `data/choice_13/qos_timeseries_*.csv`
   - Look for columns: `rsrp_dbm`, `rsrq_db`, `mcs`
   - If filled with numbers: ✅ Router connection working!
   - If empty: ⚠️ Try different username/password

---

## **Troubleshooting Matrix**

| Problem | Cause | Solution |
|---------|-------|----------|
| "Connection refused" | Wrong IP | Check default gateway with `ipconfig` |
| "Login failed" | Wrong credentials | Check router sticker or try defaults |
| "Timeout" | Router offline | Power cycle (unplug 30s, plug back) |
| "No cellular data in CSV" | API auth failed | Verify credentials in config.yaml |
| "Connection success but 0% metrics" | Router doesn't expose API | Use WiFi-only collection (it's fine!) |

---

## **Advanced: Manual API Testing**

If you want to test the API directly before running collection:

### **PowerShell Script to Test LuCI API:**

```powershell
$router = "192.168.1.1"
$username = "admin"
$password = "admin"

# Create credential object
$pair = "$($username):$($password)"
$bytes = [System.Text.Encoding]::ASCII.GetBytes($pair)
$base64 = [System.Convert]::ToBase64String($bytes)
$basicAuth = "Basic $base64"

# Test API endpoint
$headers = @{
    Authorization = $basicAuth
}

try {
    $response = Invoke-WebRequest `
        -Uri "http://$router/cgi-bin/luci/admin/status/get_band_info" `
        -Headers $headers `
        -SkipCertificateCheck `
        -TimeoutSec 5
    
    Write-Host "✅ API Response:"
    Write-Host $response.Content
} catch {
    Write-Host "❌ API Failed:"
    Write-Host $_.Exception.Message
}
```

If this returns JSON data, the API is working!

---

## **Summary for Your Friend**

Before running the tool, have them:

1. ✅ Find router IP (ping `route print`)
2. ✅ Access web interface (`http://192.168.1.1`)
3. ✅ Find login credentials (router sticker)
4. ✅ Locate signal metrics (System/Network/Status menu)
5. ✅ Update `config.yaml` with info
6. ✅ Run: `python qos_buddy_collector.py --choice 13 --duration 1`
7. ✅ Check CSV for `rsrp_dbm`, `rsrq_db` columns

If all columns filled = ✅ Success!
If columns empty = ⚠️ Router doesn't expose API (WiFi-only is fine)

---

**Questions?**

Common issues and solutions above. If stuck, check:
- Is router turned on?
- Can you access web interface manually?
- Are credentials correct?
- Is WiFi working?

If WiFi works but router API doesn't, **collection still works** - you just get WiFi metrics instead of cellular. No data is lost!

---

**Happy router exploring! 🌐**
