#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
ADB 企业级运维工具 —— 炫彩增强版 (ADB Enterprise Utility Pro)
================================================================================
版本：v2.0.0 | 日期：2026-05-22 | 作者：符爽爽

新增功能（v2.0.0）：
    1. 性能实时监控（top / meminfo / gfxinfo 轮询）
    2. 输入模拟系统（点击、滑动、文本、按键、手势）
    3. APK 提取（导出已安装应用原始 APK）
    4. 应用详情透视（dump package：权限、Activity、签名）
    5. 端口转发管理（forward / reverse / 列表 / 清除）
    6. Bugreport 一键采集（完整系统诊断报告）
    7. 多模式重启（recovery / bootloader / fastboot / edl）
    8. 网络信息面板（IP、WiFi、MAC、路由表）
    9. 批量 APK 安装（遍历目录自动安装）
    10. 应用冻结/解冻（pm disable-user / enable）
    11. 设备文件浏览器（ls / cd / pwd 交互浏览）
    12. 截图后自动打开（调用系统默认查看器）

适用环境：Python 3.8+，adb 在 PATH 中
================================================================================
"""

import os
import sys
import time
import shutil
import subprocess
import platform
import re
from typing import List, Tuple, Optional, Dict, Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


# ==============================================================================
# Windows ANSI 颜色支持启用
# ==============================================================================
def _enable_windows_ansi() -> None:
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        for handle in [-11, -12]:  # stdout, stderr
            h = kernel32.GetStdHandle(handle)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
                ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                if not (mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING):
                    kernel32.SetConsoleMode(h, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass

_enable_windows_ansi()


# ==============================================================================
# 常量与配置
# ==============================================================================
class ColorCode(Enum):
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    NEON_CYAN = "\033[38;5;51m"
    NEON_PURPLE = "\033[38;5;141m"
    NEON_PINK = "\033[38;5;213m"
    NEON_BLUE = "\033[38;5;81m"
    NEON_GREEN = "\033[38;5;84m"
    NEON_ORANGE = "\033[38;5;208m"
    NEON_YELLOW = "\033[38;5;220m"
    NEON_RED = "\033[38;5;196m"
    BG_PANEL = "\033[48;5;237m"


class Config:
    TOOL_NAME: str = "ADB Enterprise Utility"
    VERSION: str = "v2.0.0"
    ADB_TIMEOUT: int = 30
    LOG_DIR: Path = Path.home() / ".adb_tool_logs"
    SCREENSHOT_DIR: Path = Path.home() / ".adb_tool_screenshots"
    APK_EXTRACT_DIR: Path = Path.home() / ".adb_tool_apks"
    BUGREPORT_DIR: Path = Path.home() / ".adb_tool_bugreports"
    PANEL_WIDTH: int = 62
    USE_ICONS: bool = True


# ==============================================================================
# 数据模型
# ==============================================================================
@dataclass
class DeviceInfo:
    serial: str
    status: str
    product: str = "N/A"
    model: str = "N/A"
    device: str = "N/A"
    transport_id: str = "N/A"

    @property
    def is_online(self) -> bool:
        return self.status.lower() == "device"


@dataclass
class AppInfo:
    package_name: str
    version_name: str = "N/A"
    version_code: str = "N/A"
    is_system_app: bool = False


# ==============================================================================
# 核心执行引擎
# ==============================================================================
class CommandExecutor:
    def __init__(self, serial: Optional[str] = None):
        self.serial: Optional[str] = serial
        self._check_adb_binary()

    def _check_adb_binary(self) -> None:
        if shutil.which("adb") is None:
            Console.error("未检测到 adb 命令。请确认 Android SDK Platform-Tools 已安装并加入 PATH。")
            sys.exit(1)

    def _build_cmd(self, cmd_parts: List[str]) -> List[str]:
        base = ["adb"]
        if self.serial:
            base.extend(["-s", self.serial])
        base.extend(cmd_parts)
        return base

    def run(
        self,
        cmd_parts: List[str],
        timeout: int = Config.ADB_TIMEOUT,
        capture: bool = True,
        shell: bool = False,
    ) -> Tuple[int, str, str]:
        full_cmd = self._build_cmd(cmd_parts)
        stdout_str, stderr_str = "", ""
        try:
            if shell:
                result = subprocess.run(
                    " ".join(full_cmd), shell=True, capture_output=capture,
                    text=True, timeout=timeout, encoding="utf-8", errors="replace",
                )
            else:
                result = subprocess.run(
                    full_cmd, capture_output=capture,
                    text=True, timeout=timeout, encoding="utf-8", errors="replace",
                )
            if capture:
                stdout_str = result.stdout or ""
                stderr_str = result.stderr or ""
            return result.returncode, stdout_str, stderr_str
        except subprocess.TimeoutExpired:
            Console.error(f"命令执行超时（>{timeout}s）")
            return -1, "", "Timeout"
        except Exception as e:
            Console.error(f"命令执行异常: {e}")
            return -3, "", str(e)

    def run_safe(self, cmd_parts: List[str], timeout: int = Config.ADB_TIMEOUT) -> str:
        rc, out, err = self.run(cmd_parts, timeout=timeout)
        if rc != 0:
            raise RuntimeError(f"ADB 命令失败 (rc={rc}): {err or out}")
        return out


# ==============================================================================
# 炫彩终端 UI 层
# ==============================================================================
class Console:
    _enabled: bool = True
    _icons: Dict[str, str] = {
        "phone": "📱", "package": "📦", "folder": "📂", "camera": "📷",
        "film": "🎬", "cpu": "🖥️", "battery": "🔋", "display": "🖥️",
        "disk": "💾", "log": "📋", "bug": "🐛", "shell": "🐚",
        "swap": "🔄", "exit": "🚪", "arrow": "▶", "check": "✓",
        "cross": "✗", "warn": "⚠", "info": "ℹ", "star": "★",
        "bullet": "•", "dash": "─", "block": "█", "rocket": "🚀",
        "target": "🎯", "wifi": "📡", "tap": "👆", "swipe": "👋",
        "keyboard": "⌨️", "freeze": "❄️", "unfreeze": "☀️", "extract": "📤",
        "network": "🌐", "chart": "📊", "forward": "🔀", "restart": "🔁",
        "zoom": "🔍", "magic": "✨", "lock": "🔒", "unlock": "🔓",
        "corner_tl": "╭", "corner_tr": "╮", "corner_bl": "╰", "corner_br": "╯",
        "pipe": "│", "h_line": "─",
    }

    @classmethod
    def _icon(cls, name: str) -> str:
        return cls._icons.get(name, "") if Config.USE_ICONS else ""

    @classmethod
    def _color(cls, text: str, code: ColorCode) -> str:
        return f"{code.value}{text}{ColorCode.RESET.value}" if cls._enabled else text

    @classmethod
    def _gradient_text(cls, text: str, colors: List[ColorCode]) -> str:
        if not cls._enabled or not text:
            return text
        result = ""
        for i, char in enumerate(text):
            if char == " ":
                result += char
                continue
            result += f"{colors[i % len(colors)].value}{char}"
        return result + ColorCode.RESET.value

    @classmethod
    def _panel(cls, lines: List[str], width: int = Config.PANEL_WIDTH,
               border_color: ColorCode = ColorCode.NEON_CYAN, title: Optional[str] = None) -> None:
        tl = cls._color(cls._icon("corner_tl") or "╭", border_color)
        tr = cls._color(cls._icon("corner_tr") or "╮", border_color)
        bl = cls._color(cls._icon("corner_bl") or "╰", border_color)
        br = cls._color(cls._icon("corner_br") or "╯", border_color)
        pipe = cls._color(cls._icon("pipe") or "│", border_color)
        h = cls._color(cls._icon("h_line") or "─", border_color)
        top = tl + h * (width - 2) + tr
        bottom = bl + h * (width - 2) + br
        print(top)
        if title:
            pad = (width - 2 - len(title)) // 2
            print(pipe + " " * pad + cls._color(title, ColorCode.BOLD) + " " * (width - 2 - pad - len(title)) + pipe)
            print(pipe + h * (width - 2) + pipe)
        for line in lines:
            clean = line
            for cc in ColorCode:
                clean = clean.replace(cc.value, "")
            padding = max(0, width - 2 - len(clean))
            print(f"{pipe} {line}{' ' * padding} {pipe}")
        print(bottom)

    @classmethod
    def banner(cls) -> None:
        os.system("cls" if platform.system() == "Windows" else "clear")
        title_lines = [
            "",
            cls._gradient_text("    ADB Enterprise Utility", [ColorCode.NEON_CYAN, ColorCode.NEON_PURPLE, ColorCode.NEON_BLUE]),
            cls._gradient_text("           v2.0.0", [ColorCode.NEON_BLUE, ColorCode.NEON_CYAN]),
            "",
        ]
        cls._panel(title_lines, border_color=ColorCode.NEON_CYAN)

    @classmethod
    def title(cls, text: str) -> None:
        colors = [ColorCode.NEON_CYAN, ColorCode.NEON_PURPLE, ColorCode.NEON_PINK]
        print(f"\n  {cls._icon('star')} {cls._gradient_text(text, colors)}")
        print(f"  {cls._color('─' * (len(text) + 8), ColorCode.NEON_BLUE)}")

    @classmethod
    def section(cls, text: str) -> None:
        print(f"\n  {cls._icon('arrow')} {cls._color(text, ColorCode.NEON_PURPLE)}")
        print(f"  {cls._color('─' * 50, ColorCode.DIM)}")

    @classmethod
    def info(cls, text: str) -> None:
        print(f"  {cls._icon('check')} {cls._color(text, ColorCode.NEON_GREEN)}")

    @classmethod
    def warn(cls, text: str) -> None:
        print(f"  {cls._icon('warn')} {cls._color(text, ColorCode.NEON_YELLOW)}")

    @classmethod
    def error(cls, text: str) -> None:
        print(f"  {cls._icon('cross')} {cls._color(text, ColorCode.NEON_RED)}")

    @classmethod
    def prompt(cls, text: str) -> str:
        return input(f"  {cls._icon('bullet')} {cls._color(text, ColorCode.NEON_CYAN)}: ")

    @classmethod
    def confirm(cls, text: str) -> bool:
        ans = input(f"  {cls._icon('warn')} {cls._color(text, ColorCode.NEON_ORANGE)} [Y/n]: ").strip().lower()
        return ans in ("y", "yes", "")

    @classmethod
    def pause(cls) -> None:
        print()
        input(f"  {cls._color('按 Enter 键继续...', ColorCode.DIM)}")

    @classmethod
    def status_badge(cls, status: str) -> str:
        s = status.lower()
        if s in ("device", "online", "connected", "success"):
            return cls._color(f"● {status}", ColorCode.NEON_GREEN)
        elif s in ("offline", "disconnected", "error", "failed"):
            return cls._color(f"● {status}", ColorCode.NEON_RED)
        elif s in ("unauthorized", "warning"):
            return cls._color(f"● {status}", ColorCode.NEON_YELLOW)
        else:
            return cls._color(f"● {status}", ColorCode.NEON_ORANGE)

    @classmethod
    def print_table(cls, headers: List[str], rows: List[List[str]], min_width: int = 12) -> None:
        if not rows:
            cls.warn("暂无数据")
            return
        widths = [max(len(str(h)), min_width) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                clean = str(cell)
                for cc in ColorCode:
                    clean = clean.replace(cc.value, "")
                widths[i] = max(widths[i], len(clean) + 2)
        sep = cls._color("┌" + "┬".join("─" * w for w in widths) + "┐", ColorCode.NEON_BLUE)
        sep_mid = cls._color("├" + "┼".join("─" * w for w in widths) + "┤", ColorCode.NEON_BLUE)
        sep_bot = cls._color("└" + "┴".join("─" * w for w in widths) + "┘", ColorCode.NEON_BLUE)
        print(sep)
        print("│ " + " │ ".join(cls._color(str(h).ljust(widths[i]), ColorCode.BOLD) for i, h in enumerate(headers)) + " │")
        print(sep_mid)
        for row in rows:
            print("│ " + " │ ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)) + " │")
        print(sep_bot)

    @classmethod
    def menu_item(cls, key: str, title: str, icon: str = "", color: ColorCode = ColorCode.NEON_CYAN) -> None:
        icon_str = cls._icon(icon)
        print(f"    {icon_str} {cls._color(f'[{key}]', ColorCode.BOLD)} {cls._color(title, color)}")

    @classmethod
    def menu_divider(cls) -> None:
        print(f"    {cls._color('┈' * 40, ColorCode.DIM)}")

    @classmethod
    def device_card(cls, serial: str, status: str, model: str) -> None:
        print(f"    {cls._icon('phone')} {cls._color(serial, ColorCode.NEON_CYAN)}  {cls.status_badge(status)}  {cls._color(model, ColorCode.NEON_PURPLE)}")

    @classmethod
    def progress_bar(cls, current: int, total: int, width: int = 30) -> str:
        ratio = current / total if total > 0 else 0
        filled = int(width * ratio)
        bar = cls._color("█" * filled, ColorCode.NEON_GREEN) + cls._color("░" * (width - filled), ColorCode.DIM)
        return f"[{bar}] {current}/{total}"


# ==============================================================================
# 功能模块：设备管理
# ==============================================================================
class DeviceManager:
    def __init__(self, executor: CommandExecutor):
        self.exe = executor

    def list_devices(self) -> List[DeviceInfo]:
        rc, out, _ = self.exe.run(["devices", "-l"])
        devices: List[DeviceInfo] = []
        if rc != 0:
            Console.error("获取设备列表失败")
            return devices
        for line in out.strip().splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, status = parts[0], parts[1]
            extras: Dict[str, str] = {}
            for part in parts[2:]:
                if ":" in part:
                    k, v = part.split(":", 1)
                    extras[k] = v
            devices.append(DeviceInfo(
                serial=serial, status=status,
                product=extras.get("product", "N/A"),
                model=extras.get("model", "N/A"),
                device=extras.get("device", "N/A"),
                transport_id=extras.get("transport_id", "N/A"),
            ))
        return devices

    def connect(self, host: str, port: int = 5555) -> bool:
        rc, out, err = self.exe.run(["connect", f"{host}:{port}"], timeout=10)
        if rc == 0 and ("connected" in out or "already connected" in out):
            Console.info(f"设备连接成功: {host}:{port}")
            return True
        Console.error(f"连接失败: {err or out}")
        return False

    def disconnect(self, host: Optional[str] = None) -> bool:
        cmd = ["disconnect"]
        if host:
            cmd.append(host)
        rc, _, _ = self.exe.run(cmd)
        if rc == 0:
            Console.info("已断开设备连接")
            return True
        return False

    def get_device_info(self, serial: str) -> Dict[str, str]:
        exe = CommandExecutor(serial)
        props = {}
        keys = [
            "ro.product.model", "ro.product.brand",
            "ro.build.version.release", "ro.build.version.sdk",
            "ro.hardware", "persist.sys.timezone",
            "ro.build.fingerprint", "ro.serialno",
        ]
        for key in keys:
            try:
                val = exe.run_safe(["shell", "getprop", key]).strip()
                props[key] = val if val else "N/A"
            except RuntimeError:
                props[key] = "N/A"
        return props

    def reboot(self, mode: str = "") -> bool:
        """mode: '', 'recovery', 'bootloader', 'fastboot', 'edl'"""
        cmd = ["reboot"]
        if mode:
            cmd.append(mode)
        rc, _, err = self.exe.run(cmd)
        if rc == 0:
            Console.info(f"重启指令已发送{' (' + mode + ')' if mode else ''}")
            return True
        Console.error(f"重启失败: {err}")
        return False

    def bugreport(self) -> Optional[Path]:
        """采集完整系统诊断报告"""
        Config.BUGREPORT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        out_path = Config.BUGREPORT_DIR / f"bugreport_{timestamp}.zip"
        Console.info("正在采集 Bugreport，可能需要 30-60 秒...")
        rc, _, err = self.exe.run(["bugreport", str(out_path)], timeout=120)
        if rc == 0 and out_path.exists():
            Console.info(f"Bugreport 已保存: {out_path}")
            return out_path
        # 兼容旧版 adb（输出到 stdout）
        rc2, out2, _ = self.exe.run(["bugreport"], timeout=120)
        if rc2 == 0:
            txt_path = Config.BUGREPORT_DIR / f"bugreport_{timestamp}.txt"
            txt_path.write_text(out2, encoding="utf-8")
            Console.info(f"Bugreport 已保存: {txt_path}")
            return txt_path
        Console.error(f"采集失败: {err}")
        return None


# ==============================================================================
# 功能模块：应用管理
# ==============================================================================
class AppManager:
    def __init__(self, executor: CommandExecutor):
        self.exe = executor

    def list_packages(self, system_only: bool = False, third_only: bool = False) -> List[AppInfo]:
        cmd = ["shell", "pm", "list", "packages"]
        if system_only:
            cmd.append("-s")
        elif third_only:
            cmd.append("-3")
        rc, out, _ = self.exe.run(cmd)
        apps: List[AppInfo] = []
        if rc != 0:
            return apps
        for line in out.strip().splitlines():
            if line.startswith("package:"):
                pkg = line.replace("package:", "").strip()
                apps.append(AppInfo(package_name=pkg, is_system_app=system_only))
        return apps

    def get_package_detail(self, package: str) -> Dict[str, str]:
        """获取应用详细信息"""
        exe = self.exe
        detail: Dict[str, str] = {}
        # 基础信息
        rc, out, _ = exe.run(["shell", "dumpsys", "package", package])
        if rc == 0:
            detail["dump_package"] = out[:2000]  # 截断避免过长
        # 版本号
        try:
            ver = exe.run_safe(["shell", "dumpsys", "package", package, "|", "grep", "versionName"]).strip()
            detail["version"] = ver
        except RuntimeError:
            detail["version"] = "N/A"
        # 权限
        rc2, out2, _ = exe.run(["shell", "pm", "dump", package])
        if rc2 == 0:
            detail["permissions"] = out2[:1500]
        # 签名
        rc3, out3, _ = exe.run(["shell", "pm", "dump", package, "|", "grep", "signatures"])
        if rc3 == 0:
            detail["signatures"] = out3[:500]
        return detail

    def install(self, apk_path: str) -> bool:
        path = Path(apk_path)
        if not path.exists():
            Console.error(f"文件不存在: {apk_path}")
            return False
        Console.info(f"正在安装: {path.name} ...")
        rc, out, err = self.exe.run(["install", "-r", str(path.resolve())], timeout=120)
        if rc == 0 and "Success" in out:
            Console.info("安装成功")
            return True
        Console.error(f"安装失败: {err or out}")
        return False

    def batch_install(self, directory: str) -> Tuple[int, int]:
        """批量安装目录下所有 APK，返回 (成功数, 失败数)"""
        dir_path = Path(directory)
        if not dir_path.is_dir():
            Console.error("路径不是有效目录")
            return 0, 0
        apks = list(dir_path.glob("*.apk"))
        if not apks:
            Console.warn("目录下未找到 APK 文件")
            return 0, 0
        success = 0
        fail = 0
        Console.info(f"发现 {len(apks)} 个 APK，开始批量安装...")
        for idx, apk in enumerate(apks, 1):
            print(f"\n{Console.progress_bar(idx, len(apks))}")
            if self.install(str(apk)):
                success += 1
            else:
                fail += 1
        Console.info(f"批量安装完成: 成功 {success} 个, 失败 {fail} 个")
        return success, fail

    def uninstall(self, package: str, keep_data: bool = False) -> bool:
        cmd = ["uninstall"]
        if keep_data:
            cmd.append("-k")
        cmd.append(package)
        rc, out, _ = self.exe.run(cmd)
        if rc == 0 and "Success" in out:
            Console.info(f"已卸载: {package}")
            return True
        Console.error(f"卸载失败: {out}")
        return False

    def clear_data(self, package: str) -> bool:
        rc, out, _ = self.exe.run(["shell", "pm", "clear", package])
        if rc == 0 and "Success" in out:
            Console.info(f"已清除数据: {package}")
            return True
        return False

    def start_app(self, package: str, activity: Optional[str] = None) -> bool:
        if activity:
            rc, _, _ = self.exe.run(["shell", "am", "start", "-n", f"{package}/{activity}"])
            return rc == 0
        rc, out, _ = self.exe.run(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])
        if rc == 0:
            Console.info(f"已启动: {package}")
            return True
        Console.error(f"启动失败: {out}")
        return False

    def freeze_app(self, package: str) -> bool:
        """冻结应用（对当前用户禁用）"""
        rc, out, _ = self.exe.run(["shell", "pm", "disable-user", "--user", "0", package])
        if rc == 0 and ("disabled" in out or "new state" in out):
            Console.info(f"已冻结: {package}")
            return True
        Console.error(f"冻结失败: {out}")
        return False

    def unfreeze_app(self, package: str) -> bool:
        """解冻应用"""
        rc, out, _ = self.exe.run(["shell", "pm", "enable", package])
        if rc == 0 and ("enabled" in out or "new state" in out):
            Console.info(f"已解冻: {package}")
            return True
        Console.error(f"解冻失败: {out}")
        return False

    def extract_apk(self, package: str) -> Optional[Path]:
        """提取已安装应用的 APK 到本地"""
        Config.APK_EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
        # 获取 APK 路径
        rc, out, _ = self.exe.run(["shell", "pm", "path", package])
        if rc != 0 or not out.strip():
            Console.error("无法获取应用 APK 路径")
            return None
        # 可能有多条路径（split apk），取第一条 base.apk
        apk_paths = [line.replace("package:", "").strip() for line in out.strip().splitlines()]
        base_apk = next((p for p in apk_paths if "base.apk" in p), apk_paths[0])

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        local_path = Config.APK_EXTRACT_DIR / f"{package}_{timestamp}.apk"

        rc2, _, err2 = self.exe.run(["pull", base_apk, str(local_path)], timeout=60)
        if rc2 == 0:
            Console.info(f"APK 已提取: {local_path}")
            return local_path
        Console.error(f"提取失败: {err2}")
        return None


# ==============================================================================
# 功能模块：文件传输
# ==============================================================================
class FileManager:
    def __init__(self, executor: CommandExecutor):
        self.exe = executor

    def push(self, local: str, remote: str) -> bool:
        local_path = Path(local)
        if not local_path.exists():
            Console.error(f"本地文件不存在: {local}")
            return False
        rc, out, err = self.exe.run(["push", str(local_path.resolve()), remote], timeout=60)
        if rc == 0:
            Console.info(f"推送成功: {local} → {remote}")
            return True
        Console.error(f"推送失败: {err or out}")
        return False

    def pull(self, remote: str, local: str) -> bool:
        rc, out, err = self.exe.run(["pull", remote, local], timeout=60)
        if rc == 0:
            Console.info(f"拉取成功: {remote} → {local}")
            return True
        Console.error(f"拉取失败: {err or out}")
        return False


# ==============================================================================
# 功能模块：屏幕与媒体
# ==============================================================================
class ScreenManager:
    def __init__(self, executor: CommandExecutor):
        self.exe = executor
        Config.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    def screenshot(self, auto_open: bool = False) -> Optional[Path]:
        remote_path = "/sdcard/screen_adb_tool.png"
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        local_path = Config.SCREENSHOT_DIR / f"screenshot_{timestamp}.png"
        rc, _, err = self.exe.run(["shell", "screencap", "-p", remote_path])
        if rc != 0:
            Console.error(f"截图失败: {err}")
            return None
        rc2, _, err2 = self.exe.run(["pull", remote_path, str(local_path)])
        if rc2 != 0:
            Console.error(f"拉取截图失败: {err2}")
            return None
        self.exe.run(["shell", "rm", remote_path])
        Console.info(f"截图已保存: {local_path}")
        if auto_open:
            self._open_file(local_path)
        return local_path

    def screenrecord(self, duration: int = 10, bitrate: str = "8000000") -> Optional[Path]:
        remote_path = "/sdcard/record_adb_tool.mp4"
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        local_path = Config.SCREENSHOT_DIR / f"record_{timestamp}.mp4"
        Console.info(f"开始录屏，持续 {duration} 秒...")
        rc, _, err = self.exe.run(
            ["shell", "screenrecord", "--bit-rate", bitrate, "--time-limit", str(duration), remote_path],
            timeout=duration + 15,
        )
        if rc != 0:
            Console.error(f"录屏失败: {err}")
            return None
        time.sleep(1)
        rc2, _, err2 = self.exe.run(["pull", remote_path, str(local_path)])
        if rc2 != 0:
            Console.error(f"拉取录屏失败: {err2}")
            return None
        self.exe.run(["shell", "rm", remote_path])
        Console.info(f"录屏已保存: {local_path}")
        return local_path

    @staticmethod
    def _open_file(path: Path) -> None:
        """调用系统默认程序打开文件"""
        try:
            if platform.system() == "Windows":
                os.startfile(str(path))
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(path)])
            else:
                subprocess.run(["xdg-open", str(path)])
        except Exception as e:
            Console.warn(f"自动打开失败: {e}")


# ==============================================================================
# 功能模块：输入模拟
# ==============================================================================
class InputManager:
    """输入模拟：点击、滑动、文本、按键"""

    def __init__(self, executor: CommandExecutor):
        self.exe = executor

    def tap(self, x: int, y: int) -> bool:
        rc, _, err = self.exe.run(["shell", "input", "tap", str(x), str(y)])
        if rc == 0:
            Console.info(f"点击坐标 ({x}, {y})")
            return True
        Console.error(f"点击失败: {err}")
        return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        rc, _, err = self.exe.run(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)])
        if rc == 0:
            Console.info(f"滑动 ({x1},{y1}) → ({x2},{y2}), 耗时 {duration}ms")
            return True
        Console.error(f"滑动失败: {err}")
        return False

    def text(self, content: str) -> bool:
        # 转义特殊字符
        safe = content.replace(" ", "%s").replace("&", r"\&").replace("(", r"\(").replace(")", r"\)")
        rc, _, err = self.exe.run(["shell", "input", "text", f'"{safe}"'])
        if rc == 0:
            Console.info(f"输入文本: {content}")
            return True
        Console.error(f"输入失败: {err}")
        return False

    def keyevent(self, keycode: str) -> bool:
        """常见按键: HOME, BACK, POWER, VOLUME_UP, VOLUME_DOWN, MENU, ENTER, etc."""
        rc, _, err = self.exe.run(["shell", "input", "keyevent", keycode])
        if rc == 0:
            Console.info(f"按键发送: {keycode}")
            return True
        Console.error(f"按键失败: {err}")
        return False

    def get_screen_size(self) -> Tuple[int, int]:
        """获取屏幕分辨率，用于计算相对坐标"""
        rc, out, _ = self.exe.run(["shell", "wm", "size"])
        if rc == 0:
            match = re.search(r"Physical size: (\d+)x(\d+)", out)
            if match:
                return int(match.group(1)), int(match.group(2))
        return 1080, 1920  # 默认值


# ==============================================================================
# 功能模块：系统信息
# ==============================================================================
class SystemManager:
    def __init__(self, executor: CommandExecutor):
        self.exe = executor

    def cpu_info(self) -> str:
        rc, out, _ = self.exe.run(["shell", "cat", "/proc/cpuinfo"])
        return out if rc == 0 else "获取失败"

    def mem_info(self) -> str:
        rc, out, _ = self.exe.run(["shell", "cat", "/proc/meminfo"])
        return out if rc == 0 else "获取失败"

    def battery_info(self) -> Dict[str, str]:
        rc, out, _ = self.exe.run(["shell", "dumpsys", "battery"])
        info: Dict[str, str] = {}
        if rc != 0:
            return info
        for line in out.splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                info[key.strip()] = val.strip()
        return info

    def display_info(self) -> Dict[str, str]:
        rc, out, _ = self.exe.run(["shell", "wm", "size"])
        info: Dict[str, str] = {}
        if rc == 0:
            for line in out.splitlines():
                if "Physical size:" in line:
                    info["resolution"] = line.split(":")[1].strip()
        rc2, out2, _ = self.exe.run(["shell", "wm", "density"])
        if rc2 == 0:
            for line in out2.splitlines():
                if "Physical density:" in line:
                    info["density"] = line.split(":")[1].strip()
        return info

    def disk_usage(self) -> str:
        rc, out, _ = self.exe.run(["shell", "df", "-h", "/data"])
        return out if rc == 0 else "获取失败"

    def network_info(self) -> Dict[str, str]:
        """获取网络信息"""
        info: Dict[str, str] = {}
        # IP 地址
        rc, out, _ = self.exe.run(["shell", "ip", "addr"])
        if rc == 0:
            info["ip_addr"] = out[:800]
        # WiFi 信息
        rc2, out2, _ = self.exe.run(["shell", "dumpsys", "wifi", "|", "grep", "SSID"])
        if rc2 == 0:
            info["wifi"] = out2[:300]
        # 路由表
        rc3, out3, _ = self.exe.run(["shell", "ip", "route"])
        if rc3 == 0:
            info["route"] = out3[:300]
        return info

    def performance_monitor(self, duration: int = 10, interval: int = 2) -> None:
        """
        实时性能监控 —— 纯终端表格版

        监控指标：
            - CPU：使用率、核心数、频率、温度
            - 内存：总/已用/可用、ZRAM/Swap
            - 电池：电量、温度、电压、电流、健康状态
            - 存储：内部/外部存储使用率
            - 网络：WiFi 信号强度、IP 地址
            - GPU：频率（如可用）
            - 前台应用与 Top 进程
        """
        Console.info(f"开始性能监控，持续 {duration} 秒，每 {interval} 秒采样一次...")
        Console.info("按 Ctrl+C 提前结束")

        samples = duration // interval
        cpu_history: List[float] = []

        try:
            for i in range(samples):
                # ===== 数据采集 =====

                # --- CPU ---
                rc_cpu, cpu_out, _ = self.exe.run(["shell", "dumpsys", "cpuinfo"])
                cpu_percent = 0.0
                cpu_cores = 0
                cpu_freq = "N/A"
                cpu_temp = "N/A"
                if rc_cpu == 0:
                    # dumpsys cpuinfo 格式示例：
                    # "Load: 3.41 / 2.86 / 2.67 / 100%"
                    # 后面是进程列表，每行：" 12.3% 1234/com.android.systemui: 12% user + 0.3% kernel"
                    for line in cpu_out.splitlines():
                        # 匹配总负载行
                        if "Load:" in line:
                            load_match = re.search(r"Load:\s*([\d.]+)", line)
                            if load_match:
                                # loadavg 除以核心数近似 CPU 使用率
                                load = float(load_match.group(1))
                                rc_cores, cores_out, _ = self.exe.run(["shell", "nproc"])
                                if rc_cores == 0 and cores_out.strip().isdigit():
                                    cpu_cores = int(cores_out.strip())
                                else:
                                    cpu_cores = 8  # 默认值
                                cpu_percent = (load / cpu_cores) * 100
                                if cpu_percent > 100:
                                    cpu_percent = 100.0
                        # 匹配进程 CPU 行（取第一个非系统进程的百分比）
                        proc_match = re.search(r"([\d.]+)%\s+([\d]+)/([A-Za-z0-9._:]+)", line)
                        if proc_match and cpu_percent == 0:
                            cpu_percent = float(proc_match.group(1))

                # CPU 频率
                rc_freq, freq_out, _ = self.exe.run(["shell", "cat", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"])
                if rc_freq == 0 and freq_out.strip().isdigit():
                    cpu_freq = f"{int(freq_out.strip()) / 1000:.0f} MHz"

                # CPU 温度（尝试多个 thermal zone）
                for tz in ["thermal_zone0", "thermal_zone1", "thermal_zone2", "thermal_zone3",
                           "thermal_zone4", "thermal_zone5", "thermal_zone6", "thermal_zone7"]:
                    rc_temp, temp_out, _ = self.exe.run(["shell", "cat", f"/sys/class/thermal/{tz}/temp"])
                    if rc_temp == 0 and temp_out.strip().isdigit():
                        t_val = int(temp_out.strip())
                        if t_val > 1000:
                            cpu_temp = f"{t_val / 1000:.1f}°C"
                        else:
                            cpu_temp = f"{t_val:.1f}°C"
                        break

                cpu_history.append(cpu_percent)

                # --- 内存 ---
                rc_mem, mem_out, _ = self.exe.run(["shell", "dumpsys", "meminfo"])
                mem_total_kb = 0
                mem_used_kb = 0
                mem_free_kb = 0
                swap_total_kb = 0
                swap_used_kb = 0

                if rc_mem == 0:
                    # 解析 meminfo 输出（多种格式兼容）
                    for line in mem_out.splitlines():
                        line = line.strip()
                        # Total RAM: 7,683,380K (status: normal)
                        if line.startswith("Total RAM:"):
                            m = re.search(r"Total RAM:\s*([\d,]+)\s*[Kk]\b", line)
                            if m:
                                mem_total_kb = int(m.group(1).replace(",", ""))
                        # Used RAM: 3,510,234K (1,234K used pss + 2,276K kernel)
                        elif line.startswith("Used RAM:"):
                            m = re.search(r"Used RAM:\s*([\d,]+)\s*[Kk]\b", line)
                            if m:
                                mem_used_kb = int(m.group(1).replace(",", ""))
                        # Free RAM: 4,173,146K (1,234K cached + 2,939K free)
                        elif line.startswith("Free RAM:"):
                            m = re.search(r"Free RAM:\s*([\d,]+)\s*[Kk]\b", line)
                            if m:
                                mem_free_kb = int(m.group(1).replace(",", ""))

                    # 如果 dumpsys meminfo 失败，回退到 /proc/meminfo
                    if mem_total_kb == 0:
                        rc_alt, meminfo_out, _ = self.exe.run(["shell", "cat", "/proc/meminfo"])
                        if rc_alt == 0:
                            mem_available_kb = 0
                            for line in meminfo_out.splitlines():
                                if "MemTotal:" in line:
                                    mem_total_kb = int(line.split()[1])
                                elif "MemAvailable:" in line:
                                    mem_available_kb = int(line.split()[1])
                                    break
                                elif "MemFree:" in line and mem_available_kb == 0:
                                    mem_available_kb = int(line.split()[1])
                            mem_used_kb = mem_total_kb - mem_available_kb if mem_total_kb > 0 else 0
                            mem_free_kb = mem_available_kb

                # Swap
                rc_swap, swap_out, _ = self.exe.run(["shell", "cat", "/proc/swaps"])
                if rc_swap == 0:
                    for line in swap_out.splitlines()[1:]:
                        parts = line.split()
                        if len(parts) >= 4:
                            try:
                                swap_total_kb += int(parts[2])
                                swap_used_kb += int(parts[3])
                            except ValueError:
                                continue

                # --- 电池 ---
                rc_bat, bat_out, _ = self.exe.run(["shell", "dumpsys", "battery"])
                bat_level = "N/A"
                bat_temp = "N/A"
                bat_voltage = "N/A"
                bat_current = "N/A"
                bat_status = "N/A"
                bat_health = "N/A"

                if rc_bat == 0:
                    for line in bat_out.splitlines():
                        line = line.strip()
                        if line.startswith("level:"):
                            bat_level = line.split(":")[1].strip()
                        elif line.startswith("scale:"):
                            # 有些设备用 scale 表示最大电量
                            pass
                        elif line.startswith("temperature:"):
                            t = line.split(":")[1].strip()
                            try:
                                bat_temp = f"{int(t) / 10:.1f}°C"
                            except ValueError:
                                bat_temp = t
                        elif line.startswith("voltage:"):
                            v = line.split(":")[1].strip()
                            try:
                                bat_voltage = f"{int(v) / 1000:.3f}V"
                            except ValueError:
                                bat_voltage = v
                        elif "current" in line.lower():
                            # 匹配 current now:、current:、current_avg: 等
                            c_match = re.search(r"current[_\w]*:\s*(-?[\d]+)", line, re.IGNORECASE)
                            if c_match:
                                c_val = int(c_match.group(1))
                                if abs(c_val) > 1000000:
                                    bat_current = f"{abs(c_val) / 1000000:.2f}A"
                                elif abs(c_val) > 1000:
                                    bat_current = f"{abs(c_val) / 1000:.1f}mA"
                                else:
                                    bat_current = f"{abs(c_val)}mA"
                        elif line.startswith("status:"):
                            bat_status = line.split(":")[1].strip()
                            # 状态码转文字
                            status_map = {"2": "充电中", "3": "放电中", "4": "未充电", "5": "充满"}
                            bat_status = status_map.get(bat_status, bat_status)
                        elif line.startswith("health:"):
                            bat_health = line.split(":")[1].strip()
                            health_map = {"2": "良好", "3": "过热", "4": "报废", "5": "过压", "7": "温度过低"}
                            bat_health = health_map.get(bat_health, bat_health)

                # --- 存储 ---
                rc_stor, stor_out, _ = self.exe.run(["shell", "df", "-h", "/data", "/sdcard"])
                storage_data: List[List[str]] = []
                if rc_stor == 0:
                    for line in stor_out.splitlines()[1:]:
                        parts = line.split()
                        if len(parts) >= 6:
                            mount = parts[0]
                            if mount.startswith("/dev/block/"):
                                mount = mount.replace("/dev/block/", "")
                            elif mount.startswith("/dev/fuse"):
                                mount = "fuse"
                            storage_data.append([mount, parts[1], parts[2], parts[3], parts[4]])

                # --- 网络 ---
                rc_net, net_out, _ = self.exe.run(["shell", "dumpsys", "wifi"])
                wifi_ssid = "N/A"
                wifi_rssi = "N/A"
                wifi_ip = "N/A"

                if rc_net == 0:
                    for line in net_out.splitlines():
                        line = line.strip()
                        # SSID 多种格式
                        if "SSID:" in line and "BSSID" not in line and "Supplicant" not in line:
                            parts = line.split("SSID:")
                            if len(parts) > 1:
                                wifi_ssid = parts[1].strip().strip('"').strip("<>").strip()
                        # RSSI
                        if "RSSI:" in line or "rssi=" in line:
                            rssi_match = re.search(r"[Rr]SSI[:=]\s*(-?\d+)", line)
                            if rssi_match:
                                rssi = int(rssi_match.group(1))
                                wifi_rssi = f"{rssi} dBm ({self._wifi_signal_level(rssi)})"
                        # IP 从 dumpsys wifi 解析
                        if "IpAddress:" in line or "ip_address" in line:
                            ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                            if ip_match:
                                wifi_ip = ip_match.group(1)

                # 备选 IP 获取
                if wifi_ip == "N/A":
                    rc_ip, ip_out, _ = self.exe.run(["shell", "ip", "addr", "show", "wlan0"])
                    if rc_ip == 0:
                        ip_match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", ip_out)
                        if ip_match:
                            wifi_ip = ip_match.group(1)
                    else:
                        rc_if, if_out, _ = self.exe.run(["shell", "ifconfig", "wlan0"])
                        if rc_if == 0:
                            ip_match = re.search(r"inet\s+addr:(\d+\.\d+\.\d+\.\d+)", if_out)
                            if ip_match:
                                wifi_ip = ip_match.group(1)

                # --- GPU ---
                rc_gpu, gpu_out, _ = self.exe.run(["shell", "cat", "/sys/class/kgsl/kgsl-3d0/gpuclk"])
                gpu_freq = "N/A"
                if rc_gpu == 0 and gpu_out.strip().isdigit():
                    gpu_freq = f"{int(gpu_out.strip()) / 1000000:.0f} MHz"
                else:
                    rc_gpu2, gpu_out2, _ = self.exe.run(["shell", "cat", "/sys/class/misc/mali0/device/clock"])
                    if rc_gpu2 == 0 and gpu_out2.strip().isdigit():
                        gpu_freq = f"{int(gpu_out2.strip()) / 1000000:.0f} MHz"
                    else:
                        # 备选：尝试读取所有 kgsl 节点
                        rc_gpu3, gpu_out3, _ = self.exe.run(["shell", "ls", "/sys/class/kgsl/"])
                        if rc_gpu3 == 0 and "kgsl-3d0" in gpu_out3:
                            rc_gpu4, gpu_out4, _ = self.exe.run(["shell", "cat", "/sys/class/kgsl/kgsl-3d0/clock_mhz"])
                            if rc_gpu4 == 0 and gpu_out4.strip().isdigit():
                                gpu_freq = f"{gpu_out4.strip()} MHz"

                # --- Top 进程 ---
                top_processes: List[Tuple[str, str, str]] = []
                if rc_cpu == 0 and cpu_out:
                    proc_lines = []
                    for line in cpu_out.splitlines():
                        # 匹配 " 12.3% 1234/com.android.systemui: 12% user + 0.3% kernel"
                        match = re.search(r"([\d.]+)%\s+([\d]+)/([A-Za-z0-9._:]+)", line)
                        if match:
                            cpu_pct_str, pid, name = match.groups()
                            proc_lines.append((float(cpu_pct_str), pid, name))
                    proc_lines.sort(reverse=True)
                    top_processes = [(p[1], p[2], f"{p[0]:.1f}%") for p in proc_lines[:5]]

                if not top_processes:
                    rc_ps, ps_out, _ = self.exe.run(["shell", "ps", "-A", "-o", "PID,RSS,NAME"])
                    if rc_ps == 0:
                        lines = ps_out.strip().splitlines()[1:]
                        procs = []
                        for line in lines:
                            parts = line.split()
                            if len(parts) >= 3:
                                try:
                                    pid = parts[0]
                                    rss = int(parts[1])
                                    name = parts[2]
                                    procs.append((rss, pid, name))
                                except ValueError:
                                    continue
                        procs.sort(reverse=True)
                        top_processes = [(p[1], p[2], f"{p[0]}KB") for p in procs[:5]]

                # --- 前台应用 ---
                rc_fg, fg_out, _ = self.exe.run(["shell", "dumpsys", "activity", "activities", "|", "grep", "mFocusedWindow"])
                foreground_app = "N/A"
                if rc_fg == 0:
                    fg_match = re.search(r"([a-zA-Z0-9._]+)/[a-zA-Z0-9._]+", fg_out)
                    if fg_match:
                        foreground_app = fg_match.group(1)

                # ===== 渲染 =====
                os.system("cls" if platform.system() == "Windows" else "clear")
                Console.title("实时性能监控")

                # 采样进度
                progress = Console.progress_bar(i + 1, samples, width=30)
                print(f"  {Console._color('采样进度:', ColorCode.DIM)} {progress}")
                print()

                # --- CPU ---
                cpu_color = ColorCode.NEON_GREEN if cpu_percent < 50 else ColorCode.NEON_YELLOW if cpu_percent < 80 else ColorCode.NEON_RED
                self._draw_gauge("CPU 使用率", cpu_percent, 100, cpu_color, suffix="%")
                if len(cpu_history) > 1:
                    self._draw_sparkline(cpu_history, width=40)
                cpu_info = f"    核心: {cpu_cores}核  频率: {cpu_freq}  温度: {Console._color(cpu_temp, ColorCode.NEON_ORANGE)}"
                print(f"  {cpu_info}")
                print()

                # --- 内存 ---
                mem_pct = (mem_used_kb / mem_total_kb * 100) if mem_total_kb > 0 else 0
                mem_color = ColorCode.NEON_GREEN if mem_pct < 60 else ColorCode.NEON_YELLOW if mem_pct < 85 else ColorCode.NEON_RED
                self._draw_gauge("内存使用", mem_pct, 100, mem_color, 
                                 suffix=f"%  ({mem_used_kb//1024}MB / {mem_total_kb//1024}MB)")
                mem_detail = f"    可用: {mem_free_kb//1024}MB  Swap: {swap_used_kb//1024}MB / {swap_total_kb//1024}MB"
                print(f"  {Console._color(mem_detail, ColorCode.DIM)}")
                print()

                # --- 电池 ---
                bat_color = ColorCode.NEON_GREEN if bat_level != "N/A" and int(bat_level) > 20 else ColorCode.NEON_RED
                bat_line = (f"  🔋 电量: {Console._color(bat_level + '%', bat_color)}  "
                           f"温度: {Console._color(bat_temp, ColorCode.NEON_ORANGE)}  "
                           f"电压: {Console._color(bat_voltage, ColorCode.NEON_CYAN)}  "
                           f"电流: {Console._color(bat_current, ColorCode.NEON_PURPLE)}")
                print(bat_line)
                bat_line2 = (f"     状态: {Console._color(bat_status, ColorCode.NEON_BLUE)}  "
                            f"健康: {Console._color(bat_health, ColorCode.NEON_GREEN)}")
                print(bat_line2)
                print()

                # --- 存储 ---
                if storage_data:
                    Console.print_table(["挂载点", "总量", "已用", "可用", "使用率"], 
                                       storage_data[:3], min_width=8)
                print()

                # --- 网络 ---
                net_line = (f"  📡 WiFi: {Console._color(wifi_ssid, ColorCode.NEON_CYAN)}  "
                           f"信号: {Console._color(wifi_rssi, ColorCode.NEON_GREEN)}  "
                           f"IP: {Console._color(wifi_ip, ColorCode.NEON_BLUE)}")
                print(net_line)
                print()

                # --- GPU ---
                if gpu_freq != "N/A":
                    print(f"  🎮 GPU 频率: {Console._color(gpu_freq, ColorCode.NEON_PINK)}")
                    print()

                # --- 前台应用 ---
                print(f"  📱 前台应用: {Console._color(foreground_app, ColorCode.NEON_YELLOW)}")
                print()

                # --- Top 进程 ---
                if top_processes:
                    Console.print_table(["PID", "进程名", "CPU/内存"], 
                                      [[p[0], p[1], p[2]] for p in top_processes], min_width=8)

                print()
                print(f"  {Console._color('按 Ctrl+C 停止', ColorCode.DIM)}")

                if i < samples - 1:
                    time.sleep(interval)

        except KeyboardInterrupt:
            Console.info("\n监控已停止")

    def _draw_gauge(self, label: str, value: float, max_val: float, color: ColorCode, suffix: str = "") -> None:
        """Unicode 条形仪表盘"""
        width = 40
        filled = int((value / max_val) * width) if max_val > 0 else 0
        filled = min(filled, width)
        bar = Console._color("█" * filled, color) + Console._color("░" * (width - filled), ColorCode.DIM)
        val_str = f"{value:.1f}" if isinstance(value, float) else str(value)
        print(f"  {Console._color(label + ':', ColorCode.NEON_CYAN)} {bar} {Console._color(val_str + suffix, color)}")

    def _draw_sparkline(self, data: List[float], width: int = 40) -> None:
        """Unicode Sparkline 迷你折线图"""
        if not data or len(data) < 2:
            return
        blocks = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
        max_val = max(data) if max(data) > 0 else 1
        min_val = min(data)
        range_val = max_val - min_val if max_val != min_val else 1
        if len(data) > width:
            step = len(data) / width
            sampled = [data[int(i * step)] for i in range(width)]
        else:
            sampled = data
        line = ""
        for val in sampled:
            idx = int(((val - min_val) / range_val) * (len(blocks) - 1))
            idx = max(0, min(idx, len(blocks) - 1))
            line += blocks[idx]
        print(f"  {Console._color('趋势:', ColorCode.DIM)} {Console._color(line, ColorCode.NEON_BLUE)}")

    def _wifi_signal_level(self, rssi: int) -> str:
        """WiFi 信号强度分级"""
        if rssi >= -50:
            return "极强"
        elif rssi >= -60:
            return "强"
        elif rssi >= -70:
            return "中等"
        elif rssi >= -80:
            return "弱"
        else:
            return "极弱"


# ==============================================================================
# 功能模块：日志管理
# ==============================================================================
class LogManager:
    def __init__(self, executor: CommandExecutor):
        self.exe = executor
        Config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    def logcat(self, package: Optional[str] = None, lines: int = 50) -> str:
        cmd = ["logcat", "-d", "-t", str(lines)]
        if package:
            rc_pid, out_pid, _ = self.exe.run(["shell", "pidof", package])
            pid = out_pid.strip()
            if rc_pid == 0 and pid:
                cmd = ["logcat", "-d", "--pid", pid, "-t", str(lines)]
        rc, out, _ = self.exe.run(cmd, timeout=30)
        return out if rc == 0 else "日志获取失败"

    def logcat_live(self, package: Optional[str] = None) -> None:
        cmd = ["logcat"]
        if package:
            rc_pid, out_pid, _ = self.exe.run(["shell", "pidof", package])
            pid = out_pid.strip()
            if rc_pid == 0 and pid:
                cmd.extend(["--pid", pid])
        Console.info("开始实时日志输出，按 Ctrl+C 停止...")
        try:
            subprocess.run(self.exe._build_cmd(cmd))
        except KeyboardInterrupt:
            Console.info("\n已停止日志跟踪")

    def export_logcat(self, lines: int = 5000) -> Optional[Path]:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        log_path = Config.LOG_DIR / f"logcat_{timestamp}.txt"
        rc, out, _ = self.exe.run(["logcat", "-d", "-t", str(lines)], timeout=60)
        if rc == 0:
            log_path.write_text(out, encoding="utf-8")
            Console.info(f"日志已导出: {log_path}")
            return log_path
        Console.error("日志导出失败")
        return None


# ==============================================================================
# 功能模块：端口转发
# ==============================================================================
class PortForwardManager:
    """端口转发管理：forward / reverse / list / remove"""

    def __init__(self, executor: CommandExecutor):
        self.exe = executor

    def list_forwards(self) -> str:
        rc, out, _ = self.exe.run(["forward", "--list"])
        return out if rc == 0 else "获取失败"

    def add_forward(self, local: str, remote: str) -> bool:
        """local: tcp:8080, remote: tcp:8080"""
        rc, out, err = self.exe.run(["forward", local, remote])
        if rc == 0:
            Console.info(f"端口转发已建立: {local} → {remote}")
            return True
        Console.error(f"建立失败: {err or out}")
        return False

    def remove_forward(self, local: Optional[str] = None) -> bool:
        cmd = ["forward", "--remove"]
        if local:
            cmd.append(local)
        else:
            cmd = ["forward", "--remove-all"]
        rc, _, _ = self.exe.run(cmd)
        if rc == 0:
            Console.info("端口转发已清除")
            return True
        return False

    def list_reverse(self) -> str:
        rc, out, _ = self.exe.run(["reverse", "--list"])
        return out if rc == 0 else "获取失败"

    def add_reverse(self, remote: str, local: str) -> bool:
        rc, out, err = self.exe.run(["reverse", remote, local])
        if rc == 0:
            Console.info(f"反向转发已建立: {remote} → {local}")
            return True
        Console.error(f"建立失败: {err or out}")
        return False

    def remove_reverse(self, remote: Optional[str] = None) -> bool:
        cmd = ["reverse", "--remove"]
        if remote:
            cmd.append(remote)
        else:
            cmd = ["reverse", "--remove-all"]
        rc, _, _ = self.exe.run(cmd)
        if rc == 0:
            Console.info("反向转发已清除")
            return True
        return False


# ==============================================================================
# 功能模块：文件浏览器
# ==============================================================================
class FileBrowser:
    """简易设备端文件浏览器"""

    def __init__(self, executor: CommandExecutor):
        self.exe = executor
        self.current_path: str = "/sdcard"

    def browse(self) -> None:
        Console.section("设备文件浏览器")
        Console.info("命令: ls | cd <path> | pwd | cat <file> | pull <remote> [local] | exit")
        while True:
            prompt_path = self.current_path if len(self.current_path) < 30 else "..." + self.current_path[-27:]
            cmd = input(f"  {Console._color(prompt_path, ColorCode.NEON_CYAN)} {Console._color('$', ColorCode.NEON_GREEN)} ").strip()
            if cmd.lower() in ("exit", "quit", "q"):
                break
            if not cmd:
                continue
            parts = cmd.split()
            action = parts[0].lower()

            if action == "pwd":
                Console.info(self.current_path)
            elif action == "ls":
                self._ls()
            elif action == "cd" and len(parts) > 1:
                self._cd(parts[1])
            elif action == "cat" and len(parts) > 1:
                self._cat(parts[1])
            elif action == "pull" and len(parts) > 1:
                remote = parts[1] if parts[1].startswith("/") else f"{self.current_path}/{parts[1]}"
                local = parts[2] if len(parts) > 2 else "."
                FileManager(self.exe).pull(remote, local)
            else:
                Console.warn("未知命令")

    def _ls(self) -> None:
        rc, out, _ = self.exe.run(["shell", "ls", "-la", self.current_path])
        if rc == 0:
            print(out)
        else:
            Console.error("无法列出目录")

    def _cd(self, path: str) -> None:
        if path == "..":
            self.current_path = str(Path(self.current_path).parent)
        elif path.startswith("/"):
            self.current_path = path
        else:
            self.current_path = f"{self.current_path}/{path}"
        # 验证路径存在
        rc, _, _ = self.exe.run(["shell", "test", "-d", self.current_path])
        if rc != 0:
            Console.error("目录不存在")
            self.current_path = "/sdcard"

    def _cat(self, filename: str) -> None:
        filepath = filename if filename.startswith("/") else f"{self.current_path}/{filename}"
        rc, out, _ = self.exe.run(["shell", "cat", filepath])
        if rc == 0:
            print(out[:3000])  # 截断避免刷屏
        else:
            Console.error("无法读取文件")


# ==============================================================================
# 菜单系统
# ==============================================================================
class MenuItem:
    def __init__(self, key: str, title: str, handler: Callable[[], None], icon: str = "", color: ColorCode = ColorCode.NEON_CYAN):
        self.key = key
        self.title = title
        self.handler = handler
        self.icon = icon
        self.color = color


class MenuManager:
    def __init__(self):
        self.current_serial: Optional[str] = None
        self.executor = CommandExecutor()
        self.device_mgr = DeviceManager(self.executor)
        self._build_menus()

    def _build_menus(self) -> None:
        self.main_menu: List[MenuItem] = [
            MenuItem("1", "设备管理", self._device_menu, "phone", ColorCode.NEON_CYAN),
            MenuItem("2", "应用管理", self._app_menu, "package", ColorCode.NEON_PURPLE),
            MenuItem("3", "文件传输", self._file_menu, "folder", ColorCode.NEON_BLUE),
            MenuItem("4", "屏幕与媒体", self._screen_menu, "camera", ColorCode.NEON_PINK),
            MenuItem("5", "系统信息", self._system_menu, "cpu", ColorCode.NEON_GREEN),
            MenuItem("6", "日志与调试", self._log_menu, "log", ColorCode.NEON_YELLOW),
            MenuItem("7", "快捷执行命令", self._quick_exec_menu, "arrow", ColorCode.NEON_ORANGE),
            MenuItem("8", "交互式 Shell", self._shell_menu, "shell", ColorCode.NEON_PINK),
            MenuItem("9", "切换/选择设备", self._select_device, "swap", ColorCode.NEON_CYAN),
            MenuItem("0", "退出程序", self._exit, "exit", ColorCode.NEON_RED),
        ]

    def _print_banner(self) -> None:
        Console.banner()
        if self.current_serial:
            status = "已连接"
            device_color = ColorCode.NEON_GREEN
        else:
            status = "未选择"
            device_color = ColorCode.NEON_ORANGE
        panel_lines = [
            Console._color(f"当前设备: {self.current_serial or '未连接'}", ColorCode.NEON_CYAN),
            Console._color(f"状态: {status}", device_color),
        ]
        Console._panel(panel_lines, width=50, border_color=ColorCode.NEON_PURPLE)
        print()

    def _show_menu(self, title: str, items: List[MenuItem]) -> None:
        Console.title(title)
        for item in items:
            Console.menu_item(item.key, item.title, item.icon, item.color)
        Console.menu_divider()
        Console.menu_item("0", "返回上级", "", ColorCode.DIM)

    def _choose(self, items: List[MenuItem]) -> Optional[MenuItem]:
        choice = Console.prompt("请输入选项编号").strip()
        if choice == "0":
            return None
        for item in items:
            if item.key == choice:
                return item
        Console.error("无效选项，请重新输入")
        return None

    def _ensure_device(self) -> bool:
        if not self.current_serial:
            Console.warn("尚未选择设备，请先选择设备")
            self._select_device()
        return bool(self.current_serial)

    def _select_device(self) -> None:
        devices = self.device_mgr.list_devices()
        if not devices:
            Console.error("未检测到任何设备，请通过 USB 连接或检查网络连接")
            return
        Console.section("可用设备列表")
        for idx, dev in enumerate(devices, 1):
            Console.device_card(f"[{idx}] {dev.serial}", dev.status, dev.model)
        print()
        choice = Console.prompt("输入序号选择设备（或输入 IP:Port 连接新设备）").strip()
        if ":" in choice:
            parts = choice.split(":")
            if len(parts) == 2 and parts[1].isdigit():
                if self.device_mgr.connect(parts[0], int(parts[1])):
                    self.current_serial = choice
                return
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(devices):
                selected = devices[idx]
                if not selected.is_online:
                    Console.warn("该设备未处于在线状态，可能无法执行部分命令")
                self.current_serial = selected.serial
                Console.info(f"已选择设备: {selected.serial} ({selected.model})")
            else:
                Console.error("序号超出范围")
        except ValueError:
            Console.error("输入无效")

    # --------------------------------------------------------------------------
    # 1. 设备管理
    # --------------------------------------------------------------------------
    def _device_menu(self) -> None:
        items = [
            MenuItem("1", "列出所有设备", self._list_devices, "phone", ColorCode.NEON_CYAN),
            MenuItem("2", "连接网络设备", self._connect_device, "swap", ColorCode.NEON_BLUE),
            MenuItem("3", "断开网络设备", self._disconnect_device, "exit", ColorCode.NEON_ORANGE),
            MenuItem("4", "查看设备详细信息", self._device_detail, "cpu", ColorCode.NEON_PURPLE),
            MenuItem("5", "重启设备", self._reboot_device, "restart", ColorCode.NEON_YELLOW),
            MenuItem("6", "重启到 Recovery", self._reboot_recovery, "restart", ColorCode.NEON_PINK),
            MenuItem("7", "重启到 Bootloader", self._reboot_bootloader, "restart", ColorCode.NEON_RED),
            MenuItem("8", "导出 Bugreport", self._export_bugreport, "bug", ColorCode.NEON_GREEN),
        ]
        while True:
            self._show_menu("设备管理", items)
            item = self._choose(items)
            if item is None:
                break
            item.handler()
            Console.pause()

    def _list_devices(self) -> None:
        devices = self.device_mgr.list_devices()
        if not devices:
            Console.warn("暂无设备")
            return
        rows = [[d.serial, Console.status_badge(d.status), d.model, d.product, d.transport_id] for d in devices]
        Console.print_table(["序列号", "状态", "型号", "产品", "Transport ID"], rows)

    def _connect_device(self) -> None:
        host = Console.prompt("请输入设备 IP 地址")
        port_str = Console.prompt("请输入端口（默认 5555）").strip()
        port = int(port_str) if port_str.isdigit() else 5555
        self.device_mgr.connect(host, port)

    def _disconnect_device(self) -> None:
        host = Console.prompt("请输入要断开的 IP:Port（留空断开全部）").strip()
        self.device_mgr.disconnect(host if host else None)

    def _device_detail(self) -> None:
        if not self._ensure_device():
            return
        props = DeviceManager(CommandExecutor(self.current_serial)).get_device_info(self.current_serial)
        Console.section("设备详细信息")
        rows = [[k, v] for k, v in props.items()]
        Console.print_table(["属性", "值"], rows)

    def _reboot_device(self) -> None:
        if not self._ensure_device():
            return
        if Console.confirm("确定要重启设备吗？"):
            DeviceManager(CommandExecutor(self.current_serial)).reboot()

    def _reboot_recovery(self) -> None:
        if not self._ensure_device():
            return
        if Console.confirm("确定要重启到 Recovery 吗？"):
            DeviceManager(CommandExecutor(self.current_serial)).reboot("recovery")

    def _reboot_bootloader(self) -> None:
        if not self._ensure_device():
            return
        if Console.confirm("确定要重启到 Bootloader 吗？"):
            DeviceManager(CommandExecutor(self.current_serial)).reboot("bootloader")

    def _export_bugreport(self) -> None:
        if not self._ensure_device():
            return
        DeviceManager(CommandExecutor(self.current_serial)).bugreport()

    # --------------------------------------------------------------------------
    # 2. 应用管理
    # --------------------------------------------------------------------------
    def _app_menu(self) -> None:
        if not self._ensure_device():
            return
        items = [
            MenuItem("1", "列出所有应用", self._list_apps, "package", ColorCode.NEON_CYAN),
            MenuItem("2", "列出系统应用", self._list_system_apps, "package", ColorCode.NEON_BLUE),
            MenuItem("3", "列出第三方应用", self._list_third_apps, "package", ColorCode.NEON_PURPLE),
            MenuItem("4", "查看应用详情", self._app_detail, "zoom", ColorCode.NEON_GREEN),
            MenuItem("5", "安装 APK", self._install_app, "folder", ColorCode.NEON_GREEN),
            MenuItem("6", "批量安装 APK", self._batch_install, "folder", ColorCode.NEON_YELLOW),
            MenuItem("7", "卸载应用", self._uninstall_app, "exit", ColorCode.NEON_RED),
            MenuItem("8", "清除应用数据", self._clear_app_data, "warn", ColorCode.NEON_ORANGE),
            MenuItem("9", "启动应用", self._start_app, "phone", ColorCode.NEON_PINK),
            MenuItem("10", "冻结应用", self._freeze_app, "freeze", ColorCode.NEON_BLUE),
            MenuItem("11", "解冻应用", self._unfreeze_app, "unfreeze", ColorCode.NEON_YELLOW),
            MenuItem("12", "提取 APK", self._extract_apk, "extract", ColorCode.NEON_CYAN),
        ]
        while True:
            self._show_menu("应用管理", items)
            item = self._choose(items)
            if item is None:
                break
            item.handler()
            Console.pause()

    def _list_apps(self) -> None:
        mgr = AppManager(CommandExecutor(self.current_serial))
        apps = mgr.list_packages()
        rows = [[a.package_name, "系统" if a.is_system_app else "第三方"] for a in apps[:50]]
        Console.print_table(["包名", "类型"], rows)
        if len(apps) > 50:
            Console.warn(f"仅显示前 50 条，共 {len(apps)} 个应用")

    def _list_system_apps(self) -> None:
        mgr = AppManager(CommandExecutor(self.current_serial))
        apps = mgr.list_packages(system_only=True)
        rows = [[a.package_name] for a in apps[:50]]
        Console.print_table(["系统应用包名"], rows)

    def _list_third_apps(self) -> None:
        mgr = AppManager(CommandExecutor(self.current_serial))
        apps = mgr.list_packages(third_only=True)
        rows = [[a.package_name] for a in apps[:50]]
        Console.print_table(["第三方应用包名"], rows)

    def _app_detail(self) -> None:
        pkg = Console.prompt("请输入包名").strip()
        detail = AppManager(CommandExecutor(self.current_serial)).get_package_detail(pkg)
        Console.section(f"应用详情: {pkg}")
        for key, val in detail.items():
            print(f"\n{Console._color(key, ColorCode.NEON_CYAN)}:")
            print(val)

    def _install_app(self) -> None:
        path = Console.prompt("请输入本地 APK 文件完整路径").strip()
        AppManager(CommandExecutor(self.current_serial)).install(path)

    def _batch_install(self) -> None:
        path = Console.prompt("请输入 APK 所在目录路径").strip()
        AppManager(CommandExecutor(self.current_serial)).batch_install(path)

    def _uninstall_app(self) -> None:
        pkg = Console.prompt("请输入要卸载的包名").strip()
        AppManager(CommandExecutor(self.current_serial)).uninstall(pkg)

    def _clear_app_data(self) -> None:
        pkg = Console.prompt("请输入要清除数据的包名").strip()
        AppManager(CommandExecutor(self.current_serial)).clear_data(pkg)

    def _start_app(self) -> None:
        pkg = Console.prompt("请输入要启动的包名").strip()
        AppManager(CommandExecutor(self.current_serial)).start_app(pkg)

    def _freeze_app(self) -> None:
        pkg = Console.prompt("请输入要冻结的包名").strip()
        AppManager(CommandExecutor(self.current_serial)).freeze_app(pkg)

    def _unfreeze_app(self) -> None:
        pkg = Console.prompt("请输入要解冻的包名").strip()
        AppManager(CommandExecutor(self.current_serial)).unfreeze_app(pkg)

    def _extract_apk(self) -> None:
        pkg = Console.prompt("请输入要提取 APK 的包名").strip()
        AppManager(CommandExecutor(self.current_serial)).extract_apk(pkg)

    # --------------------------------------------------------------------------
    # 3. 文件传输
    # --------------------------------------------------------------------------
    def _file_menu(self) -> None:
        if not self._ensure_device():
            return
        items = [
            MenuItem("1", "推送文件到设备", self._push_file, "folder", ColorCode.NEON_GREEN),
            MenuItem("2", "从设备拉取文件", self._pull_file, "folder", ColorCode.NEON_BLUE),
            MenuItem("3", "设备文件浏览器", self._file_browser, "zoom", ColorCode.NEON_PURPLE),
        ]
        while True:
            self._show_menu("文件传输", items)
            item = self._choose(items)
            if item is None:
                break
            item.handler()
            Console.pause()

    def _push_file(self) -> None:
        local = Console.prompt("本地文件路径").strip()
        remote = Console.prompt("设备目标路径（如 /sdcard/Download/）").strip()
        FileManager(CommandExecutor(self.current_serial)).push(local, remote)

    def _pull_file(self) -> None:
        remote = Console.prompt("设备文件路径").strip()
        local = Console.prompt("本地保存路径（默认当前目录）").strip() or "."
        FileManager(CommandExecutor(self.current_serial)).pull(remote, local)

    def _file_browser(self) -> None:
        FileBrowser(CommandExecutor(self.current_serial)).browse()

    # --------------------------------------------------------------------------
    # 4. 屏幕与媒体
    # --------------------------------------------------------------------------
    def _screen_menu(self) -> None:
        if not self._ensure_device():
            return
        items = [
            MenuItem("1", "截图", self._screenshot, "camera", ColorCode.NEON_CYAN),
            MenuItem("2", "截图并打开", self._screenshot_open, "camera", ColorCode.NEON_GREEN),
            MenuItem("3", "录屏", self._screenrecord, "film", ColorCode.NEON_PINK),
            MenuItem("4", "输入模拟", self._input_menu, "tap", ColorCode.NEON_ORANGE),
        ]
        while True:
            self._show_menu("屏幕与媒体", items)
            item = self._choose(items)
            if item is None:
                break
            item.handler()
            Console.pause()

    def _screenshot(self) -> None:
        ScreenManager(CommandExecutor(self.current_serial)).screenshot(auto_open=False)

    def _screenshot_open(self) -> None:
        ScreenManager(CommandExecutor(self.current_serial)).screenshot(auto_open=True)

    def _screenrecord(self) -> None:
        duration = Console.prompt("录屏时长（秒，默认 10）").strip()
        dur = int(duration) if duration.isdigit() else 10
        bitrate = Console.prompt("比特率（默认 8000000）").strip() or "8000000"
        ScreenManager(CommandExecutor(self.current_serial)).screenrecord(dur, bitrate)

    def _input_menu(self) -> None:
        if not self._ensure_device():
            return
        items = [
            MenuItem("1", "模拟点击", self._input_tap, "tap", ColorCode.NEON_CYAN),
            MenuItem("2", "模拟滑动", self._input_swipe, "swipe", ColorCode.NEON_PURPLE),
            MenuItem("3", "模拟文本输入", self._input_text, "keyboard", ColorCode.NEON_GREEN),
            MenuItem("4", "模拟按键", self._input_keyevent, "keyboard", ColorCode.NEON_YELLOW),
            MenuItem("5", "获取屏幕分辨率", self._input_get_size, "display", ColorCode.NEON_BLUE),
        ]
        while True:
            self._show_menu("输入模拟", items)
            item = self._choose(items)
            if item is None:
                break
            item.handler()
            Console.pause()

    def _input_tap(self) -> None:
        x = Console.prompt("X 坐标").strip()
        y = Console.prompt("Y 坐标").strip()
        if x.isdigit() and y.isdigit():
            InputManager(CommandExecutor(self.current_serial)).tap(int(x), int(y))

    def _input_swipe(self) -> None:
        x1 = Console.prompt("起点 X").strip()
        y1 = Console.prompt("起点 Y").strip()
        x2 = Console.prompt("终点 X").strip()
        y2 = Console.prompt("终点 Y").strip()
        dur = Console.prompt("滑动时长 ms（默认 300）").strip() or "300"
        if all(v.isdigit() for v in [x1, y1, x2, y2, dur]):
            InputManager(CommandExecutor(self.current_serial)).swipe(int(x1), int(y1), int(x2), int(y2), int(dur))

    def _input_text(self) -> None:
        text = Console.prompt("请输入要发送的文本").strip()
        if text:
            InputManager(CommandExecutor(self.current_serial)).text(text)

    def _input_keyevent(self) -> None:
        Console.info("常用按键: HOME, BACK, POWER, VOLUME_UP, VOLUME_DOWN, MENU, ENTER, SPACE, DEL, RECENT")
        key = Console.prompt("按键名称").strip()
        if key:
            InputManager(CommandExecutor(self.current_serial)).keyevent(key)

    def _input_get_size(self) -> None:
        w, h = InputManager(CommandExecutor(self.current_serial)).get_screen_size()
        Console.info(f"屏幕分辨率: {w} x {h}")

    # --------------------------------------------------------------------------
    # 5. 系统信息
    # --------------------------------------------------------------------------
    def _system_menu(self) -> None:
        if not self._ensure_device():
            return
        items = [
            MenuItem("1", "CPU 信息", self._cpu_info, "cpu", ColorCode.NEON_CYAN),
            MenuItem("2", "内存信息", self._mem_info, "cpu", ColorCode.NEON_BLUE),
            MenuItem("3", "电池状态", self._battery_info, "battery", ColorCode.NEON_YELLOW),
            MenuItem("4", "显示分辨率", self._display_info, "display", ColorCode.NEON_PURPLE),
            MenuItem("5", "存储使用情况", self._disk_usage, "disk", ColorCode.NEON_GREEN),
            MenuItem("6", "网络信息", self._network_info, "wifi", ColorCode.NEON_CYAN),
            MenuItem("7", "实时性能监控", self._perf_monitor, "chart", ColorCode.NEON_ORANGE),
        ]
        while True:
            self._show_menu("系统信息", items)
            item = self._choose(items)
            if item is None:
                break
            item.handler()
            Console.pause()

    def _cpu_info(self) -> None:
        out = SystemManager(CommandExecutor(self.current_serial)).cpu_info()
        print(out)

    def _mem_info(self) -> None:
        out = SystemManager(CommandExecutor(self.current_serial)).mem_info()
        print(out)

    def _battery_info(self) -> None:
        info = SystemManager(CommandExecutor(self.current_serial)).battery_info()
        rows = [[k, v] for k, v in info.items()]
        Console.print_table(["属性", "值"], rows)

    def _display_info(self) -> None:
        info = SystemManager(CommandExecutor(self.current_serial)).display_info()
        rows = [[k, v] for k, v in info.items()]
        Console.print_table(["属性", "值"], rows)

    def _disk_usage(self) -> None:
        out = SystemManager(CommandExecutor(self.current_serial)).disk_usage()
        print(out)

    def _network_info(self) -> None:
        info = SystemManager(CommandExecutor(self.current_serial)).network_info()
        Console.section("网络信息")
        for key, val in info.items():
            print(f"\n{Console._color(key, ColorCode.NEON_CYAN)}:")
            print(val)

    def _perf_monitor(self) -> None:
        duration = Console.prompt("监控时长（秒，默认 10）").strip()
        interval = Console.prompt("采样间隔（秒，默认 2）").strip()
        dur = int(duration) if duration.isdigit() else 10
        inter = int(interval) if interval.isdigit() else 2
        SystemManager(CommandExecutor(self.current_serial)).performance_monitor(dur, inter)

    # --------------------------------------------------------------------------
    # 6. 日志与调试
    # --------------------------------------------------------------------------
    def _log_menu(self) -> None:
        if not self._ensure_device():
            return
        items = [
            MenuItem("1", "查看最近日志", self._logcat_recent, "log", ColorCode.NEON_CYAN),
            MenuItem("2", "实时跟踪日志", self._logcat_live, "bug", ColorCode.NEON_ORANGE),
            MenuItem("3", "导出日志到文件", self._export_logcat, "folder", ColorCode.NEON_GREEN),
            MenuItem("4", "端口转发管理", self._forward_menu, "forward", ColorCode.NEON_PURPLE),
        ]
        while True:
            self._show_menu("日志与调试", items)
            item = self._choose(items)
            if item is None:
                break
            item.handler()
            Console.pause()

    def _logcat_recent(self) -> None:
        lines = Console.prompt("查看行数（默认 100）").strip()
        n = int(lines) if lines.isdigit() else 100
        pkg = Console.prompt("按包名过滤（留空不过滤）").strip() or None
        out = LogManager(CommandExecutor(self.current_serial)).logcat(pkg, n)
        print(out)

    def _logcat_live(self) -> None:
        pkg = Console.prompt("按包名过滤（留空不过滤）").strip() or None
        LogManager(CommandExecutor(self.current_serial)).logcat_live(pkg)

    def _export_logcat(self) -> None:
        lines = Console.prompt("导出行数（默认 5000）").strip()
        n = int(lines) if lines.isdigit() else 5000
        LogManager(CommandExecutor(self.current_serial)).export_logcat(n)

    def _forward_menu(self) -> None:
        items = [
            MenuItem("1", "列出转发规则", self._forward_list, "forward", ColorCode.NEON_CYAN),
            MenuItem("2", "添加端口转发", self._forward_add, "forward", ColorCode.NEON_GREEN),
            MenuItem("3", "添加反向转发", self._reverse_add, "forward", ColorCode.NEON_PURPLE),
            MenuItem("4", "清除转发规则", self._forward_remove, "exit", ColorCode.NEON_RED),
        ]
        while True:
            self._show_menu("端口转发", items)
            item = self._choose(items)
            if item is None:
                break
            item.handler()
            Console.pause()

    def _forward_list(self) -> None:
        out = PortForwardManager(self.executor).list_forwards()
        print(out if out.strip() else "暂无转发规则")
        print()
        out2 = PortForwardManager(self.executor).list_reverse()
        print(Console._color("反向转发:", ColorCode.NEON_PURPLE))
        print(out2 if out2.strip() else "暂无反向转发规则")

    def _forward_add(self) -> None:
        local = Console.prompt("本地端口（格式 tcp:8080）").strip()
        remote = Console.prompt("设备端口（格式 tcp:8080）").strip()
        if local and remote:
            PortForwardManager(self.executor).add_forward(local, remote)

    def _reverse_add(self) -> None:
        remote = Console.prompt("设备端口（格式 tcp:8080）").strip()
        local = Console.prompt("本地端口（格式 tcp:8080）").strip()
        if remote and local:
            PortForwardManager(self.executor).add_reverse(remote, local)

    def _forward_remove(self) -> None:
        all_rules = Console.confirm("清除所有转发规则（含反向）？")
        mgr = PortForwardManager(self.executor)
        if all_rules:
            mgr.remove_forward(None)
            mgr.remove_reverse(None)
        else:
            local = Console.prompt("要清除的本地端口（格式 tcp:8080，留空取消）").strip()
            if local:
                mgr.remove_forward(local)

    # --------------------------------------------------------------------------
    # 7. 快捷执行命令
    # --------------------------------------------------------------------------
    def _quick_exec_menu(self) -> None:
        if not self._ensure_device():
            return
        Console.section("快捷执行设备命令")
        Console.info("输入 'exit' 返回上级菜单")
        Console.info("示例: sh /sdcard/script.sh")
        Console.info("示例: chmod +x /data/local/tmp/tool")
        print()
        exe = CommandExecutor(self.current_serial)
        while True:
            cmd = Console.prompt("device").strip()
            if cmd.lower() in ("exit", "quit", "q"):
                break
            if not cmd:
                continue
            Console.info(f"执行: {cmd}")
            rc, out, err = exe.run(["shell", cmd], timeout=120)
            if out.strip():
                print(out)
            if err.strip():
                filtered = "\n".join(line for line in err.splitlines() if not any(x in line for x in ["WARNING:", "* daemon", "^C"]))
                if filtered.strip():
                    Console.error(filtered)
            if rc != 0:
                Console.warn(f"返回码: {rc}")
            else:
                Console.info("执行完成")
            print()

    # --------------------------------------------------------------------------
    # 8. 交互式 Shell
    # --------------------------------------------------------------------------
    def _shell_menu(self) -> None:
        if not self._ensure_device():
            return
        Console.section("交互式 Shell 会话")
        Console.info("已进入设备 Shell，支持 Tab 补全、上下箭头历史")
        Console.info("输入 'exit' 或按 Ctrl+D 返回上级菜单")
        print()
        exe = CommandExecutor(self.current_serial)
        try:
            subprocess.run(exe._build_cmd(["shell"]))
        except KeyboardInterrupt:
            pass
        print()
        Console.info("已退出 Shell 会话")

    # --------------------------------------------------------------------------
    # 0. 退出
    # --------------------------------------------------------------------------
    def _exit(self) -> None:
        Console.info("感谢使用，再见！")
        sys.exit(0)

    # --------------------------------------------------------------------------
    # 主循环
    # --------------------------------------------------------------------------
    def run(self) -> None:
        while True:
            os.system("cls" if platform.system() == "Windows" else "clear")
            self._print_banner()
            for item in self.main_menu:
                Console.menu_item(item.key, item.title, item.icon, item.color)
            print()
            choice = Console.prompt("请输入主菜单选项编号").strip()
            for item in self.main_menu:
                if item.key == choice:
                    item.handler()
                    if choice != "0":
                        Console.pause()
                    break
            else:
                Console.error("无效选项")
                Console.pause()


# ==============================================================================
# 程序入口
# ==============================================================================
def main() -> None:
    try:
        app = MenuManager()
        app.run()
    except KeyboardInterrupt:
        Console.info("\n程序被用户中断")
        sys.exit(0)
    except Exception as e:
        Console.error(f"程序异常: {e}")
        raise


if __name__ == "__main__":
    main()