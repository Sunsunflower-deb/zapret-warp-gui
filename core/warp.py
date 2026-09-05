"""Управление Cloudflare WARP (warp-cli)."""
import getpass
import os
import shutil
import subprocess


# --- обнаружение warp-cli -----------------------------------------------
def _windows_paths():
    paths = []
    if os.name == "nt":
        for var in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(var, "")
            if base:
                p = os.path.join(base, "Cloudflare", "Cloudflare WARP", "warp-cli.exe")
                paths.append(p)
    return paths


def find_cli():
    """Полный путь к warp-cli или None."""
    if os.name == "nt":
        p = shutil.which("warp-cli.exe")
        if p:
            return p
        for p in _windows_paths():
            if os.path.isfile(p):
                return p
        return None
    return shutil.which("warp-cli")


def installed():
    return find_cli() is not None


def _cli():
    return find_cli() or ("warp-cli.exe" if os.name == "nt" else "warp-cli")


# --- подсказки по установке ----------------------------------------------
def _distro():
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("ID="):
                    return line.strip().split("=", 1)[1].strip('"')
    except OSError:
        pass
    return "unknown"


def install_guide():
    if os.name == "nt":
        return (
            "Установите официальный Cloudflare WARP (1.1.1.1): "
            "https://developers.cloudflare.com/cloudflare-one/connections/"
            "connect-devices/warp/download-warp/  "
            "или положите установщик warp.msi рядом и выполните:\n"
            "    msiexec /i warp.msi /quiet"
        )
    d = _distro()
    if d in ("arch", "manjaro", "endeavouros"):
        return "AUR:  yay -S cloudflare-warp-bin   (или paru -S cloudflare-warp-bin)"
    if d in ("debian", "ubuntu", "linuxmint", "pop"):
        return ("Официальный репозиторий Cloudflare: "
                "https://pkg.cloudflareclient.com/  затем:\n"
                "    apt install cloudflare-warp")
    if d in ("fedora", "rhel", "centos", "rocky", "almalinux"):
        return ("Официальный репозиторий Cloudflare: "
                "https://pkg.cloudflareclient.com/  затем:\n"
                "    dnf install cloudflare-warp")
    return ("Установите Cloudflare WARP — инструкции: "
            "https://developers.cloudflare.com/cloudflare-one/connections/"
            "connect-devices/warp/install-warp/linux/")


# --- выполнение ----------------------------------------------------------
def _warp_user(cfg):
    u = (cfg.get("warp_user") or "").strip() or "auto"
    if u != "auto":
        return u
    if os.name == "nt":
        return None
    if os.geteuid() == 0:
        sudo_user = os.environ.get("SUDO_USER") or os.environ.get("DOAS_USER")
        if sudo_user and sudo_user != "root":
            return sudo_user
    return None


def run(cfg, *args):
    user = _warp_user(cfg)
    cmd = [_cli()] + list(args)
    if user and user != getpass.getuser():
        cmd = ["sudo", "-u", user] + cmd
    return subprocess.run(cmd, capture_output=True, text=True)


def apply_settings(cfg):
    run(cfg, "mode", cfg.get("warp_mode", "warp+doh"))
    run(cfg, "tunnel", "protocol", "set", cfg.get("warp_protocol", "MASQUE"))
    run(cfg, "tunnel", "masque-options", "set",
        cfg.get("warp_masque", "h3-with-h2-fallback"))
    ep = (cfg.get("warp_endpoint") or "").strip()
    if ep:
        run(cfg, "tunnel", "endpoint", "set", ep)
    else:
        run(cfg, "tunnel", "endpoint", "reset")


def connect(cfg):
    apply_settings(cfg)
    run(cfg, "--accept-tos", "connect")


def disconnect(cfg):
    run(cfg, "disconnect")


def status(cfg):
    r = run(cfg, "status")
    return r.stdout.strip()
