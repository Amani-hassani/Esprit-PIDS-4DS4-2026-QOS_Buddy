#!/usr/bin/env python3
"""
QoS Buddy - iperf3 Setup & Validation Tool
"""

import sys
import subprocess
import platform
import logging
import time

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def check_iperf3_installed() -> bool:
    """Check if iperf3 is installed"""
    try:
        result = subprocess.run(['iperf3', '--version'], 
                              capture_output=True, timeout=2)
        if result.returncode == 0:
            version = result.stdout.decode() if isinstance(result.stdout, bytes) else str(result.stdout)
            logger.info(f"iperf3 found: {version.strip()}")
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return False


def show_installation_instructions():
    """Show platform-specific installation instructions"""
    system = platform.system()
    
    logger.warning("\niperf3 is NOT installed. Please install it to use network scenarios:")
    logger.info("\n" + "="*60)
    
    if system == 'Windows':
        logger.info("WINDOWS INSTALLATION:")
        logger.info("-" * 60)
        logger.info("Option 1: Download from official site:")
        logger.info("  https://iperf.fr/iperf-download.php")
        logger.info("  → Download the .exe installer")
        logger.info("  → Run the installer")
        logger.info("  → Add iperf3 to PATH (installer may do this)")
        logger.info("")
        logger.info("Option 2: Using Chocolatey (if installed):")
        logger.info("  choco install iperf3")
        logger.info("")
        logger.info("Option 3: Using Windows Package Manager:")
        logger.info("  winget install iperf3")
        logger.info("")
        logger.info("Windows PATH verification:")
        logger.info("  After installation, open PowerShell and run:")
        logger.info("  iperf3 --version")
        logger.info("  This will verify the installation.")
    
    elif system == 'Darwin':  # macOS
        logger.info("macOS INSTALLATION:")
        logger.info("-" * 60)
        logger.info("Option 1: Using Homebrew (recommended):")
        logger.info("  brew install iperf3")
        logger.info("")
        logger.info("Option 2: Build from source:")
        logger.info("  https://github.com/esnet/iperf")
        logger.info("  Follow build instructions on GitHub")
    
    elif system == 'Linux':
        logger.info("LINUX INSTALLATION:")
        logger.info("-" * 60)
        logger.info("Ubuntu/Debian:")
        logger.info("  sudo apt-get update")
        logger.info("  sudo apt-get install iperf3")
        logger.info("")
        logger.info("Fedora/CentOS/RHEL:")
        logger.info("  sudo dnf install iperf3")
        logger.info("")
        logger.info("Arch Linux:")
        logger.info("  sudo pacman -S iperf3")
    
    logger.info("="*60)
    logger.info("\nAfter installation, verify with:")
    logger.info("  iperf3 --version")
    logger.info("")


def test_iperf3_server() -> bool:
    """Test if iperf3 server can start"""
    try:
        if platform.system() == 'Windows':
            proc = subprocess.Popen(
                'iperf3 -s -p 5201',
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=True
            )
            time.sleep(1)
            
            test_result = subprocess.run(
                ['iperf3', '-c', 'localhost', '-p', '5201', '-t', '1'],
                capture_output=True, timeout=5
            )
            
            subprocess.run(['taskkill', '/F', '/IM', 'iperf3.exe'],
                         capture_output=True, timeout=2)
            return test_result.returncode == 0
        else:  # Linux
            proc = subprocess.Popen(['iperf3', '-s', '-p', '5201', '-D'],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
            time.sleep(1)
            
            test_result = subprocess.run(
                ['iperf3', '-c', 'localhost', '-p', '5201', '-t', '1'],
                capture_output=True, timeout=5
            )
            
            proc.terminate()
            return test_result.returncode == 0
    except Exception as e:
        logger.debug(f"Server test failed: {str(e)}")
        return False


def main():
    """Main setup function"""
    logger.info("QoS Buddy - iperf3 Setup & Validation Tool")
    logger.info("=" * 60)
    logger.info("")
    
    # Check if iperf3 is installed
    logger.info("Checking iperf3 installation...")
    
    if check_iperf3_installed():
        logger.info("")
        logger.info("Testing iperf3 server startup...")
        
        if test_iperf3_server():
            logger.info("✓ iperf3 server can start and accept connections")
            logger.info("")
            logger.info("SUCCESS: iperf3 is ready for QoS Buddy scenarios!")
            logger.info("")
            logger.info("You can now run scenarios with:")
            logger.info("  python qos_buddy_collector.py --scenario congestion --duration 10")
            logger.info("  python qos_buddy_collector.py --scenario packet_loss --duration 10")
            logger.info("  python qos_buddy_collector.py --scenario throughput --duration 5")
            return 0
        else:
            logger.warning("✗ iperf3 is installed but server test failed")
            logger.warning("This might be a permissions or PATH issue")
            logger.info("\nTroubleshooting:")
            logger.info("  1. Verify PATH: 'iperf3 --version'")
            logger.info("  2. Check firewall settings")
            return 1
    else:
        show_installation_instructions()
        logger.info("\nAfter installing iperf3, run this script again to verify:")
        logger.info("  python setup_iperf3.py")
        return 1


if __name__ == '__main__':
    sys.exit(main())
