import paramiko
import requests
import time
import threading
import os
from dotenv import load_dotenv

# -------------------- Configuration --------------------
load_dotenv()  # Load environment variables from .env

VPS_NAMES = os.getenv("VPS_NAMES").split(",")  # Server names from .env
VPS_IPS = os.getenv("VPS_IPS").split(",")  # IPs from .env
VPS_USERS = os.getenv("VPS_USERS").split(",")
VPS_PASSWORDS = os.getenv("VPS_PASSWORDS").split(",")
DELAY = int(os.getenv("DELAY", 5))  # Delay from .env, default to 5
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

msg_ids = {}  # Store message IDs per VPS

# ANSI Colors
RESET = "\033[0m"
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BLUE = "\033[34m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"  # Pink color

OWNER_NAME = f"{MAGENTA}Server Monitor by Chalana{RESET}"

# -------------------- Utility Functions --------------------
def ssh_run_command(vps_ip, user, password, command):
    """Runs a command on the VPS via SSH and returns the output."""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(vps_ip, username=user, password=password)
        stdin, stdout, stderr = ssh.exec_command(command)
        output = stdout.read().decode().strip()
        ssh.close()
        return output
    except Exception as e:
        print(f"{RED}SSH Error on {vps_ip}: {e}{RESET}")
        return None

def generate_colored_bar(percent):
    """Generates a progress bar with dynamic colors based on usage."""
    color = GREEN if percent < 50 else YELLOW if percent < 75 else RED
    filled_length = int(20 * percent // 100)
    bar = '█' * filled_length + '░' * (20 - filled_length)
    return f"{color}[{bar}] {percent:.2f}%{RESET}"

def fetch_network_speed(vps_ip, user, password, interface="eth0"):
    """Fetches real-time network download and upload speeds."""
    command = f"ifstat -i {interface} 1 1 | tail -n 1"
    speed_output = ssh_run_command(vps_ip, user, password, command)
    if speed_output:
        try:
            download, upload = map(float, speed_output.split()[:2])
            download_bps, upload_bps = download * 8, upload * 8

            def format_speed(speed_bps):
                if speed_bps >= 1_000_000:
                    return f"{speed_bps / 1_000_000:.2f} Gbps"
                elif speed_bps >= 1_000:
                    return f"{speed_bps / 1_000:.2f} Mbps"
                return f"{speed_bps:.2f} Kbps"

            return format_speed(download_bps), format_speed(upload_bps)
        except ValueError:
            return "N/A", "N/A"
    return "N/A", "N/A"

def fetch_total_network_usage(vps_ip, user, password, interface="eth0"):
    """Fetches all-time total IN and OUT traffic from the system."""
    rx_command = f"cat /sys/class/net/{interface}/statistics/rx_bytes"
    tx_command = f"cat /sys/class/net/{interface}/statistics/tx_bytes"
    
    rx_bytes = ssh_run_command(vps_ip, user, password, rx_command)
    tx_bytes = ssh_run_command(vps_ip, user, password, tx_command)

    try:
        total_rx_mb = int(rx_bytes) / (1024 * 1024)  # Convert bytes to MB
        total_tx_mb = int(tx_bytes) / (1024 * 1024)
        return f"{total_rx_mb:.2f} MB", f"{total_tx_mb:.2f} MB"
    except (ValueError, TypeError):
        return "N/A", "N/A"

# -------------------- Get Server Status --------------------
def get_server_status(server_name, vps_ip, user, password):
    """Fetches and formats system stats for the specified VPS."""
    os_info = ssh_run_command(vps_ip, user, password, "uname -sr")
    uptime = ssh_run_command(vps_ip, user, password, "uptime -p")
    cpu_cores = ssh_run_command(vps_ip, user, password, "nproc")

    # CPU Usage
    cpu_usage_str = ssh_run_command(vps_ip, user, password, "top -bn1 | grep 'Cpu(s)'")
    cpu_usage = 0.0
    if cpu_usage_str:
        try:
            idle_percent = float(cpu_usage_str.split(",")[3].split()[0])
            cpu_usage = 100 - idle_percent
        except (IndexError, ValueError) as e:
            print(f"{RED}CPU Usage Parsing Error: {e}{RESET}")
    cpu_bar = generate_colored_bar(cpu_usage)

    # RAM Usage
    ram_output = ssh_run_command(vps_ip, user, password, "free -m | awk 'NR==2{printf \"%d %d\", $3, $2}'")
    ram_used, ram_total = map(int, ram_output.split())
    ram_bar = generate_colored_bar((ram_used / ram_total) * 100)

    # Disk Usage
    disk_output = ssh_run_command(vps_ip, user, password, "df -h / | awk '$NF==\"/\"{print $3, $2}'")
    disk_used, disk_total = disk_output.split()

    def convert_to_gb(size_str):
        unit = size_str[-1].upper()
        size = float(size_str[:-1])
        return size if unit == 'G' else size / 1024 if unit == 'M' else size * 1024

    disk_percent = (convert_to_gb(disk_used) / convert_to_gb(disk_total)) * 100
    disk_bar = generate_colored_bar(disk_percent)

    # Network Usage
    net_rx, net_tx = fetch_network_speed(vps_ip, user, password)
    total_rx, total_tx = fetch_total_network_usage(vps_ip, user, password)

    content = (
        f"```ansi\n"
        f"{BLUE}┌───────────────────────────────────────────────┐{RESET}\n"
        f"{BLUE}  {server_name:^15} [{vps_ip:^15}]  {RESET}\n"
        f"{BLUE}└───────────────────────────────────────────────┘{RESET}\n\n"
        f"{CYAN}Operating System:{RESET} {os_info}\n"
        f"{CYAN}Uptime:{RESET} {uptime}\n\n"
        f"{YELLOW}CPU Usage:{RESET}\n{cpu_bar}\n"
        f"Usage: {cpu_usage:.2f}% (Cores: {cpu_cores})\n\n"
        f"{YELLOW}RAM Usage:{RESET}\n{ram_bar}\n"
        f"Used: {ram_used} MB / {ram_total} MB "
        f"({ram_used / 1024:.2f} GB / {ram_total / 1024:.2f} GB)\n\n"
        f"{YELLOW}Disk Usage:{RESET}\n{disk_bar}\n"
        f"Used: {disk_used} / {disk_total}\n\n"
        f"{GREEN}Network Usage (Real-Time):{RESET}\n"
        f"> IN: {net_rx}\n> OUT: {net_tx}\n\n"
        f"{GREEN}All-Time Network Usage:{RESET}\n"
        f"> Total IN: {total_rx}\n> Total OUT: {total_tx}\n\n"
        f"{OWNER_NAME}\n"
        f"```"
    )
    return content

def send_or_edit_message(server_name, vps_ip, content):
    global msg_ids
    headers = {"Content-Type": "application/json"}
    payload = {"content": content}

    if msg_ids.get(vps_ip) is None:
        response = requests.post(f"{WEBHOOK_URL}?wait=true", json=payload, headers=headers)
        if response.status_code in [200, 204]:
            msg_ids[vps_ip] = response.json().get('id')
            print(f"{GREEN}Message sent successfully for {server_name} ({vps_ip}){RESET}")
        else:
            print(f"{RED}Failed to send message for {server_name}: {response.status_code}{RESET}")
    else:
        url = f"{WEBHOOK_URL}/messages/{msg_ids[vps_ip]}"
        response = requests.patch(url, json=payload, headers=headers)
        if response.status_code not in [200, 204]:
            print(f"{RED}Failed to edit message for {server_name}{RESET}")

def monitor_vps(server_name, vps_ip, user, password):
    while True:
        content = get_server_status(server_name, vps_ip, user, password)
        send_or_edit_message(server_name, vps_ip, content)
        time.sleep(DELAY)

if __name__ == "__main__":
    threads = []
    for name, ip, user, password in zip(VPS_NAMES, VPS_IPS, VPS_USERS, VPS_PASSWORDS):
        thread = threading.Thread(target=monitor_vps, args=(name, ip, user, password))
        threads.append(thread)
        thread.start()
