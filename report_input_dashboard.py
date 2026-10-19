import os
import re
import sys
import json
import calendar as pycalendar
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import font as tkfont
from datetime import datetime, date

try:
    from PyQt6.QtCore import QDate, QEvent, QPoint, QSize, Qt, QThread, QTimer, pyqtSignal
    from PyQt6.QtGui import QAction, QColor, QTextCharFormat
    from PyQt6.QtWidgets import (
        QApplication,
        QComboBox,
        QCompleter,
        QCalendarWidget,
        QCheckBox,
        QDateEdit,
        QDialog,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QScrollArea,
        QVBoxLayout,
        QSizePolicy,
        QToolButton,
        QPushButton,
        QWidget,
    )
    from qfluentwidgets import (
        BodyLabel,
        FluentIcon,
        FluentWindow,
        NavigationItemPosition,
        PlainTextEdit,
        PrimaryPushButton,
        PushButton,
        StrongBodyLabel,
        SubtitleLabel,
        TitleLabel,
        Theme,
        setTheme,
        setThemeColor,
    )
    HAS_QT_FRONTEND = True
    QT_IMPORT_ERROR = ""
except ImportError as exc:
    HAS_QT_FRONTEND = False
    QT_IMPORT_ERROR = str(exc)

try:
    from tkcalendar import DateEntry
    HAS_TKCALENDAR = True
except ImportError:
    DateEntry = None
    HAS_TKCALENDAR = False

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOCAL_CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
LOCAL_CREDENTIALS_TEXT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.txt")

DOMAIN_OPTIONS = [
    "All",
    "None",
    "ABK",
    "Android Platform",
    "Architecture",
    "Audio Infrastructure",
    "Browser",
    "Camera Infrastructure",
    "CarFunctions",
    "Charging Settings & Value Add",
    "China Product",
    "Communication",
    "Connected Services",
    "Connectivity",
    "Core UI",
    "DCS",
    "DeliveryChain",
    "DisplayGraphicsInfra",
    "ENT_and_CON CN",
    "Entertainment",
    "ETC CHN",
    "ETC JP",
    "Experiences and Modes",
    "FOD",
    "Foresight",
    "Hardware",
    "HUD UI",
    "IBA",
    "IDC China Product",
    "IKS CV",
    "Industrialization",
    "Instrument Cluster",
    "Interior Light",
    "Interior Sensing",
    "IPA",
    "IPA CN",
    "IPA Intelligent Functions",
    "IPA Speech",
    "Keys",
    "Lifecycle/Powermgmt",
    "LinuxOS",
    "LogTrace",
    "M GmbH",
    "Mechanics",
    "MechanicsRSE",
    "My Modes",
    "Navigation",
    "Navigation CN",
    "Navigation KOR",
    "Navigation Value Add",
    "Navigation TWN",
    "Network",
    "Node0 Platform Integration",
    "PEnt Functions & UI",
    "Performance",
    "Personalization",
    "QMT",
    "QMT_CN",
    "QMT_USMCA",
    "OSIS",
    "RSU UI",
    "RSU",
    "RTOS",
    "Safety",
    "SDI",
    "Security",
    "Security & Updates",
    "Health",
    "Showroom Mode",
    "SichtAbsicht",
    "SnapShotApp",
    "Software Integration",
    "Speech",
    "Speech Amazon",
    "Speech CN",
    "Stability",
    "System Engineering",
    "System Functions",
    "System Integration",
    "System Managers",
    "System Integration Testing",
    "System Software",
    "System Validation",
    "Telematics",
    "UI Toolkit",
    "User Experience",
    "Wireless Services",
]

VARIANT_OPTIONS = [
    "All",
    "BMT",
    "CDD",
    "CDE",
    "CDE-01",
    "CID170",
    "CID180",
    "FHUD",
    "GADI",
    "HU-MGU_02_A",
    "IC-BOX",
    "IDCEVO-21",
    "IDCEVO-25",
    "MARS-SP21",
    "MARS-SP25",
    "PHUD40",
    "PHUD50",
    "RSE_EXBX-02",
    "RSE26",
    "SV_MID",
    "SV_MINI",
    "SV_HIGH",
]

TEST_PROJECT_OPTIONS = [
    "ABPI",
    "IDCEVODEV",
]

DEFECT_PROJECT_OPTIONS = [
    "HU22DM",
    "IDCEVODEV",
    "ICONSD",
]

ADHOC_DOMAIN_OPTIONS = [
    "Telematics",
    "Communication",
    "Wireless Services",
]

FEATURE_EXCLUDED_DOMAINS = {
    "China Product", "Navigation KOR", "UI Toolkit", "Navigation Korea",
    "ENT_and_CON CN", "IPA CN", "Navigation CN", "Mechanics", "Speech CN", "Safety",
}
FEATURE_DOMAIN_OPTIONS = [
    "Android Platform", "Audio Infrastructure", "Base System", "Camera Infrastructure", "CarFunctions",
    "Charging Settings & Value Add", "Communication", "Core UI", "DeliveryChain", "DisplayGraphicsInfra",
    "Entertainment", "Experiences and Modes", "FOD", "Foresight", "Hardware", "Health", "HUD UI", "IBA",
    "IKS CV", "Industrialization", "Instrument Cluster", "Interior Light", "Interior Sensing",
    "IPA Intelligent Functions", "IPA Speech", "Keys", "Lifecycle/Powermgmt", "LinuxOS", "LogTrace", "M GmbH",
    "Navigation", "Network", "PEnt Functions & UI", "Performance", "Personalization", "RSU UI", "RTOS", "SDI",
    "Security", "SichtAbsicht", "Stability", "System Functions", "System Software", "Telematics",
    "User Experience", "Wireless Services",
]
FEATURE_SOP_PU_OPTIONS = [
    "25-07", "25-11", "26-03", "26-07", "26-11", "27-03", "27-07",
    "27-11", "28-03", "28-07", "28-11",
]
FEATURE_SUBTASK_OPTIONS = [
    "RG3/RG4 - SYS.5 System Validation Test Cases",
    "RG4.5 - Feature/subfeature System Validation Testing SYS.5",
]
FEATURE_PRODUCT_OPTIONS = ["IDCEVO", "CDE/RSE26"]

ASSIGNED_ECU_OPTIONS = [
    "IDCEVO-25",
    "CDE-01",
    "RSE_EXBX-02",
    "SV_MID",
    "SV_MINI",
    "SV_HIGH",
    "OTHER",
]


# OEM delivery management palette: graphite structure, white work surfaces, BMW blue focus.
COLOR_BG = "#E9EDF2"
COLOR_PANEL = "#FFFFFF"
COLOR_PANEL_ALT = "#F4F7FA"
COLOR_FIELD = "#F1F4F7"
COLOR_FIELD_ELEVATED = "#E5EBF1"
COLOR_BORDER = "#C7D1DC"
COLOR_HEADING = "#1B2733"
COLOR_TEXT = "#1F2D3A"
COLOR_TEXT_SOFT = "#40505F"
COLOR_TEXT_MUTED = "#637282"
COLOR_ACCENT = "#0066B1"
COLOR_ACCENT_HOVER = "#00538F"
COLOR_ACCENT_PRESSED = "#003E6B"
COLOR_TEAL = "#0066B1"
COLOR_HEADER_TOP = "#F8FAFC"
COLOR_DANGER = "#B42318"
COLOR_SUCCESS = "#166534"
COLOR_WARNING = "#8A5A00"
COLOR_SCROLL_TRACK = "#DCE3EA"
COLOR_SCROLL_THUMB = "#8496A8"
COLOR_SCROLL_THUMB_HOVER = "#60788E"
COLOR_SCROLL_THUMB_PRESS = "#405B72"


# Single source of truth for the Qt dashboard: avoid inline hex/pixel literals in widget code.
# One accent color, one job: QT_THEME["accent"] is reserved for the primary CTA only.
# "selected" is intentionally a different color so scope-card selection never competes visually with the CTA.
QT_THEME = {
    "accent": COLOR_ACCENT,
    "accent_hover": COLOR_ACCENT_HOVER,
    "accent_pressed": COLOR_ACCENT_PRESSED,
    "accent_tint": "#EAF3FB",
    "accent_tint_hover": "#DCEEFF",
    "accent_tint_pressed": "#CBE3F7",
    "selected": "#1F2D3A",
    "active": "#16733A",
    "surface": "#FFFFFF",
    "surface_alt": "#F8FAFC",
    "surface_amber": "#FFF7ED",
    "border": "#DCE3EA",
    "border_amber": "#FDE1B8",
    "text": COLOR_TEXT,
    "text_soft": COLOR_TEXT_SOFT,
    "text_muted": COLOR_TEXT_MUTED,
    "text_amber": "#8A4B0D",
    "console_bg": "#101A24",
    "console_text": "#D6E5F2",
    "console_border": "#34485A",
}

QT_LAYOUT = {
    "field_min_width": 230,
    "combo_min_width": 330,
    "cw_badge_min_width": 80,
    "drawer_min_width": 430,
    "drawer_max_width": 470,
}


def is_valid_date(value: str) -> bool:
    if not isinstance(value, str) or not DATE_PATTERN.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def load_test_guide_credentials() -> None:
    """Load persisted Windows user credentials into this already-running process."""
    load_local_credentials()
    if os.getenv("TEST_GUIDE_AUTH_KEY", "").strip() or os.getenv("TEST_GUIDE_TOKEN", "").strip():
        return
    if sys.platform != "win32":
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as environment_key:
            for name in ("TEST_GUIDE_AUTH_KEY", "TEST_GUIDE_TOKEN"):
                try:
                    value, _ = winreg.QueryValueEx(environment_key, name)
                except FileNotFoundError:
                    continue
                if str(value).strip():
                    os.environ[name] = str(value).strip()
    except (FileNotFoundError, OSError):
        return


def load_jira_credentials() -> None:
    """Load persisted Jira credentials into this process when not already set."""
    load_local_credentials()
    if os.getenv("JIRA_API_TOKEN", "").strip():
        return
    if sys.platform != "win32":
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as environment_key:
            for name in ("JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_AUTH_MODE"):
                try:
                    value, _ = winreg.QueryValueEx(environment_key, name)
                except FileNotFoundError:
                    continue
                if str(value).strip():
                    os.environ[name] = str(value).strip()
    except (FileNotFoundError, OSError):
        return


def load_local_credentials() -> None:
    """Load local credentials without replacing values already set in the environment."""
    try:
        with open(LOCAL_CREDENTIALS_FILE, "r", encoding="utf-8") as credentials_file:
            credentials = json.load(credentials_file)
        jira = credentials.get("jira", {}) if isinstance(credentials, dict) else {}
        test_guide = credentials.get("test_guide", {}) if isinstance(credentials, dict) else {}
        file_values = {
            "JIRA_EMAIL": jira.get("email", ""),
            "JIRA_API_TOKEN": jira.get("api_token", ""),
            "JIRA_AUTH_MODE": jira.get("auth_mode", ""),
            "TEST_GUIDE_TOKEN": test_guide.get("token", ""),
            "TEST_GUIDE_AUTH_KEY": test_guide.get("auth_key", ""),
        }
        for name, value in file_values.items():
            if not os.getenv(name, "").strip() and is_credential_value(value):
                os.environ[name] = str(value).strip()
    except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
        pass

    try:
        with open(LOCAL_CREDENTIALS_TEXT_FILE, "r", encoding="utf-8") as credentials_file:
            for line in credentials_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                name = name.strip()
                if name in {"JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_AUTH_MODE", "TEST_GUIDE_TOKEN", "TEST_GUIDE_AUTH_KEY"}:
                    if not os.getenv(name, "").strip() and is_credential_value(value):
                        os.environ[name] = value.strip()
    except (FileNotFoundError, OSError):
        return


def is_credential_value(value) -> bool:
    normalized = str(value or "").strip().casefold()
    return bool(normalized) and not (
        normalized.startswith("your-")
        or normalized.startswith("paste-your-")
        or normalized in {"changeme", "replace-me"}
    )


def load_current_credentials() -> dict:
    """Read stored Jira/test.guide credentials for pre-filling the settings dialog."""
    values = {
        "jira_email": "",
        "jira_api_token": "",
        "jira_auth_mode": "bearer",
        "test_guide_token": "",
    }
    try:
        with open(LOCAL_CREDENTIALS_FILE, "r", encoding="utf-8") as credentials_file:
            data = json.load(credentials_file)
        jira = data.get("jira", {}) if isinstance(data, dict) else {}
        test_guide = data.get("test_guide", {}) if isinstance(data, dict) else {}
        values["jira_email"] = str(jira.get("email", "") or "")
        values["jira_api_token"] = str(jira.get("api_token", "") or "")
        values["jira_auth_mode"] = str(jira.get("auth_mode", "") or "bearer").strip().lower() or "bearer"
        # Migrate the old separate auth_key field into the single token if needed.
        values["test_guide_token"] = str(test_guide.get("token", "") or test_guide.get("auth_key", "") or "")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    # Values already loaded into this session's environment take precedence for display.
    values["jira_email"] = os.getenv("JIRA_EMAIL", values["jira_email"])
    values["jira_api_token"] = os.getenv("JIRA_API_TOKEN", values["jira_api_token"])
    values["jira_auth_mode"] = os.getenv("JIRA_AUTH_MODE", values["jira_auth_mode"]).strip().lower() or "bearer"
    values["test_guide_token"] = os.getenv("TEST_GUIDE_TOKEN", os.getenv("TEST_GUIDE_AUTH_KEY", values["test_guide_token"]))
    return values


def save_local_credentials(
    jira_email: str,
    jira_api_token: str,
    jira_auth_mode: str,
    test_guide_token: str,
) -> None:
    """Persist per-user Jira/test.guide credentials and apply them to the running process
    immediately, so no hardcoded token/user is required and Generate Report picks them up
    without restarting the dashboard. A single Test Guide Token is applied under both
    header schemes test.guide instances use (see fetch_rack_activity_from_test_guide),
    so only one credential needs to be managed."""
    data = {}
    try:
        with open(LOCAL_CREDENTIALS_FILE, "r", encoding="utf-8") as credentials_file:
            loaded = json.load(credentials_file)
        if isinstance(loaded, dict):
            data = loaded
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}

    data["jira"] = {
        "email": jira_email.strip(),
        "api_token": jira_api_token.strip(),
        "auth_mode": (jira_auth_mode.strip().lower() or "bearer"),
    }
    data["test_guide"] = {"token": test_guide_token.strip()}

    with open(LOCAL_CREDENTIALS_FILE, "w", encoding="utf-8") as credentials_file:
        json.dump(data, credentials_file, indent=2)

    for name, value in (
        ("JIRA_EMAIL", jira_email),
        ("JIRA_API_TOKEN", jira_api_token),
        ("JIRA_AUTH_MODE", jira_auth_mode),
        ("TEST_GUIDE_TOKEN", test_guide_token),
        ("TEST_GUIDE_AUTH_KEY", test_guide_token),
    ):
        if is_credential_value(value):
            os.environ[name] = value.strip()
        else:
            os.environ.pop(name, None)


def resolve_report_interpreter(script_path: str) -> str:
    """Prefer workspace venv Python for report execution to avoid interpreter mismatches."""
    base_dir = os.path.dirname(os.path.abspath(script_path))
    venv_python = os.path.join(base_dir, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable


def build_command(
    script_path: str,
    start_date: str,
    end_date: str,
    test_projects: str,
    domain: str,
    cycle_type: str,
    variant: str,
    defect_projects: str,
    defect_domain: str,
    defect_assigned_ecu: str,
    closure_projects: str,
    closure_team: str,
    resolution_start_date: str,
    resolution_end_date: str,
    report_scopes: str = "",
    adhoc_domains: str = "All",
    rack_domain: str = "",
    feature_sop_pu: str = "",
    feature_domain: str = "",
    feature_subtasks: str = "",
    feature_resolution_start_date: str = "",
    feature_resolution_end_date: str = "",
    feature_products: str = ",".join(FEATURE_PRODUCT_OPTIONS),
) -> list[str]:
    cmd = [
        resolve_report_interpreter(script_path),
        script_path,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
        "--cycle-type",
        cycle_type,
    ]

    clean_test_projects = test_projects.strip()
    if clean_test_projects and clean_test_projects.lower() != "all":
        cmd.extend(["--projects", clean_test_projects])

    clean_domain = domain.strip()
    if clean_domain and clean_domain.lower() not in {"all", "none"}:
        cmd.extend(["--domain", clean_domain])

    clean_variant = variant.strip()
    if clean_variant and clean_variant.lower() != "all":
        cmd.extend(["--variant", clean_variant])

    clean_defect_projects = defect_projects.strip()
    if clean_defect_projects and clean_defect_projects.lower() != "all":
        cmd.extend(["--defect-projects", clean_defect_projects])

    clean_defect_domain = defect_domain.strip()
    if clean_defect_domain and clean_defect_domain.lower() not in {"all", "none"}:
        cmd.extend(["--defect-domain", clean_defect_domain])

    clean_defect_ecu = defect_assigned_ecu.strip()
    if clean_defect_ecu and clean_defect_ecu.lower() != "all":
        cmd.extend(["--defect-assigned-ecu", clean_defect_ecu])

    clean_closure_projects = closure_projects.strip()
    if clean_closure_projects and clean_closure_projects.lower() != "all":
        cmd.extend(["--closure-projects", clean_closure_projects])

    clean_closure_team = closure_team.strip()
    if clean_closure_team and clean_closure_team.lower() not in {"all", "none"}:
        cmd.extend(["--closure-team", clean_closure_team])

    if is_valid_date(resolution_start_date):
        cmd.extend(["--resolution-start-date", resolution_start_date])

    if is_valid_date(resolution_end_date):
        cmd.extend(["--resolution-end-date", resolution_end_date])

    clean_scopes = report_scopes.strip()
    if clean_scopes and clean_scopes.lower() not in {"all", "none"}:
        cmd.extend(["--report-scopes", clean_scopes])

    clean_adhoc_domains = adhoc_domains.strip()
    if clean_adhoc_domains and clean_adhoc_domains.lower() != "all":
        # Unlike other filters, "none" must be sent explicitly here (not omitted)
        # so the report script's own fetch gating actually skips ad-hoc entirely,
        # instead of silently falling back to its own default of "All".
        cmd.extend(["--adhoc-domains", clean_adhoc_domains])

    clean_rack_domain = rack_domain.strip()
    if clean_rack_domain and clean_rack_domain.lower() not in {"all", "none"}:
        cmd.extend(["--rack-domain", clean_rack_domain])

    clean_feature_sop_pu = feature_sop_pu.strip()
    if clean_feature_sop_pu and clean_feature_sop_pu.lower() not in {"all", "none"}:
        cmd.extend(["--feature-sop-pu", clean_feature_sop_pu])

    clean_feature_domain = feature_domain.strip()
    if clean_feature_domain and clean_feature_domain.lower() not in {"all", "none"}:
        cmd.extend(["--feature-domain", clean_feature_domain])

    clean_feature_subtasks = feature_subtasks.strip()
    if clean_feature_subtasks and clean_feature_subtasks.lower() not in {"all", "none"}:
        include_rg3_rg4 = "true" if FEATURE_SUBTASK_OPTIONS[0] in clean_feature_subtasks else "false"
        include_rg45 = "true" if FEATURE_SUBTASK_OPTIONS[1] in clean_feature_subtasks else "false"
        cmd.extend(["--feature-include-rg3-rg4", include_rg3_rg4])
        cmd.extend(["--feature-include-rg45", include_rg45])

    if is_valid_date(feature_resolution_start_date):
        cmd.extend(["--feature-resolution-start-date", feature_resolution_start_date])
    if is_valid_date(feature_resolution_end_date):
        cmd.extend(["--feature-resolution-end-date", feature_resolution_end_date])
    clean_feature_products = feature_products.strip()
    if clean_feature_products and clean_feature_products.lower() not in {"all", "none"}:
        cmd.extend(["--feature-products", clean_feature_products])

    return cmd


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    report_script = os.path.join(base_dir, "test_execution_report_v2.py")

    root = tk.Tk()
    root.title("Efforts Calculator Simplified")
    root.geometry("1320x820")
    root.minsize(1160, 720)
    root.configure(bg=COLOR_BG)

    available_fonts = set(tkfont.families(root))
    base_family = "Segoe UI"
    heading_family = "Segoe UI Semibold" if "Segoe UI Semibold" in available_fonts else base_family
    mono_family = "Cascadia Code" if "Cascadia Code" in available_fonts else "Consolas"
    dot_heading_family = "Consolas" if "Consolas" in available_fonts else mono_family

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("App.TFrame", background=COLOR_BG)
    style.configure("Hero.TFrame", background=COLOR_HEADER_TOP, borderwidth=1, relief="solid", bordercolor="#B7C4D1")
    style.configure("Card.TFrame", background=COLOR_PANEL, borderwidth=1, relief="flat", bordercolor=COLOR_BORDER)
    style.configure("CardHover.TFrame", background="#FFFFFF", borderwidth=1, relief="solid", bordercolor="#7EA9C9")
    style.configure("Glass.TFrame", background=COLOR_PANEL_ALT, borderwidth=1, relief="flat", bordercolor=COLOR_BORDER)
    style.configure("H1.TLabel", background=COLOR_HEADER_TOP, foreground=COLOR_HEADING, font=(dot_heading_family, 17, "bold"))
    style.configure("Sub.TLabel", background=COLOR_HEADER_TOP, foreground=COLOR_TEXT_SOFT, font=(base_family, 10))
    style.configure("SectionTitle.TLabel", background=COLOR_PANEL_ALT, foreground=COLOR_HEADING, font=(dot_heading_family, 14, "bold"), padding=(8, 4))
    style.configure("Label.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT, font=(base_family, 12, "bold"))
    style.configure("Meta.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT_MUTED, font=(base_family, 10))
    style.configure("StatusHead.TLabel", background=COLOR_PANEL_ALT, foreground=COLOR_HEADING, font=(heading_family, 12, "bold"))
    style.configure("Chip.TLabel", background=COLOR_PANEL_ALT, foreground=COLOR_TEXT, font=(base_family, 10, "bold"), padding=(10, 4))
    style.configure("Soft.TButton", background=COLOR_FIELD_ELEVATED, foreground=COLOR_TEXT, borderwidth=1, padding=(13, 10), font=(base_family, 10, "bold"), bordercolor=COLOR_BORDER)
    style.map("Soft.TButton", background=[("active", "#E7ECF2"), ("pressed", "#DEE5ED")])
    style.configure("Accent.TButton", background=COLOR_ACCENT, foreground="#FFFFFF", borderwidth=1, padding=(18, 12), font=(base_family, 11, "bold"), bordercolor="#4A84B6")
    style.map("Accent.TButton", background=[("active", COLOR_ACCENT_HOVER), ("pressed", COLOR_ACCENT_PRESSED)])
    style.configure("Picker.TButton", background=COLOR_FIELD_ELEVATED, foreground=COLOR_TEXT, borderwidth=1, padding=(11, 8), font=(base_family, 10, "bold"), bordercolor=COLOR_BORDER)
    style.map("Picker.TButton", background=[("active", "#E7ECF2"), ("pressed", "#DEE5ED")])
    style.configure("Scope.TButton", background="#EAF3FF", foreground="#173A61", borderwidth=1, padding=(16, 11), font=(base_family, 10, "bold"), bordercolor="#A9C8E8")
    style.map("Scope.TButton", background=[("active", "#DCEEFF"), ("pressed", "#CBE3F7")])
    style.configure(
        "TEntry",
        fieldbackground=COLOR_FIELD,
        foreground=COLOR_TEXT,
        bordercolor=COLOR_BORDER,
        lightcolor=COLOR_BORDER,
        darkcolor=COLOR_BORDER,
        padding=(12, 10),
        font=(base_family, 11),
    )
    style.map(
        "TEntry",
        fieldbackground=[("focus", "#FFFFFF"), ("readonly", COLOR_FIELD_ELEVATED)],
        bordercolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_BORDER)],
        lightcolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_BORDER)],
        darkcolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_BORDER)],
    )

    style.configure(
        "Value.TEntry",
        fieldbackground=COLOR_FIELD_ELEVATED,
        foreground=COLOR_HEADING,
        bordercolor=COLOR_BORDER,
        lightcolor=COLOR_BORDER,
        darkcolor=COLOR_BORDER,
        padding=(12, 10),
        font=(base_family, 11, "bold"),
    )
    style.map(
        "Value.TEntry",
        fieldbackground=[("focus", "#FFFFFF"), ("readonly", COLOR_FIELD_ELEVATED)],
        bordercolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_BORDER)],
        lightcolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_BORDER)],
        darkcolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_BORDER)],
    )

    style.configure(
        "TestSelected.TEntry",
        fieldbackground="#DCEEFF",
        foreground="#0B3558",
        bordercolor="#6FA6D2",
        lightcolor="#6FA6D2",
        darkcolor="#6FA6D2",
        padding=(12, 10),
        font=(base_family, 11, "bold"),
    )
    style.map(
        "TestSelected.TEntry",
        fieldbackground=[("focus", "#EAF5FF"), ("readonly", "#DCEEFF")],
        bordercolor=[("focus", COLOR_ACCENT), ("!focus", "#A9C8E8")],
        lightcolor=[("focus", COLOR_ACCENT), ("!focus", "#A9C8E8")],
        darkcolor=[("focus", COLOR_ACCENT), ("!focus", "#A9C8E8")],
    )

    style.configure(
        "DefectSelected.TEntry",
        fieldbackground="#FCE9E4",
        foreground="#642D27",
        bordercolor="#D99181",
        lightcolor="#D99181",
        darkcolor="#D99181",
        padding=(12, 10),
        font=(base_family, 11, "bold"),
    )
    style.map(
        "DefectSelected.TEntry",
        fieldbackground=[("focus", "#FFF8F5"), ("readonly", "#FCE9E4")],
        bordercolor=[("focus", COLOR_ACCENT), ("!focus", "#E8B8A9")],
        lightcolor=[("focus", COLOR_ACCENT), ("!focus", "#E8B8A9")],
        darkcolor=[("focus", COLOR_ACCENT), ("!focus", "#E8B8A9")],
    )

    style.configure(
        "MetricsSelected.TEntry",
        fieldbackground="#E3F1E8",
        foreground="#214D31",
        bordercolor="#8FC39D",
        lightcolor="#8FC39D",
        darkcolor="#8FC39D",
        padding=(12, 10),
        font=(base_family, 11, "bold"),
    )
    style.map(
        "MetricsSelected.TEntry",
        fieldbackground=[("focus", "#F5FCF7"), ("readonly", "#E3F1E8")],
        bordercolor=[("focus", COLOR_ACCENT), ("!focus", "#AFD8B8")],
        lightcolor=[("focus", COLOR_ACCENT), ("!focus", "#AFD8B8")],
        darkcolor=[("focus", COLOR_ACCENT), ("!focus", "#AFD8B8")],
    )

    style.configure(
        "TCombobox",
        fieldbackground=COLOR_FIELD,
        foreground=COLOR_TEXT,
        bordercolor=COLOR_BORDER,
        lightcolor=COLOR_BORDER,
        darkcolor=COLOR_BORDER,
        arrowsize=14,
        padding=(11, 9),
        font=(base_family, 11),
    )
    style.map(
        "TCombobox",
        fieldbackground=[("focus", "#FFFFFF"), ("readonly", COLOR_FIELD_ELEVATED)],
        bordercolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_BORDER)],
        lightcolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_BORDER)],
        darkcolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_BORDER)],
        arrowcolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_TEXT)],
    )

    style.configure(
        "Value.TCombobox",
        fieldbackground=COLOR_FIELD_ELEVATED,
        foreground=COLOR_HEADING,
        bordercolor=COLOR_BORDER,
        lightcolor=COLOR_BORDER,
        darkcolor=COLOR_BORDER,
        arrowsize=14,
        padding=(12, 10),
        font=(base_family, 11, "bold"),
    )
    style.map(
        "Value.TCombobox",
        fieldbackground=[("focus", "#FFFFFF"), ("readonly", COLOR_FIELD_ELEVATED)],
        bordercolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_BORDER)],
        lightcolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_BORDER)],
        darkcolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_BORDER)],
        arrowcolor=[("focus", COLOR_ACCENT), ("!focus", COLOR_TEXT)],
    )

    style.configure(
        "Dashboard.Vertical.TScrollbar",
        background=COLOR_SCROLL_THUMB,
        troughcolor=COLOR_SCROLL_TRACK,
        bordercolor="#BCC8D6",
        lightcolor=COLOR_SCROLL_THUMB,
        darkcolor=COLOR_SCROLL_THUMB,
        arrowcolor="#314355",
        width=14,
        relief="flat",
    )
    style.map(
        "Dashboard.Vertical.TScrollbar",
        background=[("active", COLOR_SCROLL_THUMB_HOVER), ("pressed", COLOR_SCROLL_THUMB_PRESS)],
        arrowcolor=[("active", "#1F2D3D"), ("pressed", "#FFFFFF")],
    )

    style.configure(
        "Dashboard.Horizontal.TScrollbar",
        background=COLOR_SCROLL_THUMB,
        troughcolor=COLOR_SCROLL_TRACK,
        bordercolor="#BCC8D6",
        lightcolor=COLOR_SCROLL_THUMB,
        darkcolor=COLOR_SCROLL_THUMB,
        arrowcolor="#314355",
        width=14,
        relief="flat",
    )
    style.map(
        "Dashboard.Horizontal.TScrollbar",
        background=[("active", COLOR_SCROLL_THUMB_HOVER), ("pressed", COLOR_SCROLL_THUMB_PRESS)],
        arrowcolor=[("active", "#1F2D3D"), ("pressed", "#FFFFFF")],
    )

    # Improve combobox dropdown readability and selection contrast.
    root.option_add("*TCombobox*Listbox.background", COLOR_FIELD_ELEVATED)
    root.option_add("*TCombobox*Listbox.foreground", COLOR_TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", COLOR_ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")

    app = ttk.Frame(root, style="App.TFrame", padding=(16, 14, 16, 14))
    app.pack(fill="both", expand=True)

    header = ttk.Frame(app, style="Hero.TFrame", padding=(14, 12))
    header.pack(fill="x")
    header.columnconfigure(0, weight=1)
    header.columnconfigure(1, weight=1)

    ttk.Label(header, text="Efforts Calculator Simplified", style="H1.TLabel").grid(row=0, column=0, sticky="w")

    top_status = tk.Label(
        header,
        text="READY",
        bg="#ECF2F8",
        fg="#314355",
        font=(base_family, 9, "bold"),
        padx=10,
        pady=4,
    )
    top_status.grid(row=0, column=1, sticky="e")

    loading_indicator = tk.Label(
        header,
        text="",
        bg="#173A60",
        fg="#FFFFFF",
        font=(base_family, 9, "bold"),
        padx=8,
    )
    loading_indicator.grid(row=1, column=1, sticky="e", pady=(3, 0))

    content = ttk.Frame(app, style="App.TFrame")
    content.pack(fill="both", expand=True, pady=(14, 0))
    # Two-rail layout: filter controls and analytics panels.
    content.columnconfigure(0, weight=0, minsize=126, uniform="main_rails")
    content.columnconfigure(1, weight=1, minsize=560, uniform="main_rails")
    content.rowconfigure(0, weight=1)

    left_outer = ttk.Frame(content, style="App.TFrame")
    left_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    left_outer.rowconfigure(0, weight=1)
    left_outer.columnconfigure(0, weight=1)

    left_canvas = tk.Canvas(left_outer, bg=COLOR_BG, bd=0, highlightthickness=0)
    left_scrollbar = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview, style="Dashboard.Vertical.TScrollbar")
    left_canvas.configure(yscrollcommand=left_scrollbar.set)
    left_canvas.grid(row=0, column=0, sticky="nsew")
    left_scrollbar.grid(row=0, column=1, sticky="ns")

    left = ttk.Frame(left_canvas, style="App.TFrame")
    left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

    def _on_left_configure(event):
        left_canvas.configure(scrollregion=left_canvas.bbox("all"))

    def _on_canvas_resize(event):
        left_canvas.itemconfig(left_window, width=event.width)

    left.bind("<Configure>", _on_left_configure)
    left_canvas.bind("<Configure>", _on_canvas_resize)

    def _on_mousewheel(event):
        # Keep popup selectors independent from the main filter-pane scroll.
        widget = root.winfo_containing(event.x_root, event.y_root)
        inside_left_pane = False
        while widget is not None:
            if widget in {left, left_canvas}:
                inside_left_pane = True
                break
            parent_name = widget.winfo_parent()
            if not parent_name:
                break
            try:
                widget = root.nametowidget(parent_name)
            except KeyError:
                break

        if not inside_left_pane:
            return
        left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    left_canvas.bind_all("<MouseWheel>", _on_mousewheel)

    right = ttk.Frame(content, style="App.TFrame")
    right.grid(row=0, column=1, sticky="nsew", padx=(2, 0))
    left_outer.grid_remove()

    navigation = tk.Frame(content, bg="#14283D", bd=0, highlightthickness=0)
    navigation.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    tk.Label(navigation, text="OEM\nDELIVERY", bg="#14283D", fg="#FFFFFF", font=(base_family, 10, "bold"), justify="left", padx=14, pady=16).pack(fill="x")

    nav_items = ("Dashboard", "Projects", "Defects", "Analytics", "Test Racks", "Reports")
    for index, item in enumerate(nav_items):
        active = index == 0
        tk.Button(
            navigation,
            text=f"[{index + 1}]  {item}",
            anchor="w",
            padx=14,
            pady=10,
            relief="flat",
            bd=0,
            bg="#0A66B1" if active else "#14283D",
            fg="#FFFFFF" if active else "#C8D7E5",
            activebackground="#1C78BB",
            activeforeground="#FFFFFF",
            font=(base_family, 9, "bold"),
            cursor="hand2",
        ).pack(fill="x", padx=8, pady=(2, 0))

    selected_test_projects: list[str] = ["ABPI", "IDCEVODEV"]
    selected_defect_projects: list[str] = []
    selected_domains: list[str] = []
    selected_variants: list[str] = []
    selected_assigned_ecus: list[str] = []
    selected_closure_projects: list[str] = []
    selected_defect_domains: list[str] = []
    selected_closure_teams: list[str] = []
    selected_adhoc_domains: list[str] = ["Telematics"]
    selected_rack_domains: list[str] = []

    entry_style_bindings: list[tuple[ttk.Entry, tk.StringVar, str]] = []

    test_projects_var = tk.StringVar(value=", ".join(selected_test_projects))
    domain_var = tk.StringVar(value="All")
    cycle_var = tk.StringVar(value="both")
    variant_var = tk.StringVar(value="All")
    defect_projects_var = tk.StringVar(value="All")
    defect_domain_var = tk.StringVar(value="All")
    assigned_ecu_var = tk.StringVar(value="All")
    closure_projects_var = tk.StringVar(value="All")
    closure_team_var = tk.StringVar(value="All")
    adhoc_domain_var = tk.StringVar(value=", ".join(selected_adhoc_domains))
    rack_domain_var = tk.StringVar(value="All")
    start_var = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
    end_var = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
    resolution_start_var = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
    resolution_end_var = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
    status_var = tk.StringVar(value="Ready")
    run_state_var = tk.StringVar(value="Idle")
    run_time_var = tk.StringVar(value="Last run: N/A")
    run_result_var = tk.StringVar(value="Status: Waiting")
    loading_job: list[str | None] = [None]
    loading_frames = ("Working  o  ", "Working  .o ", "Working  ..o", "Working  .o ")
    loading_frame_index = [0]

    def animate_loading():
        if run_state_var.get() != "Running":
            loading_indicator.configure(text="")
            loading_job[0] = None
            return
        loading_indicator.configure(text=loading_frames[loading_frame_index[0]])
        loading_frame_index[0] = (loading_frame_index[0] + 1) % len(loading_frames)
        loading_job[0] = root.after(180, animate_loading)

    def start_loading_animation():
        if loading_job[0] is None:
            loading_frame_index[0] = 0
            animate_loading()

    def stop_loading_animation():
        if loading_job[0] is not None:
            root.after_cancel(loading_job[0])
            loading_job[0] = None
        loading_indicator.configure(text="")

    def refresh_kpi_strip():
        return None

    def bind_hover(widget: tk.Widget, normal_bg: str, hover_bg: str):
        def on_enter(_event):
            widget.configure(background=hover_bg)

        def on_leave(_event):
            widget.configure(background=normal_bg)

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    def bind_entry_style(widget: ttk.Entry, variable: tk.StringVar, group: str):
        entry_style_bindings.append((widget, variable, group))

    def apply_field_styles():
        style_by_group = {
            "test": "TestSelected.TEntry",
            "defect": "DefectSelected.TEntry",
            "metrics": "MetricsSelected.TEntry",
        }

        for widget, variable, group in entry_style_bindings:
            raw = variable.get().strip()
            selected = bool(raw) and raw.lower() not in {"all", "none", "n/a"}
            widget.configure(style=style_by_group[group] if selected else "Value.TEntry")

    def open_fallback_calendar(target_var: tk.StringVar):
        raw = target_var.get().strip()
        try:
            current = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            current = date.today()

        selected = {"value": current}
        view = {"year": current.year, "month": current.month}

        popup = tk.Toplevel(root)
        popup.title("Select Date")
        popup.transient(root)
        popup.grab_set()
        popup.configure(bg=COLOR_BG)
        popup.resizable(False, False)

        shell = ttk.Frame(popup, style="Glass.TFrame", padding=12)
        shell.pack(fill="both", expand=True)

        top = ttk.Frame(shell, style="Glass.TFrame")
        top.pack(fill="x")
        month_label = ttk.Label(top, text="", style="SectionTitle.TLabel")
        month_label.pack(side="left")
        nav = ttk.Frame(top, style="Glass.TFrame")
        nav.pack(side="right")

        grid = tk.Frame(shell, bg=COLOR_PANEL_ALT)
        grid.pack(fill="both", expand=True, pady=(8, 0))

        footer = ttk.Frame(shell, style="Glass.TFrame")
        footer.pack(fill="x", pady=(10, 0))

        def shift_month(delta: int):
            month = view["month"] + delta
            year = view["year"]
            if month < 1:
                month = 12
                year -= 1
            elif month > 12:
                month = 1
                year += 1
            view["month"] = month
            view["year"] = year
            render_calendar()

        def choose_day(day_value: date):
            selected["value"] = day_value
            render_calendar()

        def choose_today():
            today = date.today()
            selected["value"] = today
            view["year"] = today.year
            view["month"] = today.month
            render_calendar()

        def confirm_date():
            target_var.set(selected["value"].strftime("%Y-%m-%d"))
            popup.destroy()
            update_preview()

        ttk.Button(nav, text="<", style="Picker.TButton", command=lambda: shift_month(-1)).pack(side="left")
        ttk.Button(nav, text=">", style="Picker.TButton", command=lambda: shift_month(1)).pack(side="left", padx=(6, 0))
        ttk.Button(nav, text="Today", style="Picker.TButton", command=choose_today).pack(side="left", padx=(8, 0))
        ttk.Button(footer, text="Confirm", style="Accent.TButton", command=confirm_date).pack(side="left")
        ttk.Button(footer, text="Cancel", style="Soft.TButton", command=popup.destroy).pack(side="right")

        def render_calendar():
            for child in grid.winfo_children():
                child.destroy()

            title_date = datetime(view["year"], view["month"], 1)
            month_label.config(text=title_date.strftime("%B %Y"))

            tk.Label(grid, text="wk", bg=COLOR_PANEL_ALT, fg=COLOR_TEXT_MUTED, font=(base_family, 9, "bold")).grid(row=0, column=0, padx=4, pady=4)
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            for idx, name in enumerate(day_names, start=1):
                tk.Label(grid, text=name, bg=COLOR_PANEL_ALT, fg=COLOR_TEXT, font=(base_family, 9, "bold")).grid(row=0, column=idx, padx=4, pady=4)

            cal = pycalendar.Calendar(firstweekday=0)
            weeks = cal.monthdatescalendar(view["year"], view["month"])
            for row_idx, week in enumerate(weeks, start=1):
                week_no = week[0].isocalendar().week
                tk.Label(grid, text=str(week_no), bg=COLOR_PANEL_ALT, fg=COLOR_TEXT_MUTED, font=(base_family, 9)).grid(row=row_idx, column=0, padx=4, pady=2)

                for col_idx, day_value in enumerate(week, start=1):
                    in_month = day_value.month == view["month"]
                    fg = COLOR_TEXT if in_month else COLOR_TEXT_MUTED
                    bg = COLOR_PANEL_ALT
                    if day_value == selected["value"]:
                        fg = COLOR_HEADING
                        bg = COLOR_ACCENT

                    day_btn = tk.Button(
                        grid,
                        text=str(day_value.day),
                        bg=bg,
                        fg=fg,
                        activebackground=COLOR_ACCENT_HOVER,
                        activeforeground=COLOR_HEADING,
                        relief="flat",
                        bd=0,
                        width=3,
                        font=(base_family, 10),
                        command=lambda d=day_value: choose_day(d),
                        cursor="hand2",
                    )
                    day_btn.grid(row=row_idx, column=col_idx, padx=2, pady=2)

        render_calendar()
        popup.update_idletasks()
        popup.geometry(f"+{root.winfo_rootx() + 120}+{root.winfo_rooty() + 100}")
        popup.wait_window()

    def open_credentials_dialog():
        current = load_current_credentials()

        popup = tk.Toplevel(root)
        popup.title("Jira & test.guide Credentials")
        popup.transient(root)
        popup.grab_set()
        popup.configure(bg=COLOR_BG)
        popup.resizable(False, False)

        shell = ttk.Frame(popup, style="Card.TFrame", padding=18)
        shell.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(shell, text="Jira & test.guide Credentials", style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(
            shell,
            text="Stored locally in credentials.json for this user; no token is hardcoded in the scripts.",
            style="Meta.TLabel",
        ).pack(anchor="w", pady=(3, 14))

        form = ttk.Frame(shell, style="Card.TFrame")
        form.pack(fill="x")
        form.columnconfigure(0, weight=1)

        jira_email_var = tk.StringVar(value=current["jira_email"])
        jira_token_var = tk.StringVar(value=current["jira_api_token"])
        jira_mode_var = tk.StringVar(value=current["jira_auth_mode"])
        tg_token_var = tk.StringVar(value=current["test_guide_token"])
        show_secrets_var = tk.BooleanVar(value=False)

        secret_entries: list[ttk.Entry] = []

        def add_field(label: str, variable: tk.StringVar, secret: bool = False):
            ttk.Label(form, text=label, style="Label.TLabel").pack(anchor="w", pady=(8, 4))
            entry = ttk.Entry(form, textvariable=variable, style="Value.TEntry", show="*" if secret else "")
            entry.pack(fill="x")
            if secret:
                secret_entries.append(entry)

        add_field("Jira Email (required for Basic auth mode)", jira_email_var)
        ttk.Label(form, text="Jira Auth Mode", style="Label.TLabel").pack(anchor="w", pady=(8, 4))
        mode_row = ttk.Frame(form, style="Glass.TFrame", padding=4)
        mode_row.pack(fill="x")
        for mode in ("bearer", "basic"):
            ttk.Button(
                mode_row,
                text=mode.title(),
                style="Picker.TButton",
                command=lambda m=mode: jira_mode_var.set(m),
            ).pack(side="left", fill="x", expand=True, padx=2)
        add_field("Jira API Token", jira_token_var, secret=True)
        add_field("Test Guide Token", tg_token_var, secret=True)

        def toggle_show_secrets():
            char = "" if show_secrets_var.get() else "*"
            for entry in secret_entries:
                entry.configure(show=char)

        ttk.Checkbutton(
            form,
            text="Show tokens",
            variable=show_secrets_var,
            command=toggle_show_secrets,
        ).pack(anchor="w", pady=(10, 0))

        status_var = tk.StringVar(value="")
        ttk.Label(shell, textvariable=status_var, style="Meta.TLabel").pack(anchor="w", pady=(10, 0))

        def do_save():
            save_local_credentials(
                jira_email_var.get(),
                jira_token_var.get(),
                jira_mode_var.get(),
                tg_token_var.get(),
            )
            status_var.set("Saved. These credentials will be used for the next report run.")

        footer = ttk.Frame(shell, style="Card.TFrame")
        footer.pack(fill="x", pady=(16, 0))
        ttk.Button(footer, text="Save", style="Accent.TButton", command=do_save).pack(side="left")
        ttk.Button(footer, text="Close", style="Soft.TButton", command=popup.destroy).pack(side="right")

        popup.update_idletasks()
        popup.geometry(f"+{root.winfo_rootx() + 160}+{root.winfo_rooty() + 100}")

    def open_multi_selector(
        choices: list[str],
        selected_store: list[str],
        target_var: tk.StringVar,
        title: str,
        subtitle: str,
    ):
        popup = tk.Toplevel(root)
        popup.title(title)
        popup.transient(root)
        popup.grab_set()
        popup.configure(bg=COLOR_BG)
        popup.resizable(False, False)

        shell = ttk.Frame(popup, style="Glass.TFrame", padding=12)
        shell.pack(fill="both", expand=True)

        ttk.Label(shell, text=title, style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(shell, text=subtitle, style="Meta.TLabel").pack(anchor="w", pady=(3, 10))

        search_var = tk.StringVar()
        ttk.Entry(shell, textvariable=search_var, style="Value.TEntry").pack(fill="x")

        list_frame = ttk.Frame(shell, style="Glass.TFrame")
        list_frame.pack(fill="both", expand=True, pady=(10, 0))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", style="Dashboard.Vertical.TScrollbar")
        listbox = tk.Listbox(
            list_frame,
            selectmode=tk.MULTIPLE,
            exportselection=False,
            activestyle="none",
            height=12,
            font=(base_family, 10),
            bg=COLOR_FIELD_ELEVATED,
            fg=COLOR_TEXT,
            selectbackground=COLOR_ACCENT_HOVER,
            selectforeground="#FFFFFF",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_ACCENT,
            selectborderwidth=0,
            yscrollcommand=scrollbar.set,
        )
        listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        scrollbar.config(command=listbox.yview)

        filtered_items = list(choices)
        pending_selection: set[str] = set()

        def capture_current_selection():
            """Snapshot the currently *displayed* list's selected item names before the
            displayed list changes - curselection() indices are only valid against
            whatever filtered_items currently is, so reading them AFTER filtered_items
            is reassigned (in filter_items, below) crashes with IndexError once the
            new list is shorter than the old selected index."""
            for i in listbox.curselection():
                pending_selection.add(filtered_items[i].lower())

        def render_list():
            selected_lookup = {v.lower() for v in selected_store}
            keep = pending_selection | selected_lookup
            listbox.delete(0, "end")
            for item in filtered_items:
                listbox.insert("end", item)
            for idx, item in enumerate(filtered_items):
                if item.lower() in keep:
                    listbox.selection_set(idx)

        def filter_items(*_args):
            capture_current_selection()
            needle = search_var.get().strip().lower()
            nonlocal filtered_items
            filtered_items = [c for c in choices if needle in c.lower()] if needle else list(choices)
            render_list()

        search_var.trace_add("write", filter_items)
        render_list()

        controls = ttk.Frame(shell, style="Glass.TFrame")
        controls.pack(fill="x", pady=(10, 0))

        def select_all_visible():
            listbox.selection_set(0, "end")

        def clear_visible():
            listbox.selection_clear(0, "end")

        def apply_selection():
            picked = [filtered_items[i] for i in listbox.curselection()]
            selected_store.clear()
            selected_store.extend(picked)
            target_var.set(", ".join(selected_store) if selected_store else "All")
            popup.destroy()
            refresh_chips()
            update_preview()

        ttk.Button(controls, text="Select All", style="Picker.TButton", command=select_all_visible).pack(side="left")
        ttk.Button(controls, text="Clear", style="Picker.TButton", command=clear_visible).pack(side="left", padx=(7, 0))
        ttk.Button(controls, text="Apply", style="Accent.TButton", command=apply_selection).pack(side="right")
        ttk.Button(controls, text="Cancel", style="Soft.TButton", command=popup.destroy).pack(side="right", padx=(0, 8))

        popup.update_idletasks()
        popup.geometry(f"+{root.winfo_rootx() + 150}+{root.winfo_rooty() + 110}")
        popup.wait_window()

    def open_single_selector(
        choices: list[str],
        target_var: tk.StringVar,
        title: str,
        subtitle: str,
    ):
        popup = tk.Toplevel(root)
        popup.title(title)
        popup.transient(root)
        popup.grab_set()
        popup.configure(bg=COLOR_BG)
        popup.resizable(False, False)

        shell = ttk.Frame(popup, style="Glass.TFrame", padding=12)
        shell.pack(fill="both", expand=True)

        ttk.Label(shell, text=title, style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(shell, text=subtitle, style="Meta.TLabel").pack(anchor="w", pady=(3, 10))

        search_var = tk.StringVar()
        ttk.Entry(shell, textvariable=search_var, style="Value.TEntry").pack(fill="x")

        list_frame = ttk.Frame(shell, style="Glass.TFrame")
        list_frame.pack(fill="both", expand=True, pady=(10, 0))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", style="Dashboard.Vertical.TScrollbar")
        listbox = tk.Listbox(
            list_frame,
            selectmode=tk.SINGLE,
            exportselection=False,
            activestyle="none",
            height=12,
            font=(base_family, 10),
            bg=COLOR_FIELD_ELEVATED,
            fg=COLOR_TEXT,
            selectbackground=COLOR_ACCENT_HOVER,
            selectforeground="#FFFFFF",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_ACCENT,
            selectborderwidth=0,
            yscrollcommand=scrollbar.set,
        )
        listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        scrollbar.config(command=listbox.yview)

        filtered_items = list(choices)

        def render_list():
            current_value = target_var.get().strip().lower()
            listbox.delete(0, "end")
            for item in filtered_items:
                listbox.insert("end", item)
            for idx, item in enumerate(filtered_items):
                if item.lower() == current_value:
                    listbox.selection_set(idx)
                    listbox.see(idx)
                    break

        def filter_items(*_args):
            needle = search_var.get().strip().lower()
            nonlocal filtered_items
            filtered_items = [c for c in choices if needle in c.lower()] if needle else list(choices)
            render_list()

        search_var.trace_add("write", filter_items)
        render_list()

        controls = ttk.Frame(shell, style="Glass.TFrame")
        controls.pack(fill="x", pady=(10, 0))

        def clear_selection():
            target_var.set("All")
            popup.destroy()
            refresh_chips()
            update_preview()

        def apply_selection():
            pick = listbox.curselection()
            target_var.set(filtered_items[pick[0]] if pick else "All")
            popup.destroy()
            refresh_chips()
            update_preview()

        ttk.Button(controls, text="Clear", style="Picker.TButton", command=clear_selection).pack(side="left")
        ttk.Button(controls, text="Apply", style="Accent.TButton", command=apply_selection).pack(side="right")
        ttk.Button(controls, text="Cancel", style="Soft.TButton", command=popup.destroy).pack(side="right", padx=(0, 8))

        popup.update_idletasks()
        popup.geometry(f"+{root.winfo_rootx() + 150}+{root.winfo_rooty() + 110}")
        popup.wait_window()

    def make_searchable_combobox(parent: ttk.Frame, variable: tk.StringVar, options: list[str], width: int = 26):
        combo = ttk.Combobox(parent, textvariable=variable, values=options, state="normal", width=width, style="Value.TCombobox")

        def on_filter(_event=None):
            typed = variable.get().strip().lower()
            filtered = [opt for opt in options if typed in opt.lower()] if typed else options
            combo["values"] = filtered

        def normalize_on_focus_out(_event=None):
            value = variable.get().strip()
            if not value:
                variable.set("All")
            elif value.lower() not in {o.lower() for o in options}:
                variable.set("All")
            update_preview()
            refresh_chips()

        combo.bind("<KeyRelease>", on_filter)
        combo.bind("<<ComboboxSelected>>", lambda _e: (refresh_chips(), update_preview()))
        combo.bind("<FocusOut>", normalize_on_focus_out)
        return combo

    def create_section_card(
        parent: ttk.Frame,
        title: str,
        subtitle: str,
        group: str = "neutral",
        subtitle_emphasis: bool = False,
    ):
        group_theme = {
            "neutral": {"head_bg": COLOR_PANEL_ALT, "head_fg": COLOR_HEADING, "sub_fg": COLOR_TEXT_MUTED, "border": COLOR_BORDER},
            "test": {"head_bg": "#EAF3FF", "head_fg": "#173A61", "sub_fg": "#395A7F", "border": "#A9C8E8"},
            "defect": {"head_bg": "#FFF1EC", "head_fg": "#5C2A1F", "sub_fg": "#7E4C3E", "border": "#E8B8A9"},
            "metrics": {"head_bg": "#EEF8F0", "head_fg": "#1F4D2B", "sub_fg": "#3E6A49", "border": "#AFD8B8"},
        }
        theme = group_theme.get(group, group_theme["neutral"])

        shell = tk.Frame(parent, bg=COLOR_BG, bd=0, highlightthickness=0)
        shell.pack(fill="x", pady=(0, 16))

        shadow = tk.Frame(shell, bg="#D2DBE5", bd=0, highlightthickness=0)
        shadow.pack(fill="x", padx=(2, 0), pady=(2, 0))

        card = ttk.Frame(shadow, style="Card.TFrame", padding=20)
        card.pack(fill="x", padx=(0, 1), pady=(0, 1))

        def on_enter(_event):
            card.configure(style="CardHover.TFrame")

        def on_leave(_event):
            card.configure(style="Card.TFrame")

        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)

        head = tk.Frame(card, bg=theme["head_bg"], highlightthickness=1, highlightbackground=theme["border"], bd=0)
        head.pack(fill="x")
        tk.Label(head, text=title, bg=theme["head_bg"], fg=theme["head_fg"], font=(mono_family, 14, "bold")).pack(side="left", padx=(8, 0), pady=(6, 6))
        subtitle_fg = COLOR_ACCENT if subtitle_emphasis else theme["sub_fg"]
        subtitle_font = (base_family, 10, "bold") if subtitle_emphasis else (base_family, 10)
        tk.Label(head, text=subtitle, bg=theme["head_bg"], fg=subtitle_fg, font=subtitle_font).pack(side="left", padx=(10, 0), pady=(6, 6))
        toggle = ttk.Button(head, text="Hide", style="Soft.TButton")
        toggle.pack(side="right", padx=(0, 8), pady=(5, 5))

        body = ttk.Frame(card, style="Card.TFrame")
        body.pack(fill="x", pady=(14, 0))
        collapsed = {"value": False}

        def on_toggle():
            collapsed["value"] = not collapsed["value"]
            if collapsed["value"]:
                body.pack_forget()
                toggle.configure(text="Show")
            else:
                body.pack(fill="x", pady=(12, 0))
                toggle.configure(text="Hide")

        toggle.configure(command=on_toggle)
        return body

    # Left rail: floating filter cards
    test_body = create_section_card(left, "Test Scope", "Projects, domain, cycle, variant", group="test")
    test_body.columnconfigure(0, weight=1)
    test_body.columnconfigure(1, weight=1)

    ttk.Label(test_body, text="Test Projects", style="Label.TLabel").grid(row=0, column=0, sticky="w")
    test_row = ttk.Frame(test_body, style="Card.TFrame")
    test_row.grid(row=1, column=0, columnspan=2, sticky="we", pady=(6, 10))
    test_projects_entry = ttk.Entry(test_row, textvariable=test_projects_var, state="readonly", style="Value.TEntry")
    test_projects_entry.pack(side="left", fill="x", expand=True)
    bind_entry_style(test_projects_entry, test_projects_var, "test")
    ttk.Button(
        test_row,
        text="Browse",
        style="Picker.TButton",
        command=lambda: open_multi_selector(
            TEST_PROJECT_OPTIONS,
            selected_test_projects,
            test_projects_var,
            title="Select Test Projects",
            subtitle="Search and select one or more projects.",
        ),
    ).pack(side="left", padx=(7, 0))

    ttk.Label(test_body, text="Domain", style="Label.TLabel").grid(row=2, column=0, sticky="w")
    ttk.Label(test_body, text="Cycle Type", style="Label.TLabel").grid(row=2, column=1, sticky="w")

    domain_row = ttk.Frame(test_body, style="Card.TFrame")
    domain_row.grid(row=3, column=0, sticky="we", padx=(0, 10), pady=(6, 10))
    domain_entry = ttk.Entry(domain_row, textvariable=domain_var, state="readonly", style="Value.TEntry")
    domain_entry.pack(side="left", fill="x", expand=True)
    bind_entry_style(domain_entry, domain_var, "test")
    ttk.Button(
        domain_row,
        text="Browse",
        style="Picker.TButton",
        command=lambda: open_multi_selector(
            [d for d in DOMAIN_OPTIONS if d.lower() not in {"all", "none"}],
            selected_domains,
            domain_var,
            title="Select Domains",
            subtitle="Search and select one or more domains.",
        ),
    ).pack(side="left", padx=(7, 0))

    segment_wrap = ttk.Frame(test_body, style="Glass.TFrame", padding=(4, 4))
    segment_wrap.grid(row=3, column=1, sticky="we", pady=(6, 10))
    segment_wrap.columnconfigure((0, 1, 2), weight=1)
    seg_buttons = {}

    def refresh_cycle_segment():
        current = cycle_var.get().strip().lower()
        for mode, btn in seg_buttons.items():
            if mode == current:
                btn.configure(
                    bg=COLOR_ACCENT,
                    fg="#FFFFFF",
                    activebackground=COLOR_ACCENT_HOVER,
                    activeforeground="#FFFFFF",
                    highlightbackground="#4A84B6",
                )
            else:
                btn.configure(
                    bg=COLOR_FIELD_ELEVATED,
                    fg=COLOR_TEXT,
                    activebackground="#E7ECF2",
                    activeforeground=COLOR_HEADING,
                    highlightbackground=COLOR_BORDER,
                )

    for col, mode in enumerate(["both", "manual", "automation"]):
        b = tk.Button(
            segment_wrap,
            text=mode.title(),
            relief="flat",
            bd=0,
            highlightthickness=1,
            padx=12,
            pady=7,
            cursor="hand2",
            font=(base_family, 10, "bold"),
            command=lambda m=mode: (cycle_var.set(m), refresh_cycle_segment(), update_preview()),
        )
        b.grid(row=0, column=col, sticky="we", padx=(0 if col == 0 else 2, 0))
        seg_buttons[mode] = b
    refresh_cycle_segment()

    ttk.Label(test_body, text="Variant", style="Label.TLabel").grid(row=4, column=0, sticky="w")
    variant_row = ttk.Frame(test_body, style="Card.TFrame")
    variant_row.grid(row=5, column=0, columnspan=2, sticky="we", pady=(6, 0))
    variant_entry = ttk.Entry(variant_row, textvariable=variant_var, state="readonly", style="Value.TEntry")
    variant_entry.pack(side="left", fill="x", expand=True)
    bind_entry_style(variant_entry, variant_var, "test")
    ttk.Button(
        variant_row,
        text="Browse",
        style="Picker.TButton",
        command=lambda: open_multi_selector(
            [v for v in VARIANT_OPTIONS if v.lower() != "all"],
            selected_variants,
            variant_var,
            title="Select Variants",
            subtitle="Search and select one or more variants.",
        ),
    ).pack(side="left", padx=(7, 0))

    defect_body = create_section_card(left, "Defect Scope", "Defect summary by state report filters", group="defect")
    defect_body.columnconfigure(0, weight=1)
    defect_body.columnconfigure(1, weight=1)

    ttk.Label(defect_body, text="Project", style="Label.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(defect_body, text="Assigned ECU", style="Label.TLabel").grid(row=0, column=1, sticky="w")

    defect_project_row = ttk.Frame(defect_body, style="Card.TFrame")
    defect_project_row.grid(row=1, column=0, sticky="we", padx=(0, 10), pady=(6, 10))
    defect_projects_entry = ttk.Entry(defect_project_row, textvariable=defect_projects_var, state="readonly", style="Value.TEntry")
    defect_projects_entry.pack(side="left", fill="x", expand=True)
    bind_entry_style(defect_projects_entry, defect_projects_var, "defect")
    ttk.Button(
        defect_project_row,
        text="Browse",
        style="Picker.TButton",
        command=lambda: open_multi_selector(
            DEFECT_PROJECT_OPTIONS,
            selected_defect_projects,
            defect_projects_var,
            title="Select Defect Projects",
            subtitle="Search and select one or more defect projects.",
        ),
    ).pack(side="left", padx=(7, 0))

    ecu_row = ttk.Frame(defect_body, style="Card.TFrame")
    ecu_row.grid(row=1, column=1, sticky="we", pady=(6, 10))
    assigned_ecu_entry = ttk.Entry(ecu_row, textvariable=assigned_ecu_var, state="readonly", style="Value.TEntry")
    assigned_ecu_entry.pack(side="left", fill="x", expand=True)
    bind_entry_style(assigned_ecu_entry, assigned_ecu_var, "defect")
    ttk.Button(
        ecu_row,
        text="Browse",
        style="Picker.TButton",
        command=lambda: open_multi_selector(
            ASSIGNED_ECU_OPTIONS,
            selected_assigned_ecus,
            assigned_ecu_var,
            title="Select Assigned ECU",
            subtitle="Search and select one or more Assigned ECU values.",
        ),
    ).pack(side="left", padx=(7, 0))

    ttk.Label(defect_body, text="Defect Raised Team", style="Label.TLabel").grid(row=2, column=0, sticky="w")
    defect_domain_row = ttk.Frame(defect_body, style="Card.TFrame")
    defect_domain_row.grid(row=3, column=0, sticky="we", padx=(0, 10), pady=(6, 0))
    defect_domain_entry = ttk.Entry(defect_domain_row, textvariable=defect_domain_var, state="readonly", style="Value.TEntry")
    defect_domain_entry.pack(side="left", fill="x", expand=True)
    bind_entry_style(defect_domain_entry, defect_domain_var, "defect")
    ttk.Button(
        defect_domain_row,
        text="Browse",
        style="Picker.TButton",
        command=lambda: open_multi_selector(
            [d for d in DOMAIN_OPTIONS if d.lower() != "none"],
            selected_defect_domains,
            defect_domain_var,
            title="Select Defect Raised Teams",
            subtitle="Search and select one or more teams/domains.",
        ),
    ).pack(side="left", padx=(7, 0))

    adhoc_body = create_section_card(left, "Ad-Hoc Scope", "Select domains for Ad-Hoc effort analysis", group="metrics")
    adhoc_body.columnconfigure(0, weight=1)
    ttk.Label(adhoc_body, text="Ad-Hoc Domains", style="Label.TLabel").grid(row=0, column=0, sticky="w")
    adhoc_domain_row = ttk.Frame(adhoc_body, style="Card.TFrame")
    adhoc_domain_row.grid(row=1, column=0, sticky="we", pady=(6, 0))
    adhoc_domain_entry = ttk.Entry(adhoc_domain_row, textvariable=adhoc_domain_var, state="readonly", style="Value.TEntry")
    adhoc_domain_entry.pack(side="left", fill="x", expand=True)
    bind_entry_style(adhoc_domain_entry, adhoc_domain_var, "metrics")
    ttk.Button(
        adhoc_domain_row,
        text="Browse",
        style="Picker.TButton",
        command=lambda: open_multi_selector(
            ADHOC_DOMAIN_OPTIONS,
            selected_adhoc_domains,
            adhoc_domain_var,
            title="Select Ad-Hoc Domains",
            subtitle="Select one or more domains for Ad-Hoc effort analysis.",
        ),
    ).pack(side="left", padx=(7, 0))

    date_body = create_section_card(
        left,
        "Date Range",
        "select date range for Test, Defect, and Ad-Hoc scope",
        subtitle_emphasis=True,
    )
    date_body.columnconfigure(0, weight=1)
    date_body.columnconfigure(1, weight=1)

    ttk.Label(date_body, text="Start Date", style="Label.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(date_body, text="End Date", style="Label.TLabel").grid(row=0, column=1, sticky="w")

    if HAS_TKCALENDAR:
        calendar_style = {
            "date_pattern": "yyyy-mm-dd",
            "firstweekday": "monday",
            "showweeknumbers": True,
            "showothermonthdays": True,
            "background": COLOR_PANEL,
            "foreground": COLOR_TEXT,
            "borderwidth": 1,
            "headersbackground": COLOR_PANEL_ALT,
            "headersforeground": COLOR_TEXT,
            "normalbackground": COLOR_PANEL,
            "normalforeground": COLOR_TEXT,
            "weekendbackground": COLOR_PANEL,
            "weekendforeground": COLOR_TEXT_SOFT,
            "othermonthbackground": COLOR_PANEL,
            "othermonthforeground": COLOR_TEXT_MUTED,
            "othermonthwebackground": COLOR_PANEL,
            "othermonthweforeground": COLOR_TEXT_MUTED,
            "selectbackground": COLOR_ACCENT,
            "selectforeground": COLOR_HEADING,
        }
        start_picker = DateEntry(date_body, textvariable=start_var, width=22, **calendar_style)
        start_picker.set_date(datetime.today())
        start_picker.grid(row=1, column=0, sticky="we", padx=(0, 10), pady=(6, 0))
        end_picker = DateEntry(date_body, textvariable=end_var, width=22, **calendar_style)
        end_picker.set_date(datetime.today())
        end_picker.grid(row=1, column=1, sticky="we", pady=(6, 0))
        start_picker.bind("<<DateEntrySelected>>", lambda _e: update_preview())
        end_picker.bind("<<DateEntrySelected>>", lambda _e: update_preview())
    else:
        start_row = ttk.Frame(date_body, style="Card.TFrame")
        end_row = ttk.Frame(date_body, style="Card.TFrame")
        start_row.grid(row=1, column=0, sticky="we", padx=(0, 10), pady=(6, 0))
        end_row.grid(row=1, column=1, sticky="we", pady=(6, 0))
        start_date_entry = ttk.Entry(start_row, textvariable=start_var, state="readonly", style="Value.TEntry")
        start_date_entry.pack(side="left", fill="x", expand=True)
        bind_entry_style(start_date_entry, start_var, "metrics")
        ttk.Button(start_row, text="Pick", style="Picker.TButton", command=lambda: open_fallback_calendar(start_var)).pack(side="left", padx=(7, 0))
        end_date_entry = ttk.Entry(end_row, textvariable=end_var, state="readonly", style="Value.TEntry")
        end_date_entry.pack(side="left", fill="x", expand=True)
        bind_entry_style(end_date_entry, end_var, "metrics")
        ttk.Button(end_row, text="Pick", style="Picker.TButton", command=lambda: open_fallback_calendar(end_var)).pack(side="left", padx=(7, 0))
        ttk.Label(date_body, text="Install tkcalendar for richer pop-up date controls.", style="Meta.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

    closure_body = create_section_card(left, "Team-wise Defect Metrics", "Select project, raised team, and resolution date range", group="metrics")
    closure_body.columnconfigure(0, weight=1)
    closure_body.columnconfigure(1, weight=1)

    ttk.Label(closure_body, text="Project", style="Label.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(closure_body, text="Defect Raised Team", style="Label.TLabel").grid(row=0, column=1, sticky="w")

    closure_project_row = ttk.Frame(closure_body, style="Card.TFrame")
    closure_project_row.grid(row=1, column=0, sticky="we", padx=(0, 10), pady=(6, 10))
    closure_projects_entry = ttk.Entry(closure_project_row, textvariable=closure_projects_var, state="readonly", style="Value.TEntry")
    closure_projects_entry.pack(side="left", fill="x", expand=True)
    bind_entry_style(closure_projects_entry, closure_projects_var, "metrics")
    ttk.Button(
        closure_project_row,
        text="Browse",
        style="Picker.TButton",
        command=lambda: open_multi_selector(
            DEFECT_PROJECT_OPTIONS,
            selected_closure_projects,
            closure_projects_var,
            title="Select Closure Metric Projects",
            subtitle="Search and select one or more projects.",
        ),
    ).pack(side="left", padx=(7, 0))

    closure_team_row = ttk.Frame(closure_body, style="Card.TFrame")
    closure_team_row.grid(row=1, column=1, sticky="we", pady=(6, 10))
    closure_team_entry = ttk.Entry(closure_team_row, textvariable=closure_team_var, state="readonly", style="Value.TEntry")
    closure_team_entry.pack(side="left", fill="x", expand=True)
    bind_entry_style(closure_team_entry, closure_team_var, "metrics")
    ttk.Button(
        closure_team_row,
        text="Browse",
        style="Picker.TButton",
        command=lambda: open_multi_selector(
            [d for d in DOMAIN_OPTIONS if d.lower() != "none"],
            selected_closure_teams,
            closure_team_var,
            title="Select Closure Teams",
            subtitle="Search and select one or more teams/domains.",
        ),
    ).pack(side="left", padx=(7, 0))

    ttk.Label(closure_body, text="Resolution Start Date", style="Label.TLabel").grid(row=2, column=0, sticky="w")
    ttk.Label(closure_body, text="Resolution End Date", style="Label.TLabel").grid(row=2, column=1, sticky="w")

    if HAS_TKCALENDAR:
        closure_start_picker = DateEntry(closure_body, textvariable=resolution_start_var, width=22, **calendar_style)
        closure_start_picker.set_date(datetime.today())
        closure_start_picker.grid(row=3, column=0, sticky="we", padx=(0, 10), pady=(6, 0))
        closure_end_picker = DateEntry(closure_body, textvariable=resolution_end_var, width=22, **calendar_style)
        closure_end_picker.set_date(datetime.today())
        closure_end_picker.grid(row=3, column=1, sticky="we", pady=(6, 0))
        closure_start_picker.bind("<<DateEntrySelected>>", lambda _e: update_preview())
        closure_end_picker.bind("<<DateEntrySelected>>", lambda _e: update_preview())
    else:
        closure_start_row = ttk.Frame(closure_body, style="Card.TFrame")
        closure_end_row = ttk.Frame(closure_body, style="Card.TFrame")
        closure_start_row.grid(row=3, column=0, sticky="we", padx=(0, 10), pady=(6, 0))
        closure_end_row.grid(row=3, column=1, sticky="we", pady=(6, 0))
        closure_start_entry = ttk.Entry(closure_start_row, textvariable=resolution_start_var, state="readonly", style="Value.TEntry")
        closure_start_entry.pack(side="left", fill="x", expand=True)
        bind_entry_style(closure_start_entry, resolution_start_var, "metrics")
        ttk.Button(closure_start_row, text="Pick", style="Picker.TButton", command=lambda: open_fallback_calendar(resolution_start_var)).pack(side="left", padx=(7, 0))
        closure_end_entry = ttk.Entry(closure_end_row, textvariable=resolution_end_var, state="readonly", style="Value.TEntry")
        closure_end_entry.pack(side="left", fill="x", expand=True)
        bind_entry_style(closure_end_entry, resolution_end_var, "metrics")
        ttk.Button(closure_end_row, text="Pick", style="Picker.TButton", command=lambda: open_fallback_calendar(resolution_end_var)).pack(side="left", padx=(7, 0))

    # Right rail: analytics summary, command panel, execution controls, and runtime logs.

    scope_command_bar = ttk.Frame(right, style="Glass.TFrame", padding=(10, 8))
    scope_command_bar.pack(fill="x", pady=(0, 8))
    scope_command_bar.columnconfigure((0, 1, 2, 3, 4), weight=1)

    ttk.Button(scope_command_bar, text="[T]  Test Scope", style="Scope.TButton", command=lambda: open_scope_dialog("test")).grid(row=0, column=0, sticky="we", padx=(0, 6))
    ttk.Button(scope_command_bar, text="[D]  Defect Scope", style="Scope.TButton", command=lambda: open_scope_dialog("defect")).grid(row=0, column=1, sticky="we", padx=6)
    ttk.Button(scope_command_bar, text="[R]  Resolution Scope", style="Scope.TButton", command=lambda: open_scope_dialog("resolution")).grid(row=0, column=2, sticky="we", padx=6)
    ttk.Button(scope_command_bar, text="[+]  Test Rack Utilisation", style="Scope.TButton", command=lambda: open_scope_dialog("rack")).grid(row=0, column=3, sticky="we", padx=(6, 0))
    ttk.Button(scope_command_bar, text="[A]  Ad-Hoc Scope", style="Scope.TButton", command=lambda: open_scope_dialog("adhoc")).grid(row=0, column=4, sticky="we", padx=(6, 0))

    analytics_card = ttk.Frame(right, style="Card.TFrame", padding=10)
    analytics_card.pack(fill="x", pady=(6, 0))
    ttk.Label(analytics_card, text="Main Analytics Area", style="SectionTitle.TLabel").pack(anchor="w")
    ttk.Label(analytics_card, text="Active filters", style="Meta.TLabel").pack(anchor="w", pady=(1, 4))

    chips_wrap = ttk.Frame(analytics_card, style="Glass.TFrame")
    chips_wrap.pack(fill="x")

    command_card = ttk.Frame(right, style="Card.TFrame", padding=12)
    command_card.pack(fill="x", pady=(8, 0))
    ttk.Label(command_card, text="Generated Command and Automation Panel", style="SectionTitle.TLabel").pack(anchor="w")
    ttk.Label(command_card, text="Resolved runtime command and execution scope details.", style="Meta.TLabel").pack(anchor="w", pady=(2, 8))

    action_row = ttk.Frame(command_card, style="Card.TFrame")
    action_row.pack(fill="x", pady=(0, 10))

    # Runtime Monitoring panel removed from UI by request.
    # Keep an internal text sink so existing logging flow remains unchanged.
    log_card = ttk.Frame(right, style="Card.TFrame", padding=10)
    log_card.pack(fill="both", expand=True, pady=(8, 0))
    ttk.Label(log_card, text="Console Output", style="SectionTitle.TLabel").pack(anchor="w")
    ttk.Label(log_card, text="Live report-generation messages", style="Meta.TLabel").pack(anchor="w", pady=(1, 5))
    log_sink = tk.Frame(log_card, bg="#172331", bd=0, highlightthickness=1, highlightbackground="#34485A")
    log_sink.pack(fill="both", expand=True)
    log_sink.columnconfigure(0, weight=1)
    log_sink.rowconfigure(0, weight=1)
    output = tk.Text(
        log_sink,
        wrap="none",
        bg="#101A24",
        fg="#D6E5F2",
        insertbackground="#FFFFFF",
        selectbackground="#2D5875",
        selectforeground="#FFFFFF",
        relief="flat",
        bd=0,
        highlightthickness=0,
        padx=10,
        pady=10,
        font=(mono_family, 10),
    )
    output.tag_configure("info", foreground="#D6E5F2")
    output.tag_configure("command", foreground="#8CCBFF")
    output.tag_configure("success", foreground="#8FE3A7")
    output.tag_configure("error", foreground="#FF9B9B")
    output.tag_configure("warn", foreground="#FFD27A")
    output.tag_configure("separator", foreground="#71879A")
    output.configure(state="disabled")
    output.grid(row=0, column=0, sticky="nsew")
    output_scrollbar = ttk.Scrollbar(log_sink, orient="vertical", command=output.yview)
    output_scrollbar.grid(row=0, column=1, sticky="ns")
    output.configure(yscrollcommand=output_scrollbar.set)

    def get_start_end_dates() -> tuple[str, str]:
        if HAS_TKCALENDAR:
            return start_picker.get().strip(), end_picker.get().strip()
        return start_var.get().strip(), end_var.get().strip()

    def get_resolution_start_end_dates() -> tuple[str, str]:
        if HAS_TKCALENDAR:
            return closure_start_picker.get().strip(), closure_end_picker.get().strip()
        return resolution_start_var.get().strip(), resolution_end_var.get().strip()

    def render_chip(parent: ttk.Frame, label: str, value: str, row: int, col: int):
        tile = tk.Frame(
            parent,
            bg=COLOR_PANEL,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            bd=0,
            padx=10,
            pady=8,
        )
        tile.grid(row=row, column=col, sticky="we", padx=(0, 6), pady=(0, 6))

        tk.Label(
            tile,
            text=label,
            bg=COLOR_PANEL,
            fg=COLOR_TEXT_MUTED,
            font=(base_family, 8, "bold"),
            anchor="w",
            justify="left",
        ).pack(anchor="w")
        value_fg = COLOR_ACCENT if value.strip().lower() not in {"all", "n/a"} else COLOR_TEXT
        tk.Label(
            tile,
            text=value,
            bg=COLOR_PANEL,
            fg=value_fg,
            font=(base_family, 11, "bold"),
            anchor="w",
            justify="left",
            wraplength=230,
        ).pack(anchor="w", pady=(2, 0))

    def compact_chip_value(value: str, max_len: int = 40) -> str:
        cleaned = " ".join(str(value).split())
        if len(cleaned) <= max_len:
            return cleaned
        return cleaned[: max_len - 3] + "..."

    def refresh_chips():
        for child in chips_wrap.winfo_children():
            child.destroy()

        chips_wrap.columnconfigure(0, weight=1)
        chips_wrap.columnconfigure(1, weight=1)

        groups = [
            ("TEST PROJECTS", test_projects_var.get().strip() or "All"),
            ("DOMAIN", domain_var.get().strip() or "All"),
            ("VARIANT", variant_var.get().strip() or "All"),
            ("DEFECT PROJECT", defect_projects_var.get().strip() or "All"),
            ("DEFECT TEAM", defect_domain_var.get().strip() or "All"),
            ("ASSIGNED ECU", assigned_ecu_var.get().strip() or "All"),
            ("CLOSURE PROJECT", closure_projects_var.get().strip() or "All"),
            ("CLOSURE TEAM", closure_team_var.get().strip() or "All"),
            ("AD-HOC DOMAIN", adhoc_domain_var.get().strip() or "None"),
            ("RACK DOMAIN", rack_domain_var.get().strip() or "All"),
            ("RESOLUTION RANGE", f"{(resolution_start_var.get().strip() or 'N/A')} -> {(resolution_end_var.get().strip() or 'N/A')}") ,
        ]

        for idx, (label, value) in enumerate(groups):
            row = idx // 2
            col = idx % 2
            render_chip(chips_wrap, label, compact_chip_value(value, max_len=52), row=row, col=col)

    def open_scope_dialog(scope: str):
        titles = {
            "test": ("Test Scope", "Projects, domain, cycle type, and variant"),
            "defect": ("Defect Scope", "Defect projects, assigned ECU, and raised team"),
            "resolution": ("Resolution Scope", "Closure projects, team, and resolution period"),
            "rack": ("Test Rack Utilisation", "Rack usage follows the selected test date range and domain"),
            "adhoc": ("Ad-Hoc Scope", "Select Ad-Hoc domains and use the shared report date range as resolution dates"),
        }
        title, subtitle = titles[scope]
        dialog = tk.Toplevel(root)
        dialog.title(title)
        dialog.transient(root)
        dialog.grab_set()
        dialog.configure(bg=COLOR_BG)
        dialog.resizable(False, False)

        shell = ttk.Frame(dialog, style="Card.TFrame", padding=18)
        shell.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(shell, text=title, style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(shell, text=subtitle, style="Meta.TLabel").pack(anchor="w", pady=(3, 14))

        controls = ttk.Frame(shell, style="Card.TFrame")
        controls.pack(fill="x")

        def add_action(label: str, command, value: str):
            row = ttk.Frame(controls, style="Card.TFrame")
            row.pack(fill="x", pady=(0, 8))
            ttk.Label(row, text=label, style="Label.TLabel").pack(side="left")
            ttk.Label(row, text=value, style="Meta.TLabel").pack(side="left", padx=(12, 0), fill="x", expand=True)
            ttk.Button(row, text="Select", style="Picker.TButton", command=command).pack(side="right")

        if scope == "test":
            add_action("Projects", lambda: open_multi_selector(TEST_PROJECT_OPTIONS, selected_test_projects, test_projects_var, "Select Test Projects", "Search and select one or more projects."), test_projects_var.get())
            add_action("Domain", lambda: open_multi_selector([d for d in DOMAIN_OPTIONS if d.lower() not in {"all", "none"}], selected_domains, domain_var, "Select Domains", "Search and select one or more domains."), domain_var.get())
            add_action("Variant", lambda: open_multi_selector([v for v in VARIANT_OPTIONS if v.lower() != "all"], selected_variants, variant_var, "Select Variants", "Search and select one or more variants."), variant_var.get())
            ttk.Label(controls, text="Cycle Type", style="Label.TLabel").pack(anchor="w", pady=(4, 6))
            cycle_row = ttk.Frame(controls, style="Glass.TFrame", padding=4)
            cycle_row.pack(fill="x")
            for mode in ("both", "manual", "automation"):
                ttk.Button(cycle_row, text=mode.title(), style="Picker.TButton", command=lambda selected_mode=mode: (cycle_var.set(selected_mode), refresh_cycle_segment(), update_preview())).pack(side="left", fill="x", expand=True, padx=2)
        elif scope == "defect":
            add_action("Projects", lambda: open_multi_selector(DEFECT_PROJECT_OPTIONS, selected_defect_projects, defect_projects_var, "Select Defect Projects", "Search and select defect projects."), defect_projects_var.get())
            add_action("Assigned ECU", lambda: open_multi_selector(ASSIGNED_ECU_OPTIONS, selected_assigned_ecus, assigned_ecu_var, "Select Assigned ECU", "Search and select ECU values."), assigned_ecu_var.get())
            add_action("Raised Team", lambda: open_multi_selector([d for d in DOMAIN_OPTIONS if d.lower() != "none"], selected_defect_domains, defect_domain_var, "Select Defect Raised Teams", "Search and select one or more teams/domains."), defect_domain_var.get())
        elif scope == "resolution":
            add_action("Projects", lambda: open_multi_selector(DEFECT_PROJECT_OPTIONS, selected_closure_projects, closure_projects_var, "Select Closure Projects", "Search and select closure metric projects."), closure_projects_var.get())
            add_action("Raised Team", lambda: open_multi_selector([d for d in DOMAIN_OPTIONS if d.lower() != "none"], selected_closure_teams, closure_team_var, "Select Closure Teams", "Search and select one or more teams/domains."), closure_team_var.get())
            add_action("Date Range", lambda: open_fallback_calendar(resolution_start_var), f"{resolution_start_var.get()} -> {resolution_end_var.get()}")
        elif scope == "adhoc":
            add_action("Domains", lambda: open_multi_selector(ADHOC_DOMAIN_OPTIONS, selected_adhoc_domains, adhoc_domain_var, "Select Ad-Hoc Domains", "Select one or more domains for Ad-Hoc effort analysis."), adhoc_domain_var.get())
            add_action("Resolution Date Range", lambda: open_fallback_calendar(start_var), f"{start_var.get()} -> {end_var.get()}")
        else:
            add_action("Domain", lambda: open_multi_selector([d for d in DOMAIN_OPTIONS if d.lower() not in {"all", "none"}], selected_rack_domains, rack_domain_var, "Select Rack Domains", "Search and select one or more domains for rack utilisation."), rack_domain_var.get())
            add_action("Date Range", lambda: open_fallback_calendar(start_var), f"{start_var.get()} -> {end_var.get()}")

        ttk.Button(shell, text="Close", style="Accent.TButton", command=dialog.destroy).pack(anchor="e", pady=(16, 0))
        dialog.update_idletasks()
        dialog.geometry(f"+{root.winfo_rootx() + 180}+{root.winfo_rooty() + 120}")

    def append_log(text: str):
        raw = str(text or "").strip("\n")
        if not raw:
            return

        tag = "info"
        lowered = raw.lower()
        if lowered.startswith("stderr") or lowered.startswith("error"):
            tag = "error"
        elif lowered.startswith("command"):
            tag = "command"
        elif lowered.startswith("done"):
            tag = "success"
        elif "failed" in lowered:
            tag = "warn"

        stamp = datetime.now().strftime("%H:%M:%S")
        lines = raw.splitlines() or [raw]

        output.configure(state="normal")
        for line in lines:
            output.insert("end", f"[{stamp}] ", "separator")
            output.insert("end", line + "\n", tag)
        output.see("end")
        output.configure(state="disabled")

    def set_run_state(kind: str, details: str = ""):
        if kind == "running":
            run_state_var.set("Running")
            run_result_var.set("Status: In progress")
            top_status.configure(text="RUNNING", bg="#E8F1FB", fg="#0A4A86")
            start_loading_animation()
        elif kind == "success":
            run_state_var.set("Success")
            run_result_var.set("Status: Completed")
            top_status.configure(text="SUCCESS", bg="#EAF6EE", fg="#166534")
            stop_loading_animation()
        elif kind == "failed":
            run_state_var.set("Failed")
            run_result_var.set("Status: Failed")
            top_status.configure(text="FAILED", bg="#FEECEC", fg="#B42318")
            stop_loading_animation()
        else:
            run_state_var.set("Idle")
            run_result_var.set("Status: Waiting")
            top_status.configure(text="READY", bg="#ECF2F8", fg="#314355")
            stop_loading_animation()

        if details:
            run_result_var.set(details)
        refresh_kpi_strip()

    def update_preview(*_args):
        start_date, end_date = get_start_end_dates()
        resolution_start_date, resolution_end_date = get_resolution_start_end_dates()
        domain = domain_var.get().strip() or "All"
        cycle_type = cycle_var.get().strip().lower() or "both"
        variant = variant_var.get().strip() or "All"
        test_projects = test_projects_var.get().strip() or "ABPI, IDCEVODEV"
        defect_projects = defect_projects_var.get().strip() or "All"
        defect_domain = defect_domain_var.get().strip() or "All"
        defect_assigned_ecu = assigned_ecu_var.get().strip() or "All"
        closure_projects = closure_projects_var.get().strip() or "All"
        closure_team = closure_team_var.get().strip() or "All"
        adhoc_domains = adhoc_domain_var.get().strip() or "None"
        rack_domain = rack_domain_var.get().strip() or "All"

        cmd = build_command(
            report_script,
            start_date,
            end_date,
            test_projects,
            domain,
            cycle_type,
            variant,
            defect_projects,
            defect_domain,
            defect_assigned_ecu,
            closure_projects,
            closure_team,
            resolution_start_date,
            resolution_end_date,
            adhoc_domains=adhoc_domains,
            rack_domain=rack_domain,
        )

        apply_field_styles()
        refresh_kpi_strip()

    def on_generate():
        start_date, end_date = get_start_end_dates()
        resolution_start_date, resolution_end_date = get_resolution_start_end_dates()
        domain = domain_var.get().strip() or "All"
        cycle_type = cycle_var.get().strip().lower() or "both"
        variant = variant_var.get().strip() or "All"
        test_projects = test_projects_var.get().strip() or "ABPI, IDCEVODEV"
        defect_projects = defect_projects_var.get().strip() or "All"
        defect_domain = defect_domain_var.get().strip() or "All"
        defect_assigned_ecu = assigned_ecu_var.get().strip() or "All"
        closure_projects = closure_projects_var.get().strip() or "All"
        closure_team = closure_team_var.get().strip() or "All"
        adhoc_domains = adhoc_domain_var.get().strip() or "None"
        rack_domain = rack_domain_var.get().strip() or "All"

        if not is_valid_date(start_date):
            messagebox.showerror("Invalid Start Date", "Start Date must be in YYYY-MM-DD format.")
            return
        if not is_valid_date(end_date):
            messagebox.showerror("Invalid End Date", "End Date must be in YYYY-MM-DD format.")
            return
        if end_date < start_date:
            messagebox.showerror("Invalid Date Range", "End Date must be greater than or equal to Start Date.")
            return
        if not is_valid_date(resolution_start_date):
            messagebox.showerror("Invalid Resolution Start Date", "Resolution Start Date must be in YYYY-MM-DD format.")
            return
        if not is_valid_date(resolution_end_date):
            messagebox.showerror("Invalid Resolution End Date", "Resolution End Date must be in YYYY-MM-DD format.")
            return
        if resolution_end_date < resolution_start_date:
            messagebox.showerror("Invalid Resolution Date Range", "Resolution End Date must be greater than or equal to Resolution Start Date.")
            return

        load_jira_credentials()
        load_test_guide_credentials()
        if not (os.getenv("TEST_GUIDE_TOKEN", "").strip() or os.getenv("TEST_GUIDE_AUTH_KEY", "").strip()):
            append_log(
                "WARNING: TEST_GUIDE_TOKEN is not available in the dashboard process. "
                "Rack utilisation cannot be fetched from test.guide."
            )

        cmd = build_command(
            report_script,
            start_date,
            end_date,
            test_projects,
            domain,
            cycle_type,
            variant,
            defect_projects,
            defect_domain,
            defect_assigned_ecu,
            closure_projects,
            closure_team,
            resolution_start_date,
            resolution_end_date,
            adhoc_domains=adhoc_domains,
            rack_domain=rack_domain,
        )

        append_log("Running report generation...")
        append_log("Command: " + " ".join(cmd))
        status_var.set("Generating report...")
        set_run_state("running")
        run_time_var.set(f"Last run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        generate_btn.configure(state="disabled", text="[Run] Generating...")

        def finish_generation(result=None, error: Exception | None = None):
            generate_btn.configure(state="normal", text="[Run] Generate Report")
            if error is not None:
                messagebox.showerror("Error", str(error))
                append_log(f"Error: {error}")
                status_var.set("Execution error")
                set_run_state("failed", "Status: Runtime exception")
                return

            if result.stdout:
                append_log(result.stdout.strip())
            if result.stderr:
                append_log("STDERR:\n" + result.stderr.strip())

            if result.returncode == 0:
                messagebox.showinfo("Success", "Report generated successfully.")
                append_log("Done.")
                status_var.set("Report generated successfully")
                set_run_state("success", "Status: Completed with exit code 0")
            else:
                messagebox.showerror("Failed", f"Report generation failed with exit code {result.returncode}.")
                append_log("Failed.")
                status_var.set(f"Failed with exit code {result.returncode}")
                set_run_state("failed", f"Status: Exit code {result.returncode}")

        def run_generation():
            result = subprocess.run(cmd, cwd=base_dir, text=True, capture_output=True, check=False)
            root.after(0, finish_generation, result, None)

        def handle_generation_error(exc: Exception):
            root.after(0, finish_generation, None, exc)

        def worker():
            try:
                run_generation()
            except Exception as exc:
                handle_generation_error(exc)

        threading.Thread(target=worker, name="report-generation", daemon=True).start()

    def on_clear_log():
        output.configure(state="normal")
        output.delete("1.0", "end")
        output.configure(state="disabled")
        status_var.set("Ready")
        set_run_state("idle")

    generate_btn = tk.Button(
        action_row,
        text="[Run] Generate Report",
        command=on_generate,
        bg=COLOR_ACCENT,
        fg="#FFFFFF",
        activebackground=COLOR_ACCENT_HOVER,
        activeforeground="#FFFFFF",
        disabledforeground="#FFFFFF",
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground="#4A84B6",
        highlightcolor=COLOR_ACCENT_HOVER,
        padx=22,
        pady=12,
        cursor="hand2",
        font=(base_family, 11, "bold"),
    )
    generate_btn.pack(side="left")
    bind_hover(generate_btn, COLOR_ACCENT, COLOR_ACCENT_HOVER)

    clear_btn = tk.Button(
        action_row,
        text="[Log] Clear Output",
        command=on_clear_log,
        bg=COLOR_FIELD_ELEVATED,
        fg=COLOR_TEXT,
        activebackground="#E7ECF2",
        activeforeground=COLOR_HEADING,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=COLOR_BORDER,
        highlightcolor=COLOR_ACCENT,
        padx=18,
        pady=12,
        cursor="hand2",
        font=(base_family, 10, "bold"),
    )
    clear_btn.pack(side="left", padx=(9, 0))
    bind_hover(clear_btn, COLOR_FIELD_ELEVATED, "#E7ECF2")

    credentials_btn = tk.Button(
        action_row,
        text="[Key] Credentials",
        command=open_credentials_dialog,
        bg=COLOR_FIELD_ELEVATED,
        fg=COLOR_TEXT,
        activebackground="#E7ECF2",
        activeforeground=COLOR_HEADING,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=COLOR_BORDER,
        highlightcolor=COLOR_ACCENT,
        padx=18,
        pady=12,
        cursor="hand2",
        font=(base_family, 10, "bold"),
    )
    credentials_btn.pack(side="left", padx=(9, 0))
    bind_hover(credentials_btn, COLOR_FIELD_ELEVATED, "#E7ECF2")

    for var in [
        test_projects_var,
        domain_var,
        cycle_var,
        variant_var,
        defect_projects_var,
        defect_domain_var,
        assigned_ecu_var,
        closure_projects_var,
        closure_team_var,
        adhoc_domain_var,
        start_var,
        end_var,
        resolution_start_var,
        resolution_end_var,
    ]:
        var.trace_add("write", update_preview)

    refresh_chips()
    update_preview()
    apply_field_styles()
    root.mainloop()


if HAS_QT_FRONTEND:
    def install_qt_exception_hook():
        """PyQt6 aborts the whole process on any unhandled exception raised inside a
        Qt slot (e.g. typing in a field, a button click) unless sys.excepthook is
        overridden - the default behavior is a silent/instant crash with no dialog.
        This keeps the app alive, prints the real traceback to the console, and
        shows a message box so the error is visible even when launched without a
        console (e.g. double-clicked)."""
        import traceback

        def _handle_exception(exc_type, exc_value, exc_traceback):
            traceback.print_exception(exc_type, exc_value, exc_traceback)
            try:
                QMessageBox.critical(
                    None,
                    "Unexpected error",
                    f"{exc_type.__name__}: {exc_value}\n\n"
                    "The dashboard will stay open, but this action may not have "
                    "completed. Please report this message (and the console output "
                    "if visible) so it can be fixed.",
                )
            except Exception:
                pass

        sys.excepthook = _handle_exception

    class MultiSelectComboBox(QComboBox):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.multi_popup = None
            self.multi_options = []
            self.multi_selected = []
            self.multi_confirm = None
            self.multi_cancel = None
            self.multi_option_list = None

        def _position_popup(self, popup):
            screen = self.screen()
            available = screen.availableGeometry() if screen else None
            if available is None:
                popup.move(self.mapToGlobal(self.rect().bottomLeft()))
                return
            popup_width = min(max(self.width(), 380), available.width() - 16)
            popup.setFixedWidth(max(320, popup_width))
            popup.adjustSize()
            field_bottom = self.mapToGlobal(self.rect().bottomLeft())
            x = max(available.left() + 8, min(field_bottom.x(), available.right() - popup.width() - 8))
            below_y = field_bottom.y()
            above_y = self.mapToGlobal(self.rect().topLeft()).y() - popup.height()
            y = below_y if below_y + popup.height() <= available.bottom() else max(available.top() + 8, above_y)
            popup.move(x, y)

        def hidePopup(self):
            if self.multi_popup is not None and self.multi_popup.isVisible():
                self.multi_popup.hide()
                return
            super().hidePopup()

        def eventFilter(self, watched, event):
            if watched is self.lineEdit() and event.type() == QEvent.Type.MouseButtonPress:
                self.showPopup()
                return True
            return super().eventFilter(watched, event)

        def configure_multi_popup(self, options, selected, confirm, cancel):
            self.multi_options = list(options)
            self.multi_selected = list(selected)
            self.multi_confirm = confirm
            self.multi_cancel = cancel

        def showPopup(self):
            if self.multi_popup is not None and self.multi_popup.isVisible():
                return
            if self.multi_popup is not None and self.multi_option_list is not None:
                selected_lookup = {value.casefold() for value in self.multi_selected}
                for index in range(self.multi_option_list.count()):
                    item = self.multi_option_list.item(index)
                    checkbox = self.multi_option_list.itemWidget(item)
                    if checkbox is not None:
                        checkbox.setChecked(item.text().casefold() in selected_lookup)
                self.multi_popup.adjustSize()
                self._position_popup(self.multi_popup)
                self.multi_popup.show()
                self.multi_option_list.setFocus()
                return
            popup = QDialog(self, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
            popup.setObjectName("multiSelectPopup")
            popup.setAccessibleName("Multi-select options")
            popup.setModal(False)
            popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            popup.setStyleSheet("QFrame#multiSelectPopup { background: #FFFFFF; border: 1px solid #AFC2D3; border-radius: 8px; }")
            layout = QVBoxLayout(popup)
            layout.setContentsMargins(6, 6, 6, 6)
            search_box = QLineEdit(popup)
            search_box.setPlaceholderText("Search...")
            search_box.setClearButtonEnabled(True)
            search_box.setAccessibleName("Search options")
            search_box.setStyleSheet("QLineEdit { border: 1px solid #C9D8E5; border-radius: 6px; padding: 6px 8px; font-size: 12px; margin-bottom: 4px; background: #FFFFFF; color: #1F2D3A; } QLineEdit:focus { border-color: #0066B1; }")
            layout.addWidget(search_box)
            option_list = QListWidget(popup)
            option_list.setAccessibleName("Selectable options")
            option_list.setAccessibleDescription("Use Space to toggle an option, then choose Confirm or Cancel.")
            option_list.setTabKeyNavigation(True)
            option_list.setMinimumHeight(260)
            option_list.setMaximumHeight(360)
            option_list.setStyleSheet("QListWidget { border: 1px solid #D6E2EC; border-radius: 6px; background: #FFFFFF; color: #1F2D3A; padding: 4px; font-size: 12px; } QListWidget::item { min-height: 28px; padding: 5px 7px; } QListWidget::item:hover { background: #EEF6FD; } QListWidget::item:selected { background: #DCEEFF; color: #173A61; } QListWidget QScrollBar:vertical { background: #DCE3EA; width: 14px; margin: 2px 1px 2px 1px; border: 1px solid #B8C6D4; border-radius: 5px; } QListWidget QScrollBar::handle:vertical { background: #60788E; min-height: 36px; border-radius: 4px; } QListWidget QScrollBar::handle:vertical:hover { background: #405B72; } QListWidget QScrollBar::add-line:vertical, QListWidget QScrollBar::sub-line:vertical { height: 14px; background: #C7D1DC; border: 1px solid #AAB9C8; } QListWidget QScrollBar::add-page:vertical, QListWidget QScrollBar::sub-page:vertical { background: #DCE3EA; }")
            selected_lookup = {value.casefold() for value in self.multi_selected}

            def pending_values():
                return [
                    option_list.item(index).text()
                    for index in range(option_list.count())
                    if option_list.itemWidget(option_list.item(index)).isChecked()
                ]

            def refresh_pending_text():
                self.lineEdit().setText(", ".join(pending_values()))
                self.lineEdit().setCursorPosition(0)

            def refresh_checkbox_mark(checkbox, option, checked):
                checkbox.setText(f"{'✓' if checked else ' '} {option}")

            for option in self.multi_options:
                item = QListWidgetItem(option)
                checkbox = QCheckBox(option, option_list)
                checkbox.setChecked(option.casefold() in selected_lookup)
                checkbox.setAccessibleName(option)
                checkbox.setMinimumHeight(28)
                checkbox.setStyleSheet("QCheckBox { color: #1F2D3A; spacing: 8px; padding: 5px 7px; } QCheckBox:hover { background: #EEF6FD; } QCheckBox::indicator { width: 17px; height: 17px; }")
                refresh_checkbox_mark(checkbox, option, checkbox.isChecked())
                checkbox.stateChanged.connect(refresh_pending_text)
                checkbox.stateChanged.connect(lambda checked, control=checkbox, value=option: refresh_checkbox_mark(control, value, checked))
                option_list.addItem(item)
                option_list.setItemWidget(item, checkbox)

            def filter_options(text):
                """Self-contained filter for this popup's own list - deliberately does not
                touch the combobox's native completer/popup machinery (see showPopup's
                override above), which is what caused the crash when typing to search."""
                needle = text.strip().lower()
                for index in range(option_list.count()):
                    item = option_list.item(index)
                    item.setHidden(bool(needle) and needle not in item.text().lower())

            search_box.textChanged.connect(filter_options)
            pressed_state = {"value": None}
            option_list.itemPressed.connect(lambda item: pressed_state.__setitem__("value", item))
            option_list.itemClicked.connect(lambda item: self.multi_option_list.itemWidget(item).toggle())
            layout.addWidget(option_list)
            self.multi_option_list = option_list
            buttons = QHBoxLayout()
            select_all_button = QPushButton("Select all", popup)
            deselect_all_button = QPushButton("Deselect all", popup)
            buttons.addStretch(1)
            confirm_button = QPushButton("Confirm", popup)
            cancel_button = QPushButton("Cancel", popup)
            select_all_button.setAccessibleName("Select all options")
            deselect_all_button.setAccessibleName("Deselect all options")
            confirm_button.setAccessibleName("Confirm selection")
            cancel_button.setAccessibleName("Cancel selection")
            select_all_button.setMinimumHeight(30)
            deselect_all_button.setMinimumHeight(30)
            confirm_button.setMinimumHeight(30)
            cancel_button.setMinimumHeight(30)
            select_all_button.setStyleSheet("QPushButton { background: #F1F5F8; color: #1F2D3A; border: 1px solid #C9D8E5; border-radius: 5px; padding: 6px 15px; font-weight: 700; } QPushButton:hover { background: #E5EDF4; }")
            deselect_all_button.setStyleSheet("QPushButton { background: #F1F5F8; color: #1F2D3A; border: 1px solid #C9D8E5; border-radius: 5px; padding: 6px 15px; font-weight: 700; } QPushButton:hover { background: #E5EDF4; }")
            confirm_button.setStyleSheet("QPushButton { background: #0066B1; color: #FFFFFF; border: none; border-radius: 5px; padding: 6px 15px; font-weight: 700; } QPushButton:hover { background: #00538F; }")
            cancel_button.setStyleSheet("QPushButton { background: #F1F5F8; color: #1F2D3A; border: 1px solid #C9D8E5; border-radius: 5px; padding: 6px 15px; } QPushButton:hover { background: #E5EDF4; }")
            buttons.insertWidget(0, select_all_button)
            buttons.insertWidget(1, deselect_all_button)
            buttons.addWidget(confirm_button)
            buttons.addWidget(cancel_button)
            layout.addLayout(buttons)

            def select_all_options():
                for index in range(option_list.count()):
                    checkbox = option_list.itemWidget(option_list.item(index))
                    if checkbox is not None:
                        checkbox.setChecked(True)

            def deselect_all_options():
                for index in range(option_list.count()):
                    checkbox = option_list.itemWidget(option_list.item(index))
                    if checkbox is not None:
                        checkbox.setChecked(False)

            select_all_button.clicked.connect(select_all_options)
            deselect_all_button.clicked.connect(deselect_all_options)

            def confirm_selection():
                values = pending_values()
                self.multi_selected = values
                if self.multi_confirm:
                    self.multi_confirm(values)
                popup.hide()

            def cancel_selection():
                if self.multi_cancel:
                    self.multi_cancel()
                self.lineEdit().setText(", ".join(self.multi_selected))
                self.lineEdit().setCursorPosition(0)
                popup.hide()

            confirm_button.clicked.connect(confirm_selection)
            cancel_button.clicked.connect(cancel_selection)
            self.multi_popup = popup
            popup.adjustSize()
            self._position_popup(popup)
            popup.show()
            option_list.setFocus()
            search_box.setFocus()


    class QtReportWorker(QThread):
        output_received = pyqtSignal(str, bool)
        finished = pyqtSignal(int)

        def __init__(self, command: list[str], cwd: str):
            super().__init__()
            self.command = command
            self.cwd = cwd
            self.process = None

        def run(self):
            try:
                self.process = subprocess.Popen(
                    self.command,
                    cwd=self.cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                if self.process.stdout:
                    for line in self.process.stdout:
                        self.output_received.emit(line.rstrip(), False)
                self.finished.emit(self.process.wait())
            except Exception as exc:
                self.output_received.emit(str(exc), True)
                self.finished.emit(1)
            finally:
                self.process = None

        def stop(self):
            process = self.process
            if process is None or process.poll() is not None:
                return
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


    class QtReportDashboard(FluentWindow):
        def __init__(self):
            super().__init__()
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
            self.report_script = os.path.join(self.base_dir, "test_execution_report_v2.py")
            self.worker: QtReportWorker | None = None
            QApplication.instance().installEventFilter(self)
            self.setWindowTitle("Efforts Calculator Simplified")
            self.resize(1440, 900)
            self.setMinimumSize(1180, 760)
            setTheme(Theme.LIGHT)
            setThemeColor("#0066B1")

            self.start_date = QDate.currentDate()
            self.end_date = QDate.currentDate()
            self.resolution_start = QDate.currentDate()
            self.resolution_end = QDate.currentDate()
            self.test_projects = ["ABPI", "IDCEVODEV"]
            self.defect_projects: list[str] = []
            self.domains: list[str] = []
            self.variants: list[str] = []
            self.assigned_ecus: list[str] = []
            self.closure_projects: list[str] = []
            self.adhoc_domains: list[str] = ["Telematics"]
            self.rack_domain: list[str] = []
            self.feature_domains: list[str] = []
            self.feature_sop_pu: list[str] = list(FEATURE_SOP_PU_OPTIONS)
            self.feature_subtasks: list[str] = list(FEATURE_SUBTASK_OPTIONS)
            self.feature_products: list[str] = list(FEATURE_PRODUCT_OPTIONS)
            self.feature_resolution_start = QDate.currentDate()
            self.feature_resolution_end = QDate.currentDate()
            self.domain = "All"
            self.defect_domain = "All"
            self.closure_team = "All"
            self.cycle_type = "both"
            self.active_scope = ""
            self.report_scopes: set[str] = set()
            self.drawer_fields: dict[str, QComboBox] = {}
            self.drawer_chips: dict[str, list[str]] = {}

            self.dashboard_page = QWidget()
            self.dashboard_page.setObjectName("dashboardPage")
            self._build_dashboard()
            self.addSubInterface(self.dashboard_page, FluentIcon.HOME, "Dashboard", NavigationItemPosition.TOP)
            for text, icon in (("Projects", FluentIcon.FOLDER), ("Defects", FluentIcon.HEART), ("Analytics", FluentIcon.SPEED_HIGH), ("Test Racks", FluentIcon.SPEED_HIGH), ("Reports", FluentIcon.DOCUMENT)):
                page = QWidget()
                page.setObjectName(text.replace(" ", ""))
                page.setStyleSheet("background: #F5F7FA;")
                self.addSubInterface(page, icon, text, NavigationItemPosition.TOP)
            self.navigationInterface.hide()

        def _build_dynamic_greeting(self) -> str:
            now = datetime.now()
            hour = now.hour
            if 5 <= hour < 12:
                greeting = "Good morning"
            elif 12 <= hour < 17:
                greeting = "Good afternoon"
            elif 17 <= hour < 21:
                greeting = "Good evening"
            else:
                greeting = "Working late"
            iso = now.isocalendar()
            day_of_year = now.timetuple().tm_yday
            days_in_year = 366 if pycalendar.isleap(now.year) else 365
            return f"{greeting} — CW{iso.week:02d}, {iso.year} | Day {day_of_year} of {days_in_year}"

        def _refresh_greeting(self):
            if hasattr(self, "greeting_label"):
                self.greeting_label.setText(self._build_dynamic_greeting())

        def _build_dashboard(self):
            root_layout = QVBoxLayout(self.dashboard_page)
            root_layout.setContentsMargins(18, 12, 18, 14)
            root_layout.setSpacing(8)
            self.dashboard_page.setStyleSheet("background: #F4F7FA;")

            header = QWidget()
            header.setStyleSheet("background: #FFFFFF; border: 1px solid #DCE3EA; border-radius: 5px;")
            header_layout = QGridLayout(header)
            header_layout.setContentsMargins(16, 10, 16, 10)
            header_layout.setHorizontalSpacing(10)
            header_layout.setVerticalSpacing(2)
            header_layout.setColumnStretch(0, 1)
            title_label = TitleLabel("Efforts Calculator Simplified")
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_label.setStyleSheet("font-size: 30px; font-weight: 800; color: #0F172A; letter-spacing: 0.5px; padding: 10px 8px 0px;")
            title_box = QVBoxLayout()
            title_box.setContentsMargins(0, 0, 0, 0)
            title_box.setSpacing(2)
            title_box.addWidget(title_label)
            self.greeting_label = BodyLabel(self._build_dynamic_greeting())
            self.greeting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.greeting_label.setStyleSheet(f"color: {QT_THEME['text_muted']}; font-size: 12px; font-weight: 600; padding: 0px 8px 12px;")
            title_box.addWidget(self.greeting_label)
            header_layout.addLayout(title_box, 0, 0, 1, 2)
            self.greeting_timer = QTimer(self)
            self.greeting_timer.timeout.connect(self._refresh_greeting)
            self.greeting_timer.start(60000)
            self.status_label = StrongBodyLabel("READY")
            self.status_label.setStyleSheet("color: #16733A; font-size: 11px; font-weight: 700; padding: 4px 9px;")
            header_layout.addWidget(self.status_label, 1, 1, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            root_layout.addWidget(header)

            command_bar = QWidget()
            command_bar.setStyleSheet("background: transparent;")
            command_layout = QHBoxLayout(command_bar)
            command_layout.setContentsMargins(0, 0, 0, 0)
            command_layout.setSpacing(10)
            self.scope_cards: dict[str, QToolButton] = {}
            command_styles = {
                "test": ("#0879D1", FluentIcon.FILTER, "Test Scope", "Define test filters"),
                "defect": ("#7044D5", FluentIcon.HEART, "Defect Scope", "Define defect filters"),
                "resolution": ("#087B50", FluentIcon.ACCEPT, "Defect Resolution Scope", "Define resolution filters"),
                "rack": ("#EE8A18", FluentIcon.SPEED_HIGH, "Test Rack Utilisation", "Rack usage and execution"),
                "adhoc": ("#C04A72", FluentIcon.SEARCH, "Ad-Hoc Efforts Scope", "Define Ad-Hoc domains and dates"),
                "feature": ("#B45309", FluentIcon.DOCUMENT, "Feature Scope", "RG3/RG4 and RG4.5 SYS.5 closures"),
            }

            for scope in ("test", "defect", "resolution", "rack", "adhoc", "feature"):
                color, icon, label, subtitle = command_styles[scope]
                button = QToolButton()
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                button.setIcon(icon.icon(color=QColor(color)))
                button.setIconSize(QSize(40, 40))
                button.setText(label)
                button.setToolTip("")
                button.setMinimumHeight(92)
                button.setProperty("selected", False)
                button.setProperty("active", False)
                button.setStyleSheet(
                    "QToolButton { background: #FFFFFF; color: #1F2D3A; border: 1px solid #DCE3EA; "
                    "border-left: 4px solid transparent; border-top: 3px solid transparent; border-radius: 12px; "
                    "padding: 8px 10px 7px; font-size: 12px; font-weight: 700; } "
                    "QToolButton:hover { background: #F4F8FC; border-color: #C7D8E8; } "
                    "QToolButton:pressed { background: #EAF2F9; } "
                    f"QToolButton[selected=\"true\"] {{ background: #EEF3F8; border-left: 4px solid {QT_THEME['selected']}; color: {QT_THEME['selected']}; }} "
                    f"QToolButton[active=\"true\"] {{ border-top: 3px solid {QT_THEME['active']}; }}"
                )
                button.installEventFilter(self)
                self.scope_cards[scope] = button
                button.clicked.connect(lambda checked=False, value=scope: self.open_filter_dialog(value))
                command_layout.addWidget(button, 1)
            root_layout.addWidget(command_bar)

            self.filter_drawer = QWidget()
            self.filter_drawer.setMinimumWidth(QT_LAYOUT["drawer_min_width"])
            self.filter_drawer.setMaximumWidth(QT_LAYOUT["drawer_max_width"])
            self.filter_drawer.setStyleSheet("background: #FDFEFF; border: 1px solid #C8D8E6; border-radius: 12px;")
            drawer_layout = QVBoxLayout(self.filter_drawer)
            drawer_layout.setContentsMargins(14, 11, 14, 12)
            drawer_layout.setSpacing(10)
            drawer_header = QHBoxLayout()
            self.drawer_title = StrongBodyLabel("Filter configuration")
            drawer_header.addWidget(self.drawer_title)
            drawer_header.addStretch(1)
            self.drawer_count = BodyLabel("0 selected")
            self.drawer_count.setStyleSheet("color: #0066B1; font-weight: 700;")
            drawer_header.addWidget(self.drawer_count)
            drawer_layout.addLayout(drawer_header)
            self.drawer_subtitle = BodyLabel("Choose a scope above to configure filters.")
            self.drawer_subtitle.setStyleSheet("color: #637282; font-size: 12px;")
            drawer_layout.addWidget(self.drawer_subtitle)
            self.drawer_controls = QWidget()
            self.drawer_controls_layout = QVBoxLayout(self.drawer_controls)
            self.drawer_controls_layout.setContentsMargins(0, 0, 0, 0)
            self.drawer_controls_layout.setSpacing(6)
            drawer_scroll = QScrollArea()
            drawer_scroll.setWidgetResizable(True)
            drawer_scroll.setFrameShape(QFrame.Shape.NoFrame)
            drawer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            drawer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            drawer_scroll.setStyleSheet("QScrollBar:vertical { background: #DCE3EA; width: 14px; margin: 2px 1px 2px 1px; border: 1px solid #B8C6D4; border-radius: 5px; } QScrollBar::handle:vertical { background: #60788E; min-height: 36px; border-radius: 4px; } QScrollBar::handle:vertical:hover { background: #405B72; } QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 14px; background: #C7D1DC; border: 1px solid #AAB9C8; } QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: #DCE3EA; }")
            drawer_scroll.setMinimumHeight(250)
            drawer_scroll.setMaximumHeight(320)
            drawer_scroll.setWidget(self.drawer_controls)
            drawer_layout.addWidget(drawer_scroll, 1)
            drawer_footer = QFrame()
            drawer_footer.setObjectName("drawerFooter")
            drawer_footer.setStyleSheet("QFrame#drawerFooter { background: #F7FAFD; border-top: 1px solid #E1EAF2; border-radius: 0px 0px 10px 10px; }")
            drawer_actions = QHBoxLayout(drawer_footer)
            drawer_actions.setContentsMargins(8, 8, 0, 0)
            drawer_actions.addStretch(1)
            self.apply_filters_button = PrimaryPushButton("Apply Filters")
            self.apply_filters_button.clicked.connect(self.apply_drawer_filters)
            drawer_actions.addWidget(self.apply_filters_button)
            drawer_actions.addStretch(1)
            drawer_layout.addWidget(drawer_footer)
            self.filter_drawer.hide()
            root_layout.removeWidget(self.filter_drawer)
            self.filter_drawer.setParent(self.dashboard_page)

            content = QWidget()
            content_layout = QHBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(10)
            main_column = QVBoxLayout()
            main_column.setContentsMargins(0, 0, 0, 0)
            main_column.setSpacing(8)
            content_layout.addLayout(main_column, 1)
            root_layout.addWidget(content, 1)

            self.filter_summary = QWidget()
            self.filter_summary.setStyleSheet("background: #FFFFFF; border: 1px solid #DCE3EA; border-radius: 5px;")
            summary_layout = QGridLayout(self.filter_summary)
            summary_layout.setContentsMargins(10, 7, 10, 7)
            summary_layout.setHorizontalSpacing(7)
            summary_layout.setVerticalSpacing(4)
            summary_layout.addWidget(StrongBodyLabel("Active Filter Summary"), 0, 0, 1, 9)
            self.summary_labels: dict[str, BodyLabel] = {}
            summary_keys = ("Projects", "Domain", "Variant", "Cycle Type", "Defect Team", "Closure Team", "Date Range")
            for index, key in enumerate(summary_keys):
                label = BodyLabel()
                label.setStyleSheet("background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 3px; color: #174A88; font-size: 10px; font-weight: 600; padding: 5px 7px;")
                self.summary_labels[key] = label
                summary_layout.addWidget(label, 1, index)
            self.summary_labels["Resolution Range"] = BodyLabel()
            self.summary_labels["Resolution Range"].setStyleSheet("background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 3px; color: #174A88; font-size: 10px; font-weight: 600; padding: 5px 7px;")
            summary_layout.addWidget(self.summary_labels["Resolution Range"], 1, 7)
            clear_button = PushButton("Clear All")
            clear_button.clicked.connect(self.clear_filters)
            summary_layout.addWidget(clear_button, 1, 8)
            feature_summary_keys = ("Feature Domain", "Feature Product", "Feature Sub-task", "Feature SOP/PU", "Feature Resolution")
            for index, key in enumerate(feature_summary_keys):
                label = BodyLabel()
                label.setStyleSheet("background: #FFF7ED; border: 1px solid #FDE1B8; border-radius: 3px; color: #8A4B0D; font-size: 10px; font-weight: 600; padding: 5px 7px;")
                self.summary_labels[key] = label
                summary_layout.addWidget(label, 2, index)
            main_column.addWidget(self.filter_summary)
            self._refresh_summary()

            action_row = QHBoxLayout()
            action_row.setContentsMargins(0, 0, 0, 0)
            action_row.addStretch(1)
            self.credentials_button = PushButton("Jira / test.guide Credentials")
            self.credentials_button.clicked.connect(self.open_credentials_dialog)
            action_row.addWidget(self.credentials_button)
            self.generate_button = PrimaryPushButton("Generate Executive Report")
            self.generate_button.setMinimumWidth(230)
            self.generate_button.clicked.connect(self.generate_report)
            action_row.addWidget(self.generate_button)
            self.cancel_button = PushButton("Cancel Report")
            self.cancel_button.setEnabled(False)
            self.cancel_button.clicked.connect(self.cancel_report)
            action_row.addWidget(self.cancel_button)
            action_row.addStretch(1)
            main_column.addLayout(action_row)

            console_card = QWidget()
            console_card.setStyleSheet("background: #FFFFFF; border: 1px solid #DCE3EA; border-radius: 5px;")
            console_layout = QVBoxLayout(console_card)
            console_layout.setContentsMargins(10, 7, 10, 8)
            console_header = QHBoxLayout()
            console_header.addWidget(StrongBodyLabel("Console Output"))
            console_header.addStretch(1)
            self.console_toggle_button = PushButton("Show technical log")
            self.console_toggle_button.setCheckable(True)
            self.console_toggle_button.toggled.connect(self._toggle_console)
            console_header.addWidget(self.console_toggle_button)
            console_layout.addLayout(console_header)
            self.console = PlainTextEdit()
            self.console.setReadOnly(True)
            self.console.setStyleSheet("QPlainTextEdit { background: #101A24; color: #D6E5F2; border: 1px solid #34485A; border-radius: 4px; padding: 8px; font-family: Consolas; font-size: 10px; }")
            self.console.setVisible(False)
            console_layout.addWidget(self.console, 1)
            main_column.addWidget(console_card, 1)

        def _toggle_console(self, checked: bool):
            self.console.setVisible(checked)
            self.console_toggle_button.setText("Hide technical log" if checked else "Show technical log")

        def _refresh_summary(self):
            self.summary_labels["Projects"].setText(f"Projects: {', '.join(self.test_projects)}")
            self.summary_labels["Domain"].setText(f"Domain: {self.domain}")
            self.summary_labels["Variant"].setText(f"Variant: {', '.join(self.variants) or 'All'}")
            self.summary_labels["Cycle Type"].setText(f"Cycle Type: {self.cycle_type.title()}")
            self.summary_labels["Defect Team"].setText(f"Defect Team: {self.defect_domain}")
            self.summary_labels["Closure Team"].setText(f"Closure Team: {self.closure_team}")
            self.summary_labels["Date Range"].setText(f"Dates: {self.start_date.toString('yyyy-MM-dd')} -> {self.end_date.toString('yyyy-MM-dd')}")
            self.summary_labels["Resolution Range"].setText(f"Resolution: {self.resolution_start.toString('yyyy-MM-dd')} -> {self.resolution_end.toString('yyyy-MM-dd')}")
            self.summary_labels["Feature Domain"].setText(f"Feature Domain: {', '.join(self.feature_domains) or 'All'}")
            self.summary_labels["Feature Product"].setText(f"Product: {', '.join(self.feature_products) or 'All'}")
            subtask_short = ["RG3/RG4" if s.startswith("RG3/RG4") else "RG4.5" for s in self.feature_subtasks]
            self.summary_labels["Feature Sub-task"].setText(f"Sub-task: {', '.join(subtask_short) or 'None'}")
            self.summary_labels["Feature SOP/PU"].setText(f"SOP/PU: {', '.join(self.feature_sop_pu) or 'All'}")
            self.summary_labels["Feature Resolution"].setText(f"Feature Resolution: {self.feature_resolution_start.toString('yyyy-MM-dd')} -> {self.feature_resolution_end.toString('yyyy-MM-dd')}")

        def eventFilter(self, watched, event):
            drawer_fields = getattr(self, "drawer_fields", {})
            if event.type() == QEvent.Type.MouseButtonPress:
                if hasattr(self, "filter_drawer") and self.filter_drawer.isVisible() and self.active_scope:
                    global_point = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else QPoint()
                    inside_detail = self.filter_drawer.rect().translated(self.filter_drawer.mapToGlobal(QPoint(0, 0))).contains(global_point)
                    for field in drawer_fields.values():
                        if isinstance(field, MultiSelectComboBox) and field.multi_popup is not None and field.multi_popup.isVisible():
                            inside_detail = inside_detail or field.multi_popup.frameGeometry().contains(global_point)
                    for date_popup in self.findChildren(QFrame, "datePopup"):
                        if date_popup.isVisible():
                            inside_detail = inside_detail or date_popup.frameGeometry().contains(global_point)
                    detail_widgets = {self.filter_drawer}
                    detail_widgets.update(self.filter_drawer.findChildren(QWidget))
                    for field in drawer_fields.values():
                        if isinstance(field, MultiSelectComboBox) and field.multi_popup is not None and field.multi_popup.isVisible():
                            detail_widgets.add(field.multi_popup)
                            detail_widgets.update(field.multi_popup.findChildren(QWidget))
                    for date_popup in self.findChildren(QFrame, "datePopup"):
                        if date_popup.isVisible():
                            detail_widgets.add(date_popup)
                            detail_widgets.update(date_popup.findChildren(QWidget))
                    if not inside_detail and watched not in detail_widgets:
                        self._close_drawer_popups()
                        self.filter_drawer.hide()
                        self.active_scope = ""
                        self._refresh_scope_cards()
                        if watched not in self.scope_cards.values():
                            return True
                for date_edit in drawer_fields.values():
                    if isinstance(date_edit, QDateEdit) and (watched is date_edit or watched is date_edit.lineEdit()):
                        self._show_date_popup(date_edit)
                        return True
                for combo in drawer_fields.values():
                    if isinstance(combo, QComboBox) and (watched is combo or watched is combo.lineEdit()):
                        if isinstance(combo, MultiSelectComboBox) and combo.multi_popup is not None and combo.multi_popup.isVisible():
                            return True
                        combo.showPopup()
                        return True
            return super().eventFilter(watched, event)

        def _refresh_scope_cards(self):
            for scope, card in self.scope_cards.items():
                card.setProperty("selected", scope == self.active_scope)
                card.setProperty("active", scope in self.report_scopes)
                card.style().unpolish(card)
                card.style().polish(card)

        def _close_drawer_popups(self):
            for combo in self.drawer_fields.values():
                if isinstance(combo, QComboBox):
                    combo.hidePopup()

        def closeEvent(self, event):
            self._close_drawer_popups()
            if self.worker and self.worker.isRunning():
                self.worker.stop()
                self.worker.wait(2000)
            super().closeEvent(event)

        def _show_date_popup(self, date_edit: QDateEdit):
            popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
            popup.setStyleSheet("QFrame#datePopup { background: #FFFFFF; border: 1px solid #AFC2D3; border-radius: 3px; }")
            popup.setObjectName("datePopup")
            popup_layout = QVBoxLayout(popup)
            popup_layout.setContentsMargins(4, 4, 4, 4)
            popup_layout.setSpacing(0)

            calendar = QCalendarWidget(popup)
            selected_value = date_edit.date()
            calendar.setSelectedDate(selected_value)
            calendar.setCurrentPage(selected_value.year(), selected_value.month())
            calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.ISOWeekNumbers)
            calendar.setGridVisible(False)
            calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
            calendar.setStyleSheet("""
                QCalendarWidget { background: #FFFFFF; color: #173A61; border: none; }
                QCalendarWidget QWidget#qt_calendar_navigationbar { background: #FFFFFF; min-height: 34px; }
                QCalendarWidget QToolButton { background: #FFFFFF; color: #173A61; border: none; padding: 4px 7px; font-weight: 700; }
                QCalendarWidget QToolButton:hover { background: #E7F1FB; border-radius: 5px; }
                QCalendarWidget QSpinBox { background: #FFFFFF; color: #173A61; border: none; font-weight: 700; }
                QCalendarWidget QAbstractItemView { background: #FFFFFF; color: #173A61; selection-background-color: #0879D1; selection-color: #FFFFFF; outline: none; font-size: 11px; }
                QCalendarWidget QAbstractItemView::item:hover { background: #E7F1FB; color: #075A9A; }
            """)
            weekend_format = QTextCharFormat()
            weekend_format.setForeground(QColor("#D92D20"))
            calendar.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, weekend_format)
            calendar.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, weekend_format)
            popup_layout.addWidget(calendar)

            selected_label = QLabel("Select a date")
            selected_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            selected_label.setStyleSheet("color: #31516C; border-top: 1px solid #DCE3EA; border-bottom: 1px solid #DCE3EA; padding: 7px; font-size: 11px;")
            popup_layout.addWidget(selected_label)

            footer = QHBoxLayout()
            footer.setContentsMargins(7, 7, 7, 3)
            confirm_button = QPushButton("Confirm")
            cancel_button = QPushButton("Cancel")
            for button in (confirm_button, cancel_button):
                button.setMinimumHeight(28)
                button.setStyleSheet("QPushButton { background: transparent; color: #1F2D3A; border: none; padding: 4px 9px; font-size: 11px; } QPushButton:hover { background: #E7F1FB; border-radius: 4px; }")
            footer.addWidget(confirm_button)
            footer.addStretch(1)
            footer.addWidget(cancel_button)
            popup_layout.addLayout(footer)

            selected_date = {"value": date_edit.date()}

            def update_selected():
                selected_date["value"] = calendar.selectedDate()
                selected_label.setText(selected_date["value"].toString("dd-MMM-yyyy"))

            calendar.selectionChanged.connect(update_selected)
            confirm_button.clicked.connect(lambda: (date_edit.setDate(selected_date["value"]), popup.close()))
            cancel_button.clicked.connect(popup.close)
            update_selected()
            popup.adjustSize()
            available = self.screen().availableGeometry() if self.screen() else None
            field_bottom = date_edit.mapToGlobal(date_edit.rect().bottomLeft())
            if available and field_bottom.y() + popup.height() > available.bottom():
                popup.move(field_bottom.x(), max(available.top() + 8, date_edit.mapToGlobal(date_edit.rect().topLeft()).y() - popup.height()))
            else:
                popup.move(field_bottom)
            popup.show()
            calendar.setFocus()

        def open_filter_dialog(self, scope: str):
            if self.active_scope == scope and self.filter_drawer.isVisible():
                self.filter_drawer.hide()
                self.active_scope = ""
                self._refresh_scope_cards()
                return
            self.active_scope = scope
            self._populate_drawer(scope)
            self._position_filter_drawer(scope)
            self.filter_drawer.show()
            self.filter_drawer.raise_()
            self._refresh_scope_cards()

        def _position_filter_drawer(self, scope: str):
            card = self.scope_cards.get(scope)
            if card is None:
                return
            anchor = card.mapTo(self.dashboard_page, card.rect().bottomLeft())
            drawer_width = self.filter_drawer.sizeHint().width()
            drawer_width = max(QT_LAYOUT["drawer_min_width"], min(QT_LAYOUT["drawer_max_width"], drawer_width))
            self.filter_drawer.setFixedWidth(drawer_width)
            x = max(18, min(anchor.x(), self.dashboard_page.width() - drawer_width - 18))
            y = anchor.y() + 8
            if y + self.filter_drawer.sizeHint().height() > self.dashboard_page.height():
                y = max(12, anchor.y() - self.filter_drawer.sizeHint().height() - 8)
            self.filter_drawer.move(x, y)

        def resizeEvent(self, event):
            super().resizeEvent(event)
            if hasattr(self, "filter_drawer") and self.filter_drawer.isVisible() and self.active_scope:
                self._position_filter_drawer(self.active_scope)

        def _clear_drawer_controls(self):
            self._clear_drawer_layout(self.drawer_controls_layout)
            self.drawer_fields.clear()
            self.drawer_chips.clear()
            self._advanced_stack = []

        def _clear_drawer_layout(self, layout):
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                child_layout = item.layout()
                if widget:
                    widget.setParent(None)
                    widget.deleteLater()
                elif child_layout:
                    self._clear_drawer_layout(child_layout)
                    child_layout.deleteLater()

        def _add_drawer_combo(self, label: str, options: list[str], key: str, selected: list[str] | str, multi: bool):
            row = QVBoxLayout()
            row.setSpacing(4)
            caption = BodyLabel(label)
            caption.setStyleSheet("color: #425466; font-size: 12px; font-weight: 700; padding-left: 2px;")
            row.addWidget(caption)
            combo = MultiSelectComboBox() if multi else QComboBox()
            combo.setAccessibleName(label)
            combo.setAccessibleDescription(f"Select {label.lower()}")
            is_cycle_type = key == "cycle"
            combo.setEditable(not is_cycle_type)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.addItems(options)
            combo.setCurrentIndex(0 if is_cycle_type else -1)
            combo.setMinimumWidth(QT_LAYOUT["combo_min_width"])
            combo.setMinimumHeight(34)
            if combo.isEditable():
                combo.lineEdit().setPlaceholderText("Search or choose...")
                combo.lineEdit().addAction(QAction(FluentIcon.SEARCH.icon(color=QColor("#71869A")), "Search", combo), combo.lineEdit().ActionPosition.LeadingPosition)
            combo.setStyleSheet("QComboBox { background: #F7FAFC; color: #172B3A; border: 1px solid #C9D8E5; border-radius: 12px; padding: 7px 10px; font-size: 13px; selection-background-color: #DCEEFF; } QComboBox:hover { background: #FFFFFF; border-color: #8DB3D2; } QComboBox:focus { background: #FFFFFF; border: 1px solid #0066B1; } QComboBox::drop-down { width: 28px; border: none; } QComboBox QAbstractItemView { background: #FFFFFF; border: 1px solid #C9D8E5; selection-background-color: #E7F1FB; selection-color: #075A9A; padding: 4px; font-size: 13px; }")
            completer = None
            if combo.isEditable() and not isinstance(combo, MultiSelectComboBox):
                # MultiSelectComboBox has its own search box inside its checkbox popup
                # (see showPopup); attaching the native completer here too made two
                # popups fight over the same lineEdit/focus and crashed on typing.
                completer = QCompleter(options, combo)
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                completer.setFilterMode(Qt.MatchFlag.MatchContains)
                completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
                completer.popup().setMinimumWidth(QT_LAYOUT["combo_min_width"])
                combo.setCompleter(completer)
            combo.installEventFilter(self)
            if combo.isEditable():
                combo.lineEdit().installEventFilter(self)
                if isinstance(combo, MultiSelectComboBox):
                    combo.lineEdit().installEventFilter(combo)
            row.addWidget(combo)
            self.drawer_controls_layout.addLayout(row)
            self.drawer_fields[key] = combo
            if isinstance(selected, list):
                initial = selected
            elif multi and selected and selected != "All":
                initial = [value.strip() for value in str(selected).split(",") if value.strip()]
            else:
                initial = [selected] if selected and selected != "All" else []
            self.drawer_chips[key] = list(initial)

            def refresh_combo_text():
                if combo.isEditable():
                    combo.lineEdit().setText(", ".join(self.drawer_chips[key]))
                    combo.lineEdit().setCursorPosition(0)
                elif self.drawer_chips[key]:
                    combo.setCurrentText(self.drawer_chips[key][0])

            refresh_combo_text()

            def choose(value):
                if isinstance(value, int):
                    value = combo.itemText(value)
                value = str(value).strip()
                if not value or value.lower() == "all":
                    return
                if not multi:
                    self.drawer_chips[key] = [value]
                refresh_combo_text()
                self._refresh_drawer_chips()

            def confirm_multi_selection(values):
                self.drawer_chips[key] = list(values)
                refresh_combo_text()
                self._refresh_drawer_chips()

            if multi:
                combo.configure_multi_popup(options, self.drawer_chips[key], confirm_multi_selection, lambda: None)

            def commit_typed_value():
                typed = combo.currentText().strip()
                if not typed:
                    return
                match = next((option for option in options if option.lower() == typed.lower()), None)
                if match:
                    choose(match)

            if not multi:
                combo.textActivated.connect(choose)
                if completer is not None:
                    completer.activated[str].connect(choose)
            if combo.isEditable():
                combo.lineEdit().returnPressed.connect(commit_typed_value)
                original_focus_in_event = combo.lineEdit().focusInEvent

                def select_displayed_text(event):
                    original_focus_in_event(event)
                    combo.lineEdit().selectAll()

                combo.lineEdit().focusInEvent = select_displayed_text

            def refresh_completions(text: str):
                completer.setCompletionPrefix(text)
                completer.complete()

            if combo.isEditable() and completer is not None:
                combo.lineEdit().textEdited.connect(refresh_completions)

        def _begin_advanced_section(self, title: str):
            """Collapse less-common filters (hidden by default) to keep each scope's default view simple."""
            toggle = QPushButton(f"\u25b8 {title}")
            toggle.setCheckable(True)
            toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            toggle.setMinimumHeight(34)
            toggle.setStyleSheet(
                "QPushButton { background: " + QT_THEME["accent_tint"] + "; border: 1px solid #BFDCF2; "
                "border-radius: 8px; color: " + QT_THEME["accent"] + "; font-size: 11px; font-weight: 700; "
                "text-align: left; padding: 7px 10px; } "
                "QPushButton:hover { background: " + QT_THEME["accent_tint_hover"] + "; border-color: #8FC0E8; } "
                "QPushButton:pressed { background: " + QT_THEME["accent_tint_pressed"] + "; } "
                "QPushButton:checked { background: " + QT_THEME["accent"] + "; border-color: " + QT_THEME["accent"] + "; color: #FFFFFF; }"
            )
            self.drawer_controls_layout.addWidget(toggle)
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(6)
            container.setVisible(False)
            self.drawer_controls_layout.addWidget(container)

            def on_toggle(checked: bool):
                container.setVisible(checked)
                toggle.setText(f"{'\u25be' if checked else '\u25b8'} {title}")

            toggle.toggled.connect(on_toggle)
            self._advanced_stack.append(self.drawer_controls_layout)
            self.drawer_controls_layout = container_layout

        def _end_advanced_section(self):
            if self._advanced_stack:
                self.drawer_controls_layout = self._advanced_stack.pop()

        def _add_drawer_date(self, label: str, key: str, selected: QDate):
            row = QVBoxLayout()
            row.setSpacing(4)
            caption = BodyLabel(label)
            caption.setStyleSheet("color: #425466; font-size: 12px; font-weight: 700; padding-left: 2px;")
            row.addWidget(caption)
            date_edit = QDateEdit(selected)
            date_edit.setAccessibleName(label)
            date_edit.setAccessibleDescription(f"Choose {label.lower()} using the calendar")
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat("yyyy-MM-dd")
            date_edit.setMinimumWidth(QT_LAYOUT["field_min_width"])
            date_edit.setMinimumHeight(34)
            date_edit.setStyleSheet("QDateEdit { background: #F7FAFC; color: #172B3A; border: 1px solid #C9D8E5; border-radius: 12px; padding: 7px 10px; } QDateEdit:hover { background: #FFFFFF; border-color: #8DB3D2; } QDateEdit:focus { background: #FFFFFF; border: 1px solid #0066B1; } QDateEdit::drop-down { width: 28px; border: none; }")
            calendar = date_edit.calendarWidget()
            calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.ISOWeekNumbers)
            calendar.setGridVisible(False)
            calendar.setNavigationBarVisible(True)
            calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
            calendar.setStyleSheet("""
                QCalendarWidget {
                    background: #FFFFFF;
                    color: #173A61;
                    border: 1px solid #B8C9D8;
                }
                QCalendarWidget QWidget#qt_calendar_navigationbar {
                    background: #FFFFFF;
                    min-height: 34px;
                }
                QCalendarWidget QToolButton {
                    background: #FFFFFF;
                    color: #173A61;
                    border: none;
                    padding: 4px 7px;
                    font-weight: 700;
                }
                QCalendarWidget QToolButton:hover {
                    background: #E7F1FB;
                    border-radius: 5px;
                }
                QCalendarWidget QSpinBox {
                    background: #FFFFFF;
                    color: #173A61;
                    border: none;
                    font-weight: 700;
                }
                QCalendarWidget QAbstractItemView {
                    background: #FFFFFF;
                    color: #173A61;
                    selection-background-color: #0879D1;
                    selection-color: #FFFFFF;
                    outline: none;
                    font-size: 11px;
                }
                QCalendarWidget QAbstractItemView::item:hover {
                    background: #E7F1FB;
                    color: #075A9A;
                }
            """)
            weekend_format = QTextCharFormat()
            weekend_format.setForeground(QColor("#D92D20"))
            calendar.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, weekend_format)
            calendar.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, weekend_format)
            date_context = BodyLabel()
            date_context.setMinimumWidth(QT_LAYOUT["cw_badge_min_width"])
            date_context.setStyleSheet("color: #45627B; font-size: 10px; font-weight: 700; padding-left: 5px;")
            date_context.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

            def refresh_date_context(value: QDate):
                week_year, week_number = value.toPyDate().isocalendar().year, value.toPyDate().isocalendar().week
                date_context.setText(f"CW{week_number:02d} | {week_year}")

            refresh_date_context(selected)
            date_edit.dateChanged.connect(refresh_date_context)
            date_edit.installEventFilter(self)
            date_edit.lineEdit().installEventFilter(self)
            date_row = QHBoxLayout()
            date_row.setContentsMargins(0, 0, 0, 0)
            date_row.setSpacing(6)
            date_row.addWidget(date_edit, 1)
            date_row.addWidget(date_context)
            row.addLayout(date_row)
            self.drawer_controls_layout.addLayout(row)
            self.drawer_fields[key] = date_edit

        def _populate_drawer(self, scope: str):
            self._clear_drawer_controls()
            titles = {
                "test": ("Test Scope", "Projects, domain, cycle type and variant"),
                "defect": ("Defect Scope", "Defect projects, assigned ECU and raised team"),
                "resolution": ("Defect Resolution Scope", "Closure projects, team and resolution period"),
                "rack": ("Test Rack Utilisation", "Rack usage follows the active test date range"),
                "adhoc": ("Ad-Hoc Efforts Scope", "Ad-Hoc domains and custom resolution date range"),
                "feature": ("Feature Scope", "Feature domain, validation sub-task, SOP/PU and resolution period"),
            }
            title, subtitle = titles[scope]
            self.drawer_title.setText(title)
            self.drawer_subtitle.setText(subtitle)
            if scope == "test":
                self._add_drawer_combo("Projects", TEST_PROJECT_OPTIONS, "projects", self.test_projects, True)
                self._add_drawer_combo("Domain", DOMAIN_OPTIONS[2:], "domains", self.domains, True)
                self._add_drawer_combo("Variant", VARIANT_OPTIONS[1:], "variants", self.variants, True)
                self._add_drawer_combo("Cycle Type", ["both", "manual", "automation"], "cycle", [self.cycle_type], False)
                self._add_drawer_date("Start Date", "start_date", self.start_date)
                self._add_drawer_date("End Date", "end_date", self.end_date)
            elif scope == "defect":
                self._add_drawer_combo("Projects", DEFECT_PROJECT_OPTIONS, "defect_projects", self.defect_projects, True)
                self._add_drawer_combo("Assigned ECU", ASSIGNED_ECU_OPTIONS, "assigned_ecus", self.assigned_ecus, True)
                self._add_drawer_combo("Raised Team", DOMAIN_OPTIONS[2:], "defect_domain", self.defect_domain, True)
                self._add_drawer_date("Start Date", "start_date", self.start_date)
                self._add_drawer_date("End Date", "end_date", self.end_date)
            elif scope == "resolution":
                self._add_drawer_combo("Projects", DEFECT_PROJECT_OPTIONS, "closure_projects", self.closure_projects, True)
                self._add_drawer_combo("Raised Team", DOMAIN_OPTIONS[2:], "closure_team", self.closure_team, True)
                self._add_drawer_date("Resolution Start Date", "resolution_start", self.resolution_start)
                self._add_drawer_date("Resolution End Date", "resolution_end", self.resolution_end)
            elif scope == "adhoc":
                self._add_drawer_combo("Ad-Hoc Domains", ADHOC_DOMAIN_OPTIONS, "adhoc_domains", self.adhoc_domains, True)
                self._add_drawer_date("Resolution Start Date", "start_date", self.start_date)
                self._add_drawer_date("Resolution End Date", "end_date", self.end_date)
            elif scope == "feature":
                self._add_drawer_combo("Feature Domain", FEATURE_DOMAIN_OPTIONS, "feature_domains", self.feature_domains, True)
                self._add_drawer_date("Resolution Start Date", "feature_resolution_start", self.feature_resolution_start)
                self._add_drawer_date("Resolution End Date", "feature_resolution_end", self.feature_resolution_end)
                self._begin_advanced_section("Advanced: Product, Sub-task & SOP/PU")
                self._add_drawer_combo("Product", FEATURE_PRODUCT_OPTIONS, "feature_products", self.feature_products, True)
                self._add_drawer_combo("Validation Sub-task", FEATURE_SUBTASK_OPTIONS, "feature_subtasks", self.feature_subtasks, True)
                self._add_drawer_combo("SOP/PU", FEATURE_SOP_PU_OPTIONS, "feature_sop_pu", self.feature_sop_pu, True)
                self._end_advanced_section()
            else:
                self._add_drawer_combo("Domain", DOMAIN_OPTIONS[2:], "rack_domain", self.rack_domain, True)
                self._add_drawer_date("Start Date", "start_date", self.start_date)
                self._add_drawer_date("End Date", "end_date", self.end_date)
            self._refresh_drawer_chips()

        def _refresh_drawer_chips(self):
            total = sum(
                len(values)
                for key, values in self.drawer_chips.items()
                if key not in {"resolution_start", "resolution_end", "start_date", "end_date"}
            )
            self.drawer_count.setText(f"{total} selected")

        def apply_drawer_filters(self):
            self._close_drawer_popups()
            for key, values in self.drawer_chips.items():
                if key == "projects":
                    self.test_projects = list(values)
                elif key == "domains":
                    self.domains = values
                    self.domain = ", ".join(values) if values else "All"
                elif key == "variants":
                    self.variants = values
                elif key == "cycle" and values:
                    self.cycle_type = values[0]
                elif key == "defect_projects":
                    self.defect_projects = values
                elif key == "assigned_ecus":
                    self.assigned_ecus = values
                elif key == "defect_domain":
                    self.defect_domain = ", ".join(values) if values else "All"
                elif key == "closure_projects":
                    self.closure_projects = values
                elif key == "closure_team":
                    self.closure_team = ", ".join(values) if values else "All"
                elif key == "adhoc_domains":
                    self.adhoc_domains = values
                elif key == "rack_domain":
                    self.rack_domain = values
                elif key == "feature_domains":
                    self.feature_domains = list(values)
                elif key == "feature_sop_pu":
                    self.feature_sop_pu = list(values)
                elif key == "feature_subtasks":
                    self.feature_subtasks = list(values)
                elif key == "feature_products":
                    self.feature_products = list(values)
            start_date = self.drawer_fields.get("start_date")
            end_date = self.drawer_fields.get("end_date")
            resolution_start = self.drawer_fields.get("resolution_start")
            resolution_end = self.drawer_fields.get("resolution_end")
            if isinstance(start_date, QDateEdit):
                self.start_date = start_date.date()
            if isinstance(end_date, QDateEdit):
                self.end_date = end_date.date()
            if isinstance(resolution_start, QDateEdit):
                self.resolution_start = resolution_start.date()
            if isinstance(resolution_end, QDateEdit):
                self.resolution_end = resolution_end.date()
            feature_resolution_start = self.drawer_fields.get("feature_resolution_start")
            feature_resolution_end = self.drawer_fields.get("feature_resolution_end")
            if isinstance(feature_resolution_start, QDateEdit):
                self.feature_resolution_start = feature_resolution_start.date()
            if isinstance(feature_resolution_end, QDateEdit):
                self.feature_resolution_end = feature_resolution_end.date()
            self._refresh_summary()
            self.report_scopes.add(self.active_scope)
            self.filter_drawer.hide()
            self.active_scope = ""
            self._refresh_scope_cards()

        def clear_filters(self):
            self._close_drawer_popups()
            self.test_projects = ["ABPI", "IDCEVODEV"]
            self.domain = self.defect_domain = self.closure_team = "All"
            self.variants.clear()
            self.defect_projects.clear()
            self.assigned_ecus.clear()
            self.closure_projects.clear()
            self.adhoc_domains = ["Telematics"]
            self.rack_domain.clear()
            self.feature_domains.clear()
            self.feature_sop_pu = list(FEATURE_SOP_PU_OPTIONS)
            self.feature_subtasks = list(FEATURE_SUBTASK_OPTIONS)
            self.feature_products = list(FEATURE_PRODUCT_OPTIONS)
            self.feature_resolution_start = QDate.currentDate()
            self.feature_resolution_end = QDate.currentDate()
            self.drawer_chips.clear()
            self.report_scopes.clear()
            self.filter_drawer.hide()
            self.active_scope = ""
            self._refresh_scope_cards()
            self._refresh_summary()

        def open_credentials_dialog(self):
            current = load_current_credentials()

            dialog = QDialog(self)
            dialog.setWindowTitle("Jira & test.guide Credentials")
            dialog.setMinimumWidth(420)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(18, 16, 18, 16)
            layout.setSpacing(8)
            layout.addWidget(StrongBodyLabel("Jira & test.guide Credentials"))
            note = BodyLabel("Stored locally in credentials.json for this user; no token is hardcoded in the scripts.")
            note.setWordWrap(True)
            note.setStyleSheet("color: #637282; font-size: 12px;")
            layout.addWidget(note)

            def add_field(label_text: str, initial: str, secret: bool = False):
                layout.addWidget(BodyLabel(label_text))
                field = QLineEdit(initial)
                if secret:
                    field.setEchoMode(QLineEdit.EchoMode.Password)
                layout.addWidget(field)
                return field

            email_field = add_field("Jira Email (required for Basic auth mode)", current["jira_email"])

            layout.addWidget(BodyLabel("Jira Auth Mode"))
            mode_row = QHBoxLayout()
            mode_state = {"value": current["jira_auth_mode"]}
            mode_buttons = {}

            def select_mode(mode: str):
                mode_state["value"] = mode
                for name, button in mode_buttons.items():
                    button.setStyleSheet(
                        "QPushButton { background: #0066B1; color: #FFFFFF; border-radius: 5px; padding: 6px; font-weight: 700; }"
                        if name == mode else
                        "QPushButton { background: #F1F5F8; color: #1F2937; border: 1px solid #C9D8E5; border-radius: 5px; padding: 6px; }"
                    )

            for mode in ("bearer", "basic"):
                button = QPushButton(mode.title())
                button.clicked.connect(lambda checked=False, m=mode: select_mode(m))
                mode_row.addWidget(button)
                mode_buttons[mode] = button
            layout.addLayout(mode_row)
            select_mode(current["jira_auth_mode"])

            token_field = add_field("Jira API Token", current["jira_api_token"], secret=True)
            tg_token_field = add_field("Test Guide Token", current["test_guide_token"], secret=True)

            show_secrets = QCheckBox("Show tokens")

            def toggle_show_secrets(checked: bool):
                mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
                for field in (token_field, tg_token_field):
                    field.setEchoMode(mode)

            show_secrets.toggled.connect(toggle_show_secrets)
            layout.addWidget(show_secrets)

            status_label = BodyLabel("")
            status_label.setStyleSheet("color: #166534; font-size: 11px;")
            layout.addWidget(status_label)

            def do_save():
                save_local_credentials(
                    email_field.text(),
                    token_field.text(),
                    mode_state["value"],
                    tg_token_field.text(),
                )
                status_label.setText("Saved. These credentials will be used for the next report run.")

            button_row = QHBoxLayout()
            save_button = QPushButton("Save")
            save_button.setStyleSheet("QPushButton { background: #0066B1; color: #FFFFFF; border-radius: 5px; padding: 7px 16px; font-weight: 700; }")
            save_button.clicked.connect(do_save)
            close_button = QPushButton("Close")
            close_button.setStyleSheet("QPushButton { background: #F1F5F8; color: #1F2937; border: 1px solid #C9D8E5; border-radius: 5px; padding: 7px 16px; }")
            close_button.clicked.connect(dialog.accept)
            button_row.addWidget(save_button)
            button_row.addStretch(1)
            button_row.addWidget(close_button)
            layout.addLayout(button_row)

            dialog.exec()

        def cancel_report(self):
            if self.worker and self.worker.isRunning():
                self.console.appendPlainText("Report generation cancelled by user.")
                self.worker.stop()

        def generate_report(self):
            if self.worker and self.worker.isRunning():
                return
            load_jira_credentials()
            load_test_guide_credentials()
            command = build_command(
                self.report_script,
                self.start_date.toString("yyyy-MM-dd"),
                self.end_date.toString("yyyy-MM-dd"),
                ",".join(self.test_projects),
                self.domain,
                self.cycle_type,
                ",".join(self.variants) or "All",
                ",".join(self.defect_projects) or "All",
                self.defect_domain,
                ",".join(self.assigned_ecus) or "All",
                ",".join(self.closure_projects) or "All",
                self.closure_team,
                self.resolution_start.toString("yyyy-MM-dd"),
                self.resolution_end.toString("yyyy-MM-dd"),
                ",".join(sorted(self.report_scopes)),
                ",".join(self.adhoc_domains) or "None",
                rack_domain=",".join(self.rack_domain) or "All",
                feature_sop_pu=",".join(self.feature_sop_pu) or ",".join(FEATURE_SOP_PU_OPTIONS),
                feature_domain=",".join(self.feature_domains) or "All",
                feature_subtasks=",".join(self.feature_subtasks) or ",".join(FEATURE_SUBTASK_OPTIONS),
                feature_resolution_start_date=self.feature_resolution_start.toString("yyyy-MM-dd"),
                feature_resolution_end_date=self.feature_resolution_end.toString("yyyy-MM-dd"),
                feature_products=",".join(self.feature_products) or ",".join(FEATURE_PRODUCT_OPTIONS),
            )
            self.console.clear()
            self.console.appendPlainText("Running report generation...")
            if not self.console_toggle_button.isChecked():
                self.console_toggle_button.setChecked(True)
            self.status_label.setText("RUNNING")
            self.cancel_button.setEnabled(True)
            self.worker = QtReportWorker(command, self.base_dir)
            self.worker.output_received.connect(lambda text, error: self.console.appendPlainText(text))
            self.worker.finished.connect(self._report_finished)
            self.worker.start()

        def _report_finished(self, exit_code: int):
            self.console.appendPlainText("Report generation completed successfully." if exit_code == 0 else f"Report generation failed with exit code {exit_code}.")
            self.status_label.setText("READY" if exit_code == 0 else "FAILED")
            self.cancel_button.setEnabled(False)


    def qt_main():
        app = QApplication(sys.argv)
        install_qt_exception_hook()
        app.setStyle("Fusion")
        window = QtReportDashboard()
        window.show()
        sys.exit(app.exec())
else:
    def qt_main():
        venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Scripts", "python.exe")
        if os.path.exists(venv_python) and os.path.abspath(sys.executable).casefold() != os.path.abspath(venv_python).casefold():
            subprocess.run([venv_python, os.path.abspath(__file__), *sys.argv[1:]], check=False)
            return
        print(
            "PyQt6/qfluentwidgets is not available in this interpreter.\n"
            f"Import error: {QT_IMPORT_ERROR}\n"
            f"Use {venv_python} report_input_dashboard.py for the Fluent dashboard.\n"
            "Launching Tk dashboard fallback."
        )
        main()


if __name__ == "__main__":
    qt_main()
