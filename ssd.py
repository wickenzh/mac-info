import datetime as dt
import faulthandler
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QColor, QFont, QPainter, QPen
    from PyQt6.QtWidgets import (
        QApplication,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    print(f"PyQt6 未安装或无法加载：{exc}")
    print("请先运行：python3 -m pip install -r requirements.txt")
    sys.exit(1)


WINDOW_BG = "#171717"
CARD_BG = "#242424"
CARD_BORDER = "#444444"
TEXT_COLOR = "#f7f7f7"
MUTED_TEXT = "#a7a7a7"
BLUE = "#64b5f6"
GREEN = "#58d079"
YELLOW = "#ffc857"
RED = "#ff5a5f"
CRASH_LOG = Path(__file__).with_name("mac_info_crash.log")


def install_crash_logger():
    log_file = open(CRASH_LOG, "a", encoding="utf-8")
    log_file.write(f"\n\n===== {dt.datetime.now().isoformat(timespec='seconds')} =====\n")
    log_file.flush()
    faulthandler.enable(log_file)

    def handle_exception(exc_type, exc, traceback):
        import traceback as traceback_module

        traceback_module.print_exception(exc_type, exc, traceback, file=log_file)
        log_file.flush()
        sys.__excepthook__(exc_type, exc, traceback)

    sys.excepthook = handle_exception
    return log_file


def run_command(args, timeout=12):
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc), 1


def extract(pattern, text, default="N/A", flags=0):
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else default


def first_present(*values, default="N/A"):
    for value in values:
        if value not in (None, "", "N/A", "未知"):
            return str(value).strip()
    return default


def find_smartctl():
    candidates = [
        shutil.which("smartctl"),
        "/opt/homebrew/bin/smartctl",
        "/usr/local/bin/smartctl",
        "/usr/sbin/smartctl",
    ]
    for candidate in candidates:
        if candidate and shutil.which(candidate):
            return candidate
    return None


def get_hardware_info():
    stdout, _, _ = run_command(["system_profiler", "SPHardwareDataType"])
    return {
        "model_name": extract(r"Model Name:\s+(.+)", stdout, "未知"),
        "model_id": extract(r"Model Identifier:\s+(.+)", stdout, "未知"),
        "chip": first_present(
            extract(r"Chip:\s+(.+)", stdout, ""),
            extract(r"Processor Name:\s+(.+)", stdout, ""),
            default="未知",
        ),
        "serial": extract(r"Serial Number \(system\):\s+(.+)", stdout, "未知"),
    }


def run_smartctl():
    smartctl = find_smartctl()
    if not smartctl:
        return "", "未找到 smartctl。可安装 smartmontools 后读取 SSD SMART 信息。"

    targets = ["disk0", "/dev/disk0", "disk1", "/dev/disk1"]
    errors = []
    for target in targets:
        stdout, stderr, code = run_command([smartctl, "-a", target])
        if code == 0 and stdout:
            return stdout, ""
        if stdout and ("SMART" in stdout or "NVMe" in stdout):
            return stdout, ""
        if stderr:
            errors.append(stderr)

    return "", errors[-1] if errors else "smartctl 未能读取磁盘信息。"


def parse_ssd_data(data):
    info = {}
    if not data:
        return info

    info["型号"] = first_present(
        extract(r"Model Number:\s+(.+)", data, ""),
        extract(r"Device Model:\s+(.+)", data, ""),
        extract(r"Product:\s+(.+)", data, ""),
    )
    info["健康状态"] = first_present(
        extract(r"SMART overall-health self-assessment test result:\s+(.+)", data, ""),
        extract(r"SMART Health Status:\s+(.+)", data, ""),
        extract(r"SMART overall-health.*?:\s+(.+)", data, ""),
    )
    info["温度"] = first_present(
        extract(r"Temperature:\s+(\d+\s+Celsius)", data, ""),
        extract(r"Temperature Sensor \d+:\s+(\d+\s+Celsius)", data, ""),
    )
    info["寿命损耗"] = extract(r"Percentage Used:\s+(\d+%)", data)
    info["总读取量"] = extract(r"Data Units Read:\s+.+\[(.+)\]", data)
    info["总写入量"] = extract(r"Data Units Written:\s+.+\[(.+)\]", data)

    power_hours = extract(r"Power On Hours:\s+([\d,]+)", data, "")
    power_hours = power_hours.replace(",", "")
    info["总负载时间"] = f"{power_hours}h" if power_hours.isdigit() else "N/A"
    info["异常断电"] = first_present(
        extract(r"Unsafe Shutdowns:\s+(\d+)", data, ""),
        extract(r"Power-Off_Retract_Count\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(\d+)", data, ""),
    )
    info["数据错误"] = first_present(
        extract(r"Media and Data Integrity Errors:\s+(\d+)", data, ""),
        extract(r"Media_Wearout_Indicator.+?(\d+)$", data, "", re.MULTILINE),
    )
    return info


def get_disk_usage_info():
    try:
        usage = shutil.disk_usage("/")
        total = usage.total / (1024**3)
        used = usage.used / (1024**3)
        percent = used / total * 100 if total else 0
        return {"硬盘容量": f"{total:.0f} GB / 已用 {used:.0f} GB ({percent:.0f}%)"}
    except OSError:
        return {"硬盘容量": "读取失败"}


def parse_ioreg_value(text, key):
    quoted = re.search(rf'"{re.escape(key)}"\s+=\s+"([^"]*)"', text)
    if quoted:
        return quoted.group(1)
    raw = re.search(rf'"{re.escape(key)}"\s+=\s+([^\n\r]+)', text)
    if raw:
        return raw.group(1).strip().strip("{}")
    return None


def parse_bool(value):
    if value is None:
        return None
    value = str(value).strip().lower()
    if value in ("yes", "true", "1"):
        return True
    if value in ("no", "false", "0"):
        return False
    return None


def decode_apple_battery_date(value):
    try:
        raw = int(str(value), 0)
    except (TypeError, ValueError):
        return None

    day = raw & 0x1F
    month = (raw >> 5) & 0x0F
    year = ((raw >> 9) & 0x7F) + 1980
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def parse_temperature(value):
    try:
        raw = float(str(value))
    except (TypeError, ValueError):
        return "N/A"

    if raw > 1000:
        celsius = raw / 10 - 273.15
    elif raw > 100:
        celsius = raw / 10
    else:
        celsius = raw
    return f"{celsius:.1f} °C"


def parse_system_profiler_power():
    stdout, _, code = run_command(["system_profiler", "SPPowerDataType", "-json"])
    if code != 0 or not stdout:
        return {}
    try:
        payload = json.loads(stdout)
    except ValueError:
        return {}

    batteries = []
    for item in payload.get("SPPowerDataType", []):
        batteries.extend(item.get("sppower_battery_information", []) or [])
        batteries.extend(item.get("_items", []) or [])
    return batteries[0] if batteries else {}


@dataclass
class BatteryInfo:
    rows: dict
    percent: Optional[int]
    health_percent: Optional[int]
    available: bool


def get_battery_info():
    stdout, _, _ = run_command(["ioreg", "-r", "-c", "AppleSmartBattery"])
    profiler = parse_system_profiler_power()

    if not stdout or "AppleSmartBattery" not in stdout:
        return BatteryInfo({"电池": "无内置电池"}, None, None, False)

    installed = parse_bool(parse_ioreg_value(stdout, "BatteryInstalled"))
    max_capacity_probe = parse_ioreg_value(stdout, "MaxCapacity")
    current_capacity_probe = parse_ioreg_value(stdout, "CurrentCapacity")
    if installed is False or (max_capacity_probe == "0" and current_capacity_probe == "0"):
        return BatteryInfo({"电池": "无内置电池"}, None, None, False)

    manufacturer = first_present(
        parse_ioreg_value(stdout, "Manufacturer"),
        profiler.get("sppower_battery_model_info", {}).get("sppower_battery_manufacturer"),
        default="未知",
    )
    serial = first_present(
        parse_ioreg_value(stdout, "Serial"),
        parse_ioreg_value(stdout, "BatterySerialNumber"),
        profiler.get("sppower_battery_model_info", {}).get("sppower_battery_serial_number"),
        default="未知",
    )
    cycle_count = first_present(
        parse_ioreg_value(stdout, "CycleCount"),
        profiler.get("sppower_battery_health_info", {}).get("sppower_battery_cycle_count"),
        default="N/A",
    )

    manufacture_date = decode_apple_battery_date(parse_ioreg_value(stdout, "ManufactureDate"))
    manufacture_text = manufacture_date.isoformat() if manufacture_date else "未知"
    age_text = "未知"
    if manufacture_date:
        age_days = (dt.date.today() - manufacture_date).days
        age_text = f"{max(age_days, 0)} 天"

    temp = parse_temperature(parse_ioreg_value(stdout, "Temperature"))
    external_connected = parse_bool(parse_ioreg_value(stdout, "ExternalConnected"))
    adapter = "已连接" if external_connected else "未连接"

    current_capacity = parse_ioreg_value(stdout, "CurrentCapacity")
    max_capacity = first_present(parse_ioreg_value(stdout, "AppleRawMaxCapacity"), parse_ioreg_value(stdout, "MaxCapacity"), default="")
    design_capacity = first_present(parse_ioreg_value(stdout, "DesignCapacity"), parse_ioreg_value(stdout, "DesignCycleCount9C"), default="")

    percent = None
    try:
        percent = round(int(current_capacity) / int(max_capacity) * 100)
    except (TypeError, ValueError, ZeroDivisionError):
        pmset, _, _ = run_command(["pmset", "-g", "batt"])
        pmset_percent = extract(r"(\d+)%", pmset, "")
        percent = int(pmset_percent) if pmset_percent.isdigit() else None

    health_percent = None
    try:
        health_percent = round(int(max_capacity) / int(design_capacity) * 100)
    except (TypeError, ValueError, ZeroDivisionError):
        pass

    rows = {
        "制造商": manufacturer,
        "制造日期": manufacture_text,
        "年龄": age_text,
        "负载循环次数": cycle_count,
        "序列": serial,
        "电池温度": temp,
        "电源适配器": adapter,
    }
    if health_percent is not None:
        rows["容量健康度"] = f"{health_percent}%"
    if percent is not None:
        rows["当前电量"] = f"{percent}%"

    return BatteryInfo(rows, percent, health_percent, True)


def health_color(percent_text):
    try:
        percent = int(str(percent_text).replace("%", ""))
    except ValueError:
        return TEXT_COLOR
    if percent < 10:
        return GREEN
    if percent < 30:
        return YELLOW
    return RED


class BatteryGauge(QWidget):
    def __init__(self):
        super().__init__()
        self.percent = None
        self.available = False
        self.setMinimumHeight(58)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, percent, available):
        self.percent = percent
        self.available = available
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(8, 10, -20, -10)
        radius = 11
        painter.setPen(QPen(QColor("#707070"), 2))
        painter.setBrush(QColor("#303030"))
        painter.drawRoundedRect(rect, radius, radius)

        nub = rect.adjusted(rect.width() + 3, rect.height() // 3, rect.width() + 13, -rect.height() // 3)
        painter.drawRoundedRect(nub, 5, 5)

        if self.available and self.percent is not None:
            fill = rect.adjusted(4, 4, -4, -4)
            fill.setWidth(max(8, int(fill.width() * min(max(self.percent, 0), 100) / 100)))
            color = GREEN if self.percent >= 40 else YELLOW if self.percent >= 20 else RED
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(fill, 10, 10)
            text = f"{self.percent}%"
        else:
            text = "无电池"

        painter.setPen(QColor(TEXT_COLOR))
        painter.setFont(QFont("Helvetica Neue", 13, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


class InfoCard(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("InfoCard")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 12, 14, 14)
        self.layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        self.layout.addWidget(title_label)

        line = QFrame()
        line.setObjectName("Divider")
        line.setFrameShape(QFrame.Shape.HLine)
        self.layout.addWidget(line)

        self.grid = QGridLayout()
        self.grid.setColumnStretch(0, 0)
        self.grid.setColumnStretch(1, 1)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(6)
        self.layout.addLayout(self.grid)
        self.layout.addStretch()

    def clear_rows(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def set_rows(self, rows, color_by_key=None):
        self.clear_rows()
        for row, (key, value) in enumerate(rows.items()):
            key_label = QLabel(key)
            key_label.setObjectName("KeyLabel")
            key_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            value_label = QLabel(str(value))
            value_label.setObjectName("ValueLabel")
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setWordWrap(True)
            if color_by_key and key in color_by_key:
                value_label.setStyleSheet(f"color: {color_by_key[key]};")

            self.grid.addWidget(key_label, row, 0)
            self.grid.addWidget(value_label, row, 1)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.hardware = get_hardware_info()
        self.setWindowTitle("Mac 信息检测工具")
        self.setMinimumSize(620, 360)

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(12, 10, 12, 10)
        main.setSpacing(10)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Mac 信息检测工具")
        title.setObjectName("AppTitle")
        subtitle = QLabel(
            f"{self.hardware['model_name']}  {self.hardware['model_id']}  |  {self.hardware['chip']}  |  SN: {self.hardware['serial']}"
        )
        subtitle.setObjectName("Subtitle")
        subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh)
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)

        header.addLayout(title_box, 1)
        header.addWidget(self.refresh_button)
        main.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(14)
        self.ssd_card = InfoCard("SSD 健康状态")
        self.battery_card = InfoCard("电池信息")
        self.battery_gauge = BatteryGauge()
        self.battery_card.layout.insertWidget(2, self.battery_gauge)
        self.battery_card.setVisible(False)

        content.addWidget(self.ssd_card, 1)
        content.addWidget(self.battery_card, 1)
        main.addLayout(content, 1)

        self.status = QLabel("")
        self.status.setObjectName("Status")
        main.addWidget(self.status)

        self.apply_styles()
        self.status.setText("准备检测...")
        QTimer.singleShot(50, self.refresh)

    def apply_styles(self):
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{
                background: {WINDOW_BG};
                color: {TEXT_COLOR};
                font-family: "Helvetica Neue", "PingFang SC", Arial;
                font-size: 12px;
            }}
            #AppTitle {{
                font-size: 19px;
                font-weight: 700;
            }}
            #Subtitle, #Status {{
                color: {MUTED_TEXT};
                font-size: 11px;
            }}
            QPushButton {{
                background: #3a3a3a;
                border: 1px solid #565656;
                border-radius: 7px;
                color: {TEXT_COLOR};
                font-weight: 700;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background: #484848;
            }}
            #InfoCard {{
                background: {CARD_BG};
                border: 1px solid {CARD_BORDER};
                border-radius: 10px;
            }}
            #CardTitle {{
                font-size: 15px;
                font-weight: 800;
            }}
            #Divider {{
                color: #555555;
                background: #555555;
                max-height: 1px;
            }}
            #KeyLabel {{
                color: {TEXT_COLOR};
                font-size: 12px;
                font-weight: 700;
            }}
            #ValueLabel {{
                color: {TEXT_COLOR};
                font-size: 12px;
                font-weight: 700;
            }}
            """
        )

    def refresh(self):
        self.refresh_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            smart_raw, smart_error = run_smartctl()
            ssd_info = get_disk_usage_info()
            ssd_info.update(parse_ssd_data(smart_raw))

            color_by_key = {}
            if "健康状态" in ssd_info:
                color_by_key["健康状态"] = GREEN if "PASSED" in ssd_info["健康状态"] else RED
            if "寿命损耗" in ssd_info:
                color_by_key["寿命损耗"] = health_color(ssd_info["寿命损耗"])
            color_by_key["硬盘容量"] = BLUE

            if not smart_raw:
                ssd_info["SMART"] = smart_error
                color_by_key["SMART"] = YELLOW

            battery = get_battery_info()
            self.ssd_card.set_rows(ssd_info, color_by_key)
            if battery.available:
                self.battery_card.setVisible(True)
                self.battery_card.set_rows(battery.rows)
                self.battery_gauge.set_value(battery.percent, True)
                mode = "SSD + 电池"
            else:
                self.battery_card.setVisible(False)
                mode = "SSD"

            refresh_time = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.status.setText(f"检测模式：{mode}  |  最后刷新：{refresh_time}")
        except Exception as exc:
            QMessageBox.critical(self, "错误", str(exc))
        finally:
            QApplication.restoreOverrideCursor()
            self.refresh_button.setEnabled(True)


def main():
    crash_log_file = install_crash_logger()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    exit_code = app.exec()
    crash_log_file.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
