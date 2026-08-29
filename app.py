```python
import os
import re
import json
import time
import socket
import platform
import subprocess
import ipaddress
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import psutil
import requests

from flask import Flask, render_template, jsonify, request


# =========================================================
# APP
# =========================================================

app = Flask(__name__)

NETWORK_CACHE = {
    "data": None,
    "time": 0
}

CACHE_SECONDS = 3


# =========================================================
# COMMAND HELPER
# =========================================================

def run_command(command, timeout=3):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0
            )
        )

        return result.stdout.strip()

    except Exception:
        return ""


# =========================================================
# ACTIVE NETWORK
# =========================================================

def get_active_network():
    """
    Mencari interface IPv4 yang sedang digunakan.
    Menggunakan routing socket sebagai penentu interface utama.
    """

    local_ip = None
    gateway = None
    interface = None
    netmask = None
    mac = None

    # -----------------------------------------------------
    # Cari IP yang digunakan untuk keluar jaringan
    # -----------------------------------------------------

    try:
        s = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        s.settimeout(1)

        s.connect(("1.1.1.1", 80))

        local_ip = s.getsockname()[0]

        s.close()

    except Exception:
        pass

    interfaces = psutil.net_if_addrs()
    stats = psutil.net_if_stats()

    # -----------------------------------------------------
    # Cari interface berdasarkan local IP
    # -----------------------------------------------------

    if local_ip:

        for name, addresses in interfaces.items():

            for addr in addresses:

                if (
                    addr.family == socket.AF_INET
                    and addr.address == local_ip
                ):

                    interface = name
                    netmask = addr.netmask

                    break

            if interface:
                break

    # -----------------------------------------------------
    # Fallback: interface UP yang mempunyai IPv4
    # -----------------------------------------------------

    if not interface:

        for name, addresses in interfaces.items():

            if name not in stats:
                continue

            if not stats[name].isup:
                continue

            for addr in addresses:

                if (
                    addr.family == socket.AF_INET
                    and not addr.address.startswith("127.")
                ):

                    interface = name
                    local_ip = addr.address
                    netmask = addr.netmask

                    break

            if interface:
                break

    # -----------------------------------------------------
    # MAC interface
    # -----------------------------------------------------

    if interface:

        for addr in interfaces.get(interface, []):

            if addr.family == psutil.AF_LINK:

                mac = addr.address

                break

    # -----------------------------------------------------
    # Gateway
    # -----------------------------------------------------

    gateway = get_default_gateway()

    # -----------------------------------------------------
    # Network CIDR
    # -----------------------------------------------------

    network = None

    if local_ip and netmask:

        try:

            network = str(
                ipaddress.ip_network(
                    f"{local_ip}/{netmask}",
                    strict=False
                )
            )

        except Exception:
            network = None

    return {
        "interface": interface or "-",
        "local_ip": local_ip or "-",
        "netmask": netmask or "-",
        "gateway": gateway or "-",
        "network": network or "-",
        "mac": mac or "-"
    }


# =========================================================
# DEFAULT GATEWAY
# =========================================================

def get_default_gateway():

    system = platform.system().lower()

    # -----------------------------------------------------
    # Windows
    # -----------------------------------------------------

    if system == "windows":

        output = run_command(
            ["ipconfig"],
            timeout=3
        )

        matches = re.findall(
            r"Default Gateway[ .:]*([0-9.]+)",
            output,
            re.IGNORECASE
        )

        for value in matches:

            if value:
                return value.strip()

        return "-"

    # -----------------------------------------------------
    # Linux
    # -----------------------------------------------------

    output = run_command(
        ["ip", "route"],
        timeout=3
    )

    match = re.search(
        r"default via ([0-9.]+)",
        output
    )

    if match:
        return match.group(1)

    # -----------------------------------------------------
    # macOS / fallback
    # -----------------------------------------------------

    output = run_command(
        ["route", "-n", "get", "default"],
        timeout=3
    )

    match = re.search(
        r"gateway:\s*([0-9.]+)",
        output
    )

    if match:
        return match.group(1)

    return "-"


# =========================================================
# ARP / NEIGHBOR TABLE
# =========================================================

def get_neighbors():

    system = platform.system().lower()

    devices = {}

    # -----------------------------------------------------
    # Windows
    # -----------------------------------------------------

    if system == "windows":

        output = run_command(
            ["arp", "-a"],
            timeout=5
        )

        pattern = re.compile(
            r"^\s*([0-9.]+)\s+"
            r"([0-9a-fA-F-]{17})\s+"
            r"(\w+)",
            re.MULTILINE
        )

        for match in pattern.finditer(output):

            ip = match.group(1)

            mac = match.group(2).replace(
                "-",
                ":"
            ).upper()

            entry_type = match.group(3).lower()

            if entry_type == "static":
                continue

            devices[ip] = {
                "ip": ip,
                "mac": mac
            }

    # -----------------------------------------------------
    # Linux
    # -----------------------------------------------------

    else:

        output = run_command(
            ["ip", "neigh"],
            timeout=5
        )

        pattern = re.compile(
            r"^([0-9.]+)\s+dev\s+(\S+)"
            r"(?:\s+lladdr\s+([0-9a-fA-F:]{17}))?"
            r"\s+(\S+)",
            re.MULTILINE
        )

        for match in pattern.finditer(output):

            ip = match.group(1)
            mac = match.group(3)
            state = match.group(4).upper()

            if state in (
                "FAILED",
                "INCOMPLETE"
            ):
                continue

            devices[ip] = {
                "ip": ip,
                "mac": (
                    mac.upper()
                    if mac
                    else "-"
                )
            }

    return list(devices.values())


# =========================================================
# HOSTNAME
# =========================================================

def resolve_hostname(ip):

    try:

        old_timeout = socket.getdefaulttimeout()

        socket.setdefaulttimeout(0.5)

        hostname = socket.gethostbyaddr(ip)[0]

        socket.setdefaulttimeout(
            old_timeout
        )

        return hostname

    except Exception:

        return "-"


# =========================================================
# MAC VENDOR
# =========================================================

def get_mac_vendor(mac):

    if not mac or mac == "-":
        return "-"

    clean_mac = re.sub(
        r"[^0-9A-Fa-f]",
        "",
        mac
    ).upper()

    if len(clean_mac) < 6:
        return "-"

    oui = clean_mac[:6]

    try:

        response = requests.get(
            f"https://api.macvendors.com/{oui}",
            timeout=2
        )

        if response.ok:

            value = response.text.strip()

            if value:
                return value

    except Exception:
        pass

    return "-"


# =========================================================
# PING
# =========================================================

def ping_host(ip):

    if not ip or ip == "-":
        return None

    system = platform.system().lower()

    if system == "windows":

        command = [
            "ping",
            "-n",
            "1",
            "-w",
            "1000",
            ip
        ]

    else:

        command = [
            "ping",
            "-c",
            "1",
            "-W",
            "1",
            ip
        ]

    start = time.perf_counter()

    output = run_command(
        command,
        timeout=2
    )

    if not output:
        return None

    elapsed = (
        time.perf_counter() - start
    ) * 1000

    # Ambil nilai ping jika tersedia
    match = re.search(
        r"(?:time[=<]|Average = )\s*([0-9.,]+)",
        output,
        re.IGNORECASE
    )

    if match:

        value = match.group(1).replace(
            ",",
            "."
        )

        try:
            return round(float(value), 2)
        except Exception:
            pass

    return round(elapsed, 2)


# =========================================================
# DEVICE SCAN
# =========================================================

def scan_devices(network_info):

    neighbors = get_neighbors()

    gateway = network_info.get(
        "gateway"
    )

    local_ip = network_info.get(
        "local_ip"
    )

    devices = []

    # -----------------------------------------------------
    # Tambahkan hasil ARP / neighbor
    # -----------------------------------------------------

    for device in neighbors:

        ip = device.get(
            "ip",
            "-"
        )

        if not ip or ip == "-":
            continue

        # Jangan tampilkan loopback
        if ip.startswith("127."):
            continue

        device["hostname"] = "-"

        device["vendor"] = "-"

        device["latency_ms"] = None

        device["signal"] = None

        device["source"] = "ARP"

        devices.append(device)

    # -----------------------------------------------------
    # Pastikan komputer sendiri masuk
    # -----------------------------------------------------

    if (
        local_ip != "-"
        and local_ip
        and not any(
            d["ip"] == local_ip
            for d in devices
        )
    ):

        devices.append({

            "ip": local_ip,

            "mac": network_info.get(
                "mac",
                "-"
            ),

            "hostname":
                socket.gethostname(),

            "vendor": "-",

            "latency_ms": None,

            "signal": None,

            "source": "LOCAL"

        })

    # -----------------------------------------------------
    # Pastikan gateway masuk
    # -----------------------------------------------------

    if (
        gateway != "-"
        and gateway
        and not any(
            d["ip"] == gateway
            for d in devices
        )
    ):

        devices.append({

            "ip": gateway,

            "mac": "-",

            "hostname": "Gateway",

            "vendor": "-",

            "latency_ms": None,

            "signal": None,

            "source": "GATEWAY"

        })

    # -----------------------------------------------------
    # Batasi jumlah worker supaya tidak membebani jaringan
    # -----------------------------------------------------

    max_workers = min(
        12,
        max(
            1,
            len(devices)
        )
    )

    # -----------------------------------------------------
    # Resolve hostname + vendor + ping
    # -----------------------------------------------------

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        hostname_jobs = {
            executor.submit(
                resolve_hostname,
                d["ip"]
            ): d
            for d in devices
        }

        ping_jobs = {
            executor.submit(
                ping_host,
                d["ip"]
            ): d
            for d in devices
        }

        vendor_jobs = {
            executor.submit(
                get_mac_vendor,
                d["mac"]
            ): d
            for d in devices
        }

        for future in as_completed(
            hostname_jobs
        ):

            device = hostname_jobs[future]

            try:
                device["hostname"] = (
                    future.result()
                    or "-"
                )
            except Exception:
                pass

        for future in as_completed(
            ping_jobs
        ):

            device = ping_jobs[future]

            try:
                device["latency_ms"] = (
                    future.result()
                )
            except Exception:
                pass

        for future in as_completed(
            vendor_jobs
        ):

            device = vendor_jobs[future]

            try:
                device["vendor"] = (
                    future.result()
                    or "-"
                )
            except Exception:
                pass

    # -----------------------------------------------------
    # Router information
    # -----------------------------------------------------

    router_mac = "-"

    router_vendor = "-"

    for device in devices:

        if device["ip"] == gateway:

            router_mac = device.get(
                "mac",
                "-"
            )

            router_vendor = device.get(
                "vendor",
                "-"
            )

            break

    router_latency = ping_host(
        gateway
    )

    # -----------------------------------------------------
    # Sort
    # -----------------------------------------------------

    devices.sort(
        key=lambda d: (
            d["ip"] == gateway,
            d["ip"] == local_ip,
            d["ip"]
        ),
        reverse=True
    )

    return devices, {
        "gateway": gateway,
        "mac": router_mac,
        "vendor": router_vendor,
        "latency_ms": router_latency
    }


# =========================================================
# PUBLIC IP
# =========================================================

def get_public_ip():

    services = [
        "https://api.ipify.org",
        "https://ifconfig.me/ip"
    ]

    for url in services:

        try:

            response = requests.get(
                url,
                timeout=2
            )

            if response.ok:

                value = response.text.strip()

                if re.match(
                    r"^[0-9a-fA-F:.]+$",
                    value
                ):

                    return value

        except Exception:
            continue

    return "-"


# =========================================================
# TRAFFIC
# =========================================================

traffic_previous = {
    "time": time.time(),
    "download": 0,
    "upload": 0
}

traffic_lock = threading.Lock()


def get_traffic():

    global traffic_previous

    counters = psutil.net_io_counters()

    now = time.time()

    rx = counters.bytes_recv
    tx = counters.bytes_sent

    with traffic_lock:

        old_time = traffic_previous["time"]
        old_rx = traffic_previous["download"]
        old_tx = traffic_previous["upload"]

        elapsed = max(
            now - old_time,
            0.1
        )

        download = (
            (rx - old_rx)
            * 8
            / elapsed
            / 1_000_000
        )

        upload = (
            (tx - old_tx)
            * 8
            / elapsed
            / 1_000_000
        )

        traffic_previous = {
            "time": now,
            "download": rx,
            "upload": tx
        }

    return {
        "download_mbps": round(
            max(download, 0),
            2
        ),
        "upload_mbps": round(
            max(upload, 0),
            2
        )
    }


# =========================================================
# NETWORK DATA
# =========================================================

def build_network_data():

    network = get_active_network()

    devices, router_data = scan_devices(
        network
    )

    traffic = get_traffic()

    public_ip = get_public_ip()

    gateway = network.get(
        "gateway",
        "-"
    )

    local_ip = network.get(
        "local_ip",
        "-"
    )

    # -----------------------------------------------------
    # Network name
    # -----------------------------------------------------

    network_name = "-"

    if platform.system().lower() == "windows":

        output = run_command(
            [
                "netsh",
                "wlan",
                "show",
                "interfaces"
            ],
            timeout=3
        )

        match = re.search(
            r"^\s*SSID\s*:\s*(.+)$",
            output,
            re.MULTILINE |
            re.IGNORECASE
        )

        if match:
            network_name = (
                match.group(1).strip()
            )

    # Linux Wi-Fi fallback
    if network_name == "-":

        output = run_command(
            ["iwgetid", "-r"],
            timeout=2
        )

        if output:
            network_name = output.strip()

    # -----------------------------------------------------
    # Router online
    # -----------------------------------------------------

    router_online = (
        router_data.get(
            "latency_ms"
        ) is not None
    )

    # -----------------------------------------------------
    # Remove duplicate devices
    # -----------------------------------------------------

    unique = {}

    for device in devices:

        key = (
            device.get("ip")
            or device.get("mac")
        )

        if key:
            unique[key] = device

    devices = list(
        unique.values()
    )

    return {

        "status": "success",

        "timestamp": int(
            time.time()
        ),

        "network": {

            "name": network_name,

            "interface":
                network.get(
                    "interface",
                    "-"
                ),

            "local_ip": local_ip,

            "netmask":
                network.get(
                    "netmask",
                    "-"
                ),

            "gateway": gateway,

            "network":
                network.get(
                    "network",
                    "-"
                ),

            "mac":
                network.get(
                    "mac",
                    "-"
                )

        },

        # Compatibility dengan network.html
        "ssid": network_name,

        "gateway": gateway,

        "local_ip": local_ip,

        "public_ip": public_ip,

        "router": {

            "online": router_online,

            "gateway": gateway,

            "local_ip": local_ip,

            "public_ip": public_ip,

            "mac":
                router_data.get(
                    "mac",
                    "-"
                ),

            "vendor":
                router_data.get(
                    "vendor",
                    "-"
                ),

            "hostname": "Router",

            "latency_ms":
                router_data.get(
                    "latency_ms"
                )

        },

        "devices": devices,

        "clients_count": len(
            devices
        ),

        "download_mbps":
            traffic[
                "download_mbps"
            ],

        "upload_mbps":
            traffic[
                "upload_mbps"
            ]

    }


# =========================================================
# API
# =========================================================

@app.route("/api/network-data")
def api_network_data():

    force = (
        request.args.get(
            "force"
        ) == "1"
    )

    now = time.time()

    # Gunakan cache sebentar agar
    # polling frontend tidak membuat
    # scan berat terus-menerus.
    if (
        not force
        and NETWORK_CACHE["data"]
        and now -
        NETWORK_CACHE["time"]
        < CACHE_SECONDS
    ):

        return jsonify(
            NETWORK_CACHE["data"]
        )

    try:

        data = build_network_data()

        NETWORK_CACHE["data"] = data

        NETWORK_CACHE["time"] = now

        return jsonify(data)

    except Exception as e:

        app.logger.exception(
            "Network scan error"
        )

        return jsonify({

            "status": "error",

            "success": False,

            "message":
                "Gagal mendeteksi jaringan: "
                + str(e),

            "devices": [],

            "clients_count": 0

        }), 500


# =========================================================
# PAGE
# =========================================================

@app.route("/network")
def network_page():

    return render_template(
        "network.html"
    )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():

    return render_template(
        "network.html"
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    print("=" * 55)
    print(" NetSight Pro - Network Monitor")
    print("=" * 55)

    info = get_active_network()

    print(
        "Interface :",
        info.get("interface")
    )

    print(
        "Local IP  :",
        info.get("local_ip")
    )

    print(
        "Gateway   :",
        info.get("gateway")
    )

    print(
        "Network   :",
        info.get("network")
    )

    print("=" * 55)

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=False,
        threaded=True
    )
```
