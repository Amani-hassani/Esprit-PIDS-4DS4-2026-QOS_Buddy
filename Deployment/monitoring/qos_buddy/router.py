"""
QoS Buddy - Network Data Acquisition Framework
Phase A: Real-World Data Collection with Automatic Anomaly Detection

Author: QoS Buddy Team
Version: 1.2
Date: 2026-03-17
"""

import json
import re
import subprocess
import socket
import urllib.request
import xml.etree.ElementTree as ET
import logging
from datetime import datetime
from typing import Dict, Optional


# ==================== IPERF3 BANDWIDTH TESTING ====================
from qos_buddy.config import TunisianNetworkConfig
from qos_buddy.net_utils import find_default_gateway

# Initialize logger
logger = logging.getLogger("QoSBuddy")


class RouterAPICollector:
    """
    Polls the 4G/5G router's web admin API for cellular radio metrics.

    Supported routers (auto-detected by probing known API endpoints):
      - Huawei B315 / B525 / B818 / E5186  → /api/device/signal  (XML)
      - ZTE MF / MC series                 → /goform/goform_get_cmd_process (JSON)
      - Others                             → graceful fallback, returns empty dict

    Provides (when available):
      rsrp_dbm, rsrq_db, sinr_db, pci, cell_id_router, network_type_router

    Usage:
      collector = RouterAPICollector(config)
      collector.detect_router()          # once at startup
      metrics = collector.get_signal_metrics()   # at each interval

    To set the router IP explicitly, add to config.yaml:
      router:
        gateway: '192.168.8.1'
        type: 'huawei'    # or 'zte', 'auto'
    """

    _HUAWEI_SIGNAL_API = '/api/device/signal'
    _HUAWEI_STATUS_API  = '/api/monitoring/status'
    _ZTE_STATUS_API     = '/goform/goform_get_cmd_process'

    def __init__(self, config: 'TunisianNetworkConfig' = None):  # type: ignore
        self.config = config or TunisianNetworkConfig()
        self.gateway: Optional[str]  = getattr(config, 'ROUTER_GATEWAY', None)
        self.router_type: str        = getattr(config, 'ROUTER_TYPE', 'auto')
        self.username: Optional[str] = getattr(config, 'ROUTER_USERNAME', None)
        self.password: Optional[str] = getattr(config, 'ROUTER_PASSWORD', None)
        self._available: bool        = False
        # Cache for Selenium metrics (avoid creating Chrome every 30 seconds)
        self._selenium_metrics_cache: Dict = {}
        self._selenium_metrics_timestamp: Optional[datetime] = None
        self._selenium_cache_ttl_seconds: int = 60  # Cache for 60 seconds
    
    def _get_auth_header(self) -> Optional[str]:
        """Generate HTTP Basic Auth header if username/password are set"""
        if self.username and self.password:
            import base64
            credentials = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            return f"Basic {credentials}"
        return None

    def detect_router(self) -> bool:
        """
        Auto-discover router gateway and identify its API type.
        Call once at startup. Returns True if a supported router is found.
        """
        if self.gateway is None:
            self.gateway = self._find_gateway()
        if self.gateway is None:
            # Interactive prompt if auto-detection fails
            try:
                user_gw = input("\n[?] Router gateway could not be auto-detected.\n[?] Please enter the router IP (e.g., 192.168.1.1) or press Enter to skip: ").strip()
                if user_gw:
                    self.gateway = user_gw
                else:
                    logger.info('RouterAPICollector: no gateway found, router API disabled')
                    return False
            except (EOFError, KeyboardInterrupt):
                logger.info('RouterAPICollector: no gateway found, router API disabled')
                return False

        # Try Huawei (most common for 4G routers in Tunisia: B315, B525, B818)
        try:
            url = f'http://{self.gateway}{self._HUAWEI_SIGNAL_API}'
            req = urllib.request.Request(
                url, headers={'Accept': 'application/xml', 'User-Agent': 'QoSBuddy/1.2'}
            )
            auth_header = self._get_auth_header()
            if auth_header:
                req.add_header('Authorization', auth_header)
            with urllib.request.urlopen(req, timeout=3) as resp:
                body = resp.read().decode('utf-8', errors='replace')
            if '<response>' in body.lower() or 'rsrp' in body.lower():
                self.router_type = 'huawei'
                self._available  = True
                logger.info(f'RouterAPICollector: Huawei router detected at {self.gateway}')
                return True
        except Exception:
            pass

        # Try ZTE
        try:
            # Try HTTPS first (most ZTE routers use HTTPS), fallback to HTTP
            url = (f'https://{self.gateway}{self._ZTE_STATUS_API}'
                   f'?isTest=false&cmd=network_type,rsrp&multi_data=1')
            req = urllib.request.Request(url)
            auth_header = self._get_auth_header()
            if auth_header:
                req.add_header('Authorization', auth_header)
            req.add_header('User-Agent', 'QoSBuddy/1.2')
            
            # Create SSL context to ignore self-signed certificates (local router)
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            with urllib.request.urlopen(req, timeout=3, context=ssl_context) as resp:
                body = resp.read().decode('utf-8', errors='replace')
            logger.debug(f'RouterAPICollector: ZTE HTTPS response (first 200 chars): {body[:200]}')
            if 'rsrp' in body.lower() or 'sinr' in body.lower():
                self.router_type = 'zte'
                self._available  = True
                logger.info(f'RouterAPICollector: ZTE router detected at {self.gateway}')
                return True
            else:
                logger.debug(f'RouterAPICollector: ZTE HTTPS response received but no rsrp/sinr markers found')
        except Exception as e:
            logger.debug(f'RouterAPICollector: ZTE HTTPS attempt failed: {e}')
            # Fallback to HTTP
            try:
                url = (f'http://{self.gateway}{self._ZTE_STATUS_API}'
                       f'?isTest=false&cmd=network_type,rsrp&multi_data=1')
                req = urllib.request.Request(url)
                auth_header = self._get_auth_header()
                if auth_header:
                    req.add_header('Authorization', auth_header)
                req.add_header('User-Agent', 'QoSBuddy/1.2')
                with urllib.request.urlopen(req, timeout=3) as resp:
                    body = resp.read().decode('utf-8', errors='replace')
                logger.debug(f'RouterAPICollector: ZTE HTTP response (first 200 chars): {body[:200]}')
                if 'rsrp' in body.lower() or 'sinr' in body.lower():
                    self.router_type = 'zte'
                    self._available  = True
                    logger.info(f'RouterAPICollector: ZTE router detected at {self.gateway}')
                    return True
                else:
                    logger.debug(f'RouterAPICollector: ZTE HTTP response received but no rsrp/sinr markers found')
            except Exception as e:
                logger.debug(f'RouterAPICollector: ZTE HTTP attempt failed: {e}')

        # Try LuCI / OpenWrt
        if self._try_luci_fallback():
            self.router_type = 'luci'
            self._available = True
            logger.info(f'RouterAPICollector: LuCI (OpenWrt) router detected at {self.gateway}')
            return True

        logger.info(
            f'RouterAPICollector: router at {self.gateway} does not expose a direct HTTP API '
            f'(uses JavaScript session authentication) — trying Selenium fallback'
        )
        
        # Try Selenium fallback for ZTE routers
        if self._try_selenium_fallback():
            self.router_type = 'zte_selenium'
            self._available = True
            logger.info(f'RouterAPICollector: ZTE router with Selenium fallback enabled at {self.gateway}')
            return True
        
        logger.info('RouterAPICollector: Selenium fallback unavailable or failed — router metrics will not be collected')
        return False

    def _try_luci_fallback(self) -> bool:
        """Check if router uses OpenWrt/LuCI framework."""
        try:
            import urllib.request, ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            # Broaden the detection URLs to catch the actual API endpoint directly
            probe_urls = [
                ('https', f'https://{self.gateway}/cgi-bin/luci/'),
                ('http',  f'http://{self.gateway}/cgi-bin/luci/'),
                ('https', f'https://{self.gateway}/cgi-bin/luci/admin/status/get_sim_detail'),
                ('http',  f'http://{self.gateway}/cgi-bin/luci/admin/status/get_sim_detail'),
            ]

            for scheme, url in probe_urls:
                try:
                    req = urllib.request.Request(url)
                    ctx = ssl_context if scheme == 'https' else None
                    with urllib.request.urlopen(req, timeout=3, context=ctx) as resp:
                        body = resp.read().decode('utf-8', errors='ignore')
                        # Any of these indicate LuCI/OpenWrt
                        if ('luci_username' in body or 'LuCI' in body or 'luci' in resp.geturl() or 
                            'sysauth' in body.lower() or 'cgi-bin/luci' in resp.geturl() or 
                            resp.getcode() == 200):
                            self._luci_scheme = scheme
                            return True
                except urllib.error.HTTPError as e:
                    # 403 Forbidden or 302 Found or 401 Unauthorized on a LuCI endpoint is a dead giveaway it exists
                    if e.code in [403, 401, 302, 404]:
                        self._luci_scheme = scheme
                        return True
                except Exception:
                    continue
                
            return False
        except Exception as e:
            logger.debug(f'LuCI check failed: {e}')
            return False

    def _try_selenium_fallback(self) -> bool:
        """Try to access ZTE router using Selenium browser automation"""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.chrome.options import Options
            from webdriver_manager.chrome import ChromeDriverManager
            import time
        except ImportError:
            logger.info('RouterAPICollector: Selenium/Chrome not available for ZTE router fallback')
            return False

        driver = None
        try:
            logger.info('RouterAPICollector: Attempting Selenium/Chrome fallback for ZTE router')
            
            # Setup headless Chrome
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--ignore-certificate-errors")
            chrome_options.add_argument("--ignore-ssl-errors")
            chrome_options.add_argument("--allow-running-insecure-content")

            # Get ChromeDriver path - webdriver-manager sometimes returns incorrect path, so fix it
            chromedriver_path = ChromeDriverManager().install()
            # If path ends with wrong file, replace it with the correct executable
            if not chromedriver_path.endswith('chromedriver.exe'):
                import os
                dir_path = os.path.dirname(chromedriver_path)
                chromedriver_path = os.path.join(dir_path, 'chromedriver.exe')
                logger.debug(f'RouterAPICollector: Fixed ChromeDriver path to {chromedriver_path}')
            
            service = Service(chromedriver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)

            # Quick test: try to access cellular info page
            logger.debug(f'RouterAPICollector: Selenium (testing access to {self.gateway})')
            driver.get(f"https://{self.gateway}/index.html#CELLULAR_INFO")
            time.sleep(2)
            
            # Check if we can access the page (should redirect to login if not authenticated)
            current_url = driver.current_url
            if "login.html" in current_url or "login" in current_url.lower():
                # Need authentication, try login
                logger.info('RouterAPICollector: Selenium (login required, attempting authentication)')
                return self._selenium_login_and_test(driver)
            elif "cgi-bin/luci" in current_url.lower() or "CELLULAR_INFO" in current_url:
                # Already authenticated or uses OpenWrt/LuCI framework
                logger.info(f'RouterAPICollector: Selenium (unauthenticated access or OpenWrt/LuCI framework detected at {current_url})')
                # For LuCI based routers, we must explicitly trigger the login process 
                # because the index implicitly requires authentication
                return self._selenium_login_and_test(driver)
            elif "index.html" in current_url:
                logger.info('RouterAPICollector: Selenium (index.html loaded)')
                return self._selenium_login_and_test(driver)
            else:
                logger.warning(f'RouterAPICollector: Selenium (unexpected URL: {current_url})')
                # Attempt login anyway, as router URLs vary wildly
                return self._selenium_login_and_test(driver)
                
        except KeyboardInterrupt:
            # User interrupted - suppress the error, just return False
            return False
        except Exception as e:
            logger.info(f'RouterAPICollector: Selenium fallback test failed → {type(e).__name__}: {str(e)[:100]}')
            return False
        finally:
            # Clean up ChromeDriver gracefully, suppressing cleanup errors
            if driver:
                try:
                    # Suppress KeyboardInterrupt and other exceptions during shutdown
                    driver.quit()
                except (KeyboardInterrupt, Exception):
                    # Shut down signal sent, WebDriver was killed — that's OK
                    pass

    def _selenium_login_and_test(self, driver) -> bool:
        """Perform login via Selenium and verify access to cellular metrics"""
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            import time

            # Navigate to login
            logger.debug(f'RouterAPICollector: Attempting to find login page for {self.gateway}')
            driver.get(f"http://{self.gateway}/")
            
            # Wait for form
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "username"))
                )
            except:
                pass
            time.sleep(1)

            # Enter credentials
            if self.username:
                username_field = None
                try:
                    username_field = driver.find_element(By.ID, "username")
                except:
                    try:
                        username_field = driver.find_element(By.NAME, "username")
                    except:
                        try:
                            username_field = driver.find_element(By.ID, "luci_username")
                        except:
                            try:
                                username_field = driver.find_element(By.CSS_SELECTOR, "input[type='text']")
                            except:
                                pass
                if username_field:
                    username_field.clear()
                    username_field.send_keys(self.username)
                    logger.info(f'RouterAPICollector: Selenium (Username entered)')

            if self.password:
                password_field = None
                try:
                    password_field = driver.find_element(By.ID, "passwd")
                except:
                    try:
                        password_field = driver.find_element(By.ID, "password")
                    except:
                        try:
                            password_field = driver.find_element(By.NAME, "password")
                        except:
                            try:
                                password_field = driver.find_element(By.ID, "luci_password")
                            except:
                                try:
                                    password_field = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
                                except:
                                    pass
                if password_field:
                    password_field.clear()
                    password_field.send_keys(self.password)
                    logger.info(f'RouterAPICollector: Selenium (Password entered)')

            # Click login
            login_button = None
            try:
                login_button = driver.find_element(By.ID, "btnLogin")
            except:
                try:
                    login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                except:
                    try:
                        login_button = driver.find_element(By.CSS_SELECTOR, "input[type='submit']")
                    except:
                        try:
                            login_button = driver.find_element(By.XPATH, "//button[contains(translate(text(), 'LOGIN', 'login'), 'log')]")
                        except:
                            pass
                            
            if login_button:
                login_button.click()
                logger.info(f'RouterAPICollector: Selenium (Login button clicked)')
            elif 'password_field' in locals() and password_field:
                from selenium.webdriver.common.keys import Keys
                password_field.send_keys(Keys.RETURN)
                logger.info(f'RouterAPICollector: Selenium (Pressed Enter key instead of clicking button)')

            # Wait for redirect
            time.sleep(3)
            current_url = driver.current_url
            logger.info(f'RouterAPICollector: Selenium (URL after login attempt: {current_url})')

            # Don't check for specific URL - just try to navigate to cellular info
            # Router might redirect to different URLs depending on model/firmware
                
            # Try to access status info (the new router uses "Status" instead of "CELLULAR_INFO")
            logger.debug(f'RouterAPICollector: Attempting to navigate to status page')
            paths_to_try = [
                f"http://{self.gateway}/",
                f"http://{self.gateway}/cgi-bin/luci/",
                f"http://{self.gateway}/index.html"
            ]
            
            for path in paths_to_try:
                driver.get(path)
                time.sleep(3)
                try:
                    driver.find_element(By.ID, "mStatus")
                    logger.debug(f'RouterAPICollector: Found mStatus on {path}')
                    break
                except:
                    continue

            try:
                # The screenshot shows the click event is attached to the parent div using onclick="showDetailInfo()"
                # and contains the text "Status" in a child div with class "title_text2" or id "mStatus"
                try:
                    status_div = driver.find_element(By.ID, "mStatus")
                    status_div.click()
                except:
                    # Fallback to evaluating the onclick directly if we can't click the element
                    driver.execute_script("showDetailInfo();")
            except Exception as e:
                logger.debug(f"RouterAPICollector: Could not trigger showDetailInfo() in test: {e}")
            
            # CRITICAL: Wait long enough for JavaScript to render content
            logger.debug('RouterAPICollector: Waiting for CELLULAR_INFO page to render...')
            
            # Try increasingly longer waits for JS to render metrics
            for attempt in range(3):
                time.sleep(5 + (attempt * 3))  # 5s, 8s, 11s
                body = driver.find_element(By.TAG_NAME, "body")
                page_text = body.text
                
                # Check if metrics are visible yet - use multiple indicators
                has_rsrp = "RSRP" in page_text or "rsrp" in page_text.lower()
                has_signal = "SINR" in page_text or "sinr" in page_text.lower() or "Signal" in page_text or "signal" in page_text.lower()
                has_rssi = "RSSI" in page_text or "rssi" in page_text.lower()
                has_cellular = "cellular" in page_text.lower() or "4g" in page_text.lower() or "lte" in page_text.lower() or "3g" in page_text.lower()
                
                # Success if we find ANY combination of cell metrics
                found_metrics = (has_rsrp and has_signal) or (has_rssi and has_cellular) or (
                    (has_rsrp or has_signal or has_rssi or has_cellular) and len(page_text) > 200
                )
                
                if found_metrics:
                    logger.debug(f'RouterAPICollector: Cellular metrics found on attempt {attempt + 1} (RSRP:{has_rsrp} SINR:{has_signal} RSSI:{has_rssi} Cellular:{has_cellular})')
                    break
                else:
                    logger.debug(f'RouterAPICollector: Metrics not ready yet (attempt {attempt + 1}/3), waiting more...')
            
            # Get final page content
            page_source = driver.page_source
            body = driver.find_element(By.TAG_NAME, "body")
            page_text = body.text
            
            logger.debug(f'RouterAPICollector: Page source length: {len(page_source)}, Body text length: {len(page_text)}')
            logger.debug(f'RouterAPICollector: Body text preview: {page_text[:500]}')
            
            # Check for cellular metrics - multiple indicators accepted (IMPROVED)
            has_rsrp = "RSRP" in page_text or "rsrp" in page_text.lower()
            has_signal = "SINR" in page_text or "sinr" in page_text.lower() or "Signal" in page_text or "signal" in page_text.lower()
            has_rssi = "RSSI" in page_text or "rssi" in page_text.lower()
            has_cellular = "cellular" in page_text.lower() or "4g" in page_text.lower() or "lte" in page_text.lower() or "3g" in page_text.lower() or "antenna" in page_text.lower()
            
            logger.debug(f'RouterAPICollector: Cellular content check - RSRP: {has_rsrp}, SINR: {has_signal}, RSSI: {has_rssi}, Cellular: {has_cellular}')
            
            # More lenient acceptance: any cellular indicator + reasonable page content = success (IMPROVED)
            if (has_rsrp and has_signal) or (has_rssi and has_cellular) or (
                (has_rsrp or has_signal or has_rssi or has_cellular) and len(page_text) > 200
            ):
                logger.info(f'RouterAPICollector: Selenium login successful (cellular metrics accessible)')
                return True
            elif len(page_text) > 300:
                # Page has substantial content - even without recognizable metric keywords
                # This might be a router with different UI but still functional
                logger.info(f'RouterAPICollector: Selenium login OK with substantial content ({len(page_text)} chars) - assuming metrics may be present')
                return True
            else:
                # Page barely loaded any content
                logger.warning(f'RouterAPICollector: Selenium login OK but page content minimal ({len(page_text)} chars)')
                return False

            logger.warning(f'RouterAPICollector: Selenium login failed (URL did not redirect to index.html)')
            return False

        except Exception as e:
            logger.warning(f'RouterAPICollector: Selenium login failed ({type(e).__name__}: {str(e)[:100]})')
            return False

    def get_signal_metrics(self) -> Dict:
        """
        Fetch cellular signal metrics from the router API.
        Returns dict with available keys; empty dict if unavailable.
        Possible keys: rsrp_dbm, rsrq_db, sinr_db, pci, cell_id_router, network_type_router
        """
        if not self._available:
            # If detection failed but we know router IP and type, try anyway for Selenium
            if self.router_type == 'zte_selenium':
                logger.debug(f'RouterAPICollector: Router marked unavailable but attempting Selenium extraction anyway')
                try:
                    metrics = self._get_zte_selenium_metrics()
                    if metrics:
                        logger.info(f'RouterAPICollector: Selenium extraction succeeded despite detection failure')
                        self._available = True  # Mark as available for future calls
                        return metrics
                except Exception as e:
                    logger.debug(f'RouterAPICollector: Fallback extraction attempt failed: {e}')
            return {}
        try:
            if self.router_type == 'huawei':
                return self._get_huawei_metrics()
            elif self.router_type == 'zte':
                return self._get_zte_metrics()
            elif self.router_type == 'luci':
                return self._get_luci_metrics()
            elif self.router_type == 'zte_selenium':
                return self._get_zte_selenium_metrics()
        except Exception as e:
            logger.debug(f'Router API fetch error: {e}')
        return {}

    def _get_huawei_metrics(self) -> Dict:
        """Fetch and parse Huawei router /api/device/signal XML response."""
        result = {}
        try:
            url = f'http://{self.gateway}{self._HUAWEI_SIGNAL_API}'
            req = urllib.request.Request(url)
            auth_header = self._get_auth_header()
            if auth_header:
                req.add_header('Authorization', auth_header)
            req.add_header('User-Agent', 'QoSBuddy/1.2')
            
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode('utf-8', errors='replace')
            root = ET.fromstring(body)

            def _val(tag: str) -> Optional[str]:
                el = root.find(tag)
                return el.text.strip() if el is not None and el.text else None

            conversions = [
                ('rsrp',    'rsrp_dbm',           int),
                ('rsrq',    'rsrq_db',             int),
                ('sinr',    'sinr_db',             float),
                ('pci',     'pci',                 int),
                ('cell_id', 'cell_id_router',      str),
                ('band',    'network_type_router', str),
            ]
            for xml_tag, field, cast in conversions:
                raw = _val(xml_tag)
                if raw:
                    try:
                        result[field] = cast(raw)
                    except (ValueError, TypeError):
                        pass
        except ET.ParseError as e:
            logger.debug(f'Huawei XML parse error: {e}')
        except Exception as e:
            logger.debug(f'Huawei API error: {e}')
        return result

    def _get_zte_metrics(self) -> Dict:
        """Fetch and parse ZTE router goform JSON response."""
        result = {}
        try:
            # Try HTTPS first (most ZTE routers use HTTPS), fallback to HTTP
            url = (f'https://{self.gateway}{self._ZTE_STATUS_API}'
                   f'?isTest=false&cmd=lte_ca_pcell_info,network_type,'
                   f'rsrp,rsrq,sinr,lte_pci&multi_data=1')
            req = urllib.request.Request(url)
            auth_header = self._get_auth_header()
            if auth_header:
                req.add_header('Authorization', auth_header)
            req.add_header('User-Agent', 'QoSBuddy/1.2')
            
            # Create SSL context to ignore self-signed certificates (local router)
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            with urllib.request.urlopen(req, timeout=5, context=ssl_context) as resp:
                body = resp.read().decode('utf-8', errors='replace')
            data = json.loads(body)

            conversions = [
                ('rsrp',         'rsrp_dbm',           int),
                ('rsrq',         'rsrq_db',             int),
                ('sinr',         'sinr_db',             float),
                ('lte_pci',      'pci',                 int),
                ('network_type', 'network_type_router', str),
            ]
            for json_key, field, cast in conversions:
                if json_key in data:
                    try:
                        result[field] = cast(data[json_key])
                    except (ValueError, TypeError):
                        pass
        except (json.JSONDecodeError, Exception) as e:
            # Fallback to HTTP if HTTPS fails
            try:
                url = (f'http://{self.gateway}{self._ZTE_STATUS_API}'
                       f'?isTest=false&cmd=lte_ca_pcell_info,network_type,'
                       f'rsrp,rsrq,sinr,lte_pci&multi_data=1')
                req = urllib.request.Request(url)
                auth_header = self._get_auth_header()
                if auth_header:
                    req.add_header('Authorization', auth_header)
                req.add_header('User-Agent', 'QoSBuddy/1.2')
                
                with urllib.request.urlopen(req, timeout=5) as resp:
                    body = resp.read().decode('utf-8', errors='replace')
                data = json.loads(body)

                conversions = [
                    ('rsrp',         'rsrp_dbm',           int),
                    ('rsrq',         'rsrq_db',             int),
                    ('sinr',         'sinr_db',             float),
                    ('lte_pci',      'pci',                 int),
                    ('network_type', 'network_type_router', str),
                ]
                for json_key, field, cast in conversions:
                    if json_key in data:
                        try:
                            result[field] = cast(data[json_key])
                        except (ValueError, TypeError):
                            pass
            except (json.JSONDecodeError, Exception) as e2:
                logger.debug(f'ZTE API error (HTTPS + HTTP tried): {e2}')
        return result

    def _get_luci_metrics(self) -> Dict:
        """Fetch metrics directly via LuCI API (OpenWrt) with proper session authentication."""
        result = {}
        try:
            import urllib.request, urllib.parse, ssl, json, time, re
            import http.cookiejar
            
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            scheme = getattr(self, '_luci_scheme', 'https')
            
            # Create persistent cookie jar for session management
            cj = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(cj),
                urllib.request.HTTPSHandler(context=ssl_context),
                urllib.request.HTTPHandler()
            )
            
            logger.debug(f'RouterAPICollector: LuCI authentication starting at {scheme}://{self.gateway}')
            
            # Step 1: POST login with credentials
            login_url = f'{scheme}://{self.gateway}/cgi-bin/luci/'
            login_data = urllib.parse.urlencode({
                'luci_username': self.username or 'admin',
                'luci_password': self.password or ''
            }).encode('utf-8')
            
            req_login = urllib.request.Request(login_url, data=login_data, method='POST')
            req_login.add_header('Content-Type', 'application/x-www-form-urlencoded')
            req_login.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
            
            try:
                with opener.open(req_login, timeout=5) as resp:
                    login_response = resp.read().decode('utf-8', errors='ignore')
                logger.debug(f'RouterAPICollector: LuCI login POST successful (HTTP {resp.getcode()})')
            except urllib.error.HTTPError as e:
                # 302 redirect or 403 are expected after login attempt
                logger.debug(f'RouterAPICollector: LuCI login returned HTTP {e.code} (expected for redirect)')
                login_response = e.read().decode('utf-8', errors='ignore') if hasattr(e, 'read') else ''
            except Exception as e:
                logger.debug(f'RouterAPICollector: LuCI login failed: {e}')
                login_response = ''
            
            # Step 2: Check for sysauth cookie in jar
            sysauth = None
            for cookie in cj:
                logger.debug(f'RouterAPICollector: Cookie found: {cookie.name}={str(cookie.value)[:20]}...')
                if 'sysauth' in cookie.name.lower():
                    sysauth = cookie.value
                    logger.info(f'RouterAPICollector: Captured sysauth token from login')
                    break
            
            timestamp = int(time.time() * 1000)
            
            # Step 3: Try band_info endpoint (for MCS data)
            band_info_url = f'{scheme}://{self.gateway}/cgi-bin/luci/admin/status/get_band_info?{timestamp}'
            req_band = urllib.request.Request(band_info_url)
            req_band.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
            req_band.add_header('Accept', '*/*')
            if sysauth:
                req_band.add_header('Cookie', f'sysauth={sysauth}')
            
            try:
                logger.debug(f'RouterAPICollector: Requesting {band_info_url}')
                with opener.open(req_band, timeout=5) as resp:
                    band_body = resp.read().decode('utf-8', errors='ignore')
                    logger.debug(f'RouterAPICollector: band_info response (HTTP {resp.getcode()}): {band_body[:200]}')
                band_data = json.loads(band_body)
                logger.info(f'RouterAPICollector: band_info success: {band_data}')
                result.update(band_data)
            except Exception as e:
                logger.debug(f'RouterAPICollector: band_info failed: {e}')
            
            # Step 4: Try sim_detail endpoint (for signal metrics)
            sim_detail_url = f'{scheme}://{self.gateway}/cgi-bin/luci/admin/status/get_sim_detail?status=1&{timestamp}'
            req_sim = urllib.request.Request(sim_detail_url)
            req_sim.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
            req_sim.add_header('Accept', '*/*')
            if sysauth:
                req_sim.add_header('Cookie', f'sysauth={sysauth}')
            
            try:
                logger.debug(f'RouterAPICollector: Requesting {sim_detail_url}')
                with opener.open(req_sim, timeout=5) as resp:
                    sim_body = resp.read().decode('utf-8', errors='ignore')
                    logger.debug(f'RouterAPICollector: sim_detail response (HTTP {resp.getcode()}): {sim_body[:200]}')
                sim_data = json.loads(sim_body)
                logger.info(f'RouterAPICollector: sim_detail success: {sim_data}')
                result.update(sim_data)
                
                # Parse nested internet_info JSON string if present
                if 'internet_info' in sim_data and isinstance(sim_data['internet_info'], str):
                    try:
                        internet_data = json.loads(sim_data['internet_info'])
                        result.update(internet_data)
                        logger.debug(f'RouterAPICollector: Parsed internet_info: {internet_data}')
                    except (json.JSONDecodeError, Exception) as parse_err:
                        logger.debug(f'RouterAPICollector: Could not parse internet_info JSON: {parse_err}')
            except Exception as e:
                logger.debug(f'RouterAPICollector: sim_detail failed: {e}')
            
            if not result:
                logger.debug(f'RouterAPICollector: No LuCI API data retrieved after authentication attempts')
                return {}
            
            # Parse the aggregated results
            # Search for variations of keys since different themes name them differently
            flat_data = {}
            def flatten_dict(d):
                if isinstance(d, dict):
                    for k, v in d.items():
                        if isinstance(v, (dict, list)): flatten_dict(v)
                        else: flat_data[str(k).lower()] = v
                elif isinstance(d, list):
                    for item in d: flatten_dict(item)
                    
            flatten_dict(result)
            
            def _extract_num(val):
                if val is None: return None
                if isinstance(val, (int, float)): return val
                m = re.search(r'-?\d+(\.\d+)?', str(val).replace(',', '.'))
                return float(m.group(0)) if m else None

            for k in ['rsrp', 'rsrp_value', 'rsrp0']:
                if k in flat_data and (num := _extract_num(flat_data[k])) is not None:
                    result['rsrp_dbm'] = int(num)
                    break
                    
            for k in ['rssi', 'rssi_value']:
                if k in flat_data and (num := _extract_num(flat_data[k])) is not None:
                    result['rssi_dbm'] = int(num)
                    break
                    
            for k in ['rsrq', 'rsrq_value', 'rsrq0']:
                if k in flat_data and (num := _extract_num(flat_data[k])) is not None:
                    result['rsrq_db'] = int(num)
                    break
                    
            for k in ['sinr', 'sinr_value']:
                if k in flat_data and (num := _extract_num(flat_data[k])) is not None:
                    result['sinr_db'] = float(num)
                    break
                    
            for k in ['pci', 'phycellid']:
                if k in flat_data and (num := _extract_num(flat_data[k])) is not None:
                    result['pci'] = int(num)
                    break
                    
            for k in ['cell_id', 'cellid', 'cid']:
                if k in flat_data and flat_data[k]:
                    val = str(flat_data[k]).strip()
                    if val != '0' and val:
                        result['cell_id_router'] = val
                        break
                        
            for k in ['enodeb_id', 'enodeb', 'enodebid']:
                if k in flat_data and flat_data[k]:
                    val = str(flat_data[k]).strip()
                    if val != '0' and val:
                        result['enodeb_id'] = val
                        break
                        
            for k in ['earfcn', 'arfcn(5g)', 'arfcn(4g)', 'arfcn5g', 'arfcn4g']:
                if k in flat_data and (num := _extract_num(flat_data[k])) is not None:
                    result['earfcn'] = int(num)
                    break
                    
            for k in ['dlmcs', 'ulmcs', 'mcs', 'ul mcs', 'dl mcs', 'ul_mcs', 'dl_mcs']:
                if k in flat_data and (num := _extract_num(flat_data[k])) is not None:
                    # Prefer uplink MCS if available (more relevant for upload quality)
                    if 'ulmcs' in flat_data and (num_ul := _extract_num(flat_data['ulmcs'])) is not None:
                        result['mcs'] = int(num_ul)
                        logger.info(f'RouterAPICollector: LuCI extracted uplink MCS={result["mcs"]} from ulMcs')
                    else:
                        result['mcs'] = int(num)
                        logger.info(f'RouterAPICollector: LuCI extracted MCS={result["mcs"]}')
                    break
                    
            for k in ['cqi', 'cqi0']:
                if k in flat_data and (num := _extract_num(flat_data[k])) is not None:
                    result['cqi'] = int(num)
                    break

            for k in ['network_type', 'networktype', 'mode', 'sys_mode', 'network_provider']:
                if k in flat_data:
                    val = str(flat_data[k]).upper()
                    if '5G' in val: result['network_type_router'] = '5G'
                    elif '4G' in val or 'LTE' in val: result['network_type_router'] = '4G'
                    elif '3G' in val or 'WCDMA' in val: result['network_type_router'] = '3G'
                    
        except Exception as e:
            logger.debug(f'LuCI API Data parse error: {e}')
            
        return result

    def _get_zte_selenium_metrics(self) -> Dict:
        """Fetch ZTE router metrics using Selenium browser automation for JavaScript-rendered pages.
        
        CACHING: Avoids creating Chrome browser every collection cycle. 
        Metrics cached for 60 seconds to prevent resource exhaustion.
        """
        # Check cache first — avoid spawning Chrome every 30 seconds
        if (self._selenium_metrics_timestamp is not None and 
            (datetime.now() - self._selenium_metrics_timestamp).total_seconds() < self._selenium_cache_ttl_seconds):
            logger.debug(f'RouterAPICollector: Using cached Selenium metrics (age < {self._selenium_cache_ttl_seconds}s)')
            return self._selenium_metrics_cache
        
        result = {}
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from webdriver_manager.chrome import ChromeDriverManager
            import time
            import re
        except ImportError:
            logger.debug('Selenium not available for Selenium metrics extraction')
            return {}

        driver = None
        try:
            logger.debug(f'RouterAPICollector: Selenium metrics extraction starting for {self.gateway}')
            
            # Setup Chrome
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--ignore-certificate-errors")
            chrome_options.add_argument("--ignore-ssl-errors")
            chrome_options.add_argument("--allow-running-insecure-content")

            # Get ChromeDriver path - webdriver-manager sometimes returns incorrect path, so fix it
            chromedriver_path = ChromeDriverManager().install()
            # If path ends with wrong file, replace it with the correct executable
            if not chromedriver_path.endswith('chromedriver.exe'):
                import os
                dir_path = os.path.dirname(chromedriver_path)
                chromedriver_path = os.path.join(dir_path, 'chromedriver.exe')
                logger.debug(f'RouterAPICollector: Fixed ChromeDriver path to {chromedriver_path}')
            
            service = Service(chromedriver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)

            # Login if we have credentials
            if self.username and self.password:
                logger.debug(f'RouterAPICollector: Selenium attempting login with credentials')
                driver.get(f"https://{self.gateway}/login.html")
                time.sleep(3)
                
                try:
                    from selenium.webdriver.support.ui import WebDriverWait
                    from selenium.webdriver.support import expected_conditions as EC
                    from selenium.webdriver.common.keys import Keys
                    
                    # Try to find username field with multiple strategies
                    username_field = None
                    try:
                        username_field = WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.ID, "username"))
                        )
                        logger.debug('RouterAPICollector: Found username field by ID')
                    except:
                        try:
                            username_field = driver.find_element(By.NAME, "username")
                            logger.debug('RouterAPICollector: Found username field by name')
                        except:
                            try:
                                username_field = driver.find_element(By.CSS_SELECTOR, "input[type='text']")
                                logger.debug('RouterAPICollector: Found username field by CSS text input')
                            except:
                                logger.debug('RouterAPICollector: Could not find username field')
                                raise Exception("Username field not found")
                    
                    username_field.clear()
                    username_field.send_keys(self.username)
                    time.sleep(1)
                    
                    # Find password field
                    password_field = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
                    password_field.clear()
                    password_field.send_keys(self.password)
                    time.sleep(1)
                    
                    # Try to find and click login button - multiple strategies
                    login_btn = None
                    try:
                        login_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                        logger.debug('RouterAPICollector: Found submit button')
                    except:
                        try:
                            login_btn = driver.find_element(By.CSS_SELECTOR, "button")
                            logger.debug('RouterAPICollector: Found generic button')
                        except:
                            try:
                                login_btn = driver.find_element(By.ID, "login_btn")
                                logger.debug('RouterAPICollector: Found login_btn element')
                            except:
                                logger.debug('RouterAPICollector: Could not find login button')
                    
                    if login_btn:
                        # Wait for button to be clickable
                        WebDriverWait(driver, 5).until(EC.element_to_be_clickable(login_btn))
                        login_btn.click()
                        logger.debug('RouterAPICollector: Login button clicked')
                    else:
                        # Try pressing Enter on password field
                        password_field.send_keys(Keys.RETURN)
                        logger.debug('RouterAPICollector: Pressed Enter on password field')
                    
                    # Wait for page to load after login
                    time.sleep(5)
                    current_url = driver.current_url
                    logger.debug(f'RouterAPICollector: URL after login attempt: {current_url}')
                    
                except Exception as e:
                    logger.debug(f'RouterAPICollector: Selenium login attempt failed: {e}')
                    # Continue anyway - page might be accessible without auth

            # Navigate to cellular info page
            logger.debug(f'RouterAPICollector: Selenium navigating after login')
            
            # Instead of forcing index.html, let's just go to the root and let the router redirect
            # Also try common dashboard paths if root fails
            paths_to_try = [
                f"http://{self.gateway}/",
                f"http://{self.gateway}/cgi-bin/luci/",
                f"http://{self.gateway}/index.html"
            ]
            
            for path in paths_to_try:
                driver.get(path)
                time.sleep(3)
                logger.debug(f'RouterAPICollector: Loaded {path}, current URL is {driver.current_url}')
                try:
                    # Check if mStatus exists on this page
                    driver.find_element(By.ID, "mStatus")
                    logger.info('RouterAPICollector: Found mStatus element on this page.')
                    break
                except:
                    continue
            
            # Click on "Status" link to get to cellular metrics
            logger.info('RouterAPICollector: Activating showDetailInfo() to reveal Status popup metrics')
            try:
                # The div containing the Status image has onclick="showDetailInfo()"
                # Try clicking the ID explicitly, or fire the script tag
                try:
                    driver.find_element(By.ID, "mStatus").click()
                except:
                    driver.execute_script("showDetailInfo();")
                    
                time.sleep(4)  # Wait for modal overlay to load
            except Exception as e:
                logger.warning(f'RouterAPICollector: Could not invoke Status logic: {e}')
            
            # Wait for JavaScript to render
            time.sleep(3)
            logger.debug('RouterAPICollector: Waiting for table/content to render...')
            
            # Get page source and body text
            page_source = driver.page_source
            try:
                body = driver.find_element(By.TAG_NAME, "body")
                page_text = body.text
            except:
                page_text = ""
            
            current_url = driver.current_url
            page_title = driver.title
            
            logger.debug(f'RouterAPICollector: Current URL: {current_url}')
            logger.debug(f'RouterAPICollector: Page title: {page_title}')
            logger.info(f'RouterAPICollector: Page source length: {len(page_source)} chars, Page text length: {len(page_text)} chars')
            
            # Log full page text for debugging
            logger.info(f'RouterAPICollector: === FULL PAGE TEXT ({len(page_text)} chars) ===\n{page_text}\n=== END PAGE TEXT ===')
            
            # Parse cellular metrics from page text
            logger.info(f'RouterAPICollector: Starting metric extraction')
            
            # Direct regex search for metrics in the entire page text
            logger.info(f'RouterAPICollector: Attempting direct regex extraction')
            
            # Clean text by removing things inside parentheses (like range clues: "(-114 ~ -44)") so we don't accidentally extract them instead of the values
            clean_text = re.sub(r'\([^)]+\)', '', page_text)
            
            # RSRP: Look for RSRP followed by an optional colon/space, then a negative number
            rsrp_match = re.search(r'RSRP[^\d-]+(-?\d+)', clean_text, re.IGNORECASE)
            if rsrp_match:
                result['rsrp_dbm'] = int(rsrp_match.group(1))
                logger.info(f'RouterAPICollector: Regex found rsrp_dbm={result["rsrp_dbm"]}')
            
            # RSSI
            rssi_match = re.search(r'RSSI[^\d-]+(-?\d+)', clean_text, re.IGNORECASE)
            if rssi_match and 'rssi_dbm' not in result:
                result['rssi_dbm'] = int(rssi_match.group(1))
                logger.info(f'RouterAPICollector: Direct regex found rssi_dbm={result["rssi_dbm"]}')
            
            # RSRQ
            rsrq_match = re.search(r'RSRQ[^\d-]+(-?\d+)', clean_text, re.IGNORECASE)
            if rsrq_match:
                result['rsrq_db'] = int(rsrq_match.group(1))
                logger.info(f'RouterAPICollector: Direct regex found rsrq_db={result["rsrq_db"]}')
            
            # SINR
            sinr_match = re.search(r'SINR[^\d-]+(-?\d+)', clean_text, re.IGNORECASE)
            if sinr_match:
                result['sinr_db'] = int(sinr_match.group(1))
                logger.info(f'RouterAPICollector: Direct regex found sinr_db={result["sinr_db"]}')
            
            # PCI
            pci_match = re.search(r'PCI[^\d]+(\d+)', clean_text, re.IGNORECASE)
            if pci_match:
                result['pci'] = int(pci_match.group(1))
                logger.info(f'RouterAPICollector: Direct regex found pci={result["pci"]}')
            
            # EARFCN
            earfcn_match = re.search(r'EARFCN[^\d]+(\d+)', clean_text, re.IGNORECASE)
            if earfcn_match:
                result['earfcn'] = int(earfcn_match.group(1))
                logger.info(f'RouterAPICollector: Direct regex found earfcn={result["earfcn"]}')
            
            # EnodeB ID
            enodeb_match = re.search(r'(?:EnodeB ID|eNodeB)[^\w]+([A-F0-9]+)', clean_text, re.IGNORECASE)
            if enodeb_match:
                result['enodeb_id'] = enodeb_match.group(1)
                logger.info(f'RouterAPICollector: Direct regex found enodeb_id={result["enodeb_id"]}')
            
            # Cell ID
            cell_match = re.search(r'(?:Cell ID|ID de cellule)[^\w]+([A-F0-9]+)', clean_text, re.IGNORECASE)
            if cell_match:
                result['cell_id_router'] = cell_match.group(1)
                logger.info(f'RouterAPICollector: Direct regex found cell_id_router={result["cell_id_router"]}')
            
            # CQI
            cqi_match = re.search(r'CQI[^\d]+(\d+)', clean_text, re.IGNORECASE)
            if cqi_match:
                result['cqi'] = int(cqi_match.group(1))
                logger.info(f'RouterAPICollector: Direct regex found cqi={result["cqi"]}')
            
            # MCS
            mcs_match = re.search(r'MCS[^\d]+(\d+)', clean_text, re.IGNORECASE)
            if mcs_match:
                result['mcs'] = int(mcs_match.group(1))
                logger.info(f'RouterAPICollector: Direct regex found mcs={result["mcs"]}')
            
            # Network type
            mode_match = re.search(r'(5G|4G|LTE|3G)', clean_text, re.IGNORECASE)
            if mode_match:
                result['network_type_router'] = mode_match.group(1).upper()
                logger.info(f'RouterAPICollector: Direct regex found network_type_router={result["network_type_router"]}')
            
            logger.info(f'RouterAPICollector: Direct regex extraction found {len(result)} metrics')
            
            # If no regex metrics found, try fallback extraction methods
            if not result:
                logger.warning(f'RouterAPICollector: No regex metrics found, trying fallback methods')
                
                # Fallback 1: Try HTML table extraction (most reliable for this format)
                logger.info(f'RouterAPICollector: Attempting HTML table extraction')
                try:
                    tables = driver.find_elements(By.TAG_NAME, "table")
                    logger.info(f'RouterAPICollector: Found {len(tables)} HTML tables on page')
                    
                    for table_idx, table in enumerate(tables):
                        try:
                            rows = table.find_elements(By.TAG_NAME, "tr")
                            logger.debug(f'RouterAPICollector: Table {table_idx} has {len(rows)} rows')
                            
                            for row_idx, row in enumerate(rows):
                                cells = row.find_elements(By.TAG_NAME, "td")
                                if len(cells) >= 2:
                                    label = cells[0].text.strip()
                                    value = cells[1].text.strip() if len(cells) > 1 else ''
                                    
                                    logger.debug(f'RouterAPICollector: Table {table_idx} Row {row_idx}: "{label}" = "{value}"')
                                    
                                    # Match labels to metrics
                                    if 'RSRP' in label.upper():
                                        match = re.search(r'-?\d+', value)
                                        if match:
                                            result['rsrp_dbm'] = int(match.group(0))
                                            logger.info(f'RouterAPICollector: Table extracted rsrp_dbm={result["rsrp_dbm"]}')
                                    elif 'RSSI' in label.upper() and 'RSRP' not in label.upper():
                                        match = re.search(r'-?\d+', value)
                                        if match:
                                            result['rssi_dbm'] = int(match.group(0))
                                            logger.info(f'RouterAPICollector: Table extracted rssi_dbm={result["rssi_dbm"]}')
                                    elif 'RSRQ' in label.upper():
                                        match = re.search(r'-?\d+', value)
                                        if match:
                                            result['rsrq_db'] = int(match.group(0))
                                            logger.info(f'RouterAPICollector: Table extracted rsrq_db={result["rsrq_db"]}')
                                    elif 'SINR' in label.upper():
                                        match = re.search(r'-?\d+', value)
                                        if match:
                                            result['sinr_db'] = int(match.group(0))
                                            logger.info(f'RouterAPICollector: Table extracted sinr_db={result["sinr_db"]}')
                                    elif 'PCI' in label.upper():
                                        match = re.search(r'\d+', value)
                                        if match:
                                            result['pci'] = int(match.group(0))
                                            logger.info(f'RouterAPICollector: Table extracted pci={result["pci"]}')
                                    elif 'EARFCN' in label.upper():
                                        match = re.search(r'\d+', value)
                                        if match:
                                            result['earfcn'] = int(match.group(0))
                                            logger.info(f'RouterAPICollector: Table extracted earfcn={result["earfcn"]}')
                                    elif 'EnodeB' in label or 'eNodeB' in label:
                                        match = re.search(r'[A-F0-9]+', value)
                                        if match:
                                            result['enodeb_id'] = match.group(0)
                                            logger.info(f'RouterAPICollector: Table extracted enodeb_id={result["enodeb_id"]}')
                                    elif 'cellule' in label.lower() or ('Cell' in label and 'ID' in label.upper()):
                                        match = re.search(r'[A-F0-9]+', value)
                                        if match:
                                            result['cell_id_router'] = match.group(0)
                                            logger.info(f'RouterAPICollector: Table extracted cell_id_router={result["cell_id_router"]}')
                                    elif 'CQI' in label.upper():
                                        match = re.search(r'\d+', value)
                                        if match:
                                            result['cqi'] = int(match.group(0))
                                            logger.info(f'RouterAPICollector: Table extracted cqi={result["cqi"]}')
                                    elif 'MCS' in label.upper():
                                        match = re.search(r'\d+', value)
                                        if match:
                                            result['mcs'] = int(match.group(0))
                                            logger.info(f'RouterAPICollector: Table extracted mcs={result["mcs"]}')
                                    elif 'Mode réseau' in label or 'Network' in label.upper():
                                        for net_type in ['5G', '4G', '3G', 'LTE']:
                                            if net_type in value.upper():
                                                result['network_type_router'] = net_type
                                                logger.info(f'RouterAPICollector: Table extracted network_type_router={net_type}')
                                                break
                        except Exception as row_error:
                            logger.debug(f'RouterAPICollector: Error processing table {table_idx}: {row_error}')
                    
                    if result:
                        logger.info(f'RouterAPICollector: HTML table extraction recovered {len(result)} metrics')
                except Exception as table_error:
                    logger.warning(f'RouterAPICollector: HTML table extraction failed: {table_error}')
            
            logger.info(f'RouterAPICollector: Final result - extracted {len(result)} router metrics: {list(result.keys())}')
            # Cache successful results
            if result:
                self._selenium_metrics_cache = result
                self._selenium_metrics_timestamp = datetime.now()
                logger.debug(f'RouterAPICollector: Selenium metrics cached (valid for {self._selenium_cache_ttl_seconds}s)')
            return result
            
        except Exception as e:
            logger.warning(f'RouterAPICollector: Selenium metrics extraction error: {type(e).__name__}: {str(e)[:200]}', exc_info=False)
            return {}
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass

    def _find_gateway(self) -> Optional[str]:
        """Resolve the default IPv4 gateway via the cross-platform helper."""
        return find_default_gateway()


