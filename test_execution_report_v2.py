# -*- coding: utf-8 -*-
"""
Test Execution Report
Fetches Automation and Manual test execution cycles from Jira,
groups by domain, and generates an HTML report.

Run --discover-fields first to find the correct custom field IDs
for your Jira instance, then update CUSTOM_FIELDS below.
"""
import requests
import os
import sys
import json
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import re
import time
import urllib3
from datetime import datetime, timedelta
from html import escape
from collections import Counter
from requests.auth import HTTPBasicAuth
from requests.exceptions import HTTPError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_COMMENT_SUMMARIZER = None
_COMMENT_SUMMARIZER_LOAD_ATTEMPTED = False
_JIRA_ENV_LOADED = False
# Records which file/source actually set each credential env var (credentials.json
# is read before credentials.txt and "wins" if both set the same variable - this
# silently confused a colleague whose credentials.json still had auth_mode=basic
# even after fixing credentials.txt). Surfaced in the 403 auth-disabled hint below.
_JIRA_CREDENTIAL_SOURCES: dict[str, str] = {}

# ---------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------
JIRA_BASE_URL = "https://jira.cc.bmwgroup.net"
# No personal defaults: every user supplies their own via credentials.json,
# the dashboard's Credentials dialog, or JIRA_EMAIL/JIRA_API_TOKEN env vars.
JIRA_EMAIL    = ""
JIRA_API_TOKEN = ""
JIRA_AUTH_MODE = "bearer"  # supported: basic, bearer

PROJECTS = ["IDCEVODEV", "ABPI"]
PROJECTS_REQUIRE_VARIANT = {"ABPI"}

# Feature scope (v2 experimental): one saved Jira filter per SOP/PU, each already scoped to
# project = IDCEVOPM, issuetype = Feature, and the shared domain exclusion list below.
FEATURE_SOP_PU_FILTER_IDS = {
    "25-07": "274269",
    "25-11": "274270",
    "26-03": "274271",
    "26-07": "274272",
    "26-11": "274273",
    "27-03": "274274",
    "27-07": "274275",
    "27-11": "274279",
    "28-03": "274277",
    "28-07": "274276",
    "28-11": "274278",
}
FEATURE_SOP_PU_ORDER = tuple(FEATURE_SOP_PU_FILTER_IDS.keys())
FEATURE_PRODUCT_PROJECTS = {
    "IDCEVO": "IDCEVOPM",
    "CDE/RSE26": "PENTPM",
}
FEATURE_EXCLUDED_DOMAINS = (
    "China Product", "Navigation KOR", "UI Toolkit", "Navigation Korea",
    "ENT_and_CON CN", "IPA CN", "Navigation CN", "Mechanics", "Speech CN", "Safety",
)
FEATURE_RG3_RG4_SYS5_TEXT = "RG3/RG4 - SYS.5 System Validation Test Cases"
FEATURE_RG3_RG4_SYS5_RESOLUTIONS = ("Done", "Won't Do")
FEATURE_RG45_SYS5_TEXT = "RG4.5 - Feature/subfeature System Validation Testing SYS.5"
# NOTE: "pending" is not a valid Jira resolution value on this instance (confirmed via
# GET /rest/api/2/resolution -> Done, Won't Do, Duplicate, Cannot Reproduce, Rejected,
# Deficient). Using it caused a 400 error, so it is omitted here pending clarification.
FEATURE_RG45_SYS5_RESOLUTIONS = ("Done", "Won't Do")
FEATURE_RG42_INTEGRATION_TEXT = "RG4.2 - Feature/subfeature System Integration and Test"
FEATURE_RG42_DOMAIN_TESTING_TEXT = "RG4.2 - Feature/subfeature Domain Testing"
FEATURE_PO_REVIEW_DONE_LABEL = "po_review_done"

DEFECT_PROJECTS = ["HU22DM", "ICONSD", "IDCEVODEV"]
DEFECT_ISSUE_TYPES = ["Bug", "TAEE Defect"]
DEFECT_LABEL_TELEMATICS = "LTTS_Telematics"
DEFECT_LABEL_EXPLORATORY = "LTTS_SV_ET"
DEFECT_ASSIGNED_ECU_FIELD = "customfield_10805"

DOMAIN_DEFECT_LABELS = {
    "Entertainment": ("LTTS_ENT",),
    "Telematics": ("LTTS_Telematics",),
    "Experiences and Modes": ("LTTS_HMI",),
    "IBA": ("LTTS_HMI",),
    "Car Functions": ("LTTS_HMI",),
    "Core UI": ("LTTS_HMI",),
    "Speech": ("LTTS_Speech",),
    "Speech Amazon": ("LTTS_Speech",),
    "IPA": ("LTTS_Speech",),
    "Navigation": ("LTTS_NAV",),
    "IKS CV": ("LTTS_IKSCV",),
    "Interior Sensing": ("LTTS_IKSCV",),
    "Charging Settings and Value Add": ("LTTS_Chraging_Setting",),
    "AR Experience": ("LTTS_AR_EXP",),
    "Function on Demand": ("LTTS_FOD",),
    "Personalisation": ("LTTS_PERSO",),
    "SDI": ("LTTS_SDI",),
    "Wireless Services and Communication": ("LTTS_Connectivity",),
}

# Escalation categories per the IDCEVO SW Quality Dashboard KPI reference.
ESCALATION_LABELS = {
    "TIC": "OCT_Top_Issue_Confirmed",
    "Showstopper": "OCT_Showstopper_Confirmed",
    "PM Issue": "PM_Issue",
    "Top Candidate": "Top_Candidate",
    "SI Blocker": "SI_Blocker_Confirmed",
}

# Labels for domains not supplied by the user yet remain intentionally unmapped.
DOMAIN_DEFECT_LABEL_ALIASES = {
    "experiences and modes": "experiences and modes",
    "experience and modes": "experiences and modes",
    "carfunctions": "car functions",
    "car functions": "car functions",
    "core ui": "core ui",
    "ipa speech": "speech",
    "speech cn": "speech",
    "speech amazon": "speech amazon",
    "ikscv": "iks cv",
    "interior sesning": "interior sensing",
    "charging settings & value add": "charging settings and value add",
    "charging settings and value add": "charging settings and value add",
    "fod": "function on demand",
    "navaigation": "navigation",
    "ipa": "ipa",
    "telematics team defects": "telematics",
    "personalization": "personalisation",
    "personalisation": "personalisation",
    "wireless services": "wireless services and communication",
    "communication": "wireless services and communication",
}

# Labels that identify cycle type
AUTO_LABELS   = ["LTTS_AUTO_IDCEVO", "LTTS_AUTO_CDE", "LTTS_AUTO_RSE", "LTTS_AUTO_IDC23"]
MANUAL_LABEL  = "LTTS_SV"
TEST_SCOPE_LABELS = (MANUAL_LABEL, "SV_incar")

# Custom field IDs — run with --discover-fields to find these for your instance
# Then replace the placeholder IDs below
CUSTOM_FIELDS = {
    "domain":     "customfield_10300",   # Domain field
    "sop_pu":     "customfield_10303",   # SOP/PU
    "variant":    "customfield_10307",   # Variant
    "i_step":     "customfield_10301",   # I-Step
    "execution_status": "customfield_10020",  # Test Execution Status (contains PASS/FAIL/ABORTED/EXECUTING/TODO counts)
    "execution_defects": "customfield_10016",  # Optional fallback: Test Execution Defects
    "aborted_reason": "customfield_10319",  # Optional fallback: Pending Reason / aborted context
    "found_in_sw_version": "customfield_10809",  # Found in SW Version(s)
    "pass":       "customfield_XXXXX",   # Pass count
    "failed":     "customfield_XXXXX",   # Failed count
    "aborted":    "customfield_XXXXX",   # Aborted count
    "executing":  "customfield_XXXXX",   # Executing count
    "todo":       "customfield_XXXXX",   # Todo count
}

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_CREDENTIALS_FILE = os.path.join(WORKSPACE_DIR, "credentials.json")
LOCAL_CREDENTIALS_TEXT_FILE = os.path.join(WORKSPACE_DIR, "credentials.txt")
REPORTS_DIR = os.path.join(WORKSPACE_DIR, "reports")
# Fresh clones don't have this folder tracked in git (only a .gitkeep placeholder);
# create it on first run so writing OUTPUT_FILE below doesn't fail on a new PC.
os.makedirs(REPORTS_DIR, exist_ok=True)
OUTPUT_FILE = os.path.join(REPORTS_DIR, "test_execution_report_v2.html")
REJECTED_ONLY_OUTPUT_FILE = os.path.join(
    REPORTS_DIR,
    "rejected_tickets_report.html",
)
RACK_ONLY_OUTPUT_FILE = os.path.join(
    REPORTS_DIR,
    "test_rack_utilisation_report.html",
)
TEST_RUN_PLUGIN_ENDPOINT = os.getenv(
    "JIRA_TEST_RUN_PLUGIN_ENDPOINT",
    "",
)
TEST_RUN_PLUGIN_BATCH_SIZE = 50
RACK_ACTIVITY_FILE = os.getenv(
    "TEST_GUIDE_ACTIVITY_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_resource_activity.json"),
)
TEST_GUIDE_BASE_URL = os.getenv("TEST_GUIDE_BASE_URL", "https://tgn3.bmwgroup.net")
TEST_GUIDE_PROJECT_ID = os.getenv("TEST_GUIDE_PROJECT_ID", "37")
# ---------------------------------------------------------------

HEADERS = {"Accept": "application/json"}
PROJECT_JQL = "project in (" + ", ".join(PROJECTS) + ")"

KNOWN_TEST_RESOURCES = (
    "LTTS_OFFSHORE/IDC23/TELEMATICS/CASABLANCA",
    "LTTS_OFFSHORE/IDC23/TELEMATICS/HOUSTON",
    "LTTS_OFFSHORE/IDC23/TELEMATICS/VANCOUVER",
    "LTTS_OFFSHORE/IDCEVO/TELEMATICS/KRYPTON",
    "LTTS_OFFSHORE/IDCEVO/TELEMATICS/PATRICK STAR",
    "LTTS_ONSITE/IDC23/TELEMATICS/BUDAPEST",
    "LTTS_ONSITE/IDCEVO/TELEMATICS/TARZAN",
)

# Exact rack names per domain family, so build_rack_filters can skip the slow
# full-project wildcard discovery + per-resource metadata scan (~180s for ~200
# resources at 12-way concurrency) and go straight to the fast named-lookup path
# (same optimization already used for Telematics). Confirmed live 2026-09-02;
# re-verify via a --rack-only run if racks get renamed/decommissioned/added.
KNOWN_TEST_RESOURCES_BY_DOMAIN = {
    "telematics": KNOWN_TEST_RESOURCES,
    "communication": (
        "LTTS_OFFSHORE/IDCEVO/CONNECTIVITY/KAKASHI",
        "LTTS_OFFSHORE/IDCEVO/CONNECTIVITY/KATOWICE",
        "LTTS_OFFSHORE/IDCEVO/CONNECTIVITY/POPEYE",
        "LTTS_OFFSHORE/IDCEVO/CONNECTIVITY/THE HEAP",
    ),
    "wireless services": (
        "LTTS_OFFSHORE/PENT/WIRELESS/ELISA",
        "LTTS_OFFSHORE/PENT/WIRELESS/HIRO",
        "LTTS_OFFSHORE/PENT/WIRELESS/RUDRAKSHA",
    ),
}

RACK_DOMAIN_NAMES = {
    "automation": "AUTOMATION",
    "audio infrastructure": "SYSINFRAAUDIO",
    "carfunctions": "HMI_SV",
    "communication": "CONNECTIVITY",
    "communications": "CONNECTIVITY",
    "core ui": "HMI_SV",
    "displaygraphicsinfra": "SYSINFRADGI",
    "entertainment": "ENTERTAINMENT",
    "exm": "HMI_SV",
    "experiences and modes": "HMI_SV",
    "iba": "HMI_SV",
    "ipa speech": "Speech",
    "personalization": "PIA",
    "personalisation": "PIA",
    "rsu ui": "RSU",
    "pentui": "PENTUI",
    "pent functions & ui": "PENTUI",
    "sichtabsicht": "HMI_SV",
    "wireless services": "CONNECTIVITY",
    "sysinfra": "SYSINFRA",
    "system software": "SYSTEM SOFTWARE",
    "system_functions": "SYSTEM_FUNCTIONS",
    "system functions": "SYSTEM_FUNCTIONS",
    "system manager": "SYSTEM_MANAGER",
    "system managers": "SYSTEM_MANAGER",
    "wireless": "WIRELESS",
    "wireless services": "WIRELESS",
}


def defect_labels_for_team(team: str) -> tuple[str, ...]:
    selected_domains = [part.strip() for part in str(team or "").split(",") if part.strip()]
    if not selected_domains or any(part.casefold() in {"all", "none"} for part in selected_domains):
        return tuple(dict.fromkeys(label for labels in DOMAIN_DEFECT_LABELS.values() for label in labels))
    labels = []
    for domain in selected_domains:
        normalized = DOMAIN_DEFECT_LABEL_ALIASES.get(domain.casefold(), domain.casefold())
        for name, domain_labels in DOMAIN_DEFECT_LABELS.items():
            if name.casefold() == normalized:
                labels.extend(domain_labels)
                break
    return tuple(dict.fromkeys(labels))


def unmapped_domain_tokens(team: str) -> list[str]:
    """Return requested domain names that resolve to zero defect labels.

    A combined selection like "IPA CN, Telematics" silently contributes 0 records for
    any token with no label mapping, but the report header still displays the full
    selection - this lets the report disclose that gap instead of hiding it.
    """
    selected_domains = [part.strip() for part in str(team or "").split(",") if part.strip()]
    if not selected_domains or any(part.casefold() in {"all", "none"} for part in selected_domains):
        return []
    unmapped = []
    for domain in selected_domains:
        normalized = DOMAIN_DEFECT_LABEL_ALIASES.get(domain.casefold(), domain.casefold())
        if not any(name.casefold() == normalized for name in DOMAIN_DEFECT_LABELS):
            unmapped.append(domain)
    return unmapped


def build_defect_label_clause(labels: tuple[str, ...]) -> str:
    return " OR ".join(f'labels = "{label}"' for label in labels)


def rack_domain_matches(selected_domain: str, resource_domain: str) -> bool:
    return rack_domain_key(selected_domain) == rack_domain_key(resource_domain)


def rack_domain_key(value: str) -> str:
    """Normalize dashboard domains to the family names used in test.guide locations."""
    normalized = " ".join(str(value or "").strip().casefold().replace("_", " ").split())
    aliases = {
        "ipa speech": "speech",
        "speech cn": "speech",
        "speech amazon": "speech",
        "charging settings & value add": "charging settings and value add",
        "function on demand": "fod",
        "m gmbh": "mgmbh",
        "system managers": "system manager",
        "rsu ui": "rsu",
        "linuxos": "linux os",
        "idcevo": "idcevo",
        "pent": "pent",
    }
    return aliases.get(normalized, normalized)


def rack_domain_name(value: str) -> str:
    """Return the test.guide location family for a dashboard domain."""
    normalized = " ".join(str(value or "").strip().casefold().replace("_", " ").split())
    return RACK_DOMAIN_NAMES.get(normalized, str(value or "").strip())


def normalize_rack_location(value: str) -> str:
    """Normalize a test.guide location path for case-insensitive matching."""
    return "/".join(
        " ".join(part.strip().casefold().replace("_", " ").split())
        for part in str(value or "").split("/")
        if part.strip()
    )


def rack_scope_for_variant(variant: str) -> str:
    """Map execution variants to the test.guide rack platform name."""
    normalized = str(variant or "").strip().upper()
    if normalized in {"SV_MID", "SV_HIGH", "SV_MINI"}:
        return "IDC23"
    if normalized in {"IDCEVO-25", "IDCEVO-21"}:
        return "IDCEVO"
    if normalized in {"CDE-01", "CDE", "RSE26"}:
        return "PENT"
    return normalized


def rack_scopes_for_selection(
    projects: list[str] | None = None,
    variants: list[str] | None = None,
) -> set[str]:
    """Resolve selected project/variant values to test.guide product scopes."""
    selected_projects = {str(value).strip().upper() for value in (projects or []) if str(value).strip()}
    selected_variants = {str(value).strip().upper() for value in (variants or []) if str(value).strip()}
    if not selected_projects or "ALL" in selected_projects:
        return {"IDC23", "IDCEVO", "PENT"}

    scopes = set()
    if "ABPI" in selected_projects:
        scopes.update({"IDC23"} if not selected_variants else {
            rack_scope_for_variant(value)
            for value in selected_variants
            if rack_scope_for_variant(value) == "IDC23"
        })
    if "IDCEVODEV" in selected_projects:
        scopes.update({"IDCEVO", "PENT"} if not selected_variants else {
            rack_scope_for_variant(value)
            for value in selected_variants
            if rack_scope_for_variant(value) in {"IDCEVO", "PENT"}
        })
    return scopes or {"IDC23", "IDCEVO", "PENT"}


def build_rack_filters(
    domain: str,
    variants: list[str] | None = None,
    projects: list[str] | None = None,
) -> list[str]:
    """Return onsite/offshore test.guide paths for the selected scope."""
    selected_domains = [
        value.strip()
        for value in str(domain or "").split(",")
        if value.strip()
    ]
    if not selected_domains or any(value.casefold() in {"all", "none"} for value in selected_domains):
        return []
    scopes = rack_scopes_for_selection(projects, variants)
    filters = []
    for selected_domain in selected_domains:
        domain_name = rack_domain_name(selected_domain)
        known_resources = KNOWN_TEST_RESOURCES_BY_DOMAIN.get(rack_domain_key(selected_domain))
        if known_resources:
            filters.extend(
                resource
                for resource in known_resources
                if resource.split("/")[1] in scopes
            )
            continue
        filters.extend(
            f"LTTS_{location}/{scope}/{domain_name}"
            for location in ("ONSITE", "OFFSHORE")
            for scope in ("IDC23", "IDCEVO", "PENT")
            if scope in scopes
        )
    return list(dict.fromkeys(filters))


def _activity_number(value) -> float:
    try:
        return float(str(value or 0).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def load_rack_activity(path: str) -> list[dict]:
    """Load normalized test.guide activity rows from JSON or CSV when supplied."""
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as source:
        if path.lower().endswith(".csv"):
            import csv
            return list(csv.DictReader(source))
        payload = json.load(source)
    if isinstance(payload, dict):
        payload = payload.get("activities", payload.get("rows", []))
    return payload if isinstance(payload, list) else []


def filter_active_rack_activity(rows: list[dict]) -> list[dict]:
    """Keep every positive-duration activity row, including Offline periods."""
    positive_rows = []
    for row in rows:
        hours = _activity_number(row.get("hours", row.get("duration_hours", 0)))
        if hours > 0:
            positive_rows.append(row)
    return positive_rows


def rack_activity_category(activity_type: str) -> str:
    """Map test.guide activity labels to the report's utilisation categories."""
    normalized = " ".join(str(activity_type or "").strip().casefold().replace("_", " ").split())
    if "auto" in normalized:
        return "Automation"
    if any(value in normalized for value in ("offline", "unavailable", "decommission")):
        return "Offline"
    if any(value in normalized for value in ("manual", "user")):
        return "Manual"
    if any(value in normalized for value in ("idle", "standby")):
        return "Rack Idle"
    return ""


def fetch_rack_activity_from_test_guide(
    resources: list[str],
    start_date: str,
    end_date: str,
    domain: str = "",
    variants: list[str] | None = None,
) -> list[dict]:
    """Discover scoped resources and fetch their activity distributions."""
    # A single Test Guide Token is sent under both header schemes test.guide
    # instances use, so users only need to manage one credential.
    token = os.getenv("TEST_GUIDE_TOKEN", "").strip() or os.getenv("TEST_GUIDE_AUTH_KEY", "").strip()
    if not token:
        return []

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "TestGuide-AuthKey": token,
        "Authorization": f"Bearer {token}",
    }

    api_url = f"{TEST_GUIDE_BASE_URL.rstrip('/')}/api/testinfrastructure"
    session = requests.Session()
    session.headers.update(headers)

    def request(method: str, path: str, **kwargs):
        response = session.request(method, f"{api_url}{path}", timeout=60, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    def wait_for_task(task_id: str, result_path: str, download: bool = False):
        for _ in range(30):
            status = request("GET", f"{result_path}/{task_id}/status")
            if status.get("done"):
                suffix = "/download" if download else ""
                return request("GET", f"{result_path}/{task_id}{suffix}")
            time.sleep(1)
        raise TimeoutError(f"test.guide task did not finish: {task_id}")

    def fetch_resource_ids_by_name(resource: str) -> tuple[str, list]:
        # Each named-resource lookup is its own test.guide task/poll cycle, so
        # fan these out concurrently instead of waiting on them one at a time.
        task_ref = request(
            "POST",
            "/testresources/filter",
            params={"projectId": TEST_GUIDE_PROJECT_ID},
            json={"testResourceName": resource.rsplit("/", 1)[-1]},
        )
        result = wait_for_task(task_ref["taskId"], "/testresources/filter")
        ids = result.get("testResourceIds", result if isinstance(result, list) else [])
        return resource, ids

    try:
        resource_ids = []
        resource_names = {}
        matched_locations = set()
        requested_domain = str(domain or "").strip().casefold()
        location_filters = {
            normalize_rack_location("/".join(str(resource).strip().split("/")[:3]))
            for resource in resources
            if len(str(resource).strip().split("/")) >= 3
        }
        selected_scopes = {
            rack_scope_for_variant(value)
            for value in (variants or [])
            if str(value).strip()
        }
        if not selected_scopes:
            selected_scopes = {"IDC23", "IDCEVO", "PENT"}

        exact_resources = [
            resource for resource in resources
            if len(str(resource).strip().split("/")) >= 4
        ]
        if exact_resources and len(exact_resources) == len(resources) and requested_domain not in {"", "all", "none"}:
            # Scoped requests can use the exact known rack names and avoid a full-project scan.
            with ThreadPoolExecutor(max_workers=min(12, len(exact_resources)), thread_name_prefix="test-guide-exact-resource") as executor:
                futures = [executor.submit(fetch_resource_ids_by_name, resource) for resource in exact_resources]
                for future in as_completed(futures):
                    resource, ids = future.result()
                    for resource_id in ids:
                        resource_ids.append(resource_id)
                        matched_locations.add(normalize_rack_location("/".join(str(resource).strip().split("/")[:3])))
                        resource_names[resource_id] = resource
        else:
            discovery_ref = request(
                "POST",
                "/testresources/filter",
                params={"projectId": TEST_GUIDE_PROJECT_ID},
                json={"testResourceName": "*"},
            )
            discovered_ids = wait_for_task(discovery_ref["taskId"], "/testresources/filter").get("testResourceIds", [])

            def fetch_resource_metadata(resource_id: str) -> tuple[str, dict]:
                response = requests.get(
                    f"{api_url}/testresources/{resource_id}",
                    headers=headers,
                    params={"projectId": TEST_GUIDE_PROJECT_ID},
                    verify=False,
                    timeout=60,
                )
                response.raise_for_status()
                return resource_id, response.json() if response.content else {}

            with ThreadPoolExecutor(max_workers=12, thread_name_prefix="test-guide-resource") as executor:
                futures = [executor.submit(fetch_resource_metadata, resource_id) for resource_id in discovered_ids]
                for future in as_completed(futures):
                    resource_id, metadata = future.result()
                    metadata_location = (
                        metadata.get("location")
                        or metadata.get("resourceLocation")
                        or metadata.get("path")
                        or metadata.get("resourcePath")
                        or ""
                    )
                    location_parts = [part.strip() for part in str(metadata_location).split("/")]
                    location_prefix = location_parts[0].upper() if location_parts else ""
                    location_scope = location_parts[1].upper() if len(location_parts) > 1 else ""
                    if len(location_parts) < 3 or location_prefix not in {"LTTS_OFFSHORE", "LTTS_ONSITE"}:
                        continue
                    location = normalize_rack_location("/".join(location_parts[:3]))
                    if location_filters:
                        if location not in location_filters:
                            continue
                    elif requested_domain not in {"", "all", "none"}:
                        requested_domains = [
                            value.strip()
                            for value in requested_domain.split(",")
                            if value.strip()
                        ]
                        if not any(
                            rack_domain_matches(value, location_parts[2])
                            for value in requested_domains
                        ):
                            continue
                    if location_scope not in selected_scopes:
                        continue
                    resource_ids.append(resource_id)
                    matched_locations.add(location)
                    resource_name = str(
                        metadata.get("name")
                        or metadata.get("testResourceName")
                        or metadata.get("resourceName")
                        or ""
                    ).strip()
                    normalized_location_parts = [location_prefix, location_scope, location_parts[2].strip().upper()]
                    resource_names[resource_id] = "/".join(normalized_location_parts + ([resource_name] if resource_name else []))

        if not resource_ids and exact_resources:
            with ThreadPoolExecutor(max_workers=min(12, len(exact_resources)), thread_name_prefix="test-guide-fallback-resource") as executor:
                futures = [executor.submit(fetch_resource_ids_by_name, resource) for resource in exact_resources]
                for future in as_completed(futures):
                    resource, ids = future.result()
                    for resource_id in ids:
                        resource_ids.append(resource_id)
                        resource_names[resource_id] = resource

        if location_filters:
            ignored_locations = sorted(location_filters - matched_locations)
            if ignored_locations:
                print(f"  Ignored rack locations without resources: {', '.join(ignored_locations)}")

        if not resource_ids:
            return []

        filter_body = {
            "filterStartTime": f"{start_date}T00:00:00Z",
            "filterEndTime": f"{end_date}T23:59:59Z",
            "trIds": list(dict.fromkeys(resource_ids)),
        }
        task_ref = request(
            "POST",
            "/activities/distribution",
            params={"projectId": TEST_GUIDE_PROJECT_ID, "exportType": "JSON"},
            json=filter_body,
        )
        try:
            distribution = wait_for_task(task_ref["taskId"], "/activities/distribution", download=True)
        except requests.RequestException as download_exc:
            print(f"  test.guide distribution download failed; trying JSON task result: {download_exc}")
            distribution = wait_for_task(task_ref["taskId"], "/activities/distribution", download=False)
    except (requests.RequestException, KeyError, TimeoutError, ValueError) as exc:
        print(f"test.guide API fetch failed: {exc}")
        return []

    rows = []
    for rack in distribution.get("trActivityDistribution", []):
        resource = resource_names.get(rack.get("trId"), "")
        for activity in rack.get("distributedActivities", []):
            hours = _activity_number(activity.get("period", 0)) / 3600000
            if hours <= 0:
                continue
            rows.append(
                {
                    "test_resource": resource,
                    "activity_type": activity.get("typeName", ""),
                    "hours": hours,
                }
            )
    return rows


def aggregate_rack_utilisation(
    rows: list[dict],
    domain: str,
    start_date: str,
    end_date: str,
    variants: list[str] | None = None,
    projects: list[str] | None = None,
) -> dict:
    """Aggregate automation, offline, manual and rack-idle hours for the selected scope."""
    domains = [value.strip() for value in str(domain or "").split(",") if value.strip()]
    available_resources = [
        str(row.get("test_resource", row.get("resource", row.get("path", "")))).strip()
        for row in rows
    ]
    selected_scopes = rack_scopes_for_selection(projects, variants)

    if not domains or any(value.casefold() in {"all", "none"} for value in domains):
        filters = [
            resource for resource in available_resources
            if len(resource.split("/")) >= 3
            and resource.split("/")[0] in {"LTTS_OFFSHORE", "LTTS_ONSITE"}
            and resource.split("/")[1] in selected_scopes
        ] or [
            resource for resource in KNOWN_TEST_RESOURCES
            if resource.split("/")[1] in selected_scopes
        ]
    else:
        filters = [
            resource for resource in available_resources
            if len(resource.split("/")) >= 3
            and resource.split("/")[0] in {"LTTS_OFFSHORE", "LTTS_ONSITE"}
            and any(rack_domain_matches(rack_domain_name(value), resource.split("/")[2]) for value in domains)
            and resource.split("/")[1] in selected_scopes
        ]
        if not filters and not available_resources:
            filters = [
                resource
                for value in domains
                for resource in build_rack_filters(value, variants, projects)
            ]
    categories = ("Automation", "Offline", "Manual", "Rack Idle")
    totals = {category: 0.0 for category in categories}
    matched_resources = set()
    by_resource = {resource: {category: 0.0 for category in categories} for resource in filters}
    for row in rows:
        resource = str(row.get("test_resource", row.get("resource", row.get("path", "")))).strip()
        if domains and not any(
            resource == selected or resource.startswith(f"{selected}/")
            for selected in filters
        ):
            continue
        activity_type = str(row.get("activity_type", row.get("activity", row.get("type", ""))))
        category = rack_activity_category(activity_type)
        if not category:
            continue
        hours = _activity_number(row.get("hours", row.get("duration_hours", 0)))
        totals[category] += hours
        if resource:
            matched_resources.add(resource)
            rack_totals = by_resource.setdefault(resource, {category: 0.0 for category in categories})
            rack_totals[category] += hours
    rack_rows = [
        {
            "resource": resource,
            "total_hours": sum(values.values()),
            "automation_hours": values["Automation"],
            "offline_hours": values["Offline"],
            "manual_hours": values["Manual"],
            "rack_idle_hours": values["Rack Idle"],
        }
        for resource, values in sorted(by_resource.items())
    ]
    return {
        "domain": domain or "All",
        "week_label": build_cw_label(start_date, end_date),
        "start_date": start_date,
        "end_date": end_date,
        "total_hours": sum(totals.values()),
        "automation_hours": totals["Automation"],
        "offline_hours": totals["Offline"],
        "manual_hours": totals["Manual"],
        "rack_idle_hours": totals["Rack Idle"],
        "matched_resources": sorted(matched_resources),
        "by_resource": rack_rows,
    }


def _build_available_rack_filters(
    domain: str,
    variants: list[str] | None,
    available_resources: list[str],
    projects: list[str] | None = None,
) -> list[str]:
    selected = set(build_rack_filters(domain, variants, projects))
    if not available_resources:
        return list(selected)
    clean_domain = str(domain or "").strip().casefold()
    selected_scopes = {
        rack_scope_for_variant(value)
        for value in (variants or [])
        if str(value).strip()
    }
    if not selected_scopes:
        selected_scopes = {"IDC23", "IDCEVO", "CDE", "RSE26"}
    return [
        resource
        for resource in available_resources
        if len(resource.split("/")) == 4
        and rack_domain_matches(clean_domain, resource.split("/")[2])
        and resource.split("/")[1] in selected_scopes
    ]


def build_projects_jql(projects: list[str]) -> str:
    clean_projects = [p.strip() for p in projects if p and p.strip()]
    if not clean_projects:
        clean_projects = list(PROJECTS)
    return f'project in ({", ".join(clean_projects)})'


def ensure_jira_credentials_loaded() -> None:
    """Load local-file or Windows-user Jira credentials once for non-shell launches."""
    global _JIRA_ENV_LOADED
    if _JIRA_ENV_LOADED:
        return
    _JIRA_ENV_LOADED = True
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
            if not os.getenv(name, "").strip() and _is_credential_value(value):
                os.environ[name] = str(value).strip()
                _JIRA_CREDENTIAL_SOURCES[name] = "credentials.json"
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
                    if not os.getenv(name, "").strip() and _is_credential_value(value):
                        os.environ[name] = value.strip()
                        _JIRA_CREDENTIAL_SOURCES[name] = "credentials.txt"
    except (FileNotFoundError, OSError):
        pass

    if os.getenv("JIRA_API_TOKEN", "").strip() or os.name != "nt":
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
                    _JIRA_CREDENTIAL_SOURCES[name] = "Windows user environment variable"
    except (FileNotFoundError, OSError):
        return


def _is_credential_value(value) -> bool:
    normalized = str(value or "").strip().casefold()
    return bool(normalized) and not (
        normalized.startswith("your-")
        or normalized.startswith("paste-your-")
        or normalized in {"changeme", "replace-me"}
    )


def build_auth_and_headers():
    """Build auth/headers with env var override support for safer local usage."""
    ensure_jira_credentials_loaded()
    email = os.getenv("JIRA_EMAIL", JIRA_EMAIL)
    token = os.getenv("JIRA_API_TOKEN", JIRA_API_TOKEN)
    mode = os.getenv("JIRA_AUTH_MODE", JIRA_AUTH_MODE).strip().lower()
    if mode not in {"basic", "bearer"}:
        print(f"Unsupported JIRA_AUTH_MODE '{mode}'. Falling back to 'basic'.")
        mode = "basic"
    if not _is_credential_value(token):
        raise ValueError(
            "JIRA_API_TOKEN is missing or still a template value. Enter the real token in credentials.json."
        )
    if mode == "basic" and not _is_credential_value(email):
        raise ValueError("JIRA_EMAIL is missing or still a template value. Enter it in credentials.json for basic mode.")

    headers = dict(HEADERS)
    auth = None

    if mode == "bearer":
        headers["Authorization"] = f"Bearer {token}"
    else:
        auth = HTTPBasicAuth(email, token)

    return auth, headers, mode


def get(endpoint: str, params: dict = None, log_http_error: bool = True):
    url = f"{JIRA_BASE_URL}/rest/api/2/{endpoint}"
    auth, headers, mode = build_auth_and_headers()
    try:
        resp = requests.get(url, headers=headers, auth=auth, params=params, verify=False, timeout=60)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        if log_http_error:
            print(f"\nCould not reach Jira at {JIRA_BASE_URL} - the connection itself failed/timed out "
                  "(this happens before any login check, so it's not a credentials problem).")
            print(f"  Detail: {exc}")
            print(
                "\nHint: this is a network-reachability issue, not a code bug. Most likely "
                "causes: (1) VPN not connected, if one is required to reach this host from "
                "your location, (2) a corporate HTTP/HTTPS proxy is needed but not configured "
                "for this script (browsers often use a system-configured proxy automatically; "
                "Python's requests library only uses one if the HTTPS_PROXY/HTTP_PROXY "
                "environment variables are set), or (3) a firewall on your network path is "
                "blocking this host/port. Try opening "
                f"{JIRA_BASE_URL} directly in a browser from the same machine first - if that "
                "also fails/hangs, it confirms this is network/VPN/proxy, not the script."
            )
        raise
    try:
        resp.raise_for_status()
    except HTTPError as exc:
        if not log_http_error:
            raise exc
        # Jira usually returns a JSON body with useful permission/auth details.
        details = ""
        try:
            payload = resp.json()
            details = json.dumps(payload, indent=2)
        except Exception:
            details = resp.text.strip()[:2000]

        print("\nJira request failed.")
        print(f"  URL: {resp.url}")
        print(f"  HTTP: {resp.status_code}")
        auth_mode_source = _JIRA_CREDENTIAL_SOURCES.get(
            "JIRA_AUTH_MODE", "a pre-existing OS/session environment variable (set before this script started)"
        )
        print(f"  Auth mode: {mode} (from {auth_mode_source})")
        if details:
            print("  Response:")
            print(details)

        if resp.status_code == 403:
            if mode == "basic" and "basic authentication" in details.lower() and "disabled" in details.lower():
                print(
                    "\nHint: this Jira instance has Basic Authentication disabled - "
                    f"JIRA_AUTH_MODE=basic is currently coming from {auth_mode_source}. "
                    "credentials.json is read before credentials.txt and wins if both set "
                    "JIRA_AUTH_MODE - editing the wrong one has no effect. Fix: open "
                    "whichever file is named above (or use the dashboard's Credentials "
                    "screen, which writes credentials.json) and set Auth mode to \"Bearer\" "
                    "using your Jira Personal Access Token. If unsure, delete "
                    "credentials.json entirely and regenerate credentials.txt via "
                    "credentials_setup.html with Bearer selected."
                )
            else:
                print(
                    "\nHint: 403 means authentication worked but access is forbidden. "
                    "Check project permissions/JQL visibility, or try JIRA_AUTH_MODE=bearer "
                    "if your Jira PAT is not meant for basic auth."
                )
        elif resp.status_code == 400 and "does not exist for the field 'project'" in details:
            missing_project = re.search(r"value '([^']+)' does not exist for the field 'project'", details)
            project_name = missing_project.group(1) if missing_project else "the project"
            print(
                f"\nHint: Jira reports '{project_name}' does not exist for the 'project' "
                "field. This usually means your Jira account doesn't have Browse "
                f"Project permission for '{project_name}' (Jira hides restricted "
                "projects behind this same \"does not exist\" message rather than a "
                "permission error) - not something this tool can work around. Fix: "
                f"either ask a Jira admin to grant your account access to '{project_name}', "
                "or remove it from the Projects filter (dashboard: Test Scope > "
                f"Projects, or CLI: --projects without '{project_name}')."
            )
        raise exc
    return resp.json()


def fetch_all(jql: str, fields: list, log_http_error: bool = True) -> list:
    issues, start = [], 0
    while True:
        data  = get(
            "search",
            {"jql": jql, "startAt": start, "maxResults": 100, "fields": fields},
            log_http_error=log_http_error,
        )
        batch = data.get("issues", [])
        issues.extend(batch)
        start += len(batch)
        if start >= data.get("total", 0):
            break
    return issues


def _test_run_rows_from_payload(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("tests", "testRuns", "test_runs", "results", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _test_run_rows_from_payload(value)
            if nested:
                return nested
    return []


def fetch_test_run_details_batched(execution_keys: list[str]) -> dict[str, list[dict]]:
    """Enrich execution keys through the test-management plugin in bounded batches."""
    if not execution_keys:
        return {}
    auth, headers, _ = build_auth_and_headers()
    endpoint = TEST_RUN_PLUGIN_ENDPOINT.strip()
    if not endpoint:
        print("  Test-run plugin enrichment disabled; using standard Jira execution data.")
        return {}
    url = endpoint if endpoint.startswith("http") else f"{JIRA_BASE_URL}{endpoint}"
    details_by_execution: dict[str, list[dict]] = {}
    for offset in range(0, len(execution_keys), TEST_RUN_PLUGIN_BATCH_SIZE):
        batch = execution_keys[offset:offset + TEST_RUN_PLUGIN_BATCH_SIZE]
        try:
            response = requests.post(
                url,
                headers={**headers, "Content-Type": "application/json"},
                auth=auth,
                json={"executionKeys": batch, "execution_keys": batch, "keys": batch},
                verify=False,
                timeout=60,
            )
            response.raise_for_status()
            rows = _test_run_rows_from_payload(response.json())
            for row in rows:
                execution_key = str(
                    row.get("executionKey") or row.get("execution_key") or row.get("testExecutionKey") or row.get("parentKey") or ""
                ).strip()
                if execution_key:
                    details_by_execution.setdefault(execution_key, []).append(row)
        except (requests.RequestException, ValueError, KeyError) as exc:
            print(f"  Note: Test-run plugin batch {offset // TEST_RUN_PLUGIN_BATCH_SIZE + 1} unavailable: {exc}")
    return details_by_execution


def count_issues_by_project(issues: list[dict], projects: list[str]) -> dict[str, int]:
    """Return issue counts per project key prefix for the provided project list."""
    normalized_projects = [p.strip() for p in projects if p and p.strip()]
    counts = {p: 0 for p in normalized_projects}
    for issue in issues:
        key = str(issue.get("key", ""))
        project = key.split("-", 1)[0] if "-" in key else ""
        if project in counts:
            counts[project] += 1
    return counts


def issue_keys_by_project(issues: list[dict], projects: list[str]) -> dict[str, list[str]]:
    """Return ordered issue keys grouped by project key prefix for the provided project list."""
    normalized_projects = [p.strip() for p in projects if p and p.strip()]
    grouped = {p: [] for p in normalized_projects}
    for issue in issues:
        key = str(issue.get("key", "")).strip()
        if not key:
            continue
        project = key.split("-", 1)[0] if "-" in key else ""
        if project in grouped:
            grouped[project].append(key)

    # Deduplicate while preserving original Jira search order.
    for p in grouped:
        grouped[p] = list(dict.fromkeys(grouped[p]))
    return grouped


def discover_fields():
    """Print all field names and IDs — use this to find custom field IDs."""
    print("\n=== All Jira Fields ===\n")
    fields = get("field")
    # filter likely relevant fields
    keywords = ["domain", "sop", "variant", "step", "pass", "fail", "abort", "execut", "todo", "test"]
    print(f"{'ID':<30} {'NAME'}")
    print("-" * 60)
    for f in sorted(fields, key=lambda x: x.get("name", "")):
        name = f.get("name", "").lower()
        fid  = f.get("id", "")
        if any(k in name for k in keywords) or fid.startswith("customfield"):
            print(f"{fid:<30} {f.get('name', '')}")
    print("\nUpdate CUSTOM_FIELDS in the script with the correct IDs.")


def get_field(issue: dict, field_key: str):
    """Safely get a custom field value from an issue."""
    val = issue["fields"].get(CUSTOM_FIELDS.get(field_key, ""), None)
    if val is None:
        return ""
    if isinstance(val, dict):
        return val.get("value") or val.get("name") or ""
    if isinstance(val, list):
        return ", ".join(str(v.get("value") or v.get("name") or v) if isinstance(v, dict) else str(v) for v in val)
    return str(val)


def classify_cycle(labels: list) -> str:
    """Classify supported test-scope executions as manual or automation."""
    label_set = {str(label).strip().casefold() for label in labels}
    supported_scope_labels = {label.casefold() for label in TEST_SCOPE_LABELS}
    if not label_set & supported_scope_labels:
        return "Other"
    if label_set & {label.casefold() for label in AUTO_LABELS}:
        return "Automation"
    return "Manual"


def select_labels_for_cycle_mode(cycle_mode: str) -> list:
    mode = (cycle_mode or "both").strip().lower()
    if mode == "automation":
        return AUTO_LABELS
    if mode == "manual":
        return list(TEST_SCOPE_LABELS)
    return AUTO_LABELS + list(TEST_SCOPE_LABELS)


def classify_execution_product(project: str, variant: str) -> str:
    """Map execution project and variant values to the requested products."""
    normalized_project = str(project or "").strip().upper()
    normalized_variant = str(variant or "").strip().upper()
    if normalized_project == "ABPI" and normalized_variant in {"", "SV_MID", "SV_HIGH", "SV_MINI"}:
        return "IDC23"
    if normalized_project == "IDCEVODEV":
        if normalized_variant in {"", "IDCEVO-21", "IDCEVO-25"}:
            return "IDCEVO"
        if normalized_variant == "CDE":
            return "CDE"
        if normalized_variant == "RSE26":
            return "RSE"
    return "Unknown"


def get_execution_counts(issue: dict) -> dict:
    """Read pass/fail/aborted/executing/todo counters from Jira execution status field."""
    counts = {
        "pass": "0",
        "failed": "0",
        "aborted": "0",
        "executing": "0",
        "todo": "0",
    }

    status_field = issue["fields"].get(CUSTOM_FIELDS.get("execution_status", ""), {})
    if isinstance(status_field, dict):
        name_map = {
            "PASS": "pass",
            "FAIL": "failed",
            "ABORTED": "aborted",
            "EXECUTING": "executing",
            "TODO": "todo",
        }
        for s in status_field.get("statuses", []):
            if not isinstance(s, dict):
                continue
            key = name_map.get(str(s.get("name", "")).strip().upper())
            if not key:
                continue
            value = s.get("statusCount", 0)
            counts[key] = str(value) if str(value).isdigit() else "0"

    # Backward-compatible fallback for setups using dedicated custom fields.
    for key in counts:
        if counts[key] == "0":
            field_val = get_field(issue, key)
            if str(field_val).isdigit():
                counts[key] = str(int(field_val))

    return counts


def get_execution_defects(issue: dict) -> list[str]:
    """Return normalized defect keys from Linked Issues, with custom field fallback."""
    defects = []

    # Primary source: Linked Issues column.
    links = issue["fields"].get("issuelinks", [])
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            inward = link.get("inwardIssue", {})
            outward = link.get("outwardIssue", {})
            for linked in (inward, outward):
                if isinstance(linked, dict):
                    key = linked.get("key")
                    if key:
                        defects.append(str(key))

    # Fallback source: optional custom field if linked issues are absent.
    if not defects:
        raw = issue["fields"].get(CUSTOM_FIELDS.get("execution_defects", ""), [])
        if raw not in (None, "", [], {}):
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        key = item.get("key") or item.get("id") or item.get("value")
                        if key:
                            defects.append(str(key))
                    else:
                        defects.append(str(item))
            else:
                defects.append(str(raw))

    return list(dict.fromkeys([d for d in defects if d.strip()]))


def _extract_comment_text(comment_body) -> str:
    """Extract readable text from Jira comment payload (string or ADF-like structure)."""
    if isinstance(comment_body, str):
        return comment_body.strip()

    if isinstance(comment_body, dict):
        parts = []

        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "text" and node.get("text"):
                    parts.append(str(node.get("text")))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(comment_body)
        return " ".join(p.strip() for p in parts if p and p.strip()).strip()

    return ""


def _is_end_of_cycle_comment(text: str) -> bool:
    """Return True when comment looks like an end-of-cycle closure/update note."""
    t = (text or "").strip().lower()
    if not t:
        return False

    end_cycle_patterns = [
        r"\bend\s*of\s*cycle\b",
        r"\beoc\b",
        r"\bcycle\s*completed\b",
        r"\bcycle\s*closure\b",
        r"\bclose\s*the\s*cycle\b",
    ]
    return any(re.search(p, t) for p in end_cycle_patterns)


def _is_abort_context_comment(text: str) -> bool:
    """Return True when comment appears to describe an aborted/failure context."""
    t = (text or "").strip().lower()
    if not t:
        return False

    abort_patterns = [
        r"\babort",
        r"\bblocked\b",
        r"\bissue\b",
        r"\berror\b",
        r"\bfail",
        r"\breason\b",
        r"\bdefect\b",
    ]
    return any(re.search(p, t) for p in abort_patterns)


def _recent_comment_texts(issue: dict, limit: int = 5) -> list[str]:
    """Return the latest readable Jira comment texts for the issue."""
    comments_value = issue.get("fields", {}).get("comment", [])
    if isinstance(comments_value, str):
        return [" ".join(comments_value.split())] if comments_value.strip() else []
    if isinstance(comments_value, list):
        comments = comments_value
    elif isinstance(comments_value, dict):
        comments = comments_value.get("comments", [])
        if not comments and comments_value.get("body"):
            comments = [comments_value]
    else:
        comments = []
    texts: list[str] = []
    if not isinstance(comments, list):
        return texts

    for comment in comments[-limit:]:
        if isinstance(comment, str):
            text = " ".join(comment.split())
            if text:
                texts.append(text)
            continue
        if not isinstance(comment, dict):
            continue
        text = _extract_comment_text(comment.get("body"))
        if text:
            texts.append(" ".join(text.split()))
    return texts


def _latest_execution_comment(issue: dict) -> str:
    comments = _recent_comment_texts(issue, 1)
    return comments[-1] if comments else "No tester comment available."


def _linked_defect_comment(issue: dict, linked_defects: list[str]) -> str:
    comments = _recent_comment_texts(issue, 5)
    linked_keys = {str(key).strip().casefold() for key in linked_defects if str(key).strip()}
    if linked_keys:
        for comment in reversed(comments):
            lowered = comment.casefold()
            if any(key in lowered for key in linked_keys):
                return comment
    return _latest_execution_comment(issue)


def _explicit_aborted_comment(issue: dict) -> str:
    comments = _recent_comment_texts(issue, 5)
    for comment in reversed(comments):
        lowered = comment.casefold()
        if ("no of test cases" in lowered and "cycle closed" in lowered) or (
            "telematics system validation" in lowered and "aborted reason is mentioned" in lowered
        ):
            continue
        return comment
    return ""


def _clean_jira_markup(text: str) -> str:
    """Convert Jira wiki markup (bold, mentions, links, tables) into plain prose for summaries.

    Without this, a comment containing a wiki table (e.g. "| *CheckIN* | *nok* |") has no
    sentence-ending punctuation, so it becomes one giant "sentence" that gets truncated
    mid-table, leaking raw pipes/asterisks into the report.
    """
    raw = str(text or "")
    raw = re.sub(r"\[~([^\]]+)\]", r"@\1", raw)
    raw = re.sub(r"\[([^\|\]]+)\|[^\]]*\]", r"\1", raw)
    raw = re.sub(r"\[(https?://[^\]]+)\]", "", raw)
    raw = re.sub(r"\s*Unable to render embedded object: File \(\) not found\.?", ".", raw, flags=re.IGNORECASE)
    raw = raw.replace("*", "")

    if "|" in raw:
        parts = raw.split("|")
        prefix = parts[0].strip()
        suffix = parts[-1].strip()
        middle = parts[1:-1]
        cells = [cell.strip() for cell in middle if cell.strip() and not re.fullmatch(r"[\-\s:]+", cell.strip())]
        pairs = [f"{cells[i]}: {cells[i + 1]}" for i in range(0, len(cells) - 1, 2)]
        if len(cells) % 2 == 1:
            pairs.append(cells[-1])
        table_text = (", ".join(pairs) + ".") if pairs else ""
        raw = " ".join(part for part in (prefix, table_text, suffix) if part)

    return " ".join(raw.split()).strip()


def _split_comment_sentences(text: str) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [sentence.strip() for sentence in sentences if sentence and sentence.strip()]


def _compress_comment_sentence(sentence: str) -> str:
    text = " ".join(str(sentence or "").split()).strip()
    if not text:
        return ""

    replacements = [
        (r"^(the\s+)?(ticket|issue|defect)\s+", ""),
        (r"^(the\s+)?final\s+comment\s+", ""),
        (r"^analysis\s+concludes\s+that\s+", ""),
        (r"^analysis\s+concluded\s+that\s+", ""),
        (r"^the\s+final\s+analysis\s+concludes\s+that\s+", ""),
        (r"^the\s+final\s+analysis\s+concluded\s+that\s+", ""),
        (r"^the\s+final\s+comment\s+explicitly\s+states\s+that\s+", ""),
        (r"^comment\s+summary:\s*", ""),
        (r"^it\s+was\s+", ""),
        (r"^it\s+is\s+", ""),
    ]
    lowered = text
    for pattern, replacement in replacements:
        lowered = re.sub(pattern, replacement, lowered, flags=re.IGNORECASE)

    lowered = re.sub(r"\bwhich\s+indicates\s+that\b", "showing that", lowered, flags=re.IGNORECASE)
    lowered = re.sub(r"\bindicating\s+that\b", "showing that", lowered, flags=re.IGNORECASE)
    lowered = re.sub(r"\bindicating\b", "showing", lowered, flags=re.IGNORECASE)
    lowered = re.sub(r"\bpreventing\b", "blocking", lowered, flags=re.IGNORECASE)
    lowered = re.sub(r"\bdoes\s+not\s+indicate\b", "does not show", lowered, flags=re.IGNORECASE)
    lowered = re.sub(r"\bno\s+product\s+defect\s+was\s+identified\b", "no product defect was identified", lowered, flags=re.IGNORECASE)
    lowered = re.sub(r"\bthe\s+behavior\s+observed\s+is\s+expected\b", "behavior matches the expected design", lowered, flags=re.IGNORECASE)

    lowered = lowered.strip(" \t-–—:;,")
    if len(lowered) > 220:
        cutoff = lowered.rfind(" ", 0, 220)
        lowered = lowered[:cutoff if cutoff > 0 else 220].rstrip(" \t-–—:;,") + "..."
    return lowered


def _score_comment_sentence(sentence: str) -> int:
    text = str(sentence or "").lower()
    score = 0
    keyword_weights = [
        ("missing", 4),
        ("blocked", 4),
        ("prevent", 4),
        ("reproduc", 4),
        ("root cause", 5),
        ("duplicate", 4),
        ("rejected", 4),
        ("deficient", 4),
        ("resolved", 4),
        ("fixed", 4),
        ("retest", 3),
        ("retest", 3),
        ("analysis", 3),
        ("comment", 1),
        ("final", 1),
        ("expected design", 4),
        ("not reproducible", 5),
        ("no product defect", 5),
        ("missing information", 5),
        ("network", 3),
        ("offline", 3),
        ("coredump", 5),
        ("dlt", 4),
        ("logs", 3),
        ("software version", 3),
        ("mainline", 3),
        ("testcase", 3),
        ("layering", 3),
    ]
    for needle, weight in keyword_weights:
        if needle in text:
            score += weight
    if any(marker in text for marker in ["because", "due to", "therefore", "however", "but", "while", "although"]):
        score += 2
    if len(text) > 60:
        score += 1
    return score


def _is_comment_summary_noise(sentence: str) -> bool:
    """Exclude checklist, attachment, and routing boilerplate from summary candidates."""
    text = " ".join(str(sentence or "").split()).strip().casefold()
    if not text:
        return True
    if "checkin:" in text and "defect understood:" in text:
        return True
    noise_patterns = (
        r"^repositories? included in analysis",
        r"^all important information .* ticketkompass",
        r"^ipnext defect compass extension",
        r"^unable to render embedded object",
        r"^created:\s*\d{4}-\d{2}-\d{2}",
        r"^checkin\s*:",
        r"^eth\d+\s*:",
        r"^dlt\s*\((?:main|perf)\)\s*:",
        r"^uart\s*:",
        r"^defect understood\s*:",
        r"^[-|:_\s]+$",
    )
    return any(re.search(pattern, text) for pattern in noise_patterns)


def summarize_recent_comments(comment_texts: list[str]) -> str:
    """Summarize the latest comment thread without copying Jira text verbatim."""
    cleaned = [_clean_jira_markup(text) for text in comment_texts if str(text).strip()]
    cleaned = [text for text in cleaned if text]
    if not cleaned:
        return "No recent comments available."

    sentences: list[str] = []
    for comment in cleaned[-5:]:
        sentences.extend(
            sentence for sentence in _split_comment_sentences(comment)
            if not _is_comment_summary_noise(sentence)
        )

    ranked = []
    for index, sentence in enumerate(sentences):
        compressed = _compress_comment_sentence(sentence)
        if not compressed:
            continue
        ranked.append((
            _score_comment_sentence(compressed),
            index,
            compressed,
        ))

    if not ranked:
        return "Recent comments indicate ongoing defect handling and next-step follow-up."

    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected: list[str] = []
    seen = set()
    for _, _, sentence in ranked:
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        selected.append(sentence)
        if len(selected) >= 2:
            break

    if not selected:
        return "Recent comments indicate ongoing defect handling and next-step follow-up."
    if len(selected) == 1:
        return selected[0]

    return f"{selected[0]}; {selected[1]}"


def summarize_comments_with_transformers(comment_texts: list[str]) -> str:
    """Use Transformers when explicitly enabled, falling back to the fast heuristic summary."""
    global _COMMENT_SUMMARIZER, _COMMENT_SUMMARIZER_LOAD_ATTEMPTED

    fallback = summarize_recent_comments(comment_texts)
    cleaned = [" ".join(str(text).split()) for text in comment_texts if str(text).strip()]
    if not cleaned:
        return fallback
    use_transformers = os.getenv("JIRA_COMMENT_SUMMARY_USE_TRANSFORMERS", "0").strip().casefold()
    if use_transformers not in {"1", "true", "yes"}:
        return fallback

    if not _COMMENT_SUMMARIZER_LOAD_ATTEMPTED:
        _COMMENT_SUMMARIZER_LOAD_ATTEMPTED = True
        try:
            from transformers import pipeline

            model_name = os.getenv(
                "JIRA_COMMENT_SUMMARY_MODEL",
                "sshleifer/distilbart-cnn-12-6",
            ).strip()
            allow_download = os.getenv("JIRA_COMMENT_SUMMARY_ALLOW_DOWNLOAD", "0").strip().casefold() in {
                "1",
                "true",
                "yes",
            }
            _COMMENT_SUMMARIZER = pipeline(
                "summarization",
                model=model_name,
                device=-1,
                model_kwargs={} if allow_download else {"local_files_only": True},
            )
        except Exception as exc:
            print(f"  Transformers comment summarization unavailable; using fallback: {exc}")
            _COMMENT_SUMMARIZER = None

    if _COMMENT_SUMMARIZER is None:
        return fallback

    source = " ".join(cleaned[-5:])[:4000]
    try:
        result = _COMMENT_SUMMARIZER(
            source,
            max_length=90,
            min_length=20,
            do_sample=False,
        )
        generated = str(result[0].get("summary_text", "")).strip() if result else ""
        return generated or fallback
    except Exception as exc:
        print(f"  Transformers comment summarization failed; using fallback: {exc}")
        return fallback


def summarize_bucket_overall_comments(detail_rows: list[dict]) -> str:
    """Combine each ticket's last 4-5 comments into one representative overall summary for a closure bucket."""
    combined_texts: list[str] = []
    for detail in detail_rows:
        combined_texts.extend(detail.get("comment_texts", []) or [])
    if not combined_texts:
        return "No recent comments available across these tickets."
    return summarize_comments_with_transformers(combined_texts)


def _extract_duplicate_defect_ids(comment_texts: list[str]) -> list[str]:
    """Extract defect IDs mentioned in duplicate-related comment text."""
    if not comment_texts:
        return []

    duplicate_patterns = [
        r"\bduplicate(?:\s+of|\s+to|\s+for)?\b",
        r"\bsame\s+as\b",
        r"\brefer(?:s)?\s+to\b",
        r"\bsee\s+defect\s+id\b",
        r"\bdefect\s+id\b",
        r"\bduplicate\s+defect\b",
    ]
    issue_key_pattern = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
    extracted: list[str] = []

    for text in comment_texts:
        raw = str(text or "").strip()
        if not raw:
            continue
        lowered = raw.lower()
        if not any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in duplicate_patterns):
            continue

        for match in issue_key_pattern.findall(raw):
            if match not in extracted:
                extracted.append(match)

    return extracted


def _extract_duplicate_ids_from_issuelinks(issue: dict) -> list[str]:
    """Extract the duplicate-of key from Jira's structured 'Duplicate' issue link.

    This is authoritative over comment-text scanning: Jira's own "duplicates" link
    (Issue Links -> duplicates section) is how testers actually record the relationship,
    and it doesn't require the duplicate ID to ever be mentioned in a comment.
    Only the outward "duplicates" direction counts - the inward "is duplicated by"
    direction means some OTHER ticket duplicates this one, not the other way around.
    """
    links = issue.get("fields", {}).get("issuelinks", []) or []
    keys: list[str] = []
    for link in links:
        link_type = link.get("type", {}) or {}
        if str(link_type.get("name", "")).strip().casefold() != "duplicate":
            continue
        outward_issue = link.get("outwardIssue")
        if not outward_issue:
            continue
        key = str(outward_issue.get("key", "")).strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def summarize_duplicate_comments(comment_texts: list[str], duplicate_ids: list[str] | None = None) -> str:
    """Summarize duplicate closure comments and explicitly include referenced defect IDs."""
    duplicate_ids = list(duplicate_ids) if duplicate_ids else _extract_duplicate_defect_ids(comment_texts)
    if duplicate_ids:
        if len(duplicate_ids) == 1:
            return f"Duplicate of defect ID {duplicate_ids[0]}."
        return f"Duplicate of defect IDs {', '.join(duplicate_ids)}."

    summary = summarize_recent_comments(comment_texts)
    if summary and summary != "No recent comments available.":
        return f"Duplicate closure noted, but no defect ID reference was found. {summary}"
    return "Duplicate closure noted, but no defect ID reference was found."


def get_aborted_reason(issue: dict) -> str:
    """Best-effort aborted reason text from Comments column, with field fallback."""
    comments_block = issue["fields"].get("comment", {})
    comments = comments_block.get("comments", []) if isinstance(comments_block, dict) else []
    if isinstance(comments, list) and comments:
        # Prefer latest non end-of-cycle comment that looks abort-related.
        for c in reversed(comments):
            if not isinstance(c, dict):
                continue
            text = _extract_comment_text(c.get("body"))
            if text and not _is_end_of_cycle_comment(text) and _is_abort_context_comment(text):
                return text

        # Fallback: latest non end-of-cycle comment.
        for c in reversed(comments):
            if not isinstance(c, dict):
                continue
            text = _extract_comment_text(c.get("body"))
            if text and not _is_end_of_cycle_comment(text):
                return text

    # Fallback to optional dedicated field if comments are empty.
    value = get_field(issue, "aborted_reason")
    return str(value).strip()


def _jql_exclusive_end_date(end_date: str) -> str:
    """Jira interprets a bare date literal as 00:00:00 of that day, so
    'created <= end_date' silently excludes anything created later that same
    day. Use 'created < result' with the following day instead."""
    return (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def fetch_executions(start_date: str, end_date: str, cycle_mode: str = "both", projects: list[str] | None = None) -> dict:
    date_filter  = f'created >= "{start_date}" AND created < "{_jql_exclusive_end_date(end_date)}"'
    labels_for_query = select_labels_for_cycle_mode(cycle_mode)
    labels_csv   = ", ".join('"' + l + '"' for l in labels_for_query)
    scope_labels_jql = " OR ".join(f'labels = "{label}"' for label in TEST_SCOPE_LABELS)
    projects_jql = build_projects_jql(projects or PROJECTS)
    jql = (
        f'{projects_jql} AND issuetype = "Test Execution" AND {date_filter} '
        f'AND ({scope_labels_jql}) AND labels in ({labels_csv})'
    )

    all_fields = [
        "summary", "status", "labels", "issuelinks", "comment",
        CUSTOM_FIELDS["domain"],
        CUSTOM_FIELDS["sop_pu"],
        CUSTOM_FIELDS["variant"],
        CUSTOM_FIELDS["i_step"],
        CUSTOM_FIELDS["execution_status"],
        CUSTOM_FIELDS["execution_defects"],
        CUSTOM_FIELDS["aborted_reason"],
        CUSTOM_FIELDS["pass"],
        CUSTOM_FIELDS["failed"],
        CUSTOM_FIELDS["aborted"],
        CUSTOM_FIELDS["executing"],
        CUSTOM_FIELDS["todo"],
    ]
    # remove placeholder fields to avoid API errors before discovery is done
    all_fields = [f for f in all_fields if "XXXXX" not in f]

    print(f"  JQL: {jql}")
    issues = fetch_all(jql, all_fields)
    print(f"  Found {len(issues)} test execution issues")
    plugin_details = fetch_test_run_details_batched([str(issue.get("key", "")) for issue in issues if issue.get("key")])
    # group: { domain -> { "Automation": [...], "Manual": [...] } }
    grouped: dict = {}
    for issue in issues:
        project = issue["key"].split("-", 1)[0]
        labels   = issue["fields"].get("labels", [])
        cycle_type = classify_cycle(labels)
        domain   = get_field(issue, "domain") or "Unknown"
        variant  = (get_field(issue, "variant") or "").strip()

        # Only LTTS_SV executions are relevant; classify_cycle handles manual versus automation.
        if cycle_type == "Other":
            continue

        counts   = get_execution_counts(issue)
        defects  = get_execution_defects(issue)
        overall_comment = summarize_recent_comments(_recent_comment_texts(issue, 5))
        tester_comment = ""
        if to_int(counts["aborted"]) > 0:
            tester_comment = _explicit_aborted_comment(issue)
        plugin_rows = plugin_details.get(str(issue.get("key", "")).strip(), [])
        plugin_aborted = [
            row for row in plugin_rows
            if str(row.get("status") or row.get("state") or row.get("executionStatus") or "").casefold() == "aborted"
        ]
        if plugin_aborted:
            counts["aborted"] = str(max(to_int(counts["aborted"]), len(plugin_aborted)))
            plugin_comment = next(
                (
                    str(row.get("comment") or row.get("reason") or row.get("abortReason") or "").strip()
                    for row in plugin_aborted
                    if str(row.get("comment") or row.get("reason") or row.get("abortReason") or "").strip()
                ),
                "",
            )
            if plugin_comment:
                tester_comment = plugin_comment

        if domain not in grouped:
            grouped[domain] = {"Automation": [], "Manual": [], "Other": []}

        grouped[domain][cycle_type].append({
            "key":       issue["key"],
            "project":   project,
            "summary":   issue["fields"].get("summary", ""),
            "status":    issue["fields"].get("status", {}).get("name", ""),
            "labels":    labels,
            "product":   classify_execution_product(project, variant),
            "sop_pu":    get_field(issue, "sop_pu"),
            "variant":   variant,
            "i_step":    get_field(issue, "i_step"),
            "pass":      counts["pass"],
            "failed":    counts["failed"],
            "aborted":   counts["aborted"],
            "executing": counts["executing"],
            "todo":      counts["todo"],
            "defects":   defects,
            "tester_comment": tester_comment,
            "overall_comment": overall_comment,
        })

    return grouped


def fetch_telematics_defects(
    start_date: str,
    end_date: str,
    defect_projects: list[str],
    defect_domain: str,
    defect_assigned_ecus: list[str],
    defect_variant: str,
    closure_projects: list[str] | None = None,
    closure_team: str = "",
    resolution_start_date: str = "",
    resolution_end_date: str = "",
) -> dict:
    """Fetch telematics defects and exploratory subset for selected period."""
    fields_catalog = get("field")
    available_field_ids = {f.get("id", "") for f in fields_catalog if f.get("id")}
    domain_field_available = CUSTOM_FIELDS["domain"] in available_field_ids
    variant_field_available = CUSTOM_FIELDS["variant"] in available_field_ids
    ecu_field_available = DEFECT_ASSIGNED_ECU_FIELD in available_field_ids

    date_filter = f'created >= "{start_date}" AND created < "{_jql_exclusive_end_date(end_date)}"'
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    period_days = (end_dt - start_dt).days + 1
    prev_start = (start_dt - timedelta(days=period_days)).strftime("%Y-%m-%d")
    prev_end = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    previous_date_filter = f'created >= "{prev_start}" AND created < "{_jql_exclusive_end_date(prev_end)}"'
    scope_restrictions_seen = False

    projects_csv = ", ".join(defect_projects or DEFECT_PROJECTS)
    issue_types_csv = ", ".join('"' + i + '"' for i in DEFECT_ISSUE_TYPES)

    extra_filter_clauses = []
    if defect_variant and defect_variant.strip().lower() != "all" and variant_field_available:
        extra_filter_clauses.append(f'"{CUSTOM_FIELDS["variant"]}" ~ "{defect_variant.strip()}"')
    elif defect_variant and defect_variant.strip().lower() != "all" and not variant_field_available:
        print("  Note: defect variant field not available for this Jira scope. Skipping defect variant filter.")

    clean_ecus = [e.strip() for e in defect_assigned_ecus if e.strip() and e.strip().lower() != "all"]
    if clean_ecus and ecu_field_available:
        ecu_clause = ", ".join('"' + e + '"' for e in clean_ecus)
        extra_filter_clauses.append(f'"{DEFECT_ASSIGNED_ECU_FIELD}" in ({ecu_clause})')
    elif clean_ecus and not ecu_field_available:
        print("  Note: Assigned ECU field not available for this Jira scope. Skipping ECU filter.")

    extra_jql = " AND ".join([date_filter] + extra_filter_clauses)
    previous_extra_jql = " AND ".join([previous_date_filter] + extra_filter_clauses)
    closure_extra_filter_clauses = []

    selected_defect_labels = defect_labels_for_team(defect_domain)
    if defect_domain and defect_domain.strip().casefold() not in {"all", "none"} and not selected_defect_labels:
        print(f"  Note: no defect label mapping is configured yet for: {defect_domain}")
    unmapped_defect_domains = unmapped_domain_tokens(defect_domain)
    if unmapped_defect_domains:
        print(f"  Note: these requested domain(s) have no defect label mapping and contributed 0 records: {', '.join(unmapped_defect_domains)}")
    domain_label_clause = build_defect_label_clause(selected_defect_labels or ("__UNMAPPED_DOMAIN__",))
    selected_domain_label_clause = f"AND ({domain_label_clause})"
    telematics_base_jql = (
        f'project in ({projects_csv}) AND issuetype in ({issue_types_csv}) '
        f'{selected_domain_label_clause} AND labels = LTTS_SV AND labels != {DEFECT_LABEL_EXPLORATORY}'
    )
    exploratory_base_jql = (
        f'project in ({projects_csv}) AND issuetype in ({issue_types_csv}) '
        f'{selected_domain_label_clause} AND labels = {DEFECT_LABEL_EXPLORATORY} AND labels = LTTS_SV'
    )

    telematics_jql = f"{telematics_base_jql} AND {extra_jql}"
    exploratory_jql = f"{exploratory_base_jql} AND {extra_jql}"
    previous_week_jql = f"{telematics_base_jql} AND {previous_extra_jql}"
    previous_exploratory_jql = f"{exploratory_base_jql} AND {previous_extra_jql}"

    defect_fields = [
        "summary",
        "status",
        "labels",
        "priority",
        "reporter",
        "created",
        "issuetype",
        "project",
    ]
    if variant_field_available:
        defect_fields.append(CUSTOM_FIELDS["variant"])
    if domain_field_available:
        defect_fields.append(CUSTOM_FIELDS["domain"])
    if ecu_field_available:
        defect_fields.append(DEFECT_ASSIGNED_ECU_FIELD)
    # Always request Found in SW Version; safe to include even if absent on some projects
    defect_fields.append(CUSTOM_FIELDS["found_in_sw_version"])

    fallback_fields = [
        "summary",
        "status",
        "labels",
        "priority",
        "reporter",
        "created",
        "issuetype",
        "project",
    ]

    selected_domain_display = defect_domain.strip() or "All"
    print(f"\nFetching defects for selected domain(s): {selected_domain_display}...")
    print(f"  JQL (Non-ET defects): {telematics_jql}")
    try:
        telematics_issues = fetch_all(telematics_jql, defect_fields, log_http_error=False)
        exploratory_issues = []  # set below in same try path
        print(f"  JQL (ET defects; requires {DEFECT_LABEL_EXPLORATORY}): {exploratory_jql}")
        exploratory_issues = fetch_all(exploratory_jql, defect_fields, log_http_error=False)
        previous_week_issues = fetch_all(previous_week_jql, ["key"], log_http_error=False)
        previous_exploratory_issues = fetch_all(previous_exploratory_jql, ["key"], log_http_error=False)
    except HTTPError:
        # Some Jira scopes reject custom fields in JQL/fields for these defect projects.
        # Retry with safe filters. First keep requested field list to preserve Assigned ECU/Domain when available.
        fallback_telematics_jql = f"{telematics_base_jql} AND {date_filter}"
        fallback_exploratory_jql = f"{exploratory_base_jql} AND {date_filter}"
        fallback_previous_week_jql = f"{telematics_base_jql} AND {previous_date_filter}"
        fallback_previous_exploratory_jql = f"{exploratory_base_jql} AND {previous_date_filter}"
        print("  Note: Jira scope rejected one or more custom-field searches; using fallback defect queries.")
        closure_extra_filter_clauses = []
        scope_restrictions_seen = True
        print(f"  Fallback JQL (Non-ET defects): {fallback_telematics_jql}")
        try:
            telematics_issues = fetch_all(fallback_telematics_jql, defect_fields, log_http_error=False)
            print(f"  Fallback JQL (ET defects): {fallback_exploratory_jql}")
            exploratory_issues = fetch_all(fallback_exploratory_jql, defect_fields, log_http_error=False)
        except HTTPError:
            print("  Retrying fallback with standard fields only...")
            telematics_issues = fetch_all(fallback_telematics_jql, fallback_fields, log_http_error=False)
            exploratory_issues = fetch_all(fallback_exploratory_jql, fallback_fields, log_http_error=False)
            variant_field_available = False
            ecu_field_available = False
            domain_field_available = False
            scope_restrictions_seen = True
        previous_week_issues = fetch_all(fallback_previous_week_jql, ["key"], log_http_error=False)
        previous_exploratory_issues = fetch_all(fallback_previous_exploratory_jql, ["key"], log_http_error=False)


    exploratory_keys = {issue.get("key", "") for issue in exploratory_issues if issue.get("key")}
    known_keys = {issue.get("key", "") for issue in telematics_issues if issue.get("key")}
    telematics_issues.extend(
        issue for issue in exploratory_issues
        if issue.get("key") and issue.get("key") not in known_keys
    )

    rows = []
    for issue in telematics_issues:
        fields = issue.get("fields", {})
        labels = fields.get("labels", []) or []
        key = issue.get("key", "")
        label_set = {str(label).strip().casefold() for label in labels}
        is_exploratory = (
            DEFECT_LABEL_EXPLORATORY.casefold() in label_set
            and "ltts_sv" in label_set
            and bool(label_set & {label.casefold() for label in selected_defect_labels})
            or key in exploratory_keys
        )

        project_specific_labels = [
            lbl for lbl in labels if lbl not in {DEFECT_LABEL_TELEMATICS, DEFECT_LABEL_EXPLORATORY}
        ]

        variant_name = (get_field(issue, "variant") if variant_field_available else "") or "N/A"
        defect_domain_name = (get_field(issue, "domain") if domain_field_available else "") or "N/A"
        assigned_ecu = issue.get("fields", {}).get(DEFECT_ASSIGNED_ECU_FIELD) if ecu_field_available else ""
        if isinstance(assigned_ecu, list):
            assigned_ecu = ", ".join(
                str(v.get("value") or v.get("name") or v) if isinstance(v, dict) else str(v)
                for v in assigned_ecu
            )
        elif isinstance(assigned_ecu, dict):
            assigned_ecu = assigned_ecu.get("value") or assigned_ecu.get("name") or ""

        raw_sw_ver = fields.get(CUSTOM_FIELDS["found_in_sw_version"], [])
        if isinstance(raw_sw_ver, list):
            sw_version_names = [
                str(v.get("name") or v.get("value") or v) if isinstance(v, dict) else str(v)
                for v in raw_sw_ver if v
            ]
        elif isinstance(raw_sw_ver, dict):
            sw_version_names = [str(raw_sw_ver.get("name") or raw_sw_ver.get("value") or "")]
        elif raw_sw_ver:
            sw_version_names = [str(raw_sw_ver)]
        else:
            sw_version_names = []
        found_in_sw = ", ".join(v for v in sw_version_names if v) or "N/A"

        rows.append(
            {
                "key": key,
                "project": ((fields.get("project") or {}).get("key", "") or key.split("-", 1)[0]).strip(),
                "summary": fields.get("summary", "") or "",
                "issue_type": (fields.get("issuetype") or {}).get("name", ""),
                "status": (fields.get("status") or {}).get("name", ""),
                "priority": (fields.get("priority") or {}).get("name", ""),
                "reporter": (fields.get("reporter") or {}).get("displayName")
                or (fields.get("reporter") or {}).get("name")
                or "Unknown",
                "created": str(fields.get("created", "")) or "N/A",
                "labels": ", ".join(labels),
                "project_specific_label": ", ".join(project_specific_labels) if project_specific_labels else "N/A",
                "assigned_ecu": str(assigned_ecu or "N/A"),
                "found_in_version": found_in_sw,
                "variant": variant_name,
                "domain": defect_domain_name,
                "is_exploratory": is_exploratory,
            }
        )

    # De-duplicate by key while preserving order.
    unique = {}
    for row in rows:
        if row["key"] and row["key"] not in unique:
            unique[row["key"]] = row

    defect_rows = list(unique.values())

    # Occurrence: count how many defects share the same summary text.
    summary_count = {}
    for row in defect_rows:
        normalized = " ".join(str(row.get("summary", "")).strip().lower().split())
        if normalized:
            summary_count[normalized] = summary_count.get(normalized, 0) + 1
    for row in defect_rows:
        normalized = " ".join(str(row.get("summary", "")).strip().lower().split())
        row["occurrence"] = summary_count.get(normalized, 1)

    exploratory_count = sum(1 for r in defect_rows if r["is_exploratory"])

    closure_projects_clean = [p.strip() for p in (closure_projects or defect_projects or DEFECT_PROJECTS) if p and p.strip()]
    if not closure_projects_clean:
        closure_projects_clean = ["HU22DM", "IDCEVODEV"]

    closure_team_value = (closure_team or defect_domain or "").strip()
    closure_selected_labels = defect_labels_for_team(closure_team_value)
    if closure_team_value and closure_team_value.casefold() not in {"all", "none"} and not closure_selected_labels:
        print(f"  Note: no closure label mapping is configured yet for: {closure_team_value}")
    unmapped_closure_domains = unmapped_domain_tokens(closure_team_value)
    if unmapped_closure_domains:
        print(f"  Note: these requested closure domain(s) have no label mapping and contributed 0 records: {', '.join(unmapped_closure_domains)}")

    resolved_start = (resolution_start_date or "").strip() or start_date
    resolved_end = (resolution_end_date or "").strip() or end_date
    try:
        resolved_start_dt = datetime.strptime(resolved_start, "%Y-%m-%d")
        resolved_end_dt = datetime.strptime(resolved_end, "%Y-%m-%d")
    except ValueError:
        print("  Note: Invalid resolution date format supplied. Falling back to report created-date range.")
        resolved_start = start_date
        resolved_end = end_date
        resolved_start_dt = datetime.strptime(resolved_start, "%Y-%m-%d")
        resolved_end_dt = datetime.strptime(resolved_end, "%Y-%m-%d")

    if resolved_end_dt < resolved_start_dt:
        print("  Note: Resolution end date is before start date. Swapping resolution dates.")
        resolved_start_dt, resolved_end_dt = resolved_end_dt, resolved_start_dt
        resolved_start = resolved_start_dt.strftime("%Y-%m-%d")
        resolved_end = resolved_end_dt.strftime("%Y-%m-%d")

    resolved_period_days = (resolved_end_dt - resolved_start_dt).days + 1
    prev_resolved_start = (resolved_start_dt - timedelta(days=resolved_period_days)).strftime("%Y-%m-%d")
    prev_resolved_end = (resolved_start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    resolution_date_filter = f'resolutiondate >= "{resolved_start}" AND resolutiondate <= "{resolved_end}"'
    previous_resolution_date_filter = (
        f'resolutiondate >= "{prev_resolved_start}" AND resolutiondate <= "{prev_resolved_end}"'
    )

    closure_projects_csv = ", ".join(closure_projects_clean)
    closure_request_failed = False

    closure_fields = ["key", "project"]
    closure_fields.append("created")
    if variant_field_available:
        closure_fields.append(CUSTOM_FIELDS["variant"])
    if ecu_field_available:
        closure_fields.append(DEFECT_ASSIGNED_ECU_FIELD)
    closure_fields.extend(["summary", "comment", "reporter", "status", "resolution", "resolutiondate", "issuelinks"])
    closure_fields.append(CUSTOM_FIELDS["found_in_sw_version"])
    duplicate_summary_cache: dict[str, dict] = {}
    closure_issue_cache: dict[str, list[dict]] = {}

    def build_closure_detail_rows(issues: list[dict], use_transformers: bool = False) -> list[dict]:
        detail_rows = []
        for issue in issues:
            fields = issue.get("fields", {})
            key = str(issue.get("key", "")).strip()
            if not key:
                continue
            comment_texts = _recent_comment_texts(issue, 5)
            comments_summary = (
                summarize_comments_with_transformers(comment_texts)
                if use_transformers
                else summarize_recent_comments(comment_texts)
            )
            assigned_ecu_value = _normalize_issue_value(fields.get(DEFECT_ASSIGNED_ECU_FIELD, "")) if ecu_field_available else ""
            found_in_sw_value = _normalize_issue_value(fields.get(CUSTOM_FIELDS["found_in_sw_version"], ""))
            created_dt = parse_created_date(str(fields.get("created", "") or ""))
            resolved_dt = parse_created_date(str(fields.get("resolutiondate", "") or ""))
            dwell_days = (resolved_dt - created_dt).days if created_dt and resolved_dt else None
            structured_duplicate_ids = _extract_duplicate_ids_from_issuelinks(issue)
            comment_duplicate_ids = _extract_duplicate_defect_ids(comment_texts)
            duplicate_ids = structured_duplicate_ids + [
                defect_id for defect_id in comment_duplicate_ids if defect_id not in structured_duplicate_ids
            ]
            detail_rows.append(
                {
                    "key": key,
                    "project": str((fields.get("project") or {}).get("key", "") or key.split("-", 1)[0]).strip(),
                    "summary": str(fields.get("summary", "") or "").strip(),
                    "reporter": (fields.get("reporter") or {}).get("displayName")
                    or (fields.get("reporter") or {}).get("name")
                    or "Unknown",
                    "created": str(fields.get("created", "") or "") or "N/A",
                    "resolved": str(fields.get("resolutiondate", "") or "") or "N/A",
                    "resolution": str((fields.get("resolution") or {}).get("name", "") or "").strip() or "N/A",
                    "dwell_days": dwell_days,
                    "duplicate_ids": duplicate_ids,
                    "assigned_ecu": assigned_ecu_value or "N/A",
                    "found_in_sw_version": found_in_sw_value or "N/A",
                    "variant": _normalize_issue_value(fields.get(CUSTOM_FIELDS["variant"], "")) if variant_field_available else "N/A",
                    "comment_summary": comments_summary,
                    "comment_texts": comment_texts,
                }
            )
        referenced_ids = []
        for detail in detail_rows:
            for defect_id in detail.get("duplicate_ids", []):
                if defect_id not in referenced_ids and defect_id not in duplicate_summary_cache:
                    referenced_ids.append(defect_id)
        if referenced_ids:
            issue_keys = ", ".join(f'"{defect_id}"' for defect_id in referenced_ids)
            try:
                duplicate_issues = fetch_all(
                    f"issuekey in ({issue_keys})",
                    ["summary", "created", CUSTOM_FIELDS["found_in_sw_version"]],
                    log_http_error=False,
                )
                for duplicate_issue in duplicate_issues:
                    duplicate_key = str(duplicate_issue.get("key", "")).strip()
                    duplicate_fields = duplicate_issue.get("fields", {}) or {}
                    duplicate_summary = str(duplicate_fields.get("summary", "") or "").strip()
                    if duplicate_key:
                        duplicate_summary_cache[duplicate_key] = {
                            "summary": duplicate_summary or "Summary unavailable",
                            "created": str(duplicate_fields.get("created", "") or "") or "N/A",
                            "found_in_sw_version": _normalize_issue_value(duplicate_fields.get(CUSTOM_FIELDS["found_in_sw_version"], "")) or "N/A",
                        }
            except (HTTPError, requests.RequestException) as exc:
                print(f"  Note: Could not fetch duplicate defect summaries: {exc}")
            for defect_id in referenced_ids:
                duplicate_summary_cache.setdefault(defect_id, {"summary": "Summary unavailable", "created": "N/A", "found_in_sw_version": "N/A"})
        for detail in detail_rows:
            detail["duplicate_references"] = [
                {"key": defect_id, **duplicate_summary_cache.get(defect_id, {"summary": "Summary unavailable", "created": "N/A", "found_in_sw_version": "N/A"})}
                for defect_id in detail.get("duplicate_ids", [])
            ]
        return detail_rows

    def closure_bucket_matches(issue: dict, bucket_key: str) -> bool:
        fields = issue.get("fields", {}) if isinstance(issue, dict) else {}
        status = str((fields.get("status") or {}).get("name", "") or "").strip().casefold()
        resolution = str((fields.get("resolution") or {}).get("name", "") or "").strip().casefold()
        if bucket_key == "closed_total":
            return status == "closed"
        if bucket_key == "closed_duplicate":
            return status == "closed" and resolution == "duplicate"
        if bucket_key == "closed_rejected_deficient":
            return status == "closed" and resolution in {"rejected", "deficient"}
        if bucket_key == "closed_done":
            return status == "closed" and resolution == "done"
        if bucket_key == "closed_wont_do":
            return status == "closed" and resolution == "won't do"
        if bucket_key == "resolved_status":
            return status == "resolved" and resolution in {"unresolved", "done"}
        if bucket_key == "integrated_status":
            return status == "integrated" and resolution in {"unresolved", "done"}
        if bucket_key == "closed_cannot_reproduce":
            return status == "closed" and resolution == "cannot reproduce"
        return False

    def fetch_closure_counts(bucket_key: str, date_filter_expr: str, use_transformers: bool = False) -> dict:
        nonlocal scope_restrictions_seen, closure_request_failed
        empty_result = {
            "counts": {project: 0 for project in closure_projects_clean},
            "keys": {project: [] for project in closure_projects_clean},
            "product_counts": {},
            "details": [],
        }
        if closure_request_failed:
            return empty_result

        closure_label_clause = build_defect_label_clause(closure_selected_labels or ("__UNMAPPED_DOMAIN__",))
        base = (
            f'project in ({closure_projects_csv}) AND issuetype in ({issue_types_csv}) '
            f'AND ({closure_label_clause}) AND {date_filter_expr}'
        )
        filtered_jql = base
        if closure_extra_filter_clauses:
            filtered_jql += " AND " + " AND ".join(closure_extra_filter_clauses)
        cache_key = date_filter_expr

        if cache_key not in closure_issue_cache:
            try:
                issues = fetch_all(filtered_jql, closure_fields, log_http_error=False)
            except HTTPError:
                scope_restrictions_seen = True
                try:
                    issues = fetch_all(base, closure_fields, log_http_error=False)
                except requests.RequestException as exc:
                    closure_request_failed = True
                    print(f"  Warning: Closure metrics unavailable after Jira connection error: {exc}")
                    return empty_result
            except requests.RequestException as exc:
                closure_request_failed = True
                print(f"  Warning: Closure metrics unavailable after Jira connection error: {exc}")
                return empty_result
            closure_issue_cache[cache_key] = issues
        issues = [issue for issue in closure_issue_cache[cache_key] if closure_bucket_matches(issue, bucket_key)]
        counts = count_issues_by_project(issues, closure_projects_clean)
        keys = issue_keys_by_project(issues, closure_projects_clean)
        product_counts = count_issues_by_product_scope(issues, variant_field_available, ecu_field_available)
        detail_rows = build_closure_detail_rows(issues, use_transformers=use_transformers)
        return {
            "counts": counts,
            "keys": keys,
            "product_counts": product_counts,
            "details": detail_rows,
        }

    closure_buckets = [
        {
            "key": "closed_total",
            "label": "Closed (Status = Closed)",
            "clause": 'status = Closed',
        },
        {
            "key": "closed_duplicate",
            "label": "Closed as Duplicate",
            "clause": 'status = Closed AND resolution = Duplicate',
        },
        {
            "key": "closed_rejected_deficient",
            "label": "Closed as Rejected/Deficient",
            "clause": 'status = Closed AND resolution in (Rejected, Deficient)',
        },
        {
            "key": "closed_done",
            "label": "Closed as Done",
            "clause": 'status = Closed AND resolution = "Done"',
        },
        {
            "key": "closed_wont_do",
            "label": "Closed as Won't Do",
            "clause": 'status = Closed AND resolution = "Won\'t Do"',
        },
        {
            "key": "resolved_status",
            "label": "Resolved (Done/Unresolved)",
            "clause": 'status = Resolved AND resolution in (Unresolved, Done)',
        },
        {
            "key": "integrated_status",
            "label": "Integrated (Done/Unresolved)",
            "clause": 'status = Integrated AND resolution in (Unresolved, Done)',
        },
        {
            "key": "closed_cannot_reproduce",
            "label": "Closed as Cannot Reproduce",
            "clause": 'status = Closed AND resolution = "Cannot Reproduce"',
        },
    ]

    closure_rows = []
    print("\nFetching defect closure metrics...")
    for bucket in closure_buckets:
        use_transformers = bucket["key"] in {"closed_rejected_deficient", "closed_duplicate"}
        result = fetch_closure_counts(bucket["key"], resolution_date_filter, use_transformers=use_transformers)
        prev_result = fetch_closure_counts(bucket["key"], previous_resolution_date_filter, use_transformers=False)
        counts = result.get("counts", {})
        keys = result.get("keys", {})
        product_counts = result.get("product_counts", {})
        prev_counts = prev_result.get("counts", {})
        closure_rows.append(
            {
                "key": bucket["key"],
                "label": bucket["label"],
                "counts": counts,
                "previous_counts": prev_counts,
                "product_counts": product_counts,
                "details": result.get("details", []),
                "defect_keys": keys,
                "total": sum(counts.values()),
                "previous_total": sum(prev_counts.values()),
            }
        )

    print(f"  Found {len(defect_rows)} defects for selected domain(s): {selected_domain_display}")
    print(f"  Found {exploratory_count} ET defects matching LTTS_SV_ET")
    previous_week_keys = {issue.get("key", "") for issue in previous_week_issues if issue.get("key")}
    previous_week_keys.update(issue.get("key", "") for issue in previous_exploratory_issues if issue.get("key"))
    print(f"  Previous equivalent period defects: {len(previous_week_keys)}")

    return {
        "rows": defect_rows,
        "telematics_count": len(defect_rows),
        "exploratory_count": exploratory_count,
        "previous_week_count": len(previous_week_keys),
        "requested_domain": (defect_domain or "").strip(),
        "unmapped_domains": sorted(set(unmapped_defect_domains) | set(unmapped_closure_domains)),
        "closure_metrics": {
            "projects": closure_projects_clean,
            "team_scope": closure_team_value or "All",
            "start_date": resolved_start,
            "end_date": resolved_end,
            "previous_start_date": prev_resolved_start,
            "previous_end_date": prev_resolved_end,
            "rows": closure_rows,
        },
    }


def status_badge(status: str) -> str:
    s = status.lower()
    if s == "closed":
        return f'<span class="badge b-closed">Closed</span>'
    if "progress" in s:
        return f'<span class="badge b-progress">In Progress</span>'
    if s == "open":
        return f'<span class="badge b-open">Open</span>'
    return f'<span class="badge b-other">{status}</span>'


def adhoc_status_badge(status: str) -> str:
    """Colour-coded badge for the broader set of states an Ad-Hoc ticket can be in."""
    label = str(status or "").strip() or "Unknown"
    s = label.casefold()
    if s in {"rejected", "cancelled", "canceled", "deficient", "cannot reproduce"}:
        css_class = "b-rejected"
    elif s in {"closed", "done", "complete", "completed"}:
        css_class = "b-closed"
    elif s == "resolved":
        css_class = "b-resolved"
    elif s == "integrated":
        css_class = "b-integrated"
    elif "progress" in s:
        css_class = "b-progress"
    elif s == "reopened":
        css_class = "b-reopened"
    elif s in {"open", "to do", "todo"}:
        css_class = "b-open"
    elif s == "new":
        css_class = "b-new"
    else:
        css_class = "b-other"
    return f'<span class="badge {css_class}">{escape(label)}</span>'


def execution_table(cycles: list) -> str:
    if not cycles:
        return '<p class="empty">No executions found.</p>'

    rows = ""
    for c in cycles:
        pass_val    = int(c["pass"])    if str(c["pass"]).isdigit()    else 0
        failed_val  = int(c["failed"])  if str(c["failed"]).isdigit()  else 0
        aborted_val = int(c["aborted"]) if str(c["aborted"]).isdigit() else 0
        total = pass_val + failed_val + aborted_val + \
                (int(c["executing"]) if str(c["executing"]).isdigit() else 0) + \
                (int(c["todo"])      if str(c["todo"]).isdigit()      else 0)

        rows += f"""
        <tr>
          <td><a href="{JIRA_BASE_URL}/browse/{c['key']}" target="_blank">{c['key']}</a></td>
          <td>{c['summary']}</td>
          <td>{status_badge(c['status'])}</td>
          <td>{c['sop_pu']}</td>
          <td>{c['variant']}</td>
          <td>{c['i_step']}</td>
          <td class="num-pass">{c['pass']}</td>
          <td class="num-fail">{c['failed']}</td>
          <td class="num-abort">{c['aborted']}</td>
          <td class="num-exec">{c['executing']}</td>
          <td class="num-todo">{c['todo']}</td>
                      <td><b class="num-total">{total}</b></td>
                      <td>{escape(str(c.get("overall_comment", "No overall comment available.") or "No overall comment available."))}</td>
        </tr>"""
    return f"""
    <table class="exec-table">
      <thead><tr>
        <th>Key</th><th>Summary</th><th>Status</th>
        <th>SOP/PU</th><th>Variant</th><th>I-Step</th>
        <th class="num-pass">Pass</th>
        <th class="num-fail">Failed</th>
        <th class="num-abort">Aborted</th>
        <th class="num-exec">Executing</th>
        <th class="num-todo">Todo</th>
        <th>Total</th>
        <th>Overall Test Execution Comment</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def to_int(value) -> int:
    # Jira status counters sometimes arrive as negative, float-like, or
    # whitespace-padded strings; str.isdigit() rejected all of those and
    # silently zeroed out valid counts.
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        pass
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def executed_tests_count(cycles: list) -> int:
    """Executed tests = Pass + Failed + Aborted + Executing (Todo excluded)."""
    total = 0
    for c in cycles:
        total += to_int(c.get("pass", 0))
        total += to_int(c.get("failed", 0))
        total += to_int(c.get("aborted", 0))
        total += to_int(c.get("executing", 0))
    return total


def aggregate_status_totals(grouped: dict) -> dict:
    """Aggregate pass/failed/aborted/executing/todo counts across all grouped cycles."""
    totals = {"pass": 0, "failed": 0, "aborted": 0, "executing": 0, "todo": 0}
    for _, types in grouped.items():
        for cycle_type in ("Automation", "Manual", "Other"):
            for c in types.get(cycle_type, []):
                totals["pass"] += to_int(c.get("pass", 0))
                totals["failed"] += to_int(c.get("failed", 0))
                totals["aborted"] += to_int(c.get("aborted", 0))
                totals["executing"] += to_int(c.get("executing", 0))
                totals["todo"] += to_int(c.get("todo", 0))
    return totals


def collect_failure_abort_rows(grouped: dict) -> list[dict]:
    """Collect rows with failures or aborted tests for detailed visibility."""
    rows = []
    for _, types in grouped.items():
        for cycle_type in ("Automation", "Manual", "Other"):
            for c in types.get(cycle_type, []):
                failed = to_int(c.get("failed", 0))
                aborted = to_int(c.get("aborted", 0))
                if failed == 0 and aborted == 0:
                    continue
                rows.append(
                    {
                        "key": c.get("key", ""),
                        "cycle_type": cycle_type,
                        "failed": failed,
                        "defects": c.get("defects", []) or [],
                        "aborted": aborted,
                        "tester_comment": c.get("tester_comment", "") if aborted > 0 else "",
                    }
                )
    return rows


def failure_abort_details_html(grouped: dict) -> str:
    rows = collect_failure_abort_rows(grouped)
    if not rows:
        return '<p class="empty">No failed or aborted execution details for the selected filters.</p>'

    body = ""
    for r in rows:
        defects = r["defects"]
        defect_html = ", ".join(
            f'<a href="{JIRA_BASE_URL}/browse/{d}" target="_blank">{d}</a>' for d in defects
        ) if defects else "No linked defect"
        defect_label = "Failed defect(s):" if r["failed"] > 0 else "Linked defect(s):"
        defect_html = f"<b>{defect_label}</b> {defect_html}"
        body += f"""
        <tr>
          <td><a href="{JIRA_BASE_URL}/browse/{r['key']}" target="_blank">{r['key']}</a></td>
          <td>{r['cycle_type']}</td>
          <td class="num-fail">{r['failed']}</td>
          <td>{defect_html}</td>
          <td class="num-abort">{r['aborted']}</td>
        </tr>"""

    return f"""
    <table class="exec-table">
      <thead><tr>
        <th>Execution Key</th>
        <th>Cycle Type</th>
        <th class="num-fail">Failed</th>
        <th>Linked Defects</th>
        <th class="num-abort">Aborted</th>
      </tr></thead>
      <tbody>{body}</tbody>
    </table>"""


def overall_execution_comments_html(grouped: dict) -> str:
    rows = []
    for _, types in grouped.items():
        for cycle_type in ("Automation", "Manual", "Other"):
            for cycle in types.get(cycle_type, []):
                comment = str(cycle.get("overall_comment", "") or "").strip()
                if not comment or comment == "No recent comments available.":
                    continue
                rows.append(
                    f"""
                    <tr>
                        <td><a href="{JIRA_BASE_URL}/browse/{escape(str(cycle.get('key', '')))}" target="_blank">{escape(str(cycle.get('key', '')))}</a></td>
                        <td>{escape(cycle_type)}</td>
                        <td>{escape(str(cycle.get('summary', '') or ''))}</td>
                        <td>{escape(comment)}</td>
                    </tr>
                    """
                )
    if not rows:
        return '<p class="empty">No overall Test Execution comments were available for the selected period.</p>'
    return f"""
    <table>
        <thead><tr><th>Execution Key</th><th>Cycle Type</th><th>Summary</th><th>Overall Test Execution Comment</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
    </table>
    """


def domain_summary_cards(grouped: dict) -> str:
    """Top-level summary cards — one per domain."""
    cards = ""
    for domain, types in sorted(grouped.items()):
        auto_count   = len(types["Automation"])
        manual_count = len(types["Manual"])
        total        = auto_count + manual_count + len(types["Other"])
        cards += f"""
        <div class="sum-card">
          <div class="sum-domain">{domain}</div>
          <div class="sum-row"><span class="dot dot-auto"></span>Automation<span class="sum-n">{auto_count}</span></div>
          <div class="sum-row"><span class="dot dot-manual"></span>Manual<span class="sum-n">{manual_count}</span></div>
          <div class="sum-total">Total cycles: <b>{total}</b></div>
        </div>"""
    return cards


SEVERITY_ORDER = ["Critical", "High", "Medium", "Low"]


def classify_defect_severity(priority: str) -> str:
        p = (priority or "").strip().lower()
        if "critical" in p or "blocker" in p:
                return "Critical"
        if "high" in p:
                return "High"
        if "medium" in p or "major" in p:
                return "Medium"
        if "low" in p or "minor" in p or "trivial" in p:
                return "Low"
        return "Medium"


def is_closed_defect_status(status: str) -> bool:
        """Per BMW quality doc: a Resolved defect only has a proposed fix, not a
        verified one, so only Closed counts as truly done - everything else stays open."""
        s = (status or "").strip().lower()
        return s == "closed"


def parse_created_date(value: str) -> datetime | None:
        raw = (value or "").strip()
        if not raw:
                return None
        token = raw[:10]
        try:
                return datetime.strptime(token, "%Y-%m-%d")
        except ValueError:
                return None


def severity_badge(severity: str) -> str:
        label = str(severity or "Medium").strip() or "Medium"
        key = label.lower()
        return f'<span class="sev-badge sev-{key}">{escape(label)}</span>'


PRODUCT_CLOSURE_RULES = [
    {
        "label": "IDC23",
        "projects": {"HU22DM"},
        "tokens": {"SV_MID", "SV_MINI", "SV_HIGH"},
        "scope_label": "HU22DM | SV_MID / SV_MINI / SV_HIGH",
    },
    {
        "label": "IDCEVO",
        "projects": {"IDCEVODEV"},
        "tokens": {"IDCEVO-21", "IDCEVO-25"},
        "scope_label": "IDCEVODEV | IDCEVO-21 / IDCEVO-25",
    },
    {
        "label": "CDE/RSE",
        "projects": {"IDCEVODEV"},
        "tokens": {"CDE", "CDE-01", "RSE26", "RSE_EXBX-02"},
        "scope_label": "IDCEVODEV | CDE / RSE26",
    },
]

SIMILIAIZE_LABEL = "LTTS_DBCU"
SIMILIAIZE_DEFECT_RULES = [
    {
        "label": "IDC23",
        "projects": {"HU22DM"},
        "variants": set(),
    },
    {
        "label": "IDCEVO",
        "projects": {"ICONSD", "IDCEVODEV"},
        "variants": {"IDCEVO-21", "IDCEVO-25"},
    },
    {
        "label": "CDE/RSE",
        "projects": {"IDCEVODEV"},
        "variants": {"CDE", "RSE26"},
    },
]

ADHOC_CATEGORY_TMS_ACCOUNT = "TMS Account Requests"
ADHOC_CATEGORY_DIGITAL_PREMIUM = "Digital Premium Requests"
ADHOC_CATEGORY_TELEMATICS_SUPPORT = "Telematics Support Requests"

ADHOC_LABEL_ACCOUNT = "CD_Account"
ADHOC_LABEL_DIGITAL_PREMIUM = "Digital_Premium"
ADHOC_LABEL_TELEMATICS_SUPPORT = "Telematics_Support"

ADHOC_TRACKED_LABELS = (
    ADHOC_LABEL_ACCOUNT,
    ADHOC_LABEL_DIGITAL_PREMIUM,
    ADHOC_LABEL_TELEMATICS_SUPPORT,
)


def classify_adhoc_product(summary: str) -> str:
    text = str(summary or "").upper()
    if "IDC23" in text:
        return "IDC23"
    if "IDCEVO" in text:
        return "IDCEVO"
    return "Others"


def classify_adhoc_category(labels: list[str], summary: str) -> str:
    normalized = {str(label or "").strip() for label in (labels or [])}
    summary_text = str(summary or "").casefold()

    if ADHOC_LABEL_ACCOUNT in normalized:
        return ADHOC_CATEGORY_TMS_ACCOUNT

    # Requirement note: Telematics support may come with Digital_Premium label.
    # Use summary keyword hints to split support vs premium when same label is used.
    if ADHOC_LABEL_DIGITAL_PREMIUM in normalized:
        if "support" in summary_text or "telematics support" in summary_text:
            return ADHOC_CATEGORY_TELEMATICS_SUPPORT
        return ADHOC_CATEGORY_DIGITAL_PREMIUM

    # Backward-compatible path if dedicated support label exists in Jira.
    if ADHOC_LABEL_TELEMATICS_SUPPORT in normalized:
        return ADHOC_CATEGORY_TELEMATICS_SUPPORT

    return "Others"


def _normalize_person_name(raw_value) -> str:
    if isinstance(raw_value, dict):
        return (
            str(raw_value.get("displayName") or "").strip()
            or str(raw_value.get("name") or "").strip()
            or str(raw_value.get("emailAddress") or "").strip()
        )
    return str(raw_value or "").strip()


def _jira_iso_date(value: str) -> str:
    raw = str(value or "").strip()
    return raw[:10] if raw else "N/A"


def fetch_telematics_adhoc_effort(start_date: str, end_date: str, adhoc_domains: list[str] | None = None) -> dict:
    """Fetch and aggregate supported Telematics ad-hoc Task Tickets from LTTSTM."""
    selected_domains = {str(domain or "").strip().casefold() for domain in (adhoc_domains or []) if str(domain or "").strip()}
    if selected_domains and "all" not in selected_domains and "telematics" not in selected_domains:
        return {}
    labels_jql = " OR ".join(f'labels = "{label}"' for label in ADHOC_TRACKED_LABELS)
    primary_jql = (
        'project = LTTSTM AND issuetype = "Task Ticket" '
        f'AND resolutiondate >= "{start_date}" AND resolutiondate <= "{end_date}" '
        f"AND ({labels_jql})"
    )
    fallback_jqls = [
        (
            'project = LTTSTM AND issuetype in ("Task Ticket", "Task") '
            f'AND resolutiondate >= "{start_date}" AND resolutiondate <= "{end_date}" '
            f"AND ({labels_jql})"
        ),
        (
            'project = LTTSTM '
            f'AND resolutiondate >= "{start_date}" AND resolutiondate <= "{end_date}" '
            f"AND ({labels_jql})"
        ),
    ]
    fields = [
        "summary",
        "assignee",
        "reporter",
        "labels",
        "created",
        "resolutiondate",
        "timespent",
        "status",
    ]

    print("\nFetching Telematics ad-hoc task tickets...")
    print(f"  JQL: {primary_jql}")
    last_jql = primary_jql
    try:
        issues = fetch_all(primary_jql, fields, log_http_error=False)
    except HTTPError:
        issues = []
        for idx, fallback_jql in enumerate(fallback_jqls, start=1):
            print(f"  Fallback JQL {idx}: {fallback_jql}")
            last_jql = fallback_jql
            try:
                issues = fetch_all(fallback_jql, fields, log_http_error=False)
                break
            except HTTPError:
                issues = []
                continue

    # Jira search has shown transient eventual-consistency gaps where the exact
    # same query returns different result counts moments apart, especially when
    # this fetch runs concurrently with the heavier test/defect fetches; retry
    # the query that actually succeeded, backing off longer before giving up.
    if not issues:
        for attempt, delay in enumerate((3, 6, 10, 15, 20), start=1):
            time.sleep(delay)
            try:
                retry_issues = fetch_all(last_jql, fields, log_http_error=False)
            except HTTPError:
                retry_issues = []
            if retry_issues:
                issues = retry_issues
                print(f"  Retry {attempt} recovered {len(retry_issues)} issue(s) for a query that initially returned none.")
                break

    rows = []
    category_counts: Counter = Counter()
    product_counts: Counter = Counter()
    assignee_counts: Counter = Counter()
    assignee_category_counts: dict[str, Counter] = {}
    effort_by_product: dict[str, float] = {}
    effort_by_assignee: dict[str, float] = {}
    effort_by_category: dict[str, float] = {}
    category_counts_by_product: dict[str, Counter] = {"IDC23": Counter(), "IDCEVO": Counter(), "Others": Counter()}
    product_resource_sets: dict[str, set[str]] = {"IDC23": set(), "IDCEVO": set(), "Others": set()}
    assignee_product_counts: dict[str, Counter] = {"IDC23": Counter(), "IDCEVO": Counter(), "Others": Counter()}
    assignee_product_effort: dict[str, dict[str, float]] = {"IDC23": {}, "IDCEVO": {}, "Others": {}}
    weekly_metrics: dict[tuple[int, int], dict[str, float | int]] = {}

    for issue in issues:
        issue_fields = issue.get("fields", {})
        key = str(issue.get("key", "")).strip()
        summary = str(issue_fields.get("summary") or "").strip()
        labels = issue_fields.get("labels", []) or []
        assignee = _normalize_person_name(issue_fields.get("assignee")) or "Unassigned"
        reporter = _normalize_person_name(issue_fields.get("reporter")) or "Unknown"
        product = classify_adhoc_product(summary)
        category = classify_adhoc_category(labels, summary)
        created_date = _jira_iso_date(issue_fields.get("created", ""))
        resolved_date = _jira_iso_date(issue_fields.get("resolutiondate", ""))
        status = str((issue_fields.get("status") or {}).get("name") or "").strip() or "Unknown"
        timespent_hours = round(float(issue_fields.get("timespent") or 0) / 3600.0, 2)
        resolved_dt = parse_created_date(resolved_date)

        rows.append(
            {
                "key": key,
                "summary": summary,
                "assignee": assignee,
                "reporter": reporter,
                "labels": ", ".join(str(label) for label in labels) if labels else "N/A",
                "category": category,
                "product": product,
                "created": created_date,
                "resolved": resolved_date,
                "effort_hours": timespent_hours,
                "status": status,
            }
        )

        category_counts[category] += 1
        product_counts[product] += 1
        assignee_counts[assignee] += 1
        assignee_category_counts.setdefault(assignee, Counter())[category] += 1
        effort_by_product[product] = effort_by_product.get(product, 0.0) + timespent_hours
        effort_by_assignee[assignee] = effort_by_assignee.get(assignee, 0.0) + timespent_hours
        effort_by_category[category] = effort_by_category.get(category, 0.0) + timespent_hours
        category_counts_by_product.setdefault(product, Counter())[category] += 1
        product_resource_sets.setdefault(product, set()).add(assignee)
        assignee_product_counts.setdefault(product, Counter())[assignee] += 1
        product_effort_map = assignee_product_effort.setdefault(product, {})
        product_effort_map[assignee] = round(float(product_effort_map.get(assignee, 0.0) or 0.0) + timespent_hours, 2)
        if resolved_dt is not None:
            iso = resolved_dt.isocalendar()
            week_key = (iso.year, iso.week)
            week_bucket = weekly_metrics.setdefault(
                week_key,
                {
                    "requests": 0,
                    "effort_hours": 0.0,
                    "idc23_effort": 0.0,
                    "idcevo_effort": 0.0,
                    "others_effort": 0.0,
                },
            )
            week_bucket["requests"] = int(week_bucket.get("requests", 0) or 0) + 1
            week_bucket["effort_hours"] = float(week_bucket.get("effort_hours", 0.0) or 0.0) + timespent_hours
            if product == "IDC23":
                week_bucket["idc23_effort"] = float(week_bucket.get("idc23_effort", 0.0) or 0.0) + timespent_hours
            elif product == "IDCEVO":
                week_bucket["idcevo_effort"] = float(week_bucket.get("idcevo_effort", 0.0) or 0.0) + timespent_hours
            else:
                week_bucket["others_effort"] = float(week_bucket.get("others_effort", 0.0) or 0.0) + timespent_hours

    rows.sort(key=lambda item: item.get("created", ""), reverse=True)
    total_requests = len(rows)
    total_effort_hours = round(sum(item.get("effort_hours", 0.0) for item in rows), 2)
    avg_effort_per_request = round((total_effort_hours / total_requests), 2) if total_requests else 0.0
    resource_pool = {name for name in assignee_counts if name and name != "Unassigned"}
    total_resources = len(resource_pool)
    idc23_effort = round(float(effort_by_product.get("IDC23", 0.0) or 0.0), 2)
    idcevo_effort = round(float(effort_by_product.get("IDCEVO", 0.0) or 0.0), 2)

    resource_utilization = []
    for product in ("IDC23", "IDCEVO", "Others"):
        request_count = int(product_counts.get(product, 0) or 0)
        effort_hours = round(float(effort_by_product.get(product, 0.0) or 0.0), 2)
        resource_count = len({name for name in product_resource_sets.get(product, set()) if name != "Unassigned"})
        avg_effort_per_resource = round(effort_hours / resource_count, 2) if resource_count else 0.0
        resource_utilization.append(
            {
                "product": product,
                "request_count": request_count,
                "effort_hours": effort_hours,
                "resource_count": resource_count,
                "avg_effort_per_resource": avg_effort_per_resource,
            }
        )

    assignee_per_product = []
    for product in ("IDC23", "IDCEVO", "Others"):
        assignee_items = []
        for assignee, count in sorted(
            assignee_product_counts.get(product, Counter()).items(),
            key=lambda item: (-item[1], item[0]),
        ):
            assignee_items.append(
                {
                    "assignee": assignee,
                    "request_count": int(count or 0),
                    "effort_hours": round(float(assignee_product_effort.get(product, {}).get(assignee, 0.0) or 0.0), 2),
                }
            )
        assignee_per_product.append({"product": product, "assignees": assignee_items})

    week_wise_calculation = []
    for year_week in sorted(weekly_metrics.keys()):
        year, week = year_week
        data = weekly_metrics[year_week]
        week_wise_calculation.append(
            {
                "week": f"{year}-CW{int(week):02d}",
                "requests": int(data.get("requests", 0) or 0),
                "effort_hours": round(float(data.get("effort_hours", 0.0) or 0.0), 2),
                "idc23_effort": round(float(data.get("idc23_effort", 0.0) or 0.0), 2),
                "idcevo_effort": round(float(data.get("idcevo_effort", 0.0) or 0.0), 2),
                "others_effort": round(float(data.get("others_effort", 0.0) or 0.0), 2),
            }
        )

    return {
        "rows": rows,
        "total_requests": total_requests,
        "total_effort_hours": total_effort_hours,
        "avg_effort_per_request": avg_effort_per_request,
        "category_distribution": dict(category_counts),
        "product_distribution": dict(product_counts),
        "assignee_distribution": dict(assignee_counts),
        "assignee_category_counts": {name: dict(counts) for name, counts in assignee_category_counts.items()},
        "effort_by_product": {k: round(v, 2) for k, v in effort_by_product.items()},
        "effort_by_assignee": {k: round(v, 2) for k, v in effort_by_assignee.items()},
        "effort_by_category": {k: round(v, 2) for k, v in effort_by_category.items()},
        "category_counts_by_product": {product: dict(counts) for product, counts in category_counts_by_product.items()},
        "product_resource_utilization": resource_utilization,
        "assignee_per_product": assignee_per_product,
        "week_wise_calculation": week_wise_calculation,
        "total_resources": total_resources,
        "idc23_effort": idc23_effort,
        "idcevo_effort": idcevo_effort,
    }


# ---------------------------------------------------------------
# Communication / Wireless Services ad-hoc effort (two Jira patterns, no shared
# aggregation field - hours must be summed from subtasks directly).
# ---------------------------------------------------------------
CONNECTIVITY_STORY_DOMAINS = ("Communication", "Wireless Services")


def _iso_calendar_week_tags(start_date: str, end_date: str) -> set[str]:
    """Zero-padded CW tags (e.g. 'CW35') for every ISO week overlapping the date range."""
    start_dt = parse_created_date(start_date)
    end_dt = parse_created_date(end_date)
    if start_dt is None or end_dt is None:
        return set()
    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt
    tags: set[str] = set()
    current = start_dt
    while current <= end_dt:
        tags.add(f"CW{current.isocalendar().week:02d}")
        current += timedelta(days=1)
    return tags


def _fetch_subtask_hours(
    parent_key: str,
    parent_summary: str,
    subtask_keys: list[str],
    method: str,
    cw_filter: set[str] | None = None,
) -> list[dict]:
    """Batch-fetch subtask timespent; skip subtasks with no logged hours or (for
    Method 2) whose summary doesn't mention one of the selected calendar weeks."""
    clean_keys = [k for k in (subtask_keys or []) if k]
    if not clean_keys:
        return []
    subtask_fields: dict[str, dict] = {}
    batch_size = 40
    for offset in range(0, len(clean_keys), batch_size):
        batch = clean_keys[offset:offset + batch_size]
        jql = "key in (" + ", ".join(batch) + ")"
        for issue in fetch_all(jql, ["summary", "timespent", "assignee"], log_http_error=False):
            subtask_fields[issue.get("key")] = issue.get("fields", {})

    rows = []
    for key in clean_keys:
        fields = subtask_fields.get(key, {})
        summary = str(fields.get("summary") or "").strip()
        if cw_filter is not None and not any(tag in summary.upper() for tag in cw_filter):
            continue
        seconds = fields.get("timespent")
        if not seconds:
            continue
        hours = round(float(seconds) / 3600.0, 2)
        if hours <= 0:
            continue
        rows.append(
            {
                "method": method,
                "parent_key": parent_key,
                "parent_summary": parent_summary,
                "subtask_key": key,
                "subtask_summary": summary,
                "assignee": _normalize_person_name(fields.get("assignee")) or "Unassigned",
                "hours": hours,
            }
        )
    return rows


def fetch_connectivity_adhoc_effort(start_date: str, end_date: str, adhoc_domains: list[str] | None = None) -> dict:
    """Fetch Communication/Wireless Services ad-hoc effort. Two Jira patterns are
    combined: Method 1 (weekly LTTSTM Task, subtasks filtered by Task creation
    date) and Method 2 (fixed IDCEVODEV umbrella Stories, subtask matched by the
    calendar week(s) the selected date range falls in). Neither pattern has a
    ready-made total; hours are summed directly from subtask timespent."""
    selected_domains = {str(d or "").strip().casefold() for d in (adhoc_domains or []) if str(d or "").strip()}
    if selected_domains and not (selected_domains & {"all", "communication", "wireless services"}):
        return {}

    rows: list[dict] = []

    print("\nFetching Communication/Wireless Services ad-hoc effort (Method 1: LTTSTM Task)...")
    jql1 = (
        'project = LTTSTM AND issuetype = Task AND labels = LTTS_Connectivity '
        f'AND created >= "{start_date}" AND created <= "{end_date}"'
    )
    print(f"  JQL: {jql1}")
    try:
        tasks = fetch_all(jql1, ["summary", "subtasks"], log_http_error=False)
    except HTTPError:
        tasks = []
    for task in tasks:
        task_fields = task.get("fields", {})
        parent_key = str(task.get("key", "")).strip()
        parent_summary = str(task_fields.get("summary") or "").strip()
        subtask_keys = [st.get("key") for st in (task_fields.get("subtasks") or [])]
        rows.extend(_fetch_subtask_hours(parent_key, parent_summary, subtask_keys, "LTTSTM Task"))

    print("Fetching Communication/Wireless Services ad-hoc effort (Method 2: IDCEVODEV Story)...")
    cw_tags = _iso_calendar_week_tags(start_date, end_date)
    domains_clause = ", ".join(f'"{d}"' for d in CONNECTIVITY_STORY_DOMAINS)
    jql2 = f'project = IDCEVODEV AND issuetype = Story AND labels = LTTS_SV AND cf[10300] in ({domains_clause})'
    print(f"  JQL: {jql2}")
    print(f"  Calendar week tag(s) matched in subtasks: {', '.join(sorted(cw_tags)) or 'none (invalid date range)'}")
    try:
        stories = fetch_all(jql2, ["summary", "subtasks"], log_http_error=False)
    except HTTPError:
        stories = []
    for story in stories:
        story_fields = story.get("fields", {})
        parent_key = str(story.get("key", "")).strip()
        parent_summary = str(story_fields.get("summary") or "").strip()
        subtask_keys = [st.get("key") for st in (story_fields.get("subtasks") or [])]
        rows.extend(_fetch_subtask_hours(parent_key, parent_summary, subtask_keys, "IDCEVODEV Story", cw_filter=cw_tags))

    rows.sort(key=lambda item: (item.get("method", ""), item.get("parent_key", "")))
    total_effort_hours = round(sum(item.get("hours", 0.0) for item in rows), 2)
    method1_hours = round(sum(item.get("hours", 0.0) for item in rows if item.get("method") == "LTTSTM Task"), 2)
    method2_hours = round(sum(item.get("hours", 0.0) for item in rows if item.get("method") == "IDCEVODEV Story"), 2)

    return {
        "rows": rows,
        "total_effort_hours": total_effort_hours,
        "method1_effort_hours": method1_hours,
        "method2_effort_hours": method2_hours,
        "total_subtasks": len(rows),
    }


# ---------------------------------------------------------------
# FEATURE SCOPE (v2 experimental): RG3/RG4 SYS.5 and RG4.5 sub-task closure tracking
# ---------------------------------------------------------------
def normalize_feature_sop_pu_selection(values: list[str] | None) -> list[str]:
    """Return requested SOP/PU tokens in catalog order; empty/None selects every known SOP/PU."""
    if not values:
        return list(FEATURE_SOP_PU_ORDER)
    requested = {str(v).strip() for v in values if str(v).strip()}
    if not requested:
        return list(FEATURE_SOP_PU_ORDER)
    selected = [sop for sop in FEATURE_SOP_PU_ORDER if sop in requested]
    invalid = requested - set(FEATURE_SOP_PU_ORDER)
    if invalid:
        print(f"Ignored unknown Feature SOP/PU values: {', '.join(sorted(invalid))}")
    return selected or list(FEATURE_SOP_PU_ORDER)


def _feature_subtasks_of_clause(sop_pu_values: list[str]) -> str:
    """Build an OR'd issueFunction subtasksOf(...) clause across the selected SOP/PU feature filters."""
    filter_ids = [FEATURE_SOP_PU_FILTER_IDS[sop] for sop in sop_pu_values if sop in FEATURE_SOP_PU_FILTER_IDS]
    if not filter_ids:
        return ""
    clauses = [f'issueFunction in subtasksOf("filter={filter_id}")' for filter_id in filter_ids]
    return "(" + " OR ".join(clauses) + ")"


def _fetch_feature_metadata(feature_keys: list[str], project_keys: list[str] | None = None) -> dict[str, dict]:
    """Batch-fetch parent Feature summary/domain/SOP-PU for the closed sub-tasks found."""
    clean_keys = list(dict.fromkeys(k for k in feature_keys if k))
    if not clean_keys:
        return {}
    metadata: dict[str, dict] = {}
    domain_field = CUSTOM_FIELDS.get("domain", "")
    sop_pu_field = CUSTOM_FIELDS.get("sop_pu", "")
    fields = ["summary", domain_field, sop_pu_field]
    batch_size = 80
    for offset in range(0, len(clean_keys), batch_size):
        batch = clean_keys[offset:offset + batch_size]
        keys_csv = ", ".join(f'"{key}"' for key in batch)
        project_clause = ""
        if project_keys:
            project_csv = ", ".join(project_keys)
            project_clause = f" AND project in ({project_csv}) AND issuetype = Feature"
        issues = fetch_all(f"key in ({keys_csv}){project_clause}", fields, log_http_error=False)
        for issue in issues:
            key = str(issue.get("key", "")).strip()
            metadata[key] = {
                "summary": issue.get("fields", {}).get("summary", ""),
                "domain": get_field(issue, "domain"),
                "sop_pu": get_field(issue, "sop_pu"),
            }
    return metadata


def fetch_feature_subtask_closures(
    subtask_text: str,
    resolutions: tuple[str, ...],
    sop_pu_values: list[str],
    start_date: str,
    end_date: str,
    product_projects: dict[str, str] | None = None,
) -> list[dict]:
    """Fetch closed/resolved Feature sub-tasks from the selected product projects."""
    if not product_projects:
        return []
    resolution_csv = ", ".join(f'"{r}"' for r in resolutions)
    exclusive_end = _jql_exclusive_end_date(end_date)
    fields = ["summary", "status", "resolution", "resolutiondate", "parent", "labels", CUSTOM_FIELDS["i_step"]]
    issues = []
    issue_products: dict[str, str] = {}
    for product, project in product_projects.items():
        jql = (
            f'project = {project} AND issuetype = "Sub-task" '
            f'AND resolution in ({resolution_csv}) AND text ~ "{subtask_text}" '
            f'AND resolved >= "{start_date}" AND resolved < "{exclusive_end}"'
        )
        print(f"  JQL ({product}, {subtask_text}): {jql}")
        project_issues = fetch_all(jql, fields, log_http_error=False)
        issues.extend(project_issues)
        for issue in project_issues:
            issue_products[str(issue.get("key", "")).strip()] = product

    rows = []
    parent_keys = []
    for issue in issues:
        issue_fields = issue.get("fields", {})
        parent = issue_fields.get("parent") or {}
        parent_key = str(parent.get("key", "")).strip()
        if parent_key:
            parent_keys.append(parent_key)
        rows.append(
            {
                "key": issue.get("key", ""),
                "summary": issue_fields.get("summary", ""),
                "status": (issue_fields.get("status") or {}).get("name", ""),
                "resolution": (issue_fields.get("resolution") or {}).get("name", ""),
                "resolved": _jira_iso_date(issue_fields.get("resolutiondate", "")),
                "labels": issue_fields.get("labels", []) or [],
                "i_step": get_field(issue, "i_step") or "N/A",
                "feature_key": parent_key,
                "feature_summary": "",
                "feature_domain": "",
                "feature_sop_pu": "",
                "product": issue_products.get(str(issue.get("key", "")).strip(), ""),
                "project": next((project for product, project in (product_projects or {}).items() if product == issue_products.get(str(issue.get("key", "")).strip(), "")), ""),
            }
        )

    feature_info = _fetch_feature_metadata(parent_keys, list(product_projects.values()))
    for row in rows:
        info = feature_info.get(row["feature_key"], {})
        row["feature_summary"] = info.get("summary", "")
        row["feature_domain"] = info.get("domain", "")
        row["feature_sop_pu"] = info.get("sop_pu", "")

    selected_sop_pu = set(sop_pu_values)
    rows = [row for row in rows if row.get("feature_sop_pu") in selected_sop_pu]

    return rows


def filter_feature_rows_by_domain(rows: list[dict], domains: list[str] | None) -> list[dict]:
    """Keep only rows whose parent feature domain matches the requested selection (case-insensitive)."""
    clean_domains = {
        str(d).strip().casefold() for d in (domains or []) if str(d).strip() and str(d).strip().lower() != "all"
    }
    if not clean_domains:
        return rows
    return [row for row in rows if str(row.get("feature_domain", "")).strip().casefold() in clean_domains]


def has_po_review_done_label(labels: list[str]) -> bool:
    """Case-insensitive substring match for the PO_Review_Done marker label."""
    return any(FEATURE_PO_REVIEW_DONE_LABEL in str(label or "").strip().casefold() for label in (labels or []))


def is_rg45_ready_for_validation(rg45_status: str, rg42_integration_status: str, rg42_domain_status: str) -> bool:
    """RG4.5 is ready for validation once it is In Progress and both RG4.2 siblings are Closed/Resolved."""
    closed_states = {"closed", "resolved"}
    return (
        str(rg45_status or "").strip().casefold() == "in progress"
        and str(rg42_integration_status or "").strip().casefold() in closed_states
        and str(rg42_domain_status or "").strip().casefold() in closed_states
    )


def aggregate_feature_subtask_summary(rows: list[dict]) -> dict:
    """Aggregate total/per-SOP-PU/per-week closure counts for a feature sub-task fetch result."""
    by_sop_pu: Counter = Counter()
    by_week: dict[str, int] = {}
    for row in rows:
        sop_pu = str(row.get("feature_sop_pu") or "Unknown").strip() or "Unknown"
        by_sop_pu[sop_pu] += 1
        resolved_date = parse_created_date(str(row.get("resolved", "")))
        if resolved_date:
            iso = resolved_date.isocalendar()
            week_key = f"{iso.year}-CW{iso.week:02d}"
            by_week[week_key] = by_week.get(week_key, 0) + 1
    return {
        "total": len(rows),
        "by_sop_pu": dict(by_sop_pu),
        "by_week": dict(sorted(by_week.items())),
    }


TEST_COVERAGE_LINK_NAMES = ("is tested by",)
TEST_COVERAGE_SYS5_PATTERN = re.compile(r"sys\.?\s*5", re.IGNORECASE)
TEST_COVERAGE_CATEGORY_FIELD = "customfield_10304"


def _jira_value_text(value) -> str:
    if isinstance(value, list):
        return ", ".join(_jira_value_text(item) for item in value if item is not None)
    if isinstance(value, dict):
        return str(value.get("value") or value.get("name") or "").strip()
    return str(value or "").strip()


def classify_test_coverage_category(labels: list[str], summary: str, category_value="") -> str:
    """Best-effort SYS.5 categorization from labels/summary text.

    NOTE: Jira's Test Coverage grid on a Feature is not exposed through standard
    REST fields/properties (confirmed via prior investigation on IDCEVOPM-16331).
    This heuristic inspects the "is tested by" linked Test issues' labels and
    summary for a SYS.5 marker and should be verified against the real Test
    Coverage panel before being trusted for reporting.
    """
    haystacks = list(labels or []) + [str(summary or ""), _jira_value_text(category_value)]
    for text in haystacks:
        if TEST_COVERAGE_SYS5_PATTERN.search(str(text or "")):
            return "SYS.5"
    return "Uncategorized"


def fetch_feature_test_coverage(feature_keys: list[str]) -> dict[str, list[dict]]:
    """Best-effort Test Coverage retrieval via "is tested by" issue links per Feature.

    See classify_test_coverage_category() note: this is a heuristic stand-in until
    the actual Test Coverage/test-management source field is confirmed.
    """
    clean_keys = list(dict.fromkeys(k for k in feature_keys if k))
    coverage: dict[str, list[dict]] = {key: [] for key in clean_keys}
    if not clean_keys:
        return coverage
    batch_size = 40
    for offset in range(0, len(clean_keys), batch_size):
        batch = clean_keys[offset:offset + batch_size]
        keys_csv = ", ".join(f'"{key}"' for key in batch)
        issues = fetch_all(f"key in ({keys_csv})", ["issuelinks"], log_http_error=False)
        linked_refs: list[tuple[str, str]] = []
        linked_keys: list[str] = []
        for issue in issues:
            feature_key = str(issue.get("key", "")).strip()
            for link in issue.get("fields", {}).get("issuelinks", []) or []:
                link_type = link.get("type", {}) or {}
                inward_name = str(link_type.get("inward", "")).strip().casefold()
                outward_name = str(link_type.get("outward", "")).strip().casefold()
                for direction, name in (("inwardIssue", inward_name), ("outwardIssue", outward_name)):
                    if name not in TEST_COVERAGE_LINK_NAMES:
                        continue
                    linked = link.get(direction) or {}
                    linked_key = str(linked.get("key", "")).strip()
                    if linked_key:
                        linked_refs.append((feature_key, linked_key))
                        linked_keys.append(linked_key)

        linked_keys = list(dict.fromkeys(linked_keys))
        if not linked_keys:
            continue
        linked_issues = []
        for linked_offset in range(0, len(linked_keys), batch_size):
            linked_batch = linked_keys[linked_offset:linked_offset + batch_size]
            linked_csv = ", ".join(f'"{key}"' for key in linked_batch)
            linked_issues.extend(fetch_all(
                f"key in ({linked_csv})",
                ["summary", "labels", "issuetype", TEST_COVERAGE_CATEGORY_FIELD],
                log_http_error=False,
            ))
        linked_metadata = {
            str(issue.get("key", "")).strip(): issue.get("fields", {}) or {}
            for issue in linked_issues
        }
        for feature_key, linked_key in linked_refs:
            linked_fields = linked_metadata.get(linked_key, {})
            if str((linked_fields.get("issuetype") or {}).get("name", "")).strip().casefold() != "test":
                continue
            labels = linked_fields.get("labels", []) or []
            summary = linked_fields.get("summary", "")
            coverage.setdefault(feature_key, []).append(
                {
                    "key": linked_key,
                    "summary": summary,
                    "labels": labels,
                    "category": classify_test_coverage_category(
                        labels, summary, linked_fields.get(TEST_COVERAGE_CATEGORY_FIELD, "")
                    ),
                }
            )
    return coverage


def fetch_feature_scope_data(
    sop_pu_values: list[str] | None,
    domains: list[str] | None,
    start_date: str,
    end_date: str,
    include_rg3_rg4: bool = True,
    include_rg45: bool = True,
    products: list[str] | None = None,
) -> dict:
    """Fetch and aggregate the Feature scope: RG3/RG4 SYS.5 and RG4.5 sub-task closures."""
    selected_sop_pu = normalize_feature_sop_pu_selection(sop_pu_values)
    selected_products = [
        product for product in (products or list(FEATURE_PRODUCT_PROJECTS))
        if product in FEATURE_PRODUCT_PROJECTS
    ] or list(FEATURE_PRODUCT_PROJECTS)
    product_projects = {product: FEATURE_PRODUCT_PROJECTS[product] for product in selected_products}
    result: dict = {"sop_pu_selected": selected_sop_pu, "rg3_rg4": {}, "rg45": {}}

    if include_rg3_rg4:
        print("\nFetching RG3/RG4 - SYS.5 System Validation Test Cases closures...")
        rows = fetch_feature_subtask_closures(
            FEATURE_RG3_RG4_SYS5_TEXT, FEATURE_RG3_RG4_SYS5_RESOLUTIONS, selected_sop_pu, start_date, end_date,
            product_projects,
        )
        rows = [row for row in rows if has_po_review_done_label(row.get("labels", []))]
        rows = filter_feature_rows_by_domain(rows, domains)
        coverage = fetch_feature_test_coverage([row["feature_key"] for row in rows])
        for row in rows:
            row["test_coverage"] = coverage.get(row["feature_key"], [])
            row["sys5_test_case_count"] = sum(1 for tc in row["test_coverage"] if tc["category"] == "SYS.5")
        print(f"  Found {len(rows)} closed RG3/RG4 SYS.5 sub-tasks")
        result["rg3_rg4"] = {"rows": rows, **aggregate_feature_subtask_summary(rows)}

    if include_rg45:
        print("\nFetching RG4.5 - Feature/subfeature System Validation Testing SYS.5 closures...")
        rows = fetch_feature_subtask_closures(
            FEATURE_RG45_SYS5_TEXT, FEATURE_RG45_SYS5_RESOLUTIONS, selected_sop_pu, start_date, end_date,
            product_projects,
        )
        rows = filter_feature_rows_by_domain(rows, domains)
        coverage = fetch_feature_test_coverage([row["feature_key"] for row in rows])
        for row in rows:
            row["test_coverage"] = coverage.get(row["feature_key"], [])
            row["sys5_test_case_count"] = sum(1 for tc in row["test_coverage"] if tc["category"] == "SYS.5")
        print(f"  Found {len(rows)} closed RG4.5 SYS.5 validation sub-tasks")
        result["rg45"] = {"rows": rows, **aggregate_feature_subtask_summary(rows)}

    return result


def _feature_excel_fallback_path(output_path: str) -> str:
    """Build a timestamped sibling path used when the primary workbook is locked."""
    base, ext = os.path.splitext(output_path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{stamp}{ext}"


def _style_feature_sheet(sheet, header_count: int) -> None:
    """Apply cosmetic-only formatting (colors/widths/filter); never touches cell values."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    header_fill = PatternFill(start_color="FF0066B1", end_color="FF0066B1", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFFFF")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(bottom=Side(style="thin", color="FFB8C6D4"))
    band_fill = PatternFill(start_color="FFF2F6FA", end_color="FFF2F6FA", fill_type="solid")

    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align
        cell.border = thin_border
    sheet.row_dimensions[1].height = 22

    column_widths = {1: 12, 2: 14, 3: 16, 4: 38, 5: 10, 6: 16, 7: 20, 8: 16, 9: 42, 10: 16}
    for column in range(1, header_count + 1):
        letter = get_column_letter(column)
        sheet.column_dimensions[letter].width = column_widths.get(column, 18)

    for row_number in range(2, sheet.max_row + 1):
        band = PatternFill() if row_number % 2 == 0 else band_fill
        for column in range(1, header_count + 1):
            sheet.cell(row_number, column).fill = band

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(header_count)}{max(sheet.max_row, 1)}"


def export_feature_sys5_excel(feature_scope: dict, output_path: str) -> str:
    """Append SYS.5 rows to one workbook with one domain sheet per validation type."""
    from openpyxl import Workbook, load_workbook

    if os.path.exists(output_path):
        workbook = load_workbook(output_path)
    else:
        workbook = Workbook()

    headers = [
        "Product", "Jira Project", "Feature ID", "Feature Summary", "SOP/PU", "Sub-task Key",
        "Sub-task Resolved Date", "Test Case Key", "Test Case Summary", "Test Case Category",
    ]
    sheet_specs = (("rg3_rg4", "RG3-RG4_SYS5"), ("rg45", "RG4.5_SYS5"))
    added_rows = 0
    for scope_key, sheet_title in sheet_specs:
        rows = feature_scope.get(scope_key, {}).get("rows", [])
        domains = sorted({str(row.get("feature_domain") or "Unknown").strip() or "Unknown" for row in rows}, key=str.casefold)
        if not domains:
            continue
        for domain in domains:
            raw_sheet_title = f"{domain}_{sheet_title}"
            safe_sheet_title = re.sub(r"[\\/*?:\[\]]", "_", raw_sheet_title).strip()[:31] or f"Feature_{sheet_title}"[:31]
            sheet = workbook[safe_sheet_title] if safe_sheet_title in workbook.sheetnames else workbook.create_sheet(safe_sheet_title)
            domain_rows = [row for row in rows if (str(row.get("feature_domain") or "Unknown").strip() or "Unknown") == domain]
            if sheet.max_row == 1 and all(cell.value is None for cell in sheet[1]):
                for column, header in enumerate(headers, start=1):
                    sheet.cell(1, column).value = header
            elif sheet.max_row == 0:
                sheet.append(headers)
            elif sheet.cell(1, 1).value != headers[0]:
                sheet.insert_rows(1)
                for column, header in enumerate(headers, start=1):
                    sheet.cell(1, column).value = header

            for row_number in range(sheet.max_row, 1, -1):
                if str(sheet.cell(row_number, 10).value or "").strip().casefold() != "sys.5":
                    sheet.delete_rows(row_number, 1)

            existing_keys = set()
            for existing in sheet.iter_rows(min_row=2, values_only=True):
                existing_keys.add(tuple(str(value or "").strip() for value in (existing[0], existing[1], existing[2], existing[5], existing[7])))

            for row in domain_rows:
                product = row.get("product", "")
                project = row.get("project", FEATURE_PRODUCT_PROJECTS.get(product, ""))
                test_cases = [
                    test_case for test_case in row.get("test_coverage", [])
                    if str(test_case.get("category", "")).strip().casefold() == "sys.5"
                ]
                for test_case in test_cases:
                    values = [
                        product, project, row.get("feature_key", ""), row.get("feature_summary", ""),
                        row.get("feature_sop_pu", ""), row.get("key", ""), row.get("resolved", ""),
                        test_case.get("key", ""), test_case.get("summary", ""), test_case.get("category", ""),
                    ]
                    identity = tuple(str(values[index]).strip() for index in (0, 1, 2, 5, 7))
                    if identity not in existing_keys:
                        sheet.append(values)
                        existing_keys.add(identity)
                        added_rows += 1

            _style_feature_sheet(sheet, len(headers))

    for legacy_title in ("RG3-RG4 SYS.5 Closures", "RG4.5 SYS.5 Closures"):
        if legacy_title in workbook.sheetnames:
            workbook.remove(workbook[legacy_title])
    for sheet in list(workbook.worksheets):
        if sheet.max_row == 1 and sheet.max_column == 1 and sheet.cell(1, 1).value is None:
            workbook.remove(sheet)

    try:
        workbook.save(output_path)
    except PermissionError:
        fallback_path = _feature_excel_fallback_path(output_path)
        workbook.save(fallback_path)
        print(f"  Warning: {output_path} is open/locked; saved to {fallback_path} instead")
        print(f"  Added {added_rows} new Feature SYS.5 Excel rows")
        return fallback_path
    print(f"  Added {added_rows} new Feature SYS.5 Excel rows")
    return output_path


def _split_scope_tokens(value: str) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    return {token.strip().upper() for token in raw.split(",") if token and token.strip()}


def _normalize_issue_value(raw_value) -> str:
    if isinstance(raw_value, list):
        parts = []
        for item in raw_value:
            if isinstance(item, dict):
                parts.append(str(item.get("value") or item.get("name") or ""))
            else:
                parts.append(str(item))
        return ", ".join(part for part in parts if part and part.strip())
    if isinstance(raw_value, dict):
        return str(raw_value.get("value") or raw_value.get("name") or "")
    return str(raw_value or "").strip()


def classify_product_scope(project: str, variant: str, assigned_ecu: str) -> str:
    project_key = str(project or "").strip().upper()
    variant_tokens = _split_scope_tokens(variant)
    ecu_tokens = _split_scope_tokens(assigned_ecu)
    scope_tokens = variant_tokens | ecu_tokens

    for rule in PRODUCT_CLOSURE_RULES:
        if project_key not in rule["projects"]:
            continue
        if scope_tokens & rule["tokens"]:
            return str(rule["label"])
    return ""


def count_issues_by_product_scope(issues: list[dict], variant_field_available: bool, ecu_field_available: bool) -> dict[str, int]:
    counts = {str(rule["label"]): 0 for rule in PRODUCT_CLOSURE_RULES}
    for issue in issues:
        fields = issue.get("fields", {}) if isinstance(issue, dict) else {}
        project = ((fields.get("project") or {}).get("key", "") or str(issue.get("key", "")).split("-", 1)[0]).strip()
        variant = get_field(issue, "variant") if variant_field_available else ""
        assigned_ecu = _normalize_issue_value(fields.get(DEFECT_ASSIGNED_ECU_FIELD, "")) if ecu_field_available else ""
        product = classify_product_scope(project, variant, assigned_ecu)
        if product:
            counts[product] += 1
    return counts


def compute_reporter_project_counts(rows: list[dict]) -> list[dict]:
    counts: Counter = Counter()
    for row in rows:
        reporter = str(row.get("reporter") or "Unknown").strip() or "Unknown"
        project = str(row.get("project") or "Unknown").strip() or "Unknown"
        counts[f"{reporter} | {project}"] += 1

    return [
        {"label": label, "value": value}
        for label, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:12]
    ]


def compute_et_reporter_product_counts(rows: list[dict]) -> list[dict]:
    counts: Counter = Counter()
    for row in rows:
        if not row.get("is_exploratory"):
            continue
        reporter = str(row.get("reporter") or "Unknown").strip() or "Unknown"
        product = classify_product_scope(
            str(row.get("project") or ""),
            str(row.get("variant") or ""),
            str(row.get("assigned_ecu") or ""),
        ) or classify_similiaize_defect_product(row) or "Other"
        counts[f"{reporter} | {product}"] += 1

    return [
        {"label": label, "value": value}
        for label, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:20]
    ]


def compute_weekly_defect_counts(rows: list[dict]) -> list[dict]:
    counts: Counter = Counter()
    for row in rows:
        created = parse_created_date(str(row.get("created", "")))
        if created:
            iso = created.isocalendar()
            counts[f"CW{iso.week:02d}"] += 1
    return [{"label": label, "value": value} for label, value in sorted(counts.items())]


def compute_product_closure_rates(rows: list[dict]) -> list[dict]:
    products = []
    for rule in PRODUCT_CLOSURE_RULES:
        total = 0
        closed = 0
        for row in rows:
            project = str(row.get("project") or "").strip().upper()
            if project not in rule["projects"]:
                continue

            variant_tokens = _split_scope_tokens(str(row.get("variant") or ""))
            ecu_tokens = _split_scope_tokens(str(row.get("assigned_ecu") or ""))
            if not ((variant_tokens | ecu_tokens) & rule["tokens"]):
                continue

            total += 1
            if is_closed_defect_status(str(row.get("status", ""))):
                closed += 1

        open_count = max(total - closed, 0)
        closed_pct = (closed / total * 100.0) if total > 0 else 0.0
        products.append(
            {
                "label": rule["label"],
                "scope_label": rule["scope_label"],
                "closed": closed,
                "open": open_count,
                "total": total,
                "closed_pct": closed_pct,
            }
        )

    return products


def classify_similiaize_defect_product(row: dict) -> str:
    project = str(row.get("project") or "").strip().upper()
    variant_tokens = _split_scope_tokens(str(row.get("variant") or ""))

    for rule in SIMILIAIZE_DEFECT_RULES:
        if project not in rule["projects"]:
            continue
        if rule["variants"] and not (variant_tokens & rule["variants"]):
            continue
        return str(rule["label"])
    return ""


def compute_similiaize_coverage(rows: list[dict]) -> list[dict]:
    totals = {str(rule["label"]): 0 for rule in SIMILIAIZE_DEFECT_RULES}
    with_tool = {str(rule["label"]): 0 for rule in SIMILIAIZE_DEFECT_RULES}

    for row in rows:
        product = classify_similiaize_defect_product(row)
        if not product:
            continue

        totals[product] += 1
        labels = _split_scope_tokens(str(row.get("labels") or ""))
        if SIMILIAIZE_LABEL.upper() in labels:
            with_tool[product] += 1

    return [
        {
            "label": str(rule["label"]),
            "with_tool": with_tool[str(rule["label"])],
            "without_tool": max(totals[str(rule["label"])] - with_tool[str(rule["label"])], 0),
            "total": totals[str(rule["label"])],
        }
        for rule in SIMILIAIZE_DEFECT_RULES
        if totals[str(rule["label"])] > 0
    ]


def compute_defect_analytics(defects: dict, start_date: str, end_date: str) -> dict:
        rows = defects.get("rows", []) or []
        severity_counts = {name: 0 for name in SEVERITY_ORDER}
        reporter_counts: Counter = Counter()
        component_counts: Counter = Counter()
        domain_counts: Counter = Counter()
        exploratory_count = 0
        open_count = 0
        closed_count = 0
        open_critical_count = 0
        escalation_counts: Counter = Counter({name: 0 for name in ESCALATION_LABELS})
        grouped_by_severity = {name: [] for name in SEVERITY_ORDER}
        risk_age_days = 14
        ref_date = datetime.strptime(end_date, "%Y-%m-%d")

        risk_rows = []
        for row in rows:
                severity = classify_defect_severity(str(row.get("priority", "")))
                severity_counts[severity] += 1
                grouped_by_severity[severity].append(row)

                reporter = str(row.get("reporter") or "Unknown")
                component = str(row.get("assigned_ecu") or "Unknown")
                domain_name = str(row.get("domain") or "Unknown")
                if reporter.strip():
                        reporter_counts[reporter] += 1
                if component.strip():
                    component_counts[component] += 1
                if domain_name.strip():
                    domain_counts[domain_name] += 1

                if row.get("is_exploratory"):
                        exploratory_count += 1

                is_closed = is_closed_defect_status(str(row.get("status", "")))
                if is_closed:
                        closed_count += 1
                else:
                        open_count += 1
                if severity == "Critical" and not is_closed:
                        open_critical_count += 1
                if not is_closed:
                        label_tokens = _split_scope_tokens(str(row.get("labels", "")))
                        for name, label in ESCALATION_LABELS.items():
                                if label.upper() in label_tokens:
                                        escalation_counts[name] += 1

                summary_l = str(row.get("summary", "")).lower()
                labels_l = str(row.get("labels", "")).lower()
                status_l = str(row.get("status", "")).lower()
                created_dt = parse_created_date(str(row.get("created", "")))
                age_days = (ref_date - created_dt).days if created_dt else 0

                reasons = []
                score = 0
                if severity == "Critical":
                        reasons.append("Critical")
                        score += 4

                if re.search(r"customer|vehicle|production|field|safety|impact", summary_l):
                        reasons.append("Customer Impacting")
                        score += 3

                if re.search(r"block|blocking|blocker|cannot proceed|showstopper", summary_l + " " + labels_l + " " + status_l):
                        reasons.append("Blocking")
                        score += 3

                if (not is_closed) and age_days > risk_age_days:
                        reasons.append(f"Open > {risk_age_days} days")
                        score += 2

                if reasons:
                        risk_rows.append(
                                {
                                        "row": row,
                                        "severity": severity,
                                        "age_days": age_days,
                                        "reasons": reasons,
                                        "score": score,
                                }
                        )

        total_defects = len(rows)
        regular_count = max(total_defects - exploratory_count, 0)

        top_reporter = "N/A"
        if reporter_counts:
                top_reporter = max(reporter_counts.items(), key=lambda item: item[1])[0]

        requested_domain = str(defects.get("requested_domain") or "").strip()
        filtered_domains = {k: v for k, v in domain_counts.items() if str(k).strip().upper() not in {"", "N/A", "UNKNOWN"}}
        if filtered_domains:
            top_domain = max(filtered_domains.items(), key=lambda item: item[1])[0]
        elif requested_domain and requested_domain.lower() != "all":
            top_domain = requested_domain
        else:
            top_domain = "N/A"

        previous_week_count = int(defects.get("previous_week_count", 0) or 0)
        trend_delta = total_defects - previous_week_count
        trend_pct = 0.0
        if previous_week_count > 0:
                trend_pct = (trend_delta / previous_week_count) * 100.0

        risk_rows.sort(key=lambda item: (-item["score"], -item["age_days"], item["row"].get("key", "")))

        return {
                "total": total_defects,
                "severity_counts": severity_counts,
                "exploratory_count": exploratory_count,
                "regular_count": regular_count,
                "open_count": open_count,
                "closed_count": closed_count,
                "open_critical_count": open_critical_count,
                "risk_total_count": len(risk_rows),
                "escalation_counts": dict(escalation_counts),
                "grouped": grouped_by_severity,
                "risk_rows": risk_rows[:12],
                "risk_age_days": risk_age_days,
                "top_reporter": top_reporter,
                "top_domain": top_domain,
                "previous_week_count": previous_week_count,
                "trend_delta": trend_delta,
                "trend_pct": trend_pct,
                "reporter_counts": dict(reporter_counts),
                "reporter_project_counts": compute_reporter_project_counts(rows),
                "et_reporter_product_counts": compute_et_reporter_product_counts(rows),
                "weekly_defect_counts": compute_weekly_defect_counts(rows),
                "component_counts": dict(component_counts),
                "domain_counts": dict(domain_counts),
                "product_closure_rates": compute_product_closure_rates(rows),
                "similiaize_coverage": compute_similiaize_coverage(rows),
                "week_label": build_cw_label(start_date, end_date),
        }


def render_defect_detail_view(row: dict) -> str:
        reporter = escape(str(row.get("reporter", "Unknown") or "Unknown"))
        assigned = escape(str(row.get("assigned_ecu", "N/A") or "N/A"))
        found_in = escape(str(row.get("found_in_version", "N/A") or "N/A"))
        project_lbl = escape(str(row.get("project_specific_label", "N/A") or "N/A"))
        created = escape(str(row.get("created", "") or "N/A"))
        return f"""
        <details class="row-detail">
            <summary>Details</summary>
            <div class="row-detail-grid">
                <span><b>Reporter:</b> {reporter}</span>
                <span><b>Assigned ECU:</b> {assigned}</span>
                <span><b>Found In Version:</b> {found_in}</span>
                <span><b>Project Label:</b> {project_lbl}</span>
                <span><b>Created:</b> {created}</span>
            </div>
        </details>
        """


def render_defect_rows(rows: list[dict]) -> str:
        body = ""
        for row in rows:
                key = escape(str(row.get("key", "")))
                summary = escape(str(row.get("summary", "")))
                priority = str(row.get("priority", "") or "")
                severity = classify_defect_severity(priority)
                reporter = escape(str(row.get("reporter", "Unknown") or "Unknown"))
                variant = escape(str(row.get("variant", "N/A") or "N/A"))
                created = escape(str(row.get("created", "N/A") or "N/A"))
                status = escape(str(row.get("status", "")))
                link = f"{JIRA_BASE_URL}/browse/{key}"

                body += f"""
                <tr data-defect-search="{escape(f'{key} {summary} {reporter} {variant} {status}', quote=True)}" data-severity="{escape(severity)}" data-status="{status}">
                    <td class="cell-key">{key}</td>
                    <td>
                        <div class="cell-summary">{summary}</div>
                        {render_defect_detail_view(row)}
                    </td>
                    <td>{severity_badge(severity)}</td>
                    <td>{reporter}</td>
                    <td>{variant}</td>
                    <td>{created}</td>
                    <td>{status_badge(status)}</td>
                    <td><a href="{link}" target="_blank">Open</a></td>
                </tr>
                """

        return body


def render_severity_accordions(grouped_rows: dict) -> str:
        blocks = []
        for idx, severity in enumerate(SEVERITY_ORDER):
                rows = grouped_rows.get(severity, [])
                count = len(rows)
                open_attr = " open" if idx == 0 else ""

                if not rows:
                        table_html = '<p class="empty">No defects in this severity bucket.</p>'
                else:
                        table_html = f"""
                        <div class="defect-table-wrap">
                            <table class="defect-table">
                                <thead>
                                    <tr>
                                        <th>Defect ID</th>
                                        <th>Summary</th>
                                        <th>Severity</th>
                                        <th>Reporter</th>
                                        <th>Variant</th>
                                        <th>Creation Date</th>
                                        <th>Status</th>
                                        <th>Link</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {render_defect_rows(rows)}
                                </tbody>
                            </table>
                        </div>
                        """

                blocks.append(
                        f"""
                        <details class="defect-accordion defect-acc-{severity.lower()}"{open_attr}>
                            <summary>
                                <span>{severity} Defects</span>
                                <span class="acc-count">{count}</span>
                            </summary>
                            <div class="acc-content">{table_html}</div>
                        </details>
                        """
                )

        return "\n".join(blocks)


def render_top_risk_section(risk_rows: list[dict], risk_age_days: int) -> str:
        if not risk_rows:
                return '<p class="empty">No immediate high-risk defects detected for the selected period.</p>'

        body = ""
        for item in risk_rows:
                row = item["row"]
                reasons = " ".join(f'<span class="risk-reason">{escape(reason)}</span>' for reason in item["reasons"])
                key = escape(str(row.get("key", "")))
                summary = escape(str(row.get("summary", "")))
                reporter = escape(str(row.get("reporter", "Unknown") or "Unknown"))
                status = escape(str(row.get("status", "")))
                body += f"""
                <tr>
                    <td><a href="{JIRA_BASE_URL}/browse/{key}" target="_blank">{key}</a></td>
                    <td>{summary}</td>
                    <td>{severity_badge(item['severity'])}</td>
                    <td>{reporter}</td>
                    <td>{status}</td>
                    <td>{item['age_days']}</td>
                    <td>{reasons}</td>
                </tr>
                """

        return f"""
        <p class="risk-sub">Open defects older than {risk_age_days} days are auto-flagged for immediate action.</p>
        <div class="risk-wrap">
            <table class="risk-table">
                <thead>
                    <tr>
                        <th>Defect ID</th>
                        <th>Summary</th>
                        <th>Severity</th>
                        <th>Reporter</th>
                        <th>Status</th>
                        <th>Age (days)</th>
                        <th>Risk Flags</th>
                    </tr>
                </thead>
                <tbody>{body}</tbody>
            </table>
        </div>
        """


def render_closure_metrics_section(defects: dict) -> str:
        metrics = defects.get("closure_metrics", {}) if isinstance(defects, dict) else {}
        projects = metrics.get("projects", []) if isinstance(metrics, dict) else []
        rows = metrics.get("rows", []) if isinstance(metrics, dict) else []
        if not projects or not rows:
                return '<p class="empty">No closure metrics available for the selected filters.</p>'

        team_scope = escape(str(metrics.get("team_scope") or "All"))
        start_date = escape(str(metrics.get("start_date") or ""))
        end_date = escape(str(metrics.get("end_date") or ""))
        previous_start_date = escape(str(metrics.get("previous_start_date") or ""))
        previous_end_date = escape(str(metrics.get("previous_end_date") or ""))

        row_by_key = {str(r.get("key", "")): r for r in rows}

        closed_row = row_by_key.get("closed_total", {})
        duplicate_row = row_by_key.get("closed_duplicate", {})
        resolved_row = row_by_key.get("resolved_status", {})
        integrated_row = row_by_key.get("integrated_status", {})
        done_row = row_by_key.get("closed_done", {})
        wont_do_row = row_by_key.get("closed_wont_do", {})
        rejected_deficient_row = row_by_key.get("closed_rejected_deficient", {})
        cannot_repro_row = row_by_key.get("closed_cannot_reproduce", {})

        total_closed = int(closed_row.get("total", 0) or 0)
        previous_total_closed = int(closed_row.get("previous_total", 0) or 0)
        total_defects_scoped = int(defects.get("telematics_count", 0) or 0)

        closure_rate = (total_closed / total_defects_scoped * 100.0) if total_defects_scoped > 0 else 0.0
        duplicate_total = int(duplicate_row.get("total", 0) or 0)
        duplicate_pct = (duplicate_total / total_closed * 100.0) if total_closed > 0 else 0.0
        rejected_deficient_total = int(rejected_deficient_row.get("total", 0) or 0)
        rejected_deficient_pct = (rejected_deficient_total / total_closed * 100.0) if total_closed > 0 else 0.0
        cannot_repro_total = int(cannot_repro_row.get("total", 0) or 0)
        wont_do_total = int(wont_do_row.get("total", 0) or 0)
        resolved_total = int(resolved_row.get("total", 0) or 0)
        integrated_total = int(integrated_row.get("total", 0) or 0)
        done_total = int(done_row.get("total", 0) or 0)
        closure_status_total = total_closed + resolved_total + integrated_total
        resolved_pct = (resolved_total / closure_status_total * 100.0) if closure_status_total > 0 else 0.0
        integrated_pct = (integrated_total / closure_status_total * 100.0) if closure_status_total > 0 else 0.0
        done_pct = (done_total / closure_status_total * 100.0) if closure_status_total > 0 else 0.0

        # Everything that represents genuine progress (a real fix), vs. outcomes that
        # closed a ticket without changing the product - the single clearest signal
        # of whether this period's resolution activity was actually productive.
        fixed_total = done_total + resolved_total + integrated_total
        non_actionable_total = duplicate_total + rejected_deficient_total + cannot_repro_total + wont_do_total
        resolution_activity_total = fixed_total + non_actionable_total
        fixed_pct = (fixed_total / resolution_activity_total * 100.0) if resolution_activity_total > 0 else 0.0
        non_actionable_pct = (non_actionable_total / resolution_activity_total * 100.0) if resolution_activity_total > 0 else 0.0

        # Defect Solution Time (Dwell): average days between creation and resolution
        # for defects actually closed in this window.
        closed_details = closed_row.get("details", []) if isinstance(closed_row.get("details", []), list) else []
        dwell_pairs = [(str(d.get("key", "")), d["dwell_days"]) for d in closed_details if isinstance(d.get("dwell_days"), int)]
        dwell_values = [days for _, days in dwell_pairs]
        dwell_sum = sum(dwell_values)
        avg_dwell_days = (dwell_sum / len(dwell_values)) if dwell_values else 0.0
        # Surfaced in the Avg Dwell Time popup so readers can see which tickets are
        # skewing the average, instead of just trusting a single number.
        dwell_outliers_note = ""
        if dwell_pairs:
            top_dwell = sorted(dwell_pairs, key=lambda pair: -pair[1])[:3]
            top_dwell_str = ", ".join(f"{key} ({days}d)" for key, days in top_dwell)
            dwell_outliers_note = f" Longest-dwelling ticket(s) this period: {top_dwell_str}."
        # Full per-ticket breakdown for the popup table (every defect that fed the
        # average, not just the top-3 outliers), sorted by key to match how it's
        # reviewed manually.
        dwell_table_rows = sorted(
            (
                {
                    "key": str(d.get("key", "")),
                    "created": str(d.get("created", "") or "N/A")[:10],
                    "resolved": str(d.get("resolved", "") or "N/A")[:10],
                    "dwell": d["dwell_days"],
                }
                for d in closed_details if isinstance(d.get("dwell_days"), int)
            ),
            key=lambda row: row["key"],
        )
        dwell_table_json = escape(json.dumps(dwell_table_rows))

        # Backlog trend: defects raised this window vs. defects closed this window.
        # Positive means the open backlog is growing faster than it is being worked down.
        backlog_net_change = total_defects_scoped - total_closed
        # Full per-ticket breakdown for the Backlog Trend popup, same pattern as the
        # Avg Dwell Time table above: every raised defect and every closed defect that
        # fed the two counts, not just the net number.
        backlog_table_rows = sorted(
            (
                {
                    "type": "Raised",
                    "key": str(row.get("key", "")),
                    "date": str(row.get("created", "") or "N/A")[:10],
                    "status": str(row.get("status", "") or "N/A"),
                }
                for row in (defects.get("rows", []) or [])
            ),
            key=lambda row: row["key"],
        ) + sorted(
            (
                {
                    "type": "Closed",
                    "key": str(d.get("key", "")),
                    "date": str(d.get("resolved", "") or "N/A")[:10],
                    "status": str(d.get("resolution", "") or "N/A"),
                }
                for d in closed_details
            ),
            key=lambda row: row["key"],
        )
        backlog_table_json = escape(json.dumps(backlog_table_rows))

        open_critical = 0
        for defect in defects.get("rows", []) or []:
                status = str(defect.get("status", ""))
                priority = str(defect.get("priority", ""))
                if (not is_closed_defect_status(status)) and ("critical" in priority.lower() or "blocker" in priority.lower()):
                        open_critical += 1

        trend_delta = total_closed - previous_total_closed
        trend_arrow = "&#8593;" if trend_delta > 0 else ("&#8595;" if trend_delta < 0 else "&#8594;")
        trend_class = "trend-up" if trend_delta > 0 else ("trend-down" if trend_delta < 0 else "trend-flat")
        trend_text = f"{trend_delta:+d} vs previous period"

        raw_score = closure_rate - (duplicate_pct * 0.6) - (open_critical * 4) + (2 if trend_delta > 0 else 0)
        team_score = max(0, min(100, round(raw_score)))

        closed_counts = closed_row.get("counts", {}) if isinstance(closed_row.get("counts", {}), dict) else {}
        top_project = "N/A"
        top_project_count = 0
        for p in projects:
                value = int(closed_counts.get(p, 0) or 0)
                if value > top_project_count:
                        top_project_count = value
                        top_project = p

        observations = []
        if open_critical > 0:
                observations.append(f"{open_critical} open critical defects require immediate containment.")
        if resolution_activity_total > 0 and non_actionable_pct >= 50:
                observations.append(
                        f"Only {fixed_pct:.1f}% of this period's resolution activity reflects actual fixes "
                        f"(Done/Resolved/Integrated); {non_actionable_pct:.1f}% were non-actionable "
                        f"(Duplicate/Rejected/Deficient/Cannot Reproduce/Won't Do)."
                )
        if total_defects_scoped > 0 and closure_rate < 50:
                observations.append(
                        f"Closure rate is low at {closure_rate:.1f}% ({total_closed} of {total_defects_scoped} "
                        f"raised defects closed); backlog may be growing."
                )
        if duplicate_pct >= 20:
                observations.append(f"Duplicate ratio is high at {duplicate_pct:.1f}%.")
        if rejected_deficient_pct >= 25:
                observations.append(
                        f"Rejected/Deficient ratio is high at {rejected_deficient_pct:.1f}%; review defect "
                        "submission quality with the reporting team."
                )
        if cannot_repro_total > 0:
                observations.append(f"{cannot_repro_total} defects are closed as Cannot Reproduce.")
        if wont_do_total > 0:
                observations.append(f"{wont_do_total} defects closed as Won't Do (accepted as known limitations).")
        if trend_delta < 0:
                observations.append("Closure throughput decreased versus previous period.")
        if not observations:
                observations.append("Closure behavior is stable with no immediate red flags.")

        backlog_trend_word = "growing" if backlog_net_change > 0 else ("shrinking" if backlog_net_change < 0 else "stable")
        summary_banner = (
                f"Executive Summary: Team {team_scope} closed {total_closed} defects in this resolution window. "
                f"Top performing project is {escape(top_project)} ({top_project_count} closures). "
                f"Backlog is {backlog_trend_word} this period: {total_defects_scoped} raised vs {total_closed} closed "
                f"(net {backlog_net_change:+d})."
        )

        def render_product_pie(product_counts: dict, title: str) -> str:
            if not isinstance(product_counts, dict):
                return ""

            items = []
            palette = {
                "IDC23": "#0066B1",
                "IDCEVO-25": "#22C55E",
                "CDE/RSE": "#F59E0B",
            }
            total = 0
            for rule in PRODUCT_CLOSURE_RULES:
                label = str(rule["label"])
                value = int(product_counts.get(label, 0) or 0)
                if value > 0:
                    total += value
                    items.append((label, value, palette.get(label, "#94A3B8")))

            if total == 0:
                return '<div class="closure-product-empty">No mapped product data for this category.</div>'

            start = 0.0
            stops = []
            legend = []
            for label, value, color in items:
                pct = (value / total) * 100.0
                end = start + pct
                stops.append(f"{color} {start:.2f}% {end:.2f}%")
                legend.append(f'<li><span class="legend-swatch" style="background:{color}"></span>{escape(label)}: <b>{value}</b></li>')
                start = end

            return f"""
            <div class="closure-product-pie" title="{escape(title)}">
                <div class="closure-product-ring" style="background: conic-gradient({', '.join(stops)});">
                <div class="closure-product-hole">
                    <b>{total}</b>
                    <span>defects</span>
                </div>
                </div>
                <ul class="closure-product-legend">{''.join(legend)}</ul>
            </div>
            """

        product_ring_cards = ""
        total_product_counts = closed_row.get("product_counts", {}) if isinstance(closed_row.get("product_counts", {}), dict) else {}
        total_product_sum = sum(int(v or 0) for v in total_product_counts.values())
        # total_product_sum can be lower than total_closed: a closed defect's project/variant/ECU
        # doesn't always match one of the three tracked product rules (e.g. ICONSD tickets).
        unmapped_closed = max(total_closed - total_product_sum, 0)
        for rule in PRODUCT_CLOSURE_RULES:
            label = str(rule["label"])
            closed = int(total_product_counts.get(label, 0) or 0)
            share_pct = (closed / total_product_sum * 100.0) if total_product_sum > 0 else 0.0
            ring_bg = f"conic-gradient(#0066B1 0% {share_pct:.2f}%, #E5E7EB {share_pct:.2f}% 100%)" if total_product_sum > 0 else "conic-gradient(#E5E7EB 0% 100%)"
            product_ring_cards += f"""
                <article class="closure-ring-card">
                <div class="closure-ring-head"><span class="tlm-icon" aria-hidden="true"></span>{escape(label)}</div>
                <div class="closure-ring-sub">{escape(str(rule['scope_label']))}</div>
                    <div class="closure-ring" style="background: {ring_bg};">
                        <div class="closure-ring-inner">
                            <b>{closed}</b>
                            <span>{share_pct:.1f}%</span>
                        </div>
                    </div>
                    <div class="closure-ring-note">{closed} of {total_product_sum} total closures this period</div>
                </article>
            """

        bar_palette = {
                "closed_total": "#22C55E",
                "closed_duplicate": "#F59E0B",
                "closed_rejected_deficient": "#0066B1",
            "resolved_status": "#2563EB",
            "integrated_status": "#7C3AED",
                "closed_cannot_reproduce": "#EF4444",
                "closed_done": "#22C55E",
                "closed_wont_do": "#7C2D12",
        }
        max_bucket_total = max([int(r.get("total", 0) or 0) for r in rows] + [1])

        metric_pie_cards = ""
        bars_html = ""
        for row in rows:
                key = str(row.get("key", ""))
                label = escape(str(row.get("label", "")))
                total = int(row.get("total", 0) or 0)
                prev_total = int(row.get("previous_total", 0) or 0)
                delta = total - prev_total
                delta_arrow = "&#8593;" if delta > 0 else ("&#8595;" if delta < 0 else "&#8594;")
                delta_class = "trend-up" if delta > 0 else ("trend-down" if delta < 0 else "trend-flat")
                width_pct = (total / max_bucket_total) * 100.0
                color = bar_palette.get(key, "#0066B1")
                counts = row.get("counts", {}) if isinstance(row.get("counts", {}), dict) else {}
                product_counts = row.get("product_counts", {}) if isinstance(row.get("product_counts", {}), dict) else {}
                defect_details = row.get("details", []) if isinstance(row.get("details", []), list) else []

                if key == "closed_total":
                    resolved_product_counts = resolved_row.get("product_counts", {}) if isinstance(resolved_row.get("product_counts", {}), dict) else {}
                    metric_pie_cards += f"""
                    <article class="closure-metric-pie-card">
                        <div class="closure-metric-pie-title">{label}</div>
                        <div class="closure-metric-pie-dual">
                            <div class="closure-metric-pie-sub">
                                <span class="closure-metric-pie-sublabel">Closed</span>
                                {render_product_pie(product_counts, str(row.get('label', '')))}
                            </div>
                            <div class="closure-metric-pie-sub">
                                <span class="closure-metric-pie-sublabel">Resolved</span>
                                {render_product_pie(resolved_product_counts, "Resolved (Done/Unresolved)")}
                            </div>
                        </div>
                    </article>
                    """
                elif key != "resolved_status":
                    # Resolved is shown as a second ring inside the "Closed" card above, not its own card.
                    metric_pie_cards += f"""
                    <article class="closure-metric-pie-card">
                        <div class="closure-metric-pie-title">{label}</div>
                        {render_product_pie(product_counts, str(row.get('label', '')))}
                    </article>
                    """

                breakdown = " | ".join(f"{escape(p)}: {int(counts.get(p, 0) or 0)}" for p in projects)
                ids_block = ""
                if defect_details:
                    detail_rows = []
                    for item in defect_details:
                        issue_key = escape(str(item.get("key", "")))
                        issue_project = escape(str(item.get("project", "")))
                        issue_resolution = escape(str(item.get("resolution", "N/A") or "N/A"))
                        issue_summary = escape(str(item.get("summary", ""))) or "N/A"
                        issue_reporter = escape(str(item.get("reporter", "Unknown") or "Unknown"))
                        issue_created = escape(str(item.get("created", "N/A") or "N/A"))
                        assigned_ecu = escape(str(item.get("assigned_ecu", "N/A")))
                        found_in_sw = escape(str(item.get("found_in_sw_version", "N/A")))
                        comment_texts = item.get("comment_texts", []) if isinstance(item.get("comment_texts", []), list) else []
                        if key == "closed_duplicate":
                            duplicate_comment = summarize_duplicate_comments(comment_texts, item.get("duplicate_ids"))
                            duplicate_references = item.get("duplicate_references", [])
                            duplicate_summaries = " | ".join(
                                f"{reference.get('key', 'Unknown')}: {reference.get('summary', 'Summary unavailable')}"
                                for reference in duplicate_references
                            )
                            duplicate_details = (
                                f"Created: {item.get('created', 'N/A') or 'N/A'} | "
                                f"Found in SW version under TAEE: {item.get('found_in_sw_version', 'N/A') or 'N/A'} | "
                                f"Assigned ECU: {item.get('assigned_ecu', 'N/A') or 'N/A'} | "
                                f"Variant: {item.get('variant', 'N/A') or 'N/A'}"
                            )
                            duplicate_summary_text = f"Duplicate defect summary: {duplicate_summaries} | " if duplicate_summaries else ""
                            # Prefer the first referenced ticket actually resolvable in Jira
                            # (many "Duplicate of" IDs are from other tracking systems) so the
                            # comment shows the master ticket's own created date/SW version.
                            master_reference = next(
                                (reference for reference in duplicate_references if str(reference.get("created", "N/A") or "N/A") != "N/A"),
                                None,
                            )
                            if master_reference:
                                display_created = escape(str(master_reference.get("created", "N/A") or "N/A"))
                                display_sw_version = escape(str(master_reference.get("found_in_sw_version", "N/A") or "N/A"))
                            else:
                                display_created = issue_created
                                display_sw_version = escape(str(item.get('found_in_sw_version', 'N/A') or 'N/A'))
                            comment_summary_text = f"{duplicate_comment} {duplicate_summary_text}<b>Created: {display_created}</b> | Found in SW version under TAEE: {display_sw_version} | Assigned ECU: {escape(str(item.get('assigned_ecu', 'N/A') or 'N/A'))} | Variant: {escape(str(item.get('variant', 'N/A') or 'N/A'))}"
                        else:
                            comment_summary_text = escape(str(item.get("comment_summary", "No recent comments available.")))
                            comment_summary_text += f"<br><b>Created: {issue_created}</b>"
                        comment_summary = comment_summary_text if key == "closed_duplicate" else comment_summary_text
                        detail_rows.append(
                            f"""
                            <tr>
                                <td><a href="{JIRA_BASE_URL}/browse/{issue_key}" target="_blank">{issue_key}</a></td>
                                <td>{issue_project}</td>
                                <td>{issue_resolution}</td>
                                <td>{issue_summary}</td>
                                <td>{issue_reporter}</td>
                                <td>{issue_created}</td>
                                <td>{assigned_ecu}</td>
                                <td>{found_in_sw}</td>
                                <td>{comment_summary}</td>
                            </tr>
                            """
                        )
                    ids_block = (
                        '<details class="closure-ids"><summary>Defect Details</summary>'
                        '<div class="closure-detail-table-wrap">'
                        + (
                            f'<p class="closure-overall-summary"><b>Overall summary (last 4-5 comments across tickets):</b> {escape(summarize_bucket_overall_comments(defect_details))}</p>'
                            if key in {"closed_rejected_deficient", "closed_duplicate"}
                            else ""
                        )
                        + '<table class="closure-detail-table">'
                        '<thead><tr><th>Key</th><th>Project</th><th>Resolution</th><th>Summary</th><th>Reporter</th><th>Creation Date</th><th>Assigned ECU</th><th>Found in SW version</th><th>Comment summary</th></tr></thead>'
                        f'<tbody>{"".join(detail_rows)}</tbody>'
                        '</table></div></details>'
                    )

                bars_html += f"""
                <div class="closure-bar-row">
                    <div class="closure-bar-head">
                        <span>{label}</span>
                        <span class="{delta_class}">{delta_arrow} {delta:+d}</span>
                    </div>
                    <div class="closure-bar-track"><div class="closure-bar-fill" style="width:{width_pct:.1f}%; background:{color};"></div></div>
                    <div class="closure-bar-meta"><b>{total}</b> ({breakdown})</div>
                    {ids_block}
                </div>
                """

        observations_html = "".join(f"<li>{escape(item)}</li>" for item in observations)

        # Root-cause Pareto: rank the non-actionable closure reasons by volume so a
        # reader can see how few root causes explain most of this period's non-fixes.
        pareto_items = sorted(
            (
                ("Rejected/Deficient", rejected_deficient_total),
                ("Duplicate", duplicate_total),
                ("Cannot Reproduce", cannot_repro_total),
                ("Won't Do", wont_do_total),
            ),
            key=lambda item: -item[1],
        )
        pareto_total = sum(count for _, count in pareto_items)
        max_pareto_count = max((count for _, count in pareto_items), default=0) or 1
        pareto_rows_html = ""
        cumulative = 0
        for label, count in pareto_items:
            if count <= 0:
                continue
            cumulative += count
            share_pct = (count / pareto_total * 100.0) if pareto_total > 0 else 0.0
            cumulative_pct = (cumulative / pareto_total * 100.0) if pareto_total > 0 else 0.0
            width_pct = (count / max_pareto_count * 100.0) if max_pareto_count > 0 else 0.0
            pareto_rows_html += f"""
                <div class="pareto-row">
                    <div class="pareto-label">{escape(label)}</div>
                    <div class="pareto-bar-track"><div class="pareto-bar-fill" style="width:{width_pct:.1f}%;"></div></div>
                    <div class="pareto-value">{count} ({share_pct:.1f}%)</div>
                    <div class="pareto-cumulative">Cumulative: {cumulative_pct:.1f}%</div>
                </div>
            """
        if not pareto_rows_html:
            pareto_rows_html = '<p class="empty">No non-actionable closures in this period.</p>'

        return f"""
        <section class="closure-exec-wrap">
            <div class="closure-summary-banner">{summary_banner}</div>
            <p class="risk-sub">Team wise filter: <b>{team_scope}</b> | Resolution date range: <b>{start_date}</b> to <b>{end_date}</b> | Previous: <b>{previous_start_date}</b> to <b>{previous_end_date}</b></p>

            <div class="closure-kpi-grid">
                <article class="closure-kpi kpi-green"><i class="kpi-mark">CL</i><span>Total Defects Closed</span><b>{total_closed}</b><small class="{trend_class}">{trend_arrow} {trend_text}</small></article>
                <article class="closure-kpi kpi-navy" data-info-title="Closed + Resolved" data-info-text="Combines the Closed (Status = Closed) and Resolved (Done/Unresolved) counts into one figure. Closed means verified done; Resolved means a fix was proposed but not yet verified - kept separate elsewhere in this report, combined here for a single at-a-glance total that matches a status in (Resolved, Closed) JQL query."><i class="kpi-mark">CR</i><span>Closed + Resolved</span><b>{total_closed + resolved_total}</b><small>Closed: {total_closed} | Resolved: {resolved_total}</small></article>
                <article class="closure-kpi kpi-blue"><i class="kpi-mark">RS</i><span>Resolved %</span><b>{resolved_pct:.1f}%</b><small>Resolved count: {resolved_total}</small></article>
                <article class="closure-kpi kpi-red"><i class="kpi-mark">IG</i><span>Integrated %</span><b>{integrated_pct:.1f}%</b><small>Integrated count: {integrated_total}</small></article>
                <article class="closure-kpi kpi-amber"><i class="kpi-mark">DP</i><span>Duplicate Defects %</span><b>{duplicate_pct:.1f}%</b><small>Duplicate count: {duplicate_total}</small></article>
                <article class="closure-kpi kpi-amber"><i class="kpi-mark">RD</i><span>Rejected/Deficient %</span><b>{rejected_deficient_pct:.1f}%</b><small>Rejected/Deficient count: {rejected_deficient_total}</small></article>
                <article class="closure-kpi kpi-navy"><i class="kpi-mark">DN</i><span>Closed as Done %</span><b>{done_pct:.1f}%</b><small>Done count: {done_total}</small></article>
                <article class="closure-kpi kpi-blue" data-info-title="Avg Dwell Time" data-info-text="Avg Dwell Time = average number of days between a defect's Created date and its Resolved/Closed date, measured only across defects actually closed in this resolution window. It answers 'once a defect is raised, how long does it typically sit open before being resolved?' A lower number means faster turnaround; a higher number means defects are lingering longer before resolution. Only defects with both a created and resolution date are included in the average. For this report: {len(dwell_values)} closed defect(s) totaled {dwell_sum} day(s) of dwell time -&gt; {dwell_sum} &divide; {len(dwell_values)} = {avg_dwell_days:.1f}d average.{dwell_outliers_note}" data-info-rows="{dwell_table_json}"><i class="kpi-mark">DW</i><span>Avg Dwell Time</span><b>{avg_dwell_days:.1f}d</b><small>Created &rarr; resolved, closed defects: {len(dwell_values)} | Total dwell: {dwell_sum}d</small></article>
                <article class="closure-kpi {'kpi-red' if backlog_net_change > 0 else 'kpi-green'}" data-info-title="Backlog Trend" data-info-text="Backlog Trend = (defects raised this period) minus (defects closed this period). A positive number means the backlog is growing (more coming in than being closed); negative means it's shrinking. Note: raised and closed are independent counts for the same calendar window, not the same cohort of defects - a defect closed this week may have been raised weeks or months ago. For this report: {total_defects_scoped} raised - {total_closed} closed = {backlog_net_change:+d}." data-info-rows="{backlog_table_json}"><i class="kpi-mark">BK</i><span>Backlog Trend</span><b>{backlog_net_change:+d}</b><small>{'Growing' if backlog_net_change > 0 else ('Shrinking' if backlog_net_change < 0 else 'Stable')} ({total_defects_scoped} raised vs {total_closed} closed)</small></article>
            </div>

            <div class="metric-glossary">
                <div class="metric-glossary-title">Key Metrics Explained</div>
                <div class="metric-glossary-item">
                    <b>Avg Dwell Time</b> - average number of days between a defect's Created date and
                    its Resolved/Closed date, measured only across defects actually closed in this
                    resolution window. Answers "once raised, how long does a defect typically sit open
                    before being resolved?" Lower = faster turnaround, higher = defects lingering
                    longer. Click the KPI above for the full per-ticket breakdown.
                </div>
                <div class="metric-glossary-item">
                    <b>Backlog Trend</b> - (defects raised this period) minus (defects closed this
                    period). Positive means the backlog is growing (more coming in than being closed);
                    negative means it's shrinking. Raised and closed are independent counts for the
                    same calendar window, not the same cohort - a defect closed this week may have been
                    raised weeks or months ago. Click the KPI above for the full raised/closed list.
                </div>
            </div>

            <div class="risk-sub"><b>Product Closure Rate</b> - each product's share of this period's total closures, derived from project and variant or assigned ECU mapping.{f' {unmapped_closed} closed defect(s) could not be mapped to a tracked product and are excluded from this breakdown.' if unmapped_closed else ''}</div>
            <div class="closure-project-rings">{product_ring_cards}</div>

            <div class="section-title closure-inline-title">Defect wise metrics</div>
            <div class="closure-metric-pies">{metric_pie_cards}</div>

            <details class="closure-bars-toggle" open>
                <summary>Hide or show closure breakdown</summary>
                <div class="closure-bars-wrap">{bars_html}</div>
            </details>

            <div class="section-title closure-inline-title">Root Cause Pareto - Non-Actionable Closures</div>
            <p class="risk-sub">Ranked by volume with cumulative share, so you can see how few root causes explain most of this period's non-productive closures (Duplicate/Rejected/Deficient/Cannot Reproduce/Won't Do).</p>
            <div class="pareto-wrap">{pareto_rows_html}</div>

            <div class="closure-insights">
                <article class="closure-insight-card"><h4>Top Performing Team</h4><p>{escape(top_project)} ({top_project_count} closures)</p></article>
                <article class="closure-insight-card"><h4>Risk Areas Requiring Attention</h4><ul>{observations_html}</ul></article>
            </div>
        </section>
        """


def build_defect_executive_section(
    defects: dict,
    start_date: str,
    end_date: str,
    report_scopes: set[str] | None = None,
) -> str:
        analytics = compute_defect_analytics(defects, start_date, end_date)
        sev = analytics["severity_counts"]
        open_count = analytics["open_count"]
        closed_count = analytics["closed_count"]
        escalation_counts = analytics["escalation_counts"]
        trend_delta = analytics["trend_delta"]
        trend_sign = "+" if trend_delta > 0 else ""
        trend_pct = analytics["trend_pct"]
        trend_note = f"{trend_sign}{trend_delta} vs previous week"
        if analytics["previous_week_count"] > 0:
                trend_note += f" ({trend_sign}{trend_pct:.1f}%)"

        exploratory_pct = (analytics["exploratory_count"] / analytics["total"] * 100.0) if analytics["total"] > 0 else 0.0
        defect_observations = []
        if analytics["open_critical_count"] > 0:
                defect_observations.append(f"{analytics['open_critical_count']} open critical defects need immediate attention.")
        if analytics["risk_total_count"] > 0:
                defect_observations.append(
                        f"{analytics['risk_total_count']} defects flagged high-risk this period (critical severity, "
                        f"customer-impacting, blocking, or open more than {analytics['risk_age_days']} days)."
                )
        if analytics["total"] > 0 and exploratory_pct >= 50:
                defect_observations.append(
                        f"Exploratory (ET) defects make up {exploratory_pct:.1f}% of this period's total; most volume "
                        "came from exploratory testing rather than planned SV execution."
                )
        if analytics["previous_week_count"] > 0 and trend_delta > 0 and trend_pct >= 25:
                defect_observations.append(
                        f"Defect intake rose {trend_pct:.1f}% vs the previous period "
                        f"({analytics['previous_week_count']} to {analytics['total']})."
                )
        if not defect_observations:
                defect_observations.append("Defect intake is stable with no immediate red flags.")

        reporter_defect_links: dict[str, list[dict[str, str]]] = {}
        component_defect_links: dict[str, list[dict[str, str]]] = {}
        for defect in defects.get("rows", []) or []:
            defect_key = str(defect.get("key") or "").strip()
            if not defect_key:
                continue
            defect_link = {"key": defect_key, "url": f"{JIRA_BASE_URL}/browse/{defect_key}"}
            reporter_name = str(defect.get("reporter") or "Unknown").strip() or "Unknown"
            component_name = str(defect.get("assigned_ecu") or "Unknown").strip() or "Unknown"
            reporter_defect_links.setdefault(reporter_name, []).append(defect_link)
            component_defect_links.setdefault(component_name, []).append(defect_link)

        chart_data = {
                "severity": [
                        {"label": "Critical", "value": sev["Critical"], "color": "#C62828"},
                        {"label": "High", "value": sev["High"], "color": "#EF6C00"},
                        {"label": "Medium", "value": sev["Medium"], "color": "#F9A825"},
                        {"label": "Low", "value": sev["Low"], "color": "#1565C0"},
                ],
                "reporters": [
                    {"label": k, "value": v, "defects": reporter_defect_links.get(k, [])}
                    for k, v in sorted(analytics["reporter_counts"].items(), key=lambda it: (-it[1], it[0]))[:10]
                ],
                "reporter_projects": analytics["et_reporter_product_counts"],
                "weekly_defects": analytics["weekly_defect_counts"],
                "components": [
                    {"label": k, "value": v, "defects": component_defect_links.get(k, [])}
                    for k, v in sorted(analytics["component_counts"].items(), key=lambda it: (-it[1], it[0]))[:10]
                ],
                "exploratory": [
                        {"label": "Exploratory", "value": analytics["exploratory_count"], "color": "#0066B1"},
                        {"label": "Regular", "value": analytics["regular_count"], "color": "#90A4AE"},
                ],
                "similiaize_coverage": analytics["similiaize_coverage"],
        }

        return f"""
        <section class="defect-exec-dashboard">
            <div data-scope-panel="defect" class="scope-panel">
            <div class="section-title">Executive Defect Dashboard</div>

            <div class="defect-kpis{' scope-hidden' if 'defect' not in report_scopes else ''}">
                <div class="defect-kpi kpi-total"><span>Total Defects</span><b>{analytics['total']}</b></div>
                <div class="defect-kpi kpi-critical"><span>Critical Defects</span><b>{sev['Critical']}</b></div>
                <div class="defect-kpi kpi-high"><span>High Defects</span><b>{sev['High']}</b></div>
                <div class="defect-kpi kpi-medium"><span>Medium Defects</span><b>{sev['Medium']}</b></div>
                <div class="defect-kpi kpi-exploratory"><span>Exploratory Defects</span><b>{analytics['exploratory_count']}</b></div>
                <div class="defect-kpi kpi-openclosed"><span>Open vs Closed</span><b>{open_count} / {closed_count}</b></div>
            </div>

            <div class="defect-chart-grid{' scope-hidden' if 'defect' not in report_scopes else ''}">
                <article class="chart-card">
                    <h3>Severity Distribution</h3>
                    <div id="chart-severity" class="chart-host"></div>
                </article>
                <article class="chart-card">
                    <h3>Defects Raised With and Without Similiaize Tool</h3>
                    <div id="chart-similiaize-coverage" class="chart-host"></div>
                </article>
                <article class="chart-card">
                    <h3>Defects by Reporter</h3>
                    <div id="chart-reporters" class="chart-host bar-chart-host"></div>
                </article>
                <article class="chart-card">
                    <h3>Defects by Assigned ECU</h3>
                    <div id="chart-components" class="chart-host bar-chart-host"></div>
                </article>
                <article class="chart-card">
                    <h3>Exploratory vs Regular</h3>
                    <div id="chart-exploratory" class="chart-host"></div>
                </article>
                <article class="chart-card">
                    <h3>ET Defects by Problem Finder and Product</h3>
                    <div id="chart-reporter-projects" class="chart-host"></div>
                </article>
                <article class="chart-card">
                    <h3>Defects Raised by Calendar Week</h3>
                    <div id="chart-weekly-defects" class="chart-host bar-chart-host"></div>
                </article>
            </div>

            <div class="weekly-insights{' scope-hidden' if 'defect' not in report_scopes else ''}">
                <article class="insight-card"><h4>Defects This Week ({analytics['week_label']})</h4><p>{analytics['total']}</p></article>
                <article class="insight-card"><h4>Trend Vs Previous Week</h4><p>{trend_note}</p></article>
                <article class="insight-card"><h4>Top Affected Component</h4><p>{escape(str(analytics['top_domain']))}</p></article>
                <article class="insight-card"><h4>Most Active Reporter</h4><p>{escape(str(analytics['top_reporter']))}</p></article>
            </div>

            <div class="section-title{' scope-hidden' if 'defect' not in report_scopes else ''}">Escalation Categories (Open)</div>
            <div class="defect-kpis{' scope-hidden' if 'defect' not in report_scopes else ''}">
                <div class="defect-kpi kpi-critical"><span>TIC</span><b>{escalation_counts.get('TIC', 0)}</b></div>
                <div class="defect-kpi kpi-critical"><span>Showstopper</span><b>{escalation_counts.get('Showstopper', 0)}</b></div>
                <div class="defect-kpi kpi-high"><span>PM Issue</span><b>{escalation_counts.get('PM Issue', 0)}</b></div>
                <div class="defect-kpi kpi-medium"><span>Top Candidate</span><b>{escalation_counts.get('Top Candidate', 0)}</b></div>
                <div class="defect-kpi kpi-high"><span>SI Blocker</span><b>{escalation_counts.get('SI Blocker', 0)}</b></div>
            </div>

            <div class="section-title{' scope-hidden' if 'defect' not in report_scopes else ''}">Key Observations</div>
            <div class="closure-insights{' scope-hidden' if 'defect' not in report_scopes else ''}" style="grid-template-columns: 1fr;">
                <article class="closure-insight-card"><h4>Risk Areas Requiring Attention</h4><ul>{''.join(f'<li>{escape(item)}</li>' for item in defect_observations)}</ul></article>
            </div>

            <div class="section-title{' scope-hidden' if 'defect' not in report_scopes else ''}">Top Risk Defects</div>
            <div class="{'scope-hidden' if 'defect' not in report_scopes else ''}">{render_top_risk_section(analytics['risk_rows'], analytics['risk_age_days'])}</div>

            <div class="section-title{' scope-hidden' if 'defect' not in report_scopes else ''}">Defects by Severity (Collapsible)</div>
            <div class="defect-accordions{' scope-hidden' if 'defect' not in report_scopes else ''}">
                {render_severity_accordions(analytics['grouped'])}
            </div>
            </div>

            <div data-scope-panel="resolution" class="scope-panel">
                <div class="section-title">Team-wise Defect Closure Metrics</div>
                {render_closure_metrics_section(defects)}
            </div>
            <script id="defect-chart-data" type="application/json">{json.dumps(chart_data).replace('</', '<\\/')}</script>
        </section>
        """


def build_adhoc_effort_section(adhoc: dict) -> str:
    if not adhoc:
        return ""

    rows = adhoc.get("rows", []) or []
    total_requests = int(adhoc.get("total_requests", 0) or 0)
    total_effort_hours = float(adhoc.get("total_effort_hours", 0.0) or 0.0)
    avg_effort_per_request = float(adhoc.get("avg_effort_per_request", 0.0) or 0.0)
    total_resources = int(adhoc.get("total_resources", 0) or 0)
    idc23_effort = float(adhoc.get("idc23_effort", 0.0) or 0.0)
    idcevo_effort = float(adhoc.get("idcevo_effort", 0.0) or 0.0)

    category_distribution = adhoc.get("category_distribution", {}) or {}
    product_distribution = adhoc.get("product_distribution", {}) or {}
    assignee_distribution = adhoc.get("assignee_distribution", {}) or {}
    effort_by_product = adhoc.get("effort_by_product", {}) or {}
    effort_by_category = adhoc.get("effort_by_category", {}) or {}
    category_counts_by_product = adhoc.get("category_counts_by_product", {}) or {}
    product_resource_utilization = adhoc.get("product_resource_utilization", []) or []
    assignee_per_product = adhoc.get("assignee_per_product", []) or []
    week_wise_calculation = adhoc.get("week_wise_calculation", []) or []
    tms_account_requests = int(category_distribution.get(ADHOC_CATEGORY_TMS_ACCOUNT, 0) or 0)
    digital_premium_requests = int(category_distribution.get(ADHOC_CATEGORY_DIGITAL_PREMIUM, 0) or 0)
    support_requests = int(category_distribution.get(ADHOC_CATEGORY_TELEMATICS_SUPPORT, 0) or 0)

    def _dist_rows(distribution: dict, unit: str, color: str) -> str:
        if not distribution:
            return '<p class="empty">No data available.</p>'
        max_value = max(distribution.values()) if distribution else 1
        lines = []
        for label, value in sorted(distribution.items(), key=lambda item: (-item[1], item[0])):
            pct = (float(value) / float(max_value) * 100.0) if max_value else 0.0
            lines.append(
                f'<div class="adhoc-bar-row"><div class="adhoc-bar-label">{escape(str(label))}</div>'
                f'<div class="adhoc-bar-track"><div class="adhoc-bar-fill" style="width:{pct:.1f}%; background:{color};"></div></div>'
                f'<div class="adhoc-bar-value">{value} {unit}</div></div>'
            )
        return "".join(lines)

    top_assignees = dict(sorted(assignee_distribution.items(), key=lambda item: (-item[1], item[0]))[:10])
    effort_distribution_rows = _dist_rows(
        {name: round(hours, 2) for name, hours in sorted((adhoc.get("effort_by_assignee", {}) or {}).items(), key=lambda item: (-item[1], item[0]))[:10]},
        "h",
        "#7C3AED",
    )
    effort_by_product_display = {
        name: value for name, value in effort_by_product.items()
        if str(name).strip().upper() != "OTHERS"
    }

    table_rows = "".join(
        "<tr>"
        f"<td><a href=\"{JIRA_BASE_URL}/browse/{escape(str(item.get('key', '')))}\" target=\"_blank\">{escape(str(item.get('key', '')))}</a></td>"
        f"<td>{escape(str(item.get('summary', '')))}</td>"
        f"<td>{escape(str(item.get('assignee', '')))}</td>"
        f"<td>{escape(str(item.get('reporter', '')))}</td>"
        f"<td>{escape(str(item.get('labels', '')))}</td>"
        f"<td>{escape(str(item.get('product', '')))}</td>"
        f"<td>{escape(str(item.get('created', '')))}</td>"
        f"<td>{escape(str(item.get('resolved', '')))}</td>"
        f"<td>{float(item.get('effort_hours', 0.0) or 0.0):.2f}</td>"
        f"<td>{adhoc_status_badge(item.get('status', ''))}</td>"
        "</tr>"
        for item in rows
    )
    if not table_rows:
        table_rows = '<tr><td colspan="10">No ad-hoc task tickets found for this period.</td></tr>'

    utilization_rows = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('product', '')))}</td>"
        f"<td>{int(item.get('request_count', 0) or 0)}</td>"
        f"<td>{float(item.get('effort_hours', 0.0) or 0.0):.2f}</td>"
        f"<td>{int(item.get('resource_count', 0) or 0)}</td>"
        f"<td>{float(item.get('avg_effort_per_resource', 0.0) or 0.0):.2f}</td>"
        "</tr>"
        for item in product_resource_utilization
        if str(item.get("product", "")).strip().upper() != "OTHERS"
    )

    def _assignee_product_text(item: dict) -> str:
        assignees = item.get("assignees", []) or []
        if not assignees:
            return "N/A"
        parts = []
        for assignee in assignees:
            name = escape(str(assignee.get("assignee", "") or ""))
            request_count = int(assignee.get("request_count", 0) or 0)
            effort_hours = float(assignee.get("effort_hours", 0.0) or 0.0)
            parts.append(f"{name} ({request_count} req, {effort_hours:.2f} h)")
        return " | ".join(parts)

    assignee_per_product_rows = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('product', '')))}</td>"
        f"<td>{_assignee_product_text(item)}</td>"
        "</tr>"
        for item in assignee_per_product
    )
    if not assignee_per_product_rows:
        assignee_per_product_rows = '<tr><td colspan="2">No product-wise assignee data available.</td></tr>'

    product_order = ["IDC23", "IDCEVO", "Others"]
    requests_per_product_rows = "".join(
        "<tr>"
        f"<td>{escape(product)}</td>"
        f"<td>{int(product_distribution.get(product, 0) or 0)}</td>"
        "</tr>"
        for product in product_order
    )

    assignee_category_counts = adhoc.get("assignee_category_counts", {}) or {}

    assignee_ticket_rows = "".join(
        "<tr>"
        f"<td>{escape(assignee_name)}</td>"
        f"<td>{counts.get(ADHOC_CATEGORY_TMS_ACCOUNT, 0)}</td>"
        f"<td>{counts.get(ADHOC_CATEGORY_DIGITAL_PREMIUM, 0)}</td>"
        f"<td>{counts.get(ADHOC_CATEGORY_TELEMATICS_SUPPORT, 0)}</td>"
        f"<td>{sum(counts.get(category, 0) for category in (ADHOC_CATEGORY_TMS_ACCOUNT, ADHOC_CATEGORY_DIGITAL_PREMIUM, ADHOC_CATEGORY_TELEMATICS_SUPPORT))}</td>"
        "</tr>"
        for assignee_name, counts in sorted(
            assignee_category_counts.items(),
            key=lambda item: (-sum(item[1].get(category, 0) for category in (ADHOC_CATEGORY_TMS_ACCOUNT, ADHOC_CATEGORY_DIGITAL_PREMIUM, ADHOC_CATEGORY_TELEMATICS_SUPPORT)), item[0]),
        )
    )
    if not assignee_ticket_rows:
        assignee_ticket_rows = '<tr><td colspan="5">No assignee category data available.</td></tr>'

    category_bar_definitions = (
        (ADHOC_CATEGORY_TMS_ACCOUNT, "TMS Account", "#0F766E"),
        (ADHOC_CATEGORY_DIGITAL_PREMIUM, "Digital Premium", "#1D4ED8"),
        (ADHOC_CATEGORY_TELEMATICS_SUPPORT, "Support", "#EA580C"),
    )

    def _render_category_pie(values: dict, unit_label: str = "") -> str:
        items = []
        total = 0.0
        for key, label, color in category_bar_definitions:
            value = float(values.get(key, 0) or 0)
            if value <= 0:
                continue
            total += value
            items.append((label, value, color))
        if total <= 0:
            return '<div class="closure-product-empty">No data available.</div>'

        def _fmt(value: float) -> str:
            return f"{value:.1f} {unit_label}".strip() if unit_label else f"{int(value)}"

        start = 0.0
        stops = []
        legend = []
        for label, value, color in items:
            pct = (value / total) * 100.0
            end = start + pct
            stops.append(f"{color} {start:.2f}% {end:.2f}%")
            legend.append(f'<li><span class="legend-swatch" style="background:{color}"></span>{escape(label)}: <b>{_fmt(value)}</b></li>')
            start = end

        return f"""
        <div class="closure-product-pie">
            <div class="closure-product-ring" style="background: conic-gradient({', '.join(stops)});">
            <div class="closure-product-hole">
                <b>{_fmt(total)}</b>
                <span>{unit_label or 'total'}</span>
            </div>
            </div>
            <ul class="closure-product-legend">{''.join(legend)}</ul>
        </div>
        """
    max_assignee_category_count = max(
        (int(counts.get(category, 0) or 0) for counts in assignee_category_counts.values() for category, _, _ in category_bar_definitions),
        default=1,
    )
    assignee_category_bar_rows = "".join(
        f'<div class="assignee-category-chart-row"><div class="assignee-category-name">{escape(assignee_name)}</div><div class="assignee-category-bars">'
        + "".join(
            f'<div class="assignee-category-bar-line"><span class="assignee-category-label">{label}</span><div class="adhoc-bar-track"><div class="adhoc-bar-fill" style="width:{(int(counts.get(category, 0) or 0) / max_assignee_category_count * 100.0):.1f}%; background:{color};"></div></div><span class="assignee-category-value">{int(counts.get(category, 0) or 0)}</span></div>'
            for category, label, color in category_bar_definitions
        )
        + "</div></div>"
        for assignee_name, counts in sorted(
            assignee_category_counts.items(),
            key=lambda item: (-sum(item[1].get(category, 0) for category, _, _ in category_bar_definitions), item[0]),
        )
    )
    if not assignee_category_bar_rows:
        assignee_category_bar_rows = '<p class="empty">No assignee category data available.</p>'

    week_wise_rows = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('week', '')))}</td>"
        f"<td>{int(item.get('requests', 0) or 0)}</td>"
        f"<td>{float(item.get('effort_hours', 0.0) or 0.0):.2f}</td>"
        f"<td>{float(item.get('idc23_effort', 0.0) or 0.0):.2f}</td>"
        f"<td>{float(item.get('idcevo_effort', 0.0) or 0.0):.2f}</td>"
        "</tr>"
        for item in week_wise_calculation
    )
    if not week_wise_rows:
        week_wise_rows = '<tr><td colspan="5">No week-wise ad-hoc data available.</td></tr>'

    return f"""
    <section class="adhoc-effort-section">
        <div class="section-title">Telematics Ad-Hoc Effort Analysis</div>
        <div class="section-title">Section 1 : Executive Summary</div>

        <div class="adhoc-kpi-grid">
            <article class="adhoc-kpi"><span>No. of TMS Account Requests</span><b>{tms_account_requests}</b></article>
            <article class="adhoc-kpi"><span>No. of Digital Premium Requests</span><b>{digital_premium_requests}</b></article>
            <article class="adhoc-kpi"><span>No. of Support Requests</span><b>{support_requests}</b></article>
        </div>

        <div class="adhoc-chart-grid">
            <article class="chart-card"><h3>Category-wise Distribution</h3><div class="adhoc-bars">{_dist_rows(category_distribution, "tickets", "#0F766E")}</div></article>
            <article class="chart-card"><h3>Product-wise Distribution</h3><div class="adhoc-bars">{_dist_rows(product_distribution, "tickets", "#1D4ED8")}</div></article>
            <article class="chart-card"><h3>Assignee-wise Contribution (Top 10)</h3><div class="adhoc-bars">{_dist_rows(top_assignees, "tickets", "#EA580C")}</div></article>
        </div>

        <div class="section-title">Requests per Product</div>
        <div class="adhoc-table-wrap">
            <table class="adhoc-table">
                <thead><tr><th>Product</th><th>Requests</th></tr></thead>
                <tbody>{requests_per_product_rows}</tbody>
            </table>
        </div>

        <div class="section-title">Category Breakdown by Product</div>
        <div class="adhoc-chart-grid">
            <article class="chart-card"><h3>IDC23 - TMS Account / Digital Premium / Support</h3>{_render_category_pie(category_counts_by_product.get('IDC23', {}), 'tickets')}</article>
            <article class="chart-card"><h3>IDCEVO - TMS Account / Digital Premium / Support</h3>{_render_category_pie(category_counts_by_product.get('IDCEVO', {}), 'tickets')}</article>
            <article class="chart-card"><h3>Effort (Time Spent) by Category</h3>{_render_category_pie(effort_by_category, 'hours')}</article>
        </div>

        <div class="section-title">No. of Requests by Assignee per Category</div>
        <div class="chart-card assignee-category-chart">
            <h3>Requests by Assignee and Category</h3>
            <div class="adhoc-chart-legend"><span><i style="background:#0F766E;"></i>TMS Account</span><span><i style="background:#1D4ED8;"></i>Digital Premium</span><span><i style="background:#EA580C;"></i>Support</span></div>
            <div class="assignee-category-bars-wrap">{assignee_category_bar_rows}</div>
        </div>
        <div class="adhoc-table-wrap">
            <table class="adhoc-table">
            <thead><tr><th>Assignee</th><th>TMS Account Requests</th><th>Digital Premium Requests</th><th>Support Requests</th><th>Total</th></tr></thead>
                <tbody>{assignee_ticket_rows}</tbody>
            </table>
        </div>

        <details class="report-detail" open>
            <summary>Ad-Hoc Ticket Details</summary>
            <div class="report-detail-content">
                <div class="adhoc-table-wrap">
                    <table id="adhoc-ticket-table" class="adhoc-table adhoc-ticket-table">
                        <thead>
                            <tr>
                                <th>Jira Key</th><th>Summary</th><th>Assignee</th><th>Reporter</th><th>Labels</th>
                                <th>Product</th><th>Created Date</th><th>Resolved Date</th><th>Time Spent (Hours)</th><th>Status</th>
                            </tr>
                        </thead>
                        <tbody>{table_rows}</tbody>
                    </table>
                </div>
            </div>
        </details>
    </section>
    """


def build_connectivity_adhoc_section(data: dict) -> str:
    if not data:
        return ""
    rows = data.get("rows", []) or []
    total_effort_hours = float(data.get("total_effort_hours", 0.0) or 0.0)
    method1_hours = float(data.get("method1_effort_hours", 0.0) or 0.0)
    method2_hours = float(data.get("method2_effort_hours", 0.0) or 0.0)
    total_subtasks = int(data.get("total_subtasks", 0) or 0)

    if rows:
        rows_html = "".join(
            "<tr>"
            f"<td>{escape(str(item.get('method', '')))}</td>"
            f"<td><a href=\"{JIRA_BASE_URL}/browse/{escape(str(item.get('parent_key', '')))}\" target=\"_blank\">{escape(str(item.get('parent_key', '')))}</a></td>"
            f"<td>{escape(str(item.get('parent_summary', '')))}</td>"
            f"<td><a href=\"{JIRA_BASE_URL}/browse/{escape(str(item.get('subtask_key', '')))}\" target=\"_blank\">{escape(str(item.get('subtask_key', '')))}</a></td>"
            f"<td>{escape(str(item.get('subtask_summary', '')))}</td>"
            f"<td>{escape(str(item.get('assignee', '')))}</td>"
            f"<td>{float(item.get('hours', 0.0) or 0.0):.2f}</td>"
            "</tr>"
            for item in rows
        )
    else:
        rows_html = '<tr><td colspan="7">No ad-hoc effort recorded for the selected period.</td></tr>'

    return f"""
    <section class="adhoc-effort-section">
        <header><h3>Communication / Wireless Services Ad-Hoc Effort</h3><p>Method 1: LTTSTM weekly Task, matched by Task creation date. Method 2: IDCEVODEV umbrella Story, matched by calendar week. Subtasks with no logged hours are excluded.</p></header>
        <div class="adhoc-kpi-grid">
            <article class="adhoc-kpi"><span>Total Ad-Hoc Hours</span><b>{total_effort_hours:.2f}</b></article>
            <article class="adhoc-kpi"><span>Method 1 Hours (LTTSTM)</span><b>{method1_hours:.2f}</b></article>
            <article class="adhoc-kpi"><span>Method 2 Hours (IDCEVODEV)</span><b>{method2_hours:.2f}</b></article>
            <article class="adhoc-kpi"><span>Subtasks with Logged Hours</span><b>{total_subtasks}</b></article>
        </div>
        <div class="adhoc-table-wrap">
            <table class="adhoc-table">
                <thead><tr><th>Method</th><th>Parent</th><th>Parent Summary</th><th>Subtask</th><th>Subtask Summary</th><th>Assignee</th><th>Hours</th></tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
    </section>
    """


def _feature_subtask_rows_html(rows: list[dict]) -> str:
    if not rows:
        return '<tr><td colspan="10">No matching sub-task closures for this period.</td></tr>'
    body = ""
    for row in rows:
        feature_key = escape(str(row.get("feature_key", "")))
        test_cases = row.get("test_coverage", [])
        sys5_count = int(row.get("sys5_test_case_count", 0) or 0)
        coverage_note = f"{sys5_count} SYS.5 / {len(test_cases)} linked" if test_cases else "0 linked"
        body += (
            "<tr>"
            f"<td><a href=\"{JIRA_BASE_URL}/browse/{feature_key}\" target=\"_blank\">{feature_key}</a></td>"
            f"<td>{escape(str(row.get('feature_summary', '')))}</td>"
            f"<td>{escape(str(row.get('product', '') or row.get('project', '')))}</td>"
            f"<td>{escape(str(row.get('feature_sop_pu', '')))}</td>"
            f"<td>{escape(str(row.get('feature_domain', '')))}</td>"
            f"<td><a href=\"{JIRA_BASE_URL}/browse/{escape(str(row.get('key', '')))}\" target=\"_blank\">{escape(str(row.get('key', '')))}</a></td>"
            f"<td>{escape(str(row.get('resolution', '')))}</td>"
            f"<td>{escape(str(row.get('resolved', '')))}</td>"
            f"<td>{escape(str(row.get('i_step', 'N/A')))}</td>"
            f"<td>{coverage_note}</td>"
            "</tr>"
        )
    return body


def _feature_sop_pu_breakdown_html(by_sop_pu: dict) -> str:
    if not by_sop_pu:
        return '<p class="empty">No closures in the selected period.</p>'
    max_value = max(by_sop_pu.values()) if by_sop_pu else 1
    lines = []
    for sop_pu in FEATURE_SOP_PU_ORDER:
        value = int(by_sop_pu.get(sop_pu, 0) or 0)
        if value == 0:
            continue
        pct = (value / max_value * 100.0) if max_value else 0.0
        lines.append(
            f'<div class="adhoc-bar-row"><div class="adhoc-bar-label">{escape(sop_pu)}</div>'
            f'<div class="adhoc-bar-track"><div class="adhoc-bar-fill" style="width:{pct:.1f}%; background:#0066B1;"></div></div>'
            f'<div class="adhoc-bar-value">{value}</div></div>'
        )
    return "".join(lines) or '<p class="empty">No closures in the selected period.</p>'


def build_sys5_qualification_summary(
    total_cycles: int,
    status_totals: dict,
    feature_scope: dict,
    open_critical_defects: int,
) -> str:
    """Single consolidated ASPICE SYS.5-style rollup: qualification test execution
    results + RG3/RG4/RG4.5 SYS.5 sub-task closures + open critical/blocker defects
    that would block qualification sign-off - pulled from data already fetched
    elsewhere in the report, just aggregated into one artifact instead of requiring
    an assessor to piece it together across the Test/Defect/Feature tabs."""
    pass_count = int(status_totals.get("pass", 0) or 0)
    fail_count = int(status_totals.get("failed", 0) or 0)
    aborted_count = int(status_totals.get("aborted", 0) or 0)
    executing_count = int(status_totals.get("executing", 0) or 0)
    todo_count = int(status_totals.get("todo", 0) or 0)
    executed_count = pass_count + fail_count
    pass_rate = (pass_count / executed_count * 100.0) if executed_count else 0.0
    rg3_rg4_closed = int(feature_scope.get("rg3_rg4", {}).get("total", 0) or 0)
    rg45_closed = int(feature_scope.get("rg45", {}).get("total", 0) or 0)
    sign_off_class = "kpi-red" if open_critical_defects > 0 else "kpi-green"
    sign_off_text = f"{open_critical_defects} open critical/blocker defect(s)" if open_critical_defects else "No open critical/blocker defects"

    return f"""
    <div class="data-quality-note" style="margin-bottom:14px;">
        ASPICE SYS.5 (System Qualification Test) rollup - combines Test Scope execution
        results, Feature Scope SYS.5 sub-task closures, and Defect Scope open
        critical/blocker defects into one summary artifact.
    </div>
    <div class="adhoc-kpi-grid">
        <article class="adhoc-kpi"><span>Qualification Test Cycles</span><b>{total_cycles}</b></article>
        <article class="adhoc-kpi"><span>Executed (Pass+Fail)</span><b>{executed_count}</b></article>
        <article class="adhoc-kpi"><span>Pass Rate</span><b>{pass_rate:.1f}%</b></article>
        <article class="adhoc-kpi"><span>Failed</span><b>{fail_count}</b></article>
        <article class="adhoc-kpi"><span>Aborted / Executing / Todo</span><b>{aborted_count} / {executing_count} / {todo_count}</b></article>
        <article class="adhoc-kpi"><span>RG3/RG4 SYS.5 Closed</span><b>{rg3_rg4_closed}</b></article>
        <article class="adhoc-kpi"><span>RG4.5 SYS.5 Closed</span><b>{rg45_closed}</b></article>
        <article class="adhoc-kpi {sign_off_class}"><span>Qualification Sign-off Status</span><b>{sign_off_text}</b></article>
    </div>
    """


def build_feature_scope_section(feature_scope: dict) -> str:
    if not feature_scope:
        return '<p class="empty">No Feature scope data available for the selected filters.</p>'

    rg3_rg4 = feature_scope.get("rg3_rg4", {}) or {}
    rg45 = feature_scope.get("rg45", {}) or {}
    rg3_rg4_rows = rg3_rg4.get("rows", [])
    rg45_rows = rg45.get("rows", [])
    rg3_rg4_sys5_total = sum(int(r.get("sys5_test_case_count", 0) or 0) for r in rg3_rg4_rows)
    rg45_sys5_total = sum(int(r.get("sys5_test_case_count", 0) or 0) for r in rg45_rows)
    sop_pu_label = ", ".join(feature_scope.get("sop_pu_selected", [])) or "All"

    return f"""
    <div class="data-quality-note">
        Test Coverage/SYS.5 test-case counts below are a best-effort heuristic derived from
        "is tested by" linked Test issues (Jira's Test Coverage grid is not exposed via standard
        REST fields). Please verify against the Test Coverage panel before relying on these counts.
    </div>
    <p class="risk-sub">SOP/PU selection: <b>{escape(sop_pu_label)}</b></p>

    <div class="adhoc-kpi-grid">
        <article class="adhoc-kpi"><span>RG3/RG4 SYS.5 Sub-tasks Closed</span><b>{rg3_rg4.get('total', 0)}</b></article>
        <article class="adhoc-kpi"><span>RG3/RG4 Linked SYS.5 Test Cases</span><b>{rg3_rg4_sys5_total}</b></article>
        <article class="adhoc-kpi"><span>RG4.5 SYS.5 Sub-tasks Closed</span><b>{rg45.get('total', 0)}</b></article>
        <article class="adhoc-kpi"><span>RG4.5 Linked SYS.5 Test Cases</span><b>{rg45_sys5_total}</b></article>
    </div>

    <div class="adhoc-chart-grid">
        <article class="chart-card"><h3>RG3/RG4 Closures by SOP/PU</h3><div class="adhoc-bars">{_feature_sop_pu_breakdown_html(rg3_rg4.get('by_sop_pu', {}))}</div></article>
        <article class="chart-card"><h3>RG4.5 Closures by SOP/PU</h3><div class="adhoc-bars">{_feature_sop_pu_breakdown_html(rg45.get('by_sop_pu', {}))}</div></article>
    </div>

    <details class="report-detail" open>
        <summary>RG3/RG4 - SYS.5 System Validation Test Cases (Closed/Resolved)</summary>
        <div class="report-detail-content">
            <div class="adhoc-table-wrap">
                <table class="adhoc-table">
                    <thead><tr><th>Feature</th><th>Feature Summary</th><th>Product</th><th>SOP/PU</th><th>Domain</th><th>Sub-task</th><th>Resolution</th><th>Resolved</th><th>I-Step</th><th>SYS.5 Coverage</th></tr></thead>
                    <tbody>{_feature_subtask_rows_html(rg3_rg4_rows)}</tbody>
                </table>
            </div>
        </div>
    </details>

    <details class="report-detail">
        <summary>RG4.5 - Feature/subfeature System Validation Testing SYS.5 (Closed/Resolved)</summary>
        <div class="report-detail-content">
            <div class="adhoc-table-wrap">
                <table class="adhoc-table">
                    <thead><tr><th>Feature</th><th>Feature Summary</th><th>Product</th><th>SOP/PU</th><th>Domain</th><th>Sub-task</th><th>Resolution</th><th>Resolved</th><th>I-Step</th><th>SYS.5 Coverage</th></tr></thead>
                    <tbody>{_feature_subtask_rows_html(rg45_rows)}</tbody>
                </table>
            </div>
        </div>
    </details>
    """


def product_wise_summary(grouped: dict) -> dict:
    """Aggregate pass/fail/aborted/executing/todo by mapped product."""
    summary = {}
    for _, types in grouped.items():
        for cycle_type in ("Automation", "Manual", "Other"):
            for c in types.get(cycle_type, []):
                product = c.get("product") or classify_execution_product(
                    c.get("project", ""),
                    c.get("variant", ""),
                )

                if product not in summary:
                    summary[product] = {
                        "cycles": 0,
                        "automation_tests": 0,
                        "manual_tests": 0,
                        "pass": 0,
                        "failed": 0,
                        "aborted": 0,
                        "executing": 0,
                        "todo": 0,
                    }

                issue_total_tests = (
                    to_int(c.get("pass", 0))
                    + to_int(c.get("failed", 0))
                    + to_int(c.get("aborted", 0))
                    + to_int(c.get("executing", 0))
                    + to_int(c.get("todo", 0))
                )

                summary[product]["cycles"] += 1
                summary[product]["pass"] += to_int(c.get("pass", 0))
                summary[product]["failed"] += to_int(c.get("failed", 0))
                summary[product]["aborted"] += to_int(c.get("aborted", 0))
                summary[product]["executing"] += to_int(c.get("executing", 0))
                summary[product]["todo"] += to_int(c.get("todo", 0))
                if cycle_type == "Automation":
                    summary[product]["automation_tests"] += issue_total_tests
                elif cycle_type == "Manual":
                    summary[product]["manual_tests"] += issue_total_tests

    return summary


def product_summary_cards(grouped: dict) -> str:
    summary = product_wise_summary(grouped)
    if not summary:
        return '<p class="empty">No product-wise data found.</p>'

    cards = ""
    for product, stats in sorted(summary.items()):
        total_tests = stats["pass"] + stats["failed"] + stats["aborted"] + stats["executing"] + stats["todo"]
        cards += f"""
        <div class="variant-card">
          <div class="variant-name">{product}</div>
          <div class="variant-grid">
                        <div class="variant-cell status-cycles"><span>Cycles</span><b>{stats['cycles']}</b></div>
                        <div class="variant-cell status-pass"><span class="num-pass">Pass</span><b class="num-pass">{stats['pass']}</b></div>
                        <div class="variant-cell status-fail"><span class="num-fail">Failed</span><b class="num-fail">{stats['failed']}</b></div>
                        <div class="variant-cell status-abort"><span class="num-abort">Aborted</span><b class="num-abort">{stats['aborted']}</b></div>
                        <div class="variant-cell status-exec"><span class="num-exec">Executing</span><b class="num-exec">{stats['executing']}</b></div>
                        <div class="variant-cell status-todo"><span class="num-todo">Todo</span><b class="num-todo">{stats['todo']}</b></div>
          </div>
                    <div class="variant-split">
                        <span>Automation Test Cases: <b>{stats['automation_tests']}</b></span>
                        <span>Manual Test Cases: <b>{stats['manual_tests']}</b></span>
                    </div>
                    <div class="variant-total">Total Tests: <b class="num-total">{total_tests}</b></div>
        </div>"""

    return f'<div class="variant-cards">{cards}</div>'


def _normalize_sop_pu(value: str, fallback_product: str) -> tuple[str, str]:
    """Extract a stable product and PU label from the SOP/PU field."""
    raw_value = " ".join(str(value or "").strip().split())
    match = re.search(r"(?:bmw[_-])?(idc23|idcevo|cde|rse26)[_-]pu(\d+)", raw_value, flags=re.IGNORECASE)
    if match:
        product = match.group(1).upper()
        pu = f"PU{match.group(2)}"
        return product, pu

    pu_match = re.search(r"\bpu[-_ ]?(\d+)\b", raw_value, flags=re.IGNORECASE)
    pu = f"PU{pu_match.group(1)}" if pu_match else (raw_value or "Unknown PU")
    product = str(fallback_product or "Unknown").strip()
    normalized_product = product.upper()
    if normalized_product in {"SV_MID", "SV_MINI", "SV_HIGH"}:
        product = "IDC23"
    elif normalized_product in {"IDCEVO-21", "IDCEVO-25"}:
        product = "IDCEVO"
    return product, pu


def sop_pu_execution_counts(grouped: dict) -> str:
    """Render Automation and Manual execution counts grouped by product and SOP/PU."""
    summary: dict[tuple[str, str], dict[str, int]] = {}
    for _, types in grouped.items():
        for cycle_type in ("Automation", "Manual"):
            for cycle in types.get(cycle_type, []):
                product, pu = _normalize_sop_pu(cycle.get("sop_pu", ""), cycle.get("variant", "Unknown"))
                key = (product, pu)
                stats = summary.setdefault(key, {"automation": 0, "manual": 0})
                issue_total_tests = sum(
                    to_int(cycle.get(field, 0))
                    for field in ("pass", "failed", "aborted", "executing", "todo")
                )
                stats["automation" if cycle_type == "Automation" else "manual"] += issue_total_tests

    if not summary:
        return '<p class="empty">No SOP/PU execution count data found.</p>'

    max_automation = max(stats["automation"] for stats in summary.values())
    max_manual = max(stats["manual"] for stats in summary.values())
    rows = "".join(
        f"""
        <tr>
            <td class="pu-product"><b>{escape(product)}</b></td>
            <td class="pu-sop"><b>{escape(pu)}</b></td>
            <td class="pu-count-automation{' pu-max-automation' if stats['automation'] == max_automation else ''}">{stats['automation']}</td>
            <td class="pu-count-manual{' pu-max-manual' if stats['manual'] == max_manual else ''}">{stats['manual']}</td>
            <td class="pu-count-total"><b>{stats['automation'] + stats['manual']}</b></td>
        </tr>
        """
        for (product, pu), stats in sorted(summary.items())
    )
    return f"""
    <div class="pu-execution-counts">
        <table class="pu-execution-table">
            <thead>
                <tr><th>Product</th><th>SOP/PU</th><th>Automation Executed</th><th>Manual Executed</th><th>Total Executed</th></tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    """


def _domain_anchor_id(domain: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(domain or "").strip()).strip("-").lower()
    return f"domain-{slug or 'unknown'}"


def domain_quick_jump(grouped: dict) -> str:
    """Anchor-link list so a long Detailed Execution Cycles view can jump between domains."""
    domains = sorted(grouped.keys())
    if len(domains) < 2:
        return ""
    links = "".join(f'<a href="#{_domain_anchor_id(domain)}">{escape(domain)}</a>' for domain in domains)
    return f'<div class="domain-quick-jump"><span>Jump to domain:</span>{links}</div>'


def domain_sections(grouped: dict) -> str:
    sections = ""
    for domain, types in sorted(grouped.items()):
        auto_html   = execution_table(types["Automation"])
        manual_html = execution_table(types["Manual"])
        sections += f"""
        <div class="domain-block" id="{_domain_anchor_id(domain)}">
          <div class="domain-title">{domain}</div>

          <div class="cycle-type-label auto-label">Automation Cycles
            <span class="cycle-count">{len(types['Automation'])} cycles</span>
          </div>
          {auto_html}

          <div class="cycle-type-label manual-label" style="margin-top:18px;">Manual Cycles
            <span class="cycle-count">{len(types['Manual'])} cycles</span>
          </div>
          {manual_html}
        </div>"""
    return sections or '<p class="empty">No test execution data found for the selected period.</p>'


def apply_domain_filter(grouped: dict, raw_selection: str) -> tuple[dict, str, list]:
    """Apply domain filter from comma-separated names/numbers; returns filtered, label, invalid tokens."""
    domains = sorted(grouped.keys())
    if not domains or not raw_selection:
        return grouped, "All", []

    normalized = raw_selection.strip()
    if normalized.lower() == "all":
        return grouped, "All", []

    by_lower = {d.lower(): d for d in domains}
    selected = []
    invalid = []

    for token in [t.strip() for t in normalized.split(",") if t.strip()]:
        if token.isdigit():
            pos = int(token)
            if 1 <= pos <= len(domains):
                selected.append(domains[pos - 1])
            else:
                invalid.append(token)
            continue

        token_lower = token.lower()
        match = (
            by_lower.get(token_lower)
            or by_lower.get(token_lower.replace("isation", "ization"))
            or by_lower.get(token_lower.replace("ization", "isation"))
        )
        if match:
            selected.append(match)
        else:
            invalid.append(token)

    selected_unique = list(dict.fromkeys(selected))
    if not selected_unique:
        return grouped, "All", invalid

    filtered = {k: grouped[k] for k in selected_unique if k in grouped}
    return filtered, ", ".join(selected_unique), invalid


def apply_cycle_filter(grouped: dict, cycle_mode: str) -> dict:
    """Restrict grouped data to Automation, Manual, or keep both."""
    mode = (cycle_mode or "both").strip().lower()
    if mode not in {"automation", "manual"}:
        return grouped

    filtered = {}
    for domain, types in grouped.items():
        if mode == "automation":
            auto = types.get("Automation", [])
            if auto:
                filtered[domain] = {"Automation": auto, "Manual": [], "Other": []}
        else:
            manual = types.get("Manual", [])
            if manual:
                filtered[domain] = {"Automation": [], "Manual": manual, "Other": []}

    return filtered


def apply_variant_filter(grouped: dict, raw_selection: str) -> tuple[dict, str, list]:
    """Apply variant filter from comma-separated names; returns filtered, label, invalid tokens."""
    if not grouped or not raw_selection:
        return grouped, "All", []

    normalized = raw_selection.strip()
    if normalized.lower() == "all":
        return grouped, "All", []

    requested = [t.strip() for t in normalized.split(",") if t.strip()]
    if not requested:
        return grouped, "All", []

    requested_lower = {v.lower(): v for v in requested}

    filtered = {}
    found_requested = set()
    for domain, types in grouped.items():
        next_types = {"Automation": [], "Manual": [], "Other": []}
        for cycle_type in ("Automation", "Manual", "Other"):
            for c in types.get(cycle_type, []):
                variant_name = str(c.get("variant", "")).strip()
                # IDCEVO-21 is considered part of IDCEVO-25 for filtering.
                effective_variant = "IDCEVO-25" if variant_name.upper() == "IDCEVO-21" else variant_name
                if effective_variant and effective_variant.lower() in requested_lower:
                    next_types[cycle_type].append(c)
                    found_requested.add(effective_variant.lower())

        if next_types["Automation"] or next_types["Manual"] or next_types["Other"]:
            filtered[domain] = next_types

    invalid = [token for token in requested if token.lower() not in found_requested]
    label = ", ".join(requested)
    if not filtered:
        return grouped, "All", invalid

    return filtered, label, invalid


def choose_domains(grouped: dict) -> tuple[dict, str]:
    """Ask user for domain filter and return filtered grouped data + display label."""
    domains = sorted(grouped.keys())
    if not domains:
        return grouped, "All"

    if domains == ["Unknown"] and "XXXXX" in CUSTOM_FIELDS.get("domain", ""):
        print(
            "\nNote: Domain field is not configured yet (CUSTOM_FIELDS['domain']). "
            "Run with --discover-fields and set the real domain custom field ID to filter by actual domain names."
        )

    print("\nAvailable domains in fetched data:")
    for idx, name in enumerate(domains, start=1):
        print(f"  {idx:>2}. {name}")

    raw = input("\nSelect domain(s) by number/name (comma-separated), or press Enter for All: ").strip()
    filtered, label, invalid = apply_domain_filter(grouped, raw)

    if invalid:
        print(f"Ignored invalid domain entries: {', '.join(invalid)}")

    if not raw or label == "All":
        if raw and invalid:
            print("No valid domains selected. Falling back to All domains.")
        return grouped, "All"

    if not filtered:
        print("No valid domains selected. Falling back to All domains.")
        return grouped, "All"

    return filtered, label


def parse_args():
    parser = argparse.ArgumentParser(description="Generate Jira Test Execution HTML report")
    parser.add_argument("--discover-fields", action="store_true", help="Print Jira fields and exit")
    parser.add_argument(
        "--rejected-only",
        action="store_true",
        help="Generate only the Closed as Rejected/Deficient ticket report",
    )
    parser.add_argument(
        "--domain",
        default="",
        help="Domain filter: single value or comma-separated list (example: \"Telematics\" or \"Architecture,Telematics\" or \"all\")",
    )
    parser.add_argument(
        "--rack-domain",
        default="",
        help="Domain filter for the Test Rack Utilisation scope (defaults to --domain when not set)",
    )
    parser.add_argument(
        "--variant",
        default="",
        help="Variant filter: single value or comma-separated list (example: \"CDE-01\" or \"SV_MID,SV_HIGH\" or \"all\")",
    )
    parser.add_argument("--start-date", default="", help="Start date in YYYY-MM-DD")
    parser.add_argument("--end-date", default="", help="End date in YYYY-MM-DD")
    parser.add_argument(
        "--rack-activity-file",
        default=RACK_ACTIVITY_FILE,
        help="Normalized test.guide activity JSON/CSV export (or TEST_GUIDE_ACTIVITY_FILE)",
    )
    parser.add_argument(
        "--rack-only",
        action="store_true",
        help="Generate only the test rack utilisation report; defaults to the current Monday-through-today week",
    )
    parser.add_argument(
        "--cycle-type",
        default="both",
        choices=["both", "manual", "automation"],
        help="Include cycle type in report",
    )
    parser.add_argument(
        "--projects",
        default=",".join(PROJECTS),
        help='Comma-separated test execution projects (example: "ABPI,IDCEVODEV")',
    )
    parser.add_argument(
        "--defect-projects",
        default=",".join(["HU22DM", "IDCEVODEV"]),
        help='Comma-separated defect projects (example: "HU22DM,IDCEVODEV")',
    )
    parser.add_argument(
        "--defect-domain",
        default="",
        help='Defect domain filter (use "All" or empty for no domain filter)',
    )
    parser.add_argument(
        "--defect-assigned-ecu",
        default="",
        help='Comma-separated assigned ECU filter (example: "HU-MGU_02_A,IDCEVO-25")',
    )
    parser.add_argument(
        "--closure-projects",
        default="",
        help='Comma-separated projects for team-wise closure metrics (example: "HU22DM,IDCEVODEV")',
    )
    parser.add_argument(
        "--closure-team",
        default="",
        help='Defect raised team/domain filter for closure metrics (example: "Telematics")',
    )
    parser.add_argument(
        "--resolution-start-date",
        default="",
        help="Resolution start date for closure metrics in YYYY-MM-DD",
    )
    parser.add_argument(
        "--resolution-end-date",
        default="",
        help="Resolution end date for closure metrics in YYYY-MM-DD",
    )
    parser.add_argument(
        "--report-scopes",
        default="",
        help='Comma-separated report scopes: test,defect,resolution,adhoc,rack,feature (empty means all)',
    )
    parser.add_argument(
        "--adhoc-domains",
        default="All",
        help='Comma-separated Ad-Hoc domains (supported: Telematics, Communication, Wireless Services; default "All" fetches every supported domain)',
    )
    parser.add_argument(
        "--feature-domain",
        default="",
        help='Comma-separated Feature scope domain filter (empty/"all" keeps every non-excluded domain)',
    )
    parser.add_argument(
        "--feature-products",
        default=",".join(FEATURE_PRODUCT_PROJECTS),
        help='Comma-separated Feature products: IDCEVO,PENTPM (empty selects both)',
    )
    parser.add_argument(
        "--feature-sop-pu",
        default="",
        help='Comma-separated Feature SOP/PU selection, e.g. "27-03,27-07" (empty selects all: '
        + ", ".join(FEATURE_SOP_PU_ORDER) + ")",
    )
    parser.add_argument(
        "--feature-include-rg3-rg4",
        default="true",
        choices=["true", "false"],
        help='Include RG3/RG4 - SYS.5 System Validation Test Cases sub-task closures',
    )
    parser.add_argument(
        "--feature-include-rg45",
        default="true",
        choices=["true", "false"],
        help='Include RG4.5 - Feature/subfeature System Validation Testing SYS.5 sub-task closures',
    )
    parser.add_argument(
        "--feature-excel",
        default="",
        help='Optional output path for the SYS.5 test-case Excel export (defaults inside reports/ when Feature scope is active)',
    )
    parser.add_argument(
        "--feature-resolution-start-date",
        default="",
        help="Feature Scope resolution start date in YYYY-MM-DD (defaults to the report start date)",
    )
    parser.add_argument(
        "--feature-resolution-end-date",
        default="",
        help="Feature Scope resolution end date in YYYY-MM-DD (defaults to the report end date)",
    )
    return parser.parse_args()


def parse_report_scopes(value: str) -> set[str]:
    allowed = {"test", "defect", "resolution", "adhoc", "rack", "feature"}
    requested = {part.strip().lower() for part in str(value or "").split(",") if part.strip()}
    if not requested:
        return set(allowed)

    invalid = requested - allowed
    if invalid:
        print(f"Ignored invalid report scopes: {', '.join(sorted(invalid))}")

    valid = requested & allowed
    if not valid:
        print("No valid report scopes matched; running all scopes instead.")
        return set(allowed)
    return valid


def build_cw_label(start_date: str, end_date: str) -> str:
    """Return CW label from selected date range (ISO week)."""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_iso = start_dt.isocalendar()
    end_iso = end_dt.isocalendar()

    if start_iso.year == end_iso.year and start_iso.week == end_iso.week:
        return f"CW{start_iso.week:02d}"
    if start_iso.year == end_iso.year:
        return f"CW{start_iso.week:02d}-CW{end_iso.week:02d}"
    # ISO week-year can differ from the calendar year at year boundaries
    # (e.g. Dec 29 belongs to next year's week 1); disambiguate explicitly.
    return f"CW{start_iso.week:02d}/{start_iso.year}-CW{end_iso.week:02d}/{end_iso.year}"


def _rack_donut_svg(percentages: list[tuple[str, float, str]], utilisation_pct: float) -> str:
    """Render one labelled donut so percentages are not repeated as legends."""
    center = 76
    outer_radius = 64
    inner_radius = 38
    circumference = 2 * math.pi * outer_radius
    offset = 0.0
    segments = []
    labels = []

    def point(radius: float, angle: float) -> tuple[float, float]:
        radians = math.radians(angle - 90)
        return center + radius * math.cos(radians), center + radius * math.sin(radians)

    for label, percentage, color in percentages:
        if percentage <= 0:
            continue
        start = offset
        end = offset + percentage * 3.6
        large_arc = 1 if percentage > 50 else 0
        outer_start = point(outer_radius, start)
        outer_end = point(outer_radius, end)
        inner_end = point(inner_radius, end)
        inner_start = point(inner_radius, start)
        path = (
            f"M {outer_start[0]:.2f} {outer_start[1]:.2f} "
            f"A {outer_radius} {outer_radius} 0 {large_arc} 1 {outer_end[0]:.2f} {outer_end[1]:.2f} "
            f"L {inner_end[0]:.2f} {inner_end[1]:.2f} "
            f"A {inner_radius} {inner_radius} 0 {large_arc} 0 {inner_start[0]:.2f} {inner_start[1]:.2f} Z"
        )
        text_x, text_y = point((outer_radius + inner_radius) / 2, (start + end) / 2)
        text_color = "#0A2342" if label in {"Manual", "Rack Idle"} else "#FFFFFF"
        segments.append(f'<path d="{path}" fill="{color}"/>')
        labels.append(f'<text x="{text_x:.2f}" y="{text_y + 3:.2f}" fill="{text_color}" text-anchor="middle">{percentage:.0f}%</text>')
        offset = end

    return (
        f'<svg class="rack-donut-svg" viewBox="0 0 152 152" role="img" '
        f'aria-label="Automation {percentages[0][1]:.1f}%, Offline {percentages[1][1]:.1f}%, '
        f'Manual {percentages[2][1]:.1f}%, Rack Idle {percentages[3][1]:.1f}%">'
        f'{"".join(segments)}<circle cx="76" cy="76" r="38" fill="#FFFFFF"/>'
        f'{"".join(labels)}<text class="rack-donut-total" x="76" y="73" text-anchor="middle">{utilisation_pct:.1f}%</text>'
        '<text class="rack-donut-caption" x="76" y="86" text-anchor="middle">Utilization</text></svg>'
    )


def _render_rack_card(rack: dict) -> str:
    total = float(rack.get("total_hours", 0) or 0)
    automation = float(rack.get("automation_hours", 0) or 0)
    offline = float(rack.get("offline_hours", 0) or 0)
    manual = float(rack.get("manual_hours", 0) or 0)
    rack_idle = float(rack.get("rack_idle_hours", 0) or 0)
    resource = str(rack.get("resource") or "Unknown rack")
    rack_name = resource.rsplit("/", 1)[-1]
    resource_parts = resource.split("/")
    product = resource_parts[1] if len(resource_parts) > 1 else "N/A"
    utilisation_pct = (automation + manual) / total * 100 if total else 0.0
    status = "No activity" if total <= 0 else "Excellent" if utilisation_pct >= 65 else "Pool" if utilisation_pct >= 50 else "Decommission"
    status_class = status.casefold().replace(" ", "-")
    if total:
        auto_pct = automation / total * 100
        offline_pct = (automation + offline) / total * 100
        manual_pct = (automation + offline + manual) / total * 100
        pie = f"conic-gradient(#2E7D32 0 {auto_pct:.2f}%, #D93025 {auto_pct:.2f}% {offline_pct:.2f}%, #F2C94C {offline_pct:.2f}% {manual_pct:.2f}%, #B8BEC7 {manual_pct:.2f}% 100%)"
    else:
        auto_pct = offline_pct = manual_pct = 0.0
        pie = "conic-gradient(#B8BEC7 0 100%)"
    rack_idle_pct = max(0.0, 100.0 - manual_pct)

    def hours(value: float) -> str:
        return f"{value:.1f} h"

    return f"""
    <article class="rack-utilisation-item">
        <div class="rack-utilisation-heading">
            <div><h3>{escape(rack_name)}</h3><p class="rack-product">Product: {escape(product)}</p><span class="rack-status rack-status-{status_class}">{status}</span></div>
            <strong>{hours(total)}<span>Total hours</span></strong>
        </div>
        <div class="rack-utilisation-body">
            {_rack_donut_svg([
                ("Automation", auto_pct, "#2E7D32"),
                ("Offline", offline / total * 100 if total else 0, "#D93025"),
                ("Manual", manual / total * 100 if total else 0, "#F2C94C"),
                ("Rack Idle", rack_idle_pct, "#B8BEC7"),
            ], utilisation_pct)}
        </div>
        <div class="rack-utilisation-kpi"><span>Utilization</span><strong>{utilisation_pct:.1f}%</strong></div>
    </article>
    """


def render_rack_utilisation_section(utilisation: dict) -> str:
    """Render the selected-week test rack utilisation summary and pie chart."""
    per_rack = utilisation.get("by_resource", [])
    if per_rack:
        cards = "".join(_render_rack_card(rack) for rack in per_rack)
        return f"""
        <section class="rack-utilisation-section">
            <div class="section-title">Rack Utilisation by Resource</div>
            <p class="rack-utilisation-period">{escape(str(utilisation.get('week_label') or 'Selected range'))} | {escape(str(utilisation.get('start_date') or ''))} to {escape(str(utilisation.get('end_date') or ''))} | Onsite and Offshore</p>
            <div class="rack-utilisation-card">
                <div class="rack-utilisation-grid">{cards}</div>
                <div class="rack-formula">Utilization = (Manual + Automation) / Total hours</div>
                <div class="rack-shared-legend">
                    <span><i class="rack-dot rack-auto"></i>Automation</span>
                    <span><i class="rack-dot rack-offline"></i>Offline</span>
                    <span><i class="rack-dot rack-manual"></i>Manual</span>
                    <span><i class="rack-dot rack-idle"></i>Rack Idle</span>
                </div>
            </div>
        </section>
        """
    total = float(utilisation.get("total_hours", 0) or 0)
    automation = float(utilisation.get("automation_hours", 0) or 0)
    manual = float(utilisation.get("manual_hours", 0) or 0)
    idle = float(utilisation.get("rack_idle_hours", 0) or 0)
    data_warning = str(utilisation.get("data_warning") or "").strip()
    if total:
        auto_pct = automation / total * 100
        manual_pct = (automation + manual) / total * 100
        pie = f"conic-gradient(#0066B1 0 {auto_pct:.2f}%, #2E7D32 {auto_pct:.2f}% {manual_pct:.2f}%, #A66A00 {manual_pct:.2f}% 100%)"
    else:
        pie = "conic-gradient(#D8DFE8 0 100%)"

    def hours(value: float) -> str:
        return f"{value:.1f} h"

    resources = utilisation.get("matched_resources", [])
    has_data = bool(resources) or total > 0
    resource_note = f"{len(resources)} matching test resources" if resources else "No matching activity rows"
    primary_metric = hours(total) if has_data else "N/A"
    metric_caption = "Total utilisation" if has_data else "Rack data status"
    message = data_warning or "No rack activity was returned for the selected scope and date range."
    return f"""
    <section class="rack-utilisation-section">
        <div class="section-title">Test Rack Utilisation</div>
        <div class="rack-utilisation-card">
            <div class="rack-utilisation-heading">
                <div><h3>{escape(str(utilisation.get('domain') or 'All'))}</h3><p>{escape(str(utilisation.get('week_label') or 'Selected range'))} | {escape(str(utilisation.get('start_date') or ''))} to {escape(str(utilisation.get('end_date') or ''))}</p></div>
                <strong>{primary_metric}<span>{metric_caption}</span></strong>
            </div>
            <div class="rack-utilisation-body">
                <div class="rack-pie" style="background:{pie};"><div class="rack-pie-hole">{hours(total)}<small>Total</small></div></div>
                <div class="rack-legend">
                    <div><i class="rack-dot rack-auto"></i><span>Automation</span><b>{hours(automation)}</b></div>
                    <div><i class="rack-dot rack-manual"></i><span>Manual</span><b>{hours(manual)}</b></div>
                    <div><i class="rack-dot rack-idle"></i><span>Idle</span><b>{hours(idle)}</b></div>
                </div>
            </div>
            <p class="rack-utilisation-note">Scope: LTTS_ONSITE and LTTS_OFFSHORE | {resource_note}</p>
            {f'<p class="rack-utilisation-note">{escape(message)}</p>' if not has_data else ''}
        </div>
    </section>
    """


def generate_rack_only_html(utilisation: dict) -> str:
    """Generate a standalone rack report without Jira execution or defect data."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Test Rack Utilisation - {escape(str(utilisation.get('week_label') or 'Selected range'))}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; background: #F5F7FA; color: #1F2937; font-family: "Segoe UI", Arial, sans-serif; }}
.page {{ max-width: 980px; margin: 0 auto; padding: 38px 24px 60px; }}
.header {{ background: linear-gradient(120deg, #0E2A47, #1F4D7E); color: #FFFFFF; padding: 26px 30px; border-radius: 12px; margin-bottom: 24px; }}
.header h1 {{ margin: 0 0 8px; font-size: 25px; }}
.header p {{ margin: 0; color: #D8E7FB; font-size: 13px; }}
.rack-utilisation-section {{ margin-bottom: 30px; }}
    .rack-utilisation-period {{ color: #4B5563; font-size: 12px; margin: -4px 0 12px; }}
    .rack-utilisation-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }}
.section-title {{ margin: 0 0 12px; color: #0E2A47; font-size: 18px; font-weight: 700; }}
.rack-utilisation-card {{ background: #FFFFFF; border: 1px solid #D5DDE7; border-radius: 12px; padding: 22px 26px; box-shadow: 0 12px 26px rgba(10, 35, 66, .10); }}
.rack-utilisation-item {{ min-width: 0; border: 1px solid #B8C8D8; border-top: 4px solid #0066B1; border-radius: 8px; padding: 16px; background: linear-gradient(145deg, #FFFFFF 0%, #F4F8FC 100%); box-shadow: 0 10px 22px rgba(10, 35, 66, .12); }}
.rack-utilisation-heading {{ display: flex; justify-content: space-between; gap: 18px; border-bottom: 1px solid #E5E7EB; padding-bottom: 14px; }}
.rack-utilisation-heading h3 {{ margin: 0 0 3px; color: #0A2342; font-size: 19px; }}
.rack-product {{ margin: 0 0 7px; color: #0066B1; font-size: 12px; font-weight: 800; letter-spacing: .03em; }}
.rack-utilisation-heading p, .rack-utilisation-note {{ color: #4B5563; font-size: 12px; }}
.rack-utilisation-heading strong {{ color: #0E2A47; font-size: 28px; text-align: right; white-space: nowrap; }}
.rack-utilisation-heading strong span {{ display: block; color: #6B7280; font-size: 11px; font-weight: 400; margin-top: 3px; }}
.rack-utilisation-body {{ display: flex; align-items: center; gap: 34px; padding: 22px 0 16px; }}
.rack-donut-svg {{ width: 190px; height: 190px; display: block; flex: 0 0 auto; overflow: visible; }}
.rack-donut-svg path {{ stroke: #FFFFFF; stroke-width: 1; }}
.rack-donut-svg text {{ font-family: "Segoe UI", Arial, sans-serif; font-size: 11px; font-weight: 800; pointer-events: none; }}
.rack-donut-total {{ fill: #0A2342; font-size: 16px !important; }}
.rack-donut-caption {{ fill: #64748B; font-size: 7px !important; font-weight: 400 !important; }}
.rack-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
.rack-auto {{ background: #2E7D32; }} .rack-offline {{ background: #D93025; }} .rack-manual {{ background: #F2C94C; }} .rack-idle {{ background: #B8BEC7; }}
.rack-status {{ display: inline-block; padding: 3px 7px; border-radius: 10px; font-size: 10px; font-weight: 700; }}
.rack-status-excellent {{ color: #FFFFFF; background: #166534; }} .rack-status-pool {{ color: #FFFFFF; background: #A16207; }} .rack-status-decommission {{ color: #FFFFFF; background: #B42318; }} .rack-status-no-activity {{ color: #FFFFFF; background: #475569; }}
.rack-utilisation-kpi {{ display: grid; grid-template-columns: 1fr auto; align-items: baseline; gap: 4px 10px; border-top: 1px solid #E5E7EB; padding-top: 11px; }}
.rack-utilisation-kpi span {{ color: #40566D; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; }} .rack-utilisation-kpi strong {{ color: #0066B1; font-size: 32px; font-weight: 900; line-height: 1; }} .rack-utilisation-kpi small {{ grid-column: 1 / -1; color: #94A3B8; font-size: 9px; }}
.rack-formula {{ margin-top: 18px; color: #64748B; font-size: 12px; font-weight: 600; text-align: center; }}
.rack-shared-legend {{ display: flex; justify-content: center; gap: 28px; flex-wrap: wrap; margin-top: 18px; padding-top: 14px; border-top: 1px solid #E5E7EB; color: #0A2342; font-size: 14px; font-weight: 800; }}
.rack-shared-legend span {{ display: inline-flex; align-items: center; gap: 7px; }}
.rack-utilisation-note {{ border-top: 1px solid #E5E7EB; padding-top: 12px; margin-bottom: 0; }}
@media (max-width: 600px) {{ .rack-utilisation-heading, .rack-utilisation-body {{ flex-direction: column; align-items: flex-start; }} .rack-utilisation-heading strong {{ text-align: left; }} }}
@media print {{ body {{ background: #FFFFFF; }} .page {{ padding: 0; }} .header, .rack-utilisation-card {{ box-shadow: none; }} }}
</style>
</head>
<body>
<main class="page">
<header class="header"><h1>Test Rack Utilisation</h1><p>{escape(str(utilisation.get('week_label') or 'Selected range'))} | {escape(str(utilisation.get('start_date') or ''))} to {escape(str(utilisation.get('end_date') or ''))}</p></header>
{render_rack_utilisation_section(utilisation)}
</main>
</body>
</html>"""


def generate_rejected_only_html(
    closure_metrics: dict,
    start_date: str,
    end_date: str,
) -> str:
    """Generate a compact report containing only rejected/deficient tickets."""
    rejected_row = next(
        (
            row for row in closure_metrics.get("rows", [])
            if row.get("key") == "closed_rejected_deficient"
        ),
        {},
    )
    details = rejected_row.get("details", [])
    rows_html = "".join(
        "<tr>"
        f"<td><a href=\"{JIRA_BASE_URL}/browse/{escape(str(item.get('key', '')))}\" target=\"_blank\">{escape(str(item.get('key', '')))}</a></td>"
        f"<td>{escape(str(item.get('project', '')))}</td>"
        f"<td>{escape(str(item.get('summary', '')))}</td>"
        f"<td>{escape(str(item.get('assigned_ecu', 'N/A')))}</td>"
        f"<td>{escape(str(item.get('found_in_sw_version', 'N/A')))}</td>"
        f"<td>{escape(str(item.get('comment_summary', 'No recent comments available.')))}</td>"
        "</tr>"
        for item in details
    )
    if not rows_html:
        rows_html = '<tr><td colspan="6">No rejected or deficient tickets found.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Rejected Tickets Report - {escape(build_cw_label(start_date, end_date))}</title>
<style>
body {{ margin: 0; background: #F5F7FA; color: #17202A; font-family: "Segoe UI", Arial, sans-serif; }}
main {{ max-width: 1500px; margin: 0 auto; padding: 32px 28px 56px; }}
header {{ background: #0E2A47; color: #FFFFFF; padding: 24px 28px; border-left: 5px solid #0066B1; }}
h1 {{ margin: 0 0 8px; font-size: 25px; }}
header p {{ margin: 0; color: #D8E7FB; }}
.summary {{ margin: 22px 0 14px; font-size: 17px; font-weight: 700; color: #0E2A47; }}
.table-wrap {{ overflow-x: auto; background: #FFFFFF; border: 1px solid #D5DDE7; }}
table {{ width: 100%; border-collapse: collapse; min-width: 1050px; }}
th, td {{ padding: 12px 14px; border-bottom: 1px solid #E5E7EB; text-align: left; vertical-align: top; line-height: 1.4; }}
th {{ background: #EAF3FF; color: #173A61; font-size: 12px; text-transform: uppercase; }}
td {{ font-size: 13px; }}
tr:last-child td {{ border-bottom: 0; }}
a {{ color: #0066B1; font-weight: 700; }}
</style>
</head>
<body>
<main>
<header><h1>Rejected / Deficient Jira Tickets</h1><p>{escape(build_cw_label(start_date, end_date))} | Resolution window: {escape(start_date)} to {escape(end_date)}</p></header>
<div class="summary">{len(details)} rejected or deficient ticket(s)</div>
<div class="table-wrap"><table><thead><tr><th>Key</th><th>Project</th><th>Summary</th><th>Assigned ECU</th><th>Found in SW version</th><th>Transformers comment summary</th></tr></thead><tbody>{rows_html}</tbody></table></div>
</main>
</body>
</html>"""


def generate_html(
    grouped: dict,
    defects: dict,
    adhoc_effort: dict,
    rack_utilisation: dict,
    start_date: str,
    end_date: str,
    domain_filter_label: str = "All",
    selected_projects: list[str] | None = None,
    report_scopes: set[str] | None = None,
    feature_scope: dict | None = None,
    connectivity_adhoc: dict | None = None,
) -> str:
    report_scopes = report_scopes or {"test", "defect", "resolution", "adhoc", "rack", "feature"}
    feature_scope = feature_scope or {}
    connectivity_adhoc = connectivity_adhoc or {}
    total_cycles    = sum(len(v["Automation"]) + len(v["Manual"]) + len(v["Other"]) for v in grouped.values())
    total_auto      = sum(len(v["Automation"]) for v in grouped.values())
    total_manual    = sum(len(v["Manual"]) for v in grouped.values())
    status_totals   = aggregate_status_totals(grouped)
    status_total    = sum(status_totals.values())
    sys5_open_critical_defects = sum(
        1 for row in defects.get("rows", []) or []
        if not is_closed_defect_status(str(row.get("status", "")))
        and ("critical" in str(row.get("priority", "")).lower() or "blocker" in str(row.get("priority", "")).lower())
    )
    cw_label        = build_cw_label(start_date, end_date)
    report_heading  = f"Test Execution Report - {domain_filter_label} - {cw_label}"
    projects_label  = ", ".join(selected_projects or PROJECTS)
    generated_at    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_summary = {
        "test_cycles": total_cycles,
        "defects": int(defects.get("telematics_count", 0) or 0),
        "et_defects": int(defects.get("exploratory_count", 0) or 0),
        "closed_defects": sum(int(row.get("total", 0) or 0) for row in defects.get("closure_metrics", {}).get("rows", [])),
        "adhoc_requests": int(adhoc_effort.get("total_requests", 0) or 0),
        "feature_rg3_rg4_closed": int(feature_scope.get("rg3_rg4", {}).get("total", 0) or 0),
        "feature_rg45_closed": int(feature_scope.get("rg45", {}).get("total", 0) or 0),
    }

    if status_total > 0:
        pass_pct = (status_totals["pass"] / status_total) * 100
        fail_pct = (status_totals["failed"] / status_total) * 100
        abort_pct = (status_totals["aborted"] / status_total) * 100
        exec_pct = (status_totals["executing"] / status_total) * 100
        todo_pct = (status_totals["todo"] / status_total) * 100

        p1 = round(pass_pct, 2)
        p2 = round(p1 + fail_pct, 2)
        p3 = round(p2 + abort_pct, 2)
        p4 = round(p3 + exec_pct, 2)
        p5 = 100
        donut_bg = (
            f"conic-gradient("
            f"#1b9e3f 0% {p1}%, "
            f"#d93025 {p1}% {p2}%, "
            f"#111111 {p2}% {p3}%, "
            f"#c28a00 {p3}% {p4}%, "
            f"#7a7a7a {p4}% {p5}%"
            f")"
        )
    else:
        donut_bg = "conic-gradient(#dfe5ee 0% 100%)"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Test Execution Report</title>
<style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        :root {{
                        --ink-900: #1F2937;
                        --ink-700: #374151;
                        --ink-500: #4B5563;
                        --surface: #ffffff;
                        --surface-strong: #ffffff;
                        --line-soft: #D1D5DB;
                        --shadow-1: 0 1px 2px rgba(0, 0, 0, 0.06);
                        --shadow-2: 0 4px 12px rgba(0, 0, 0, 0.08);
        }}
        body {{
            font-family: "Segoe UI Variable Text", "Aptos", "Segoe UI", Arial, sans-serif;
                        color: #0F172A;
            font-size: 13px;
                background:
                    radial-gradient(circle at 8% 10%, rgba(0, 102, 177, 0.08) 0, rgba(0, 102, 177, 0) 40%),
                    radial-gradient(circle at 92% 88%, rgba(51, 65, 85, 0.08) 0, rgba(51, 65, 85, 0) 45%),
                    #FFFFFF;
            min-height: 100vh;
            position: relative;
            overflow-x: hidden;
        }}

    .header {{
                        background: linear-gradient(120deg, #0E2A47 0%, #1F4D7E 48%, #0E2A47 100%);
            color: #ffffff; padding: 24px 48px;
        display: flex; justify-content: space-between; align-items: center;
            border: 0;
                        box-shadow: 0 12px 30px rgba(15, 23, 42, 0.18);
            border-radius: 0;
  }}
    .header h1 {{ font-size: 22px; font-weight: 700; letter-spacing: 0.01em; }}
        .header .meta {{ font-size: 12px; text-align: right; line-height: 1.8; color: #d8e7fb; }}

    .container {{ width: min(1800px, calc(100% - 40px)); max-width: 1800px; margin: 26px auto; padding: 0 0 48px; }}
    .header, .container, .footer {{ position: relative; z-index: 1; }}

  /* summary cards */
  .sum-cards {{ display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 30px; }}
    .sum-card {{
        background: var(--surface-strong); border-radius: 12px; padding: 16px 20px; min-width: 180px;
        box-shadow: 0 12px 26px rgba(15, 23, 42, 0.08); border-top: 3px solid #0066B1;
        border: 1px solid rgba(148, 163, 184, 0.34);
  }}
        .sum-domain {{ font-weight: 700; font-size: 15px; color: #1F2937; margin-bottom: 8px; }}
    .sum-row {{ display: flex; align-items: center; gap: 6px; margin: 4px 0; color: #4B5563; }}
    .sum-n {{ margin-left: auto; font-weight: 700; color: #111827; }}
    .sum-total {{ margin-top: 10px; font-size: 12px; color: #4B5563; border-top: 1px solid #E5E7EB; padding-top: 8px; }}

    /* variant summary cards */
    .variant-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; margin-bottom: 30px; }}
    .variant-card {{
        background: var(--surface-strong); border-radius: 12px; padding: 14px 16px;
        box-shadow: 0 12px 26px rgba(15, 23, 42, 0.08); border-top: 3px solid #0066B1;
        border: 1px solid rgba(148, 163, 184, 0.34);
    }}
    .variant-name {{ font-size: 16px; font-weight: 700; color: #1F2937; margin-bottom: 10px; }}
    .variant-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 12px; }}
    .variant-cell {{ background: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 8px; padding: 8px 10px; }}
    .variant-cell span {{ display: block; font-size: 11px; color: #4B5563; margin-bottom: 3px; }}
    .variant-cell b {{ font-size: 15px; color: #1F2937; }}
    .variant-cell.status-pass  {{ background: #eef9f1; border-color: #d4ecd9; }}
    .variant-cell.status-fail  {{ background: #fdeeee; border-color: #f6d6d3; }}
    .variant-cell.status-abort {{ background: #f2f2f2; border-color: #dddddd; }}
    .variant-cell.status-exec  {{ background: #fff8e8; border-color: #f3e0ae; }}
    .variant-cell.status-todo  {{ background: #f4f4f4; border-color: #e1e1e1; }}
    .variant-cell.status-cycles {{ background: #f0f6ff; border-color: #d9e6fa; }}
    .variant-cell span.num-pass, .variant-cell b.num-pass {{ color: #1b9e3f; }}
    .variant-cell span.num-fail, .variant-cell b.num-fail {{ color: #d93025; }}
    .variant-cell span.num-abort, .variant-cell b.num-abort {{ color: #111111; }}
    .variant-cell span.num-exec, .variant-cell b.num-exec {{ color: #c28a00; }}
    .variant-cell span.num-todo, .variant-cell b.num-todo {{ color: #7a7a7a; }}
        .variant-split {{
            margin-top: 10px;
            display: flex;
            justify-content: space-between;
            gap: 10px;
            font-size: 12px;
            color: #4B5563;
            border-top: 1px solid #E5E7EB;
            padding-top: 8px;
        }}
        .variant-split b {{ color: #1F2937; }}
    .variant-total {{ margin-top: 10px; font-size: 12px; color: #4B5563; border-top: 1px solid #E5E7EB; padding-top: 8px; }}
  .dot {{ width: 9px; height: 9px; border-radius: 50%; display: inline-block; }}
  .dot-auto   {{ background: #2d6cb4; }}
  .dot-manual {{ background: #27ae60; }}

  /* top stat bar */
    .stat-bar {{ display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 34px; }}
    .stat {{ background: var(--surface-strong); border-radius: 12px; padding: 14px 22px; text-align: center;
                                         box-shadow: 0 14px 28px rgba(15, 23, 42, 0.08); flex: 1; border: 1px solid rgba(148, 163, 184, 0.32); }}
  .stat .n {{ font-size: 34px; font-weight: 700; }}
        .stat .l {{ font-size: 12px; color: #4B5563; margin-top: 3px; }}
    .stat.s-total  .n {{ color: #1F2937; }}
  .stat.s-auto   .n {{ color: #2d6cb4; }}
  .stat.s-manual .n {{ color: #27ae60; }}
    .stat.s-auto-exec .n {{ color: #0b4f6c; }}
    .stat.s-manual-exec .n {{ color: #7a3e00; }}

    /* compact donut chart */
    .donut-wrap {{
        background: var(--surface-strong);
        border-radius: 16px;
        box-shadow: 0 16px 30px rgba(15, 23, 42, 0.1);
        padding: 18px 20px;
        display: flex;
        align-items: center;
        gap: 24px;
        margin-bottom: 34px;
        flex-wrap: wrap;
        border: 1px solid rgba(148, 163, 184, 0.3);
    }}
    .donut-chart {{
        width: 156px;
        height: 156px;
        border-radius: 50%;
        display: grid;
        place-items: center;
        flex: 0 0 auto;
    }}
    .donut-hole {{
        width: 76px;
        height: 76px;
        border-radius: 50%;
        background: #ffffff;
        display: grid;
        place-items: center;
        text-align: center;
        box-shadow: inset 0 0 0 1px #CBD5E1;
    }}
    .donut-total {{ font-size: 26px; font-weight: 800; color: #0F172A; line-height: 1; }}
    .donut-sub {{ font-size: 10px; color: #4B5563; margin-top: 2px; }}
    .donut-legend {{ display: flex; gap: 16px; flex-wrap: wrap; }}
    .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 12px; color: #4B5563; }}
    .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
    .dot-pass {{ background: #1b9e3f; }}
    .dot-fail {{ background: #d93025; }}
    .dot-abort {{ background: #111111; }}
    .dot-exec {{ background: #c28a00; }}
    .dot-todo {{ background: #7a7a7a; }}

    .status-detail-wrap {{
        background: var(--surface-strong);
        border-radius: 16px;
        box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
        padding: 14px 16px;
        margin-bottom: 34px;
        border: 1px solid rgba(148, 163, 184, 0.3);
    }}

        /* rack utilisation */
        .rack-utilisation-section {{ margin-bottom: 30px; }}
        .rack-utilisation-card {{ background: #FFFFFF; border: 1px solid #D5DDE7; border-radius: 12px; padding: 20px 24px; box-shadow: 0 12px 26px rgba(10, 35, 66, 0.10); }}
        .rack-utilisation-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 14px; }}
        .rack-utilisation-item {{ min-width: 0; border: 1px solid #B8C8D8; border-top: 4px solid #0066B1; border-radius: 8px; padding: 16px; background: linear-gradient(145deg, #FFFFFF 0%, #F4F8FC 100%); box-shadow: 0 10px 22px rgba(10, 35, 66, 0.12); }}
        .rack-utilisation-heading {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; border-bottom: 1px solid #E5E7EB; padding-bottom: 12px; }}
        .rack-utilisation-heading h3 {{ color: #0A2342; font-size: 16px; letter-spacing: 0; margin: 0 0 3px; }}
        .rack-product {{ margin: 0 0 7px; color: #0066B1; font-size: 12px; font-weight: 800; letter-spacing: .03em; }}
        .rack-utilisation-heading p, .rack-utilisation-note {{ color: #4B5563; font-size: 12px; }}
        .rack-utilisation-heading strong {{ color: #0A2342; font-size: 22px; text-align: right; white-space: nowrap; }}
        .rack-utilisation-heading strong span {{ display: block; color: #6B7280; font-size: 11px; font-weight: 400; margin-top: 3px; }}
        .rack-utilisation-body {{ display: flex; align-items: center; gap: 18px; padding: 18px 0 14px; }}
        .rack-donut-svg {{ width: 142px; height: 142px; display: block; flex: 0 0 auto; overflow: visible; }}
        .rack-donut-svg path {{ stroke: #FFFFFF; stroke-width: 1; }}
        .rack-donut-svg text {{ font-family: "Segoe UI", Arial, sans-serif; font-size: 11px; font-weight: 800; pointer-events: none; }}
        .rack-donut-total {{ fill: #0A2342; font-size: 16px !important; }}
        .rack-donut-caption {{ fill: #64748B; font-size: 7px !important; font-weight: 400 !important; }}
        .rack-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
        .rack-auto {{ background: #2E7D32; }}
        .rack-offline {{ background: #D93025; }}
        .rack-manual {{ background: #F2C94C; }}
        .rack-idle {{ background: #B8BEC7; }}
        .rack-status {{ display: inline-block; padding: 3px 7px; border-radius: 10px; font-size: 10px; font-weight: 700; }}
        .rack-status-excellent {{ color: #FFFFFF; background: #166534; }}
        .rack-status-pool {{ color: #FFFFFF; background: #A16207; }}
        .rack-status-decommission {{ color: #FFFFFF; background: #B42318; }}
        .rack-status-no-activity {{ color: #FFFFFF; background: #475569; }}
        .rack-utilisation-kpi {{ display: grid; grid-template-columns: 1fr auto; align-items: baseline; gap: 4px 10px; border-top: 1px solid #E5E7EB; padding-top: 11px; }}
        .rack-utilisation-kpi span {{ color: #40566D; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; }}
        .rack-utilisation-kpi strong {{ color: #0066B1; font-size: 32px; font-weight: 900; line-height: 1; }}
        .rack-formula {{ margin-top: 18px; color: #64748B; font-size: 12px; font-weight: 600; text-align: center; }}
        .rack-shared-legend {{ display: flex; justify-content: center; gap: 28px; flex-wrap: wrap; margin-top: 18px; padding-top: 14px; border-top: 1px solid #E5E7EB; color: #0A2342; font-size: 14px; font-weight: 800; }}
        .rack-shared-legend span {{ display: inline-flex; align-items: center; gap: 7px; }}
        .rack-utilisation-note {{ border-top: 1px solid #E5E7EB; padding-top: 12px; }}
        .report-section {{ margin-bottom: 30px; }}
        .report-section-title {{ margin: 0 0 14px; padding: 14px 18px; border-left: 4px solid #0066B1; background: #F3F6FA; color: #0A2342; font-size: 20px; font-weight: 800; }}
        .report-section-title svg.lucide {{ width: 20px; height: 20px; vertical-align: -4px; margin-right: 6px; color: #0066B1; }}
        .scope-nav-card svg.lucide {{ width: 22px; height: 22px; margin-bottom: 6px; color: var(--scope-color, #0066B1); }}
        .report-detail {{ border: 1px solid #D5DDE7; border-radius: 10px; background: #FFFFFF; box-shadow: 0 8px 18px rgba(10, 35, 66, 0.08); }}
        .report-detail > summary {{ cursor: pointer; list-style: none; padding: 14px 18px; color: #0066B1; font-size: 14px; font-weight: 800; }}
        .report-detail > summary::-webkit-details-marker {{ display: none; }}
        .report-detail > summary::before {{ content: "▸ "; color: #0A2342; }}
        .report-detail[open] > summary::before {{ content: "▾ "; }}
        .report-detail-content {{ padding: 0 18px 18px; }}
        .pu-execution-counts {{ margin: 16px 0 22px; border: 1px solid #CBD5E1; border-radius: 12px; overflow: auto; background: #FFFFFF; box-shadow: 0 12px 26px rgba(10, 35, 66, 0.10); }}
        .pu-execution-table {{ width: 100%; border-collapse: separate; border-spacing: 0; min-width: 720px; font-variant-numeric: tabular-nums; }}
        .pu-execution-table th, .pu-execution-table td {{ padding: 14px 18px; border-bottom: 1px solid #E2E8F0; text-align: left; color: #334155; }}
        .pu-execution-table th {{ position: sticky; top: 0; z-index: 1; background: #0A2342; color: #FFFFFF; font-size: 12px; font-weight: 800; letter-spacing: .02em; white-space: nowrap; }}
        .pu-execution-table th:not(:first-child), .pu-execution-table td:not(:first-child) {{ text-align: right; }}
        .pu-execution-table tbody tr:nth-child(even) {{ background: #F8FAFC; }}
        .pu-execution-table tbody tr {{ transition: background-color .15s ease, box-shadow .15s ease; }}
        .pu-execution-table tbody tr:hover {{ background: #EAF3FB; box-shadow: inset 4px 0 0 #0066B1; }}
        .pu-execution-table tbody tr:last-child td {{ border-bottom: 0; }}
        .pu-product {{ color: #0A2342 !important; font-weight: 700; }}
        .pu-sop {{ color: #475569 !important; font-weight: 600; }}
        .pu-count-automation {{ color: #166534 !important; font-weight: 800; }}
        .pu-count-manual {{ color: #A16207 !important; font-weight: 800; }}
        .pu-count-total {{ color: #0A2342 !important; font-size: 15px; font-weight: 900; }}
        .pu-max-automation {{ background: #DCFCE7 !important; color: #166534 !important; box-shadow: inset 3px 0 0 #16A34A; }}
        .pu-max-manual {{ background: #FEF3C7 !important; color: #92400E !important; box-shadow: inset 3px 0 0 #D97706; }}

    /* domain block */
    .domain-block {{ background: var(--surface-strong); border-radius: 16px; margin-bottom: 28px;
                                     box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08); overflow: hidden; border: 1px solid rgba(148, 163, 184, 0.3); }}
    .domain-title {{ background: #F3F4F6; color: #1F2937; padding: 12px 20px;
                   font-size: 15px; font-weight: 600; }}
  .cycle-type-label {{
    padding: 8px 18px; font-size: 12px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.05em;
  }}
  .auto-label   {{ color: #2d6cb4; border-left: 4px solid #2d6cb4; margin: 10px 0 4px; }}
  .manual-label {{ color: #27ae60; border-left: 4px solid #27ae60; margin: 4px 0; }}
    .cycle-count  {{ font-weight: 400; color: #4B5563; margin-left: 8px; }}

  /* table */
  table {{ width: 100%; border-collapse: collapse; }}
        thead {{ background: #EEF2F7; }}
  thead th {{ padding: 9px 12px; text-align: left; font-size: 12px; font-weight: 600;
                                                        color: #1F2937; border-bottom: 2px solid #D1D5DB; white-space: nowrap; }}
        tbody tr:nth-child(even) {{ background: #FCFCFD; }}
        tbody tr:nth-child(odd) {{ background: #FFFFFF; }}
        tbody td {{ padding: 10px 12px; border-bottom: 1px solid #E5E7EB; vertical-align: middle; color: #1F2937; }}
  tbody tr:last-child td {{ border-bottom: none; }}
    a {{ color: #0066B1; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}

    .num-pass  {{ color: #1b9e3f; font-weight: 600; text-align: center; }}
    .num-fail  {{ color: #d93025; font-weight: 600; text-align: center; }}
    .num-abort {{ color: #111111; font-weight: 600; text-align: center; }}
    .num-exec  {{ color: #c28a00; font-weight: 700; text-align: center; }}
    .num-todo  {{ color: #7a7a7a; font-weight: 600; text-align: center; }}
    .num-total {{ color: #0b4f6c; font-weight: 700; }}

  .badge {{ display: inline-block; padding: 2px 9px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
  .b-closed    {{ background: #d4edda; color: #155724; }}
  .b-progress  {{ background: #fff3cd; color: #856404; }}
  .b-open      {{ background: #cfe2ff; color: #084298; }}
  .b-other     {{ background: #e2e3e5; color: #383d41; }}
  .b-new       {{ background: #e0e7ff; color: #3730a3; }}
  .b-resolved  {{ background: #d1fae5; color: #065f46; }}
  .b-reopened  {{ background: #ffe4c4; color: #9a4a00; }}
  .b-rejected  {{ background: #fde2e1; color: #a11d1d; }}
  .b-integrated {{ background: #ede9fe; color: #5b21b6; }}

        .empty {{ color: #6B7280; padding: 12px 20px; font-style: italic; }}
        .footer {{ text-align: center; font-size: 11px; color: #4B5563; margin-top: 20px; }}
    .section-title {{
        font-size: 13px; font-weight: 800; text-transform: uppercase;
                    letter-spacing: 0.08em; color: #0F172A; margin: 28px 0 14px;
                border-left: 4px solid #0066B1; padding-left: 11px;
  }}

    .cycles-toggle-bar {{
        display: flex;
        justify-content: flex-start;
        margin: 18px 0 8px;
    }}
    .cycles-toggle-btn {{
        appearance: none;
        border: 1px solid #0066B1;
        background: #FFFFFF;
        color: #0066B1;
        border-radius: 999px;
        padding: 8px 14px;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
        transition: background 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
    }}
    .cycles-toggle-btn:hover {{ background: #EAF4FC; box-shadow: 0 8px 18px rgba(0, 102, 177, 0.12); }}
    .cycles-toggle-btn:focus-visible {{ outline: 2px solid #0A5EA0; outline-offset: 2px; }}
    .cycles-toggle-btn.is-collapsed {{ background: #0066B1; color: #FFFFFF; }}
    .cycles-wrap.is-hidden {{ display: none; }}

    /* Executive defect dashboard */
    .defect-exec-dashboard {{ margin-bottom: 38px; }}
    .defect-kpis {{
        display: grid;
        grid-template-columns: repeat(6, minmax(150px, 1fr));
        gap: 14px;
        margin-bottom: 20px;
    }}
    .defect-kpi {{
        background: rgba(255, 255, 255, 0.8);
        border: 1px solid rgba(148, 163, 184, 0.34);
        border-radius: 14px;
        padding: 13px;
        box-shadow: 0 12px 26px rgba(15, 23, 42, 0.08);
        backdrop-filter: blur(8px);
        transition: transform 0.24s ease, box-shadow 0.24s ease;
    }}
    .defect-kpi:hover {{ box-shadow: 0 18px 34px rgba(15, 23, 42, 0.14); transform: translateY(-3px); }}
    .defect-kpi span {{ display: block; font-size: 11px; color: #4B5563; text-transform: uppercase; letter-spacing: 0.06em; }}
    .defect-kpi b {{ display: block; margin-top: 6px; font-size: 26px; color: #1F2937; }}
    .kpi-total {{ border-top: 4px solid #0066B1; }}
    .kpi-critical {{ border-top: 4px solid #C62828; }}
    .kpi-high {{ border-top: 4px solid #EF6C00; }}
    .kpi-medium {{ border-top: 4px solid #F9A825; }}
    .kpi-exploratory {{ border-top: 4px solid #2E7D32; }}
    .kpi-openclosed {{ border-top: 4px solid #3949AB; }}

    .defect-chart-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(320px, 1fr));
        gap: 14px;
        margin-bottom: 16px;
    }}
    .chart-card {{
        background: var(--surface-strong);
        border: 1px solid rgba(148, 163, 184, 0.32);
        border-radius: 16px;
        box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
        padding: 14px;
        min-height: 210px;
    }}
    .chart-card h3 {{ font-size: 14px; color: #1F2937; margin-bottom: 8px; }}
    .chart-host {{ min-height: 160px; }}
    .chart-canvas-wrap {{ height: 200px; position: relative; }}

    .domain-quick-jump {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 10px 0 16px; font-size: 12px; color: #4B5563; }}
    .domain-quick-jump span {{ font-weight: 700; color: #1F2937; }}
    .domain-quick-jump a {{ background: #EAF4FC; border: 1px solid #BFE0F5; border-radius: 999px; padding: 4px 12px; color: #0066B1; text-decoration: none; font-weight: 600; }}
    .domain-quick-jump a:hover {{ background: #0066B1; color: #FFFFFF; }}

    .domain-block {{ content-visibility: auto; contain-intrinsic-size: 900px; }}

    @media print {{
        #download-pdf {{ display: none !important; }}
    }}

    .adhoc-effort-section {{ margin-top: 20px; }}
    .adhoc-kpi-grid {{
        display: grid;
        grid-template-columns: repeat(6, minmax(145px, 1fr));
        gap: 12px;
        margin-bottom: 14px;
    }}
    .adhoc-kpi {{
        background: #FFFFFF;
        border: 1px solid rgba(148, 163, 184, 0.34);
        border-top: 4px solid #0B7285;
        border-radius: 12px;
        padding: 12px;
        box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08);
    }}
    .adhoc-kpi span {{ display: block; font-size: 11px; color: #4B5563; text-transform: uppercase; letter-spacing: .05em; }}
    .adhoc-kpi b {{ display: block; margin-top: 6px; font-size: 24px; color: #0F172A; }}
    .adhoc-chart-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(300px, 1fr));
        gap: 12px;
        margin-bottom: 12px;
    }}
    .adhoc-bars {{ display: grid; gap: 7px; }}
    .adhoc-bar-row {{ display: grid; grid-template-columns: minmax(140px, 1fr) 2fr auto; align-items: center; gap: 8px; }}
    .adhoc-bar-label {{ font-size: 12px; color: #1F2937; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .adhoc-bar-track {{ height: 12px; border-radius: 8px; background: #EDF2F7; border: 1px solid #D6E0EB; overflow: hidden; }}
    .adhoc-bar-fill {{ height: 100%; border-radius: 8px; }}
    .adhoc-bar-value {{ font-size: 12px; color: #1F2937; font-weight: 700; }}
    .assignee-category-chart {{ min-height: 0; margin-bottom: 12px; }}
    .adhoc-chart-legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 2px 0 12px; font-size: 11px; color: #4B5563; font-weight: 600; }}
    .adhoc-chart-legend span {{ display: inline-flex; align-items: center; gap: 5px; }}
    .adhoc-chart-legend i {{ width: 10px; height: 10px; border-radius: 3px; display: inline-block; }}
    .assignee-category-bars-wrap {{ display: grid; gap: 14px; }}
    .assignee-category-chart-row {{ display: grid; grid-template-columns: minmax(150px, 190px) 1fr; gap: 14px; align-items: start; }}
    .assignee-category-name {{ font-size: 12px; color: #1F2937; font-weight: 700; padding-top: 2px; overflow-wrap: anywhere; }}
    .assignee-category-bars {{ display: grid; gap: 6px; }}
    .assignee-category-bar-line {{ display: grid; grid-template-columns: minmax(90px, 125px) 1fr 28px; align-items: center; gap: 7px; }}
    .assignee-category-label {{ font-size: 11px; color: #4B5563; }}
    .assignee-category-value {{ font-size: 11px; color: #1F2937; font-weight: 700; text-align: right; }}
    .adhoc-table-wrap {{ overflow-x: auto; border: 1px solid #D1D5DB; border-radius: 10px; background: #FFFFFF; }}
    .adhoc-table {{ width: 100%; border-collapse: collapse; min-width: 820px; }}
    .adhoc-table th, .adhoc-table td {{ padding: 10px 12px; border-bottom: 1px solid #E5E7EB; text-align: left; vertical-align: top; }}
    .adhoc-table th {{ background: #EEF2F7; font-size: 12px; color: #1F2937; white-space: nowrap; }}
    .adhoc-ticket-table {{ min-width: 1350px; }}

    .ring-grid {{ display: grid; grid-template-columns: 230px 1fr; gap: 14px; align-items: center; min-height: 230px; }}
    .ring-chart {{ width: 230px; height: 230px; border-radius: 50%; display: grid; place-items: center; margin: 0 auto; }}
    .ring-hole {{ width: 112px; height: 112px; border-radius: 50%; background: #fff; box-shadow: inset 0 0 0 1px #CBD5E1; display: grid; place-items: center; text-align: center; }}
    .ring-total {{ font-size: 28px; font-weight: 800; color: #0F172A; line-height: 1; }}
    .ring-sub {{ font-size: 11px; color: #4B5563; margin-top: 3px; }}
    .ring-legend {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; }}
    .ring-legend li {{ display: flex; align-items: center; gap: 7px; color: #4B5563; font-size: 12px; }}
    .legend-swatch {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}

    .bar-chart-host {{ display: flex; flex-direction: column; }}
    .bar-chart-host .bar-list {{ display: grid; flex: 1; grid-template-rows: repeat(var(--bar-row-count, 1), minmax(0, 1fr)); align-content: stretch; gap: 8px; }}
    .bar-row {{ display: grid; grid-template-columns: minmax(120px, 1fr) 2fr auto; gap: 8px; align-items: center; }}
    .bar-label {{ font-size: 12px; color: #1F2937; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .bar-track {{ height: 12px; border-radius: 8px; background: #edf3fb; border: 1px solid #dbe7f8; overflow: hidden; }}
    .bar-fill {{ height: 100%; width: 0; border-radius: 8px; transition: width 0.7s ease; }}
    .bar-value {{ font-size: 12px; font-weight: 700; color: #1F2937; }}
    .bar-defects {{ grid-column: 1 / -1; margin-top: -2px; }}
    .bar-defects summary {{ width: fit-content; cursor: pointer; color: #0066B1; font-size: 11px; font-weight: 700; }}
    .bar-defect-links {{ display: flex; flex-wrap: wrap; gap: 5px 12px; padding: 6px 0 2px; }}
    .bar-defect-links a {{ color: #00538F; font-size: 11px; font-weight: 600; text-decoration: none; }}
    .bar-defect-links a:hover {{ text-decoration: underline; }}
    .coverage-list {{
        display: grid;
        gap: 14px;
    }}
    .coverage-row {{ display: grid; gap: 8px; }}
    .coverage-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }}
    .coverage-label {{ font-size: 12px; font-weight: 700; color: #1F2937; }}
    .coverage-total {{ font-size: 12px; color: #475569; }}
    .coverage-chart {{
        display: grid;
        gap: 6px;
    }}
    .coverage-bar {{
        display: grid;
        grid-template-columns: 70px 1fr 32px;
        align-items: center;
        gap: 8px;
        font-size: 10px;
        color: #64748B;
    }}
    .coverage-track {{ height: 12px; border-radius: 8px; background: #EDF3FB; border: 1px solid #DBE7F8; overflow: hidden; }}
    .coverage-fill {{ height: 100%; width: 0; transition: width 0.7s ease; }}
    .coverage-fill.with-tool {{ background: #B45309; }}
    .coverage-fill.without-tool {{ background: #94A3B8; }}
    .coverage-value {{ font-size: 11px; font-weight: 700; color: #1F2937; text-align: right; }}
    .coverage-bar-labels {{ display: none; }}
    .coverage-col {{ display: none; }}
    .coverage-col-value {{ display: none; }}
    .coverage-fill-label {{
        font-size: 10px;
        color: #64748B;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }}
    .coverage-legend {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 10px; font-size: 11px; color: #475569; }}
    .coverage-legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
    .coverage-legend i {{ width: 10px; height: 10px; border-radius: 999px; display: inline-block; }}
    .coverage-note {{ font-size: 11px; color: #64748B; margin-top: 6px; }}

    .weekly-insights {{
        display: grid;
        grid-template-columns: repeat(4, minmax(170px, 1fr));
        gap: 12px;
        margin-bottom: 14px;
    }}
    .insight-card {{
        background: #ffffff;
        border: 1px solid rgba(148, 163, 184, 0.3);
        border-radius: 12px;
        padding: 12px 14px;
        box-shadow: 0 10px 22px rgba(15, 23, 42, 0.07);
    }}
    .insight-card h4 {{ font-size: 12px; color: #4B5563; margin-bottom: 6px; }}
    .insight-card p {{ font-size: 18px; font-weight: 700; color: #1F2937; }}

    .risk-sub {{ color: #4B5563; font-size: 12px; margin: 2px 0 10px; }}
    .risk-wrap {{ overflow-x: auto; background: var(--surface-strong); border: 1px solid #D1D5DB; border-radius: 12px; box-shadow: var(--shadow-1); }}
    .risk-table {{ width: 100%; border-collapse: collapse; min-width: 920px; }}
    .risk-table thead th {{ position: sticky; top: 0; z-index: 2; background: #EEF2F7; color: #1F2937; }}
    .risk-table tbody tr:nth-child(even) {{ background: #FCFCFD; }}
    .risk-table tbody tr:hover {{ background: #F3F4F6; }}
    .risk-table td, .risk-table th {{ padding: 10px 12px; border-bottom: 1px solid #E5E7EB; vertical-align: top; color: #1F2937; }}
    .risk-reason {{
        display: inline-block;
        margin: 0 6px 6px 0;
        padding: 2px 8px;
        border-radius: 999px;
        background: #fdecea;
        color: #8f1d1d;
        font-size: 11px;
        font-weight: 700;
    }}

    .defect-accordions {{ display: grid; gap: 10px; }}
    .defect-accordion {{
        background: var(--surface-strong);
        border: 1px solid #D1D5DB;
        border-radius: 12px;
        box-shadow: var(--shadow-1);
        overflow: hidden;
    }}
    .defect-accordion > summary {{
        cursor: pointer;
        list-style: none;
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 14px;
        font-weight: 700;
        color: #1F2937;
    }}
    .defect-accordion > summary::-webkit-details-marker {{ display: none; }}
    .acc-count {{
        min-width: 34px;
        text-align: center;
        border-radius: 999px;
        padding: 2px 8px;
        color: #fff;
        font-size: 12px;
    }}
    .defect-acc-critical .acc-count {{ background: #C62828; }}
    .defect-acc-high .acc-count {{ background: #EF6C00; }}
    .defect-acc-medium .acc-count {{ background: #F9A825; color: #2a1f00; }}
    .defect-acc-low .acc-count {{ background: #1565C0; }}
    .acc-content {{ padding: 0 10px 10px; }}

    .defect-table-wrap {{ overflow-x: auto; border: 1px solid #D1D5DB; border-radius: 10px; }}
    .defect-table {{ width: 100%; min-width: 980px; border-collapse: collapse; }}
    .defect-table thead th {{
        position: sticky;
        top: 0;
        z-index: 2;
        background: #EEF2F7;
        border-bottom: 2px solid #D1D5DB;
        color: #1F2937;
    }}
    .defect-table tbody tr:nth-child(even) {{ background: #FCFCFD; }}
    .defect-table tbody tr:hover {{ background: #F3F4F6; }}
    .defect-table td, .defect-table th {{ padding: 10px 12px; border-bottom: 1px solid #E5E7EB; vertical-align: top; color: #1F2937; }}
    .cell-key {{ font-weight: 700; color: #0066B1; }}
    .cell-summary {{ color: #1F2937; line-height: 1.35; margin-bottom: 6px; }}

    .sev-badge {{
        display: inline-block;
        border-radius: 999px;
        padding: 2px 9px;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.02em;
    }}
    .sev-critical {{ background: #C62828; color: #fff; }}
    .sev-high {{ background: #EF6C00; color: #fff; }}
    .sev-medium {{ background: #F9A825; color: #262100; }}
    .sev-low {{ background: #1565C0; color: #fff; }}

    .row-detail summary {{ cursor: pointer; color: #0066B1; font-size: 12px; }}
    .row-detail-grid {{
        margin-top: 6px;
        display: grid;
        grid-template-columns: repeat(2, minmax(180px, 1fr));
        gap: 6px 12px;
        font-size: 12px;
        color: #4B5563;
        background: #F9FAFB;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 8px;
    }}

    .closure-exec-wrap {{
        margin-top: 10px;
        border: 1px solid rgba(148, 163, 184, 0.34);
        border-radius: 18px;
        background: linear-gradient(140deg, rgba(255, 255, 255, 0.92) 0%, rgba(239, 246, 255, 0.72) 100%);
        backdrop-filter: blur(10px);
        box-shadow: 0 18px 34px rgba(15, 23, 42, 0.1);
        padding: 18px;
    }}
    .closure-summary-banner {{
        border-radius: 10px;
        border: 1px solid #C7DBF5;
        background: linear-gradient(135deg, #EEF5FF 0%, #F8FAFC 100%);
        color: #0E2A47;
        font-weight: 700;
        font-size: 13px;
        padding: 12px 14px;
        margin-bottom: 12px;
    }}
    .closure-kpi-grid {{
        display: grid;
        grid-template-columns: repeat(5, minmax(150px, 1fr));
        gap: 12px;
        margin-bottom: 16px;
    }}
    .metric-glossary {{
        border: 1px solid #C7DBF5;
        border-radius: 10px;
        background: #F8FAFC;
        padding: 12px 16px;
        margin-bottom: 16px;
    }}
    .metric-glossary-title {{ font-weight: 800; color: #0E2A47; font-size: 13px; margin-bottom: 8px; }}
    .metric-glossary-item {{ font-size: 12.5px; line-height: 1.5; color: #374151; margin-bottom: 8px; }}
    .metric-glossary-item:last-child {{ margin-bottom: 0; }}
    .closure-kpi {{
        position: relative;
        border-radius: 14px;
        border: 1px solid rgba(148, 163, 184, 0.32);
        background: rgba(255, 255, 255, 0.82);
        padding: 12px 12px 12px 14px;
        box-shadow: 0 12px 26px rgba(15, 23, 42, 0.09);
        backdrop-filter: blur(8px);
        transition: transform 0.24s ease, box-shadow 0.24s ease;
    }}
    .closure-kpi:hover {{
        transform: translateY(-3px);
        box-shadow: 0 18px 34px rgba(15, 23, 42, 0.14);
    }}
    .closure-kpi[data-info-text] {{ cursor: pointer; }}
    .closure-kpi[data-info-text]::after {{
        content: "?";
        position: absolute;
        left: 10px;
        top: 10px;
        width: 16px;
        height: 16px;
        border-radius: 999px;
        display: grid;
        place-items: center;
        font-size: 10px;
        font-weight: 800;
        color: #4B5563;
        background: rgba(148, 163, 184, 0.22);
    }}
    .kpi-info-dialog {{
        border: none;
        border-radius: 14px;
        padding: 0;
        max-width: 360px;
        box-shadow: 0 22px 44px rgba(15, 23, 42, 0.24);
        position: fixed;
        margin: 0;
    }}
    .kpi-info-dialog.has-table {{ max-width: 640px; width: 90vw; }}
    .kpi-info-dialog::backdrop {{ background: rgba(15, 23, 42, 0.45); }}
    .kpi-info-dialog-body {{ padding: 18px 20px; }}
    .kpi-info-title {{ margin: 0 0 8px; font-size: 15px; font-weight: 800; color: #0F172A; }}
    .kpi-info-figure {{ display: flex; align-items: baseline; gap: 8px; margin: 0 0 10px; font-size: 22px; font-weight: 800; color: #0F172A; }}
    .kpi-info-figure small {{ font-size: 12px; font-weight: 600; color: #6B7280; }}
    .kpi-info-text {{ margin: 0; font-size: 13px; line-height: 1.5; color: #374151; }}
    .kpi-info-rows-wrap {{ margin-top: 12px; max-height: 320px; overflow-y: auto; border: 1px solid #E5E7EB; border-radius: 8px; }}
    .kpi-info-rows-wrap table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    .kpi-info-rows-wrap th, .kpi-info-rows-wrap td {{ padding: 6px 10px; text-align: left; border-bottom: 1px solid #EEF2F6; white-space: nowrap; }}
    .kpi-info-rows-wrap th {{ position: sticky; top: 0; background: #F8FAFC; color: #4B5563; font-weight: 700; }}
    .kpi-info-close {{
        margin-top: 14px;
        border: 1px solid #B8C9DA;
        border-radius: 7px;
        background: #FFFFFF;
        color: #0E2A47;
        padding: 7px 12px;
        font-weight: 700;
        cursor: pointer;
    }}
    .kpi-info-close:hover {{ background: #EAF4FC; border-color: #0066B1; }}
    .closure-kpi .kpi-mark {{
        position: absolute;
        right: 10px;
        top: 10px;
        width: 22px;
        height: 22px;
        border-radius: 999px;
        display: grid;
        place-items: center;
        font-size: 10px;
        font-weight: 800;
        border: 1px solid rgba(15, 23, 42, 0.14);
        color: #0F172A;
        background: rgba(255, 255, 255, 0.86);
    }}
    .closure-kpi span {{ display: block; font-size: 11px; color: #4B5563; text-transform: uppercase; letter-spacing: 0.05em; }}
    .closure-kpi b {{ display: block; margin-top: 6px; font-size: 28px; color: #111827; line-height: 1.05; }}
    .closure-kpi small {{ display: block; margin-top: 5px; font-size: 11px; color: #6B7280; }}
    .kpi-blue {{ border-top: 4px solid #0066B1; }}
    .kpi-green {{ border-top: 4px solid #10B981; }}
    .kpi-red {{ border-top: 4px solid #DC2626; }}
    .kpi-amber {{ border-top: 4px solid #D97706; }}
    .kpi-navy {{ border-top: 4px solid #0F172A; }}
    .kpi-green .kpi-mark {{ background: rgba(16, 185, 129, 0.16); color: #047857; border-color: rgba(4, 120, 87, 0.26); }}
    .kpi-blue .kpi-mark {{ background: rgba(0, 102, 177, 0.16); color: #005492; border-color: rgba(0, 84, 146, 0.26); }}
    .kpi-red .kpi-mark {{ background: rgba(220, 38, 38, 0.16); color: #B91C1C; border-color: rgba(185, 28, 28, 0.26); }}
    .kpi-amber .kpi-mark {{ background: rgba(217, 119, 6, 0.16); color: #B45309; border-color: rgba(180, 83, 9, 0.26); }}
    .kpi-navy .kpi-mark {{ background: rgba(15, 23, 42, 0.14); color: #0F172A; border-color: rgba(15, 23, 42, 0.24); }}

    .trend-up {{ color: #15803D; font-weight: 700; }}
    .trend-down {{ color: #B91C1C; font-weight: 700; }}
    .trend-flat {{ color: #374151; font-weight: 700; }}

    .closure-project-rings {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 12px;
        margin-bottom: 16px;
    }}
    .closure-ring-card {{
        border: 1px solid rgba(148, 163, 184, 0.3);
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.84);
        box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
        backdrop-filter: blur(8px);
        padding: 12px;
        transition: transform 0.22s ease, box-shadow 0.22s ease;
    }}
    .closure-ring-card:hover {{
        transform: translateY(-2px);
        box-shadow: 0 16px 30px rgba(15, 23, 42, 0.13);
    }}
    .closure-ring-head {{
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        font-weight: 700;
        color: #1F2937;
        margin-bottom: 8px;
    }}
    .closure-ring-sub {{ margin: -4px 0 8px; font-size: 11px; color: #4B5563; min-height: 28px; }}
    .tlm-icon {{
        width: 16px;
        height: 10px;
        display: inline-block;
        border-radius: 5px 5px 3px 3px;
        background: linear-gradient(135deg, #0B0F1A, #4B5563);
        position: relative;
    }}
    .tlm-icon::before, .tlm-icon::after {{
        content: "";
        position: absolute;
        bottom: -3px;
        width: 4px;
        height: 4px;
        background: #111827;
        border-radius: 50%;
    }}
    .tlm-icon::before {{ left: 2px; }}
    .tlm-icon::after {{ right: 2px; }}

    .closure-ring {{
        width: 126px;
        height: 126px;
        margin: 0 auto;
        border-radius: 50%;
        display: grid;
        place-items: center;
    }}
    .closure-ring-inner {{
        width: 68px;
        height: 68px;
        border-radius: 50%;
        background: #FFFFFF;
        display: grid;
        place-items: center;
        box-shadow: inset 0 0 0 1px #D1D5DB;
        text-align: center;
    }}
    .closure-ring-inner b {{ font-size: 18px; color: #111827; line-height: 1; }}
    .closure-ring-inner span {{ font-size: 11px; color: #4B5563; line-height: 1.1; }}
    .closure-ring-note {{ margin-top: 8px; font-size: 11px; color: #4B5563; text-align: center; }}

    .closure-bars-wrap {{
        border: 1px solid rgba(148, 163, 184, 0.3);
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.85);
        padding: 12px;
        box-shadow: 0 12px 26px rgba(15, 23, 42, 0.08);
        margin-bottom: 16px;
        display: grid;
        gap: 10px;
    }}
    .closure-bar-row {{
        border: 1px solid #DCE4EE;
        border-radius: 10px;
        background: #F8FBFF;
        padding: 9px;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }}
    .closure-bar-row:hover {{
        transform: translateY(-1px);
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.1);
    }}
    .closure-bar-head {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; font-weight: 700; color: #1F2937; font-size: 13px; }}
    .closure-bar-track {{
        height: 14px;
        margin-top: 7px;
        border-radius: 999px;
        background: #E5E7EB;
        overflow: hidden;
        border: 1px solid #D1D5DB;
    }}
    .closure-bar-fill {{
        height: 100%;
        border-radius: 999px;
        transition: width 0.8s ease;
    }}
    .closure-bar-meta {{ margin-top: 6px; font-size: 12px; color: #4B5563; line-height: 1.35; }}
    .closure-product-pie {{
        margin-top: 8px;
        display: grid;
        grid-template-columns: 86px 1fr;
        gap: 10px;
        align-items: center;
        border: 1px solid #DBEAFE;
        border-radius: 10px;
        background: #F8FBFF;
        padding: 8px;
    }}
    .closure-product-ring {{ width: 72px; height: 72px; border-radius: 50%; display: grid; place-items: center; margin: 0 auto; }}
    .closure-product-hole {{ width: 42px; height: 42px; border-radius: 50%; background: #FFFFFF; box-shadow: inset 0 0 0 1px #D1D5DB; display: grid; place-items: center; text-align: center; }}
    .closure-product-hole b {{ font-size: 13px; color: #111827; line-height: 1; }}
    .closure-product-hole span {{ font-size: 9px; color: #4B5563; line-height: 1.1; }}
    .closure-product-legend {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; font-size: 11px; color: #4B5563; }}
    .closure-product-legend li {{ display: flex; align-items: center; gap: 6px; }}
    .closure-product-empty {{ margin-top: 8px; font-size: 11px; color: #6B7280; }}
    .closure-inline-title {{ margin: 18px 0 10px; }}
    .closure-metric-pies {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        margin-bottom: 16px;
    }}
    .closure-metric-pie-card {{
        border: 1px solid rgba(148, 163, 184, 0.3);
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.86);
        padding: 12px;
        box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
    }}
    .closure-metric-pie-title {{ font-size: 12px; font-weight: 700; color: #1F2937; margin-bottom: 8px; min-height: 32px; }}
    .closure-metric-pie-dual {{ display: grid; gap: 10px; }}
    .closure-metric-pie-sublabel {{ display: block; font-size: 10px; font-weight: 700; color: #6B7280; text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 4px; }}
    .closure-bars-toggle {{ margin-top: 4px; }}
    .closure-bars-toggle > summary {{
        cursor: pointer;
        list-style: none;
        font-size: 12px;
        font-weight: 700;
        color: #0066B1;
        margin: 0 0 10px;
    }}
    .closure-bars-toggle > summary::-webkit-details-marker {{ display: none; }}
    .closure-bars-toggle > summary::before {{ content: "▾ "; color: #1F2937; }}
    .closure-bars-toggle:not([open]) > summary::before {{ content: "▸ "; }}
    .closure-ids summary {{ cursor: pointer; color: #0066B1; font-size: 12px; margin-top: 5px; }}
    .closure-overall-summary {{ margin: 0 0 8px; padding: 8px 10px; border-radius: 8px; background: #F8FBFF; border: 1px solid #DBEAFE; color: #1F2937; font-size: 12px; line-height: 1.4; }}
    .closure-detail-table-wrap {{
        margin-top: 6px;
        border: 1px solid #DBEAFE;
        border-radius: 10px;
        background: #F8FBFF;
        padding: 8px;
        overflow-x: auto;
    }}
    .closure-detail-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
        min-width: 900px;
    }}
    .closure-detail-table th,
    .closure-detail-table td {{
        border-bottom: 1px solid #DCE4EE;
        padding: 7px 8px;
        vertical-align: top;
        text-align: left;
        color: #1F2937;
    }}
    .closure-detail-table th {{
        background: #EFF6FF;
        color: #0F172A;
        font-weight: 700;
        white-space: nowrap;
    }}
    .closure-detail-table tbody tr:last-child td {{ border-bottom: none; }}
    .closure-detail-table td:nth-child(4),
    .closure-detail-table td:nth-child(9) {{ word-break: break-word; }}
    .closure-detail-table td:nth-child(4) {{ min-width: 240px; }}
    .closure-detail-table td:nth-child(9) {{ min-width: 320px; }}

    .closure-insights {{
        display: grid;
        grid-template-columns: 1fr 1.6fr;
        gap: 12px;
    }}
    .closure-insight-card {{
        border: 1px solid rgba(148, 163, 184, 0.3);
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.86);
        padding: 12px 14px;
        box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
        backdrop-filter: blur(8px);
    }}
    .closure-insight-card h4 {{ margin-bottom: 6px; font-size: 12px; color: #4B5563; text-transform: uppercase; letter-spacing: 0.04em; }}
    .closure-insight-card p {{ font-size: 18px; font-weight: 700; color: #1F2937; }}
    .closure-insight-card ul {{ margin: 0; padding-left: 18px; color: #374151; font-size: 13px; line-height: 1.4; }}
    .pareto-wrap {{
        border: 1px solid rgba(148, 163, 184, 0.3);
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.85);
        padding: 14px;
        margin-bottom: 16px;
        display: grid;
        gap: 10px;
    }}
    .pareto-row {{ display: grid; grid-template-columns: 150px 1fr 90px 130px; align-items: center; gap: 10px; }}
    .pareto-label {{ font-size: 12px; font-weight: 700; color: #1F2937; }}
    .pareto-bar-track {{ height: 14px; border-radius: 999px; background: #E5E7EB; border: 1px solid #D1D5DB; overflow: hidden; }}
    .pareto-bar-fill {{ height: 100%; border-radius: 999px; background: #0066B1; transition: width 0.8s ease; }}
    .pareto-value {{ font-size: 12px; font-weight: 700; color: #1F2937; text-align: right; }}
    .pareto-cumulative {{ font-size: 11px; color: #6B7280; text-align: right; }}
    .scope-hidden {{ display: none !important; }}
    .scope-dashboard-nav {{
        width: min(1500px, calc(100% - 32px));
        margin: 24px auto 0;
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 14px;
    }}
    .scope-nav-card {{
        appearance: none;
        border: 1px solid #D8E2ED;
        border-top: 4px solid var(--scope-color, #0066B1);
        border-radius: 14px;
        background: linear-gradient(145deg, #FFFFFF 0%, #F2F7FC 100%);
        color: #0F172A;
        min-height: 86px;
        padding: 14px 16px;
        text-align: left;
        cursor: pointer;
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
        transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease, background .2s ease;
    }}
    .scope-nav-card:hover {{ transform: translateY(-2px); box-shadow: 0 14px 28px rgba(15, 23, 42, 0.13); }}
    .scope-nav-card:focus-visible {{ outline: 3px solid rgba(0, 102, 177, .28); outline-offset: 2px; }}
    .scope-nav-card.is-active {{ background: #EAF4FC; border-color: var(--scope-color, #0066B1); box-shadow: 0 14px 30px rgba(0, 102, 177, .16); }}
    .scope-nav-card strong {{ display: block; font-size: 14px; font-weight: 800; letter-spacing: .01em; }}
    .scope-nav-card span {{ display: block; margin-top: 5px; color: #64748B; font-size: 11px; }}
    .scope-panel {{ animation: scope-panel-in .28s ease both; }}
    .report-toolbar {{ width: min(1800px, calc(100% - 40px)); margin: 16px auto 0; display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }}
    .report-toolbar button {{ border: 1px solid #B8C9DA; border-radius: 7px; background: #FFFFFF; color: #0E2A47; padding: 8px 12px; font-weight: 700; cursor: pointer; }}
    .report-toolbar button:hover {{ background: #EAF4FC; border-color: #0066B1; }}
    .executive-summary {{ width: min(1800px, calc(100% - 40px)); margin: 16px auto 0; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }}
    .executive-summary-card {{ border: 1px solid #D8E2ED; border-radius: 10px; background: #FFFFFF; padding: 11px 14px; box-shadow: 0 5px 14px rgba(15,23,42,.06); }}
    .executive-summary-card span {{ display: block; color: #64748B; font-size: 11px; text-transform: uppercase; font-weight: 700; }}
    .executive-summary-card b {{ display: block; color: #0E2A47; font-size: 22px; margin-top: 4px; }}
    .report-metadata {{ width: min(1800px, calc(100% - 40px)); margin: 12px auto 0; padding: 10px 14px; border-left: 4px solid #0066B1; background: #F3F7FB; color: #334155; font-size: 12px; line-height: 1.6; }}
    .defect-filter-bar {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 10px 0; padding: 9px; border: 1px solid #D8E2ED; border-radius: 8px; background: #F8FBFF; }}
    .defect-filter-bar input, .defect-filter-bar select {{ min-height: 32px; border: 1px solid #B8C9DA; border-radius: 6px; padding: 5px 8px; color: #1F2937; background: #FFFFFF; }}
    .defect-filter-count {{ margin-left: auto; color: #64748B; font-size: 12px; font-weight: 700; }}
    .data-quality-note {{ margin: 8px 0 14px; padding: 9px 12px; border-radius: 7px; background: #FFF8E1; border: 1px solid #F2D58A; color: #6B4E00; font-size: 12px; }}
    .data-coverage-warning {{ margin: 8px 0 14px; padding: 9px 12px; border-radius: 7px; background: #FDECEA; border: 1px solid #F5B3AD; color: #8A1F11; font-size: 12px; font-weight: 700; }}
    .back-to-top {{ position: fixed; right: 20px; bottom: 20px; z-index: 10; border: 0; border-radius: 999px; background: #0066B1; color: #FFFFFF; padding: 10px 14px; font-weight: 800; cursor: pointer; box-shadow: 0 8px 18px rgba(15,23,42,.2); }}
    @media (max-width: 720px) {{ .executive-summary {{ width: calc(100% - 20px); grid-template-columns: repeat(2, minmax(0, 1fr)); }} .report-metadata, .report-toolbar {{ width: calc(100% - 20px); }} .defect-filter-count {{ width: 100%; margin-left: 0; }} }}
    @keyframes scope-panel-in {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    @media (max-width: 720px) {{
        .scope-dashboard-nav {{ width: calc(100% - 20px); grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 14px; }}
        .scope-nav-card {{ min-height: 72px; padding: 10px; }}
        .scope-nav-card strong {{ font-size: 12px; }}
        .scope-nav-card span {{ font-size: 10px; }}
    }}

    @media print {{
        body {{
            background: #ffffff !important;
            color: #111827 !important;
            font-size: 11px;
        }}
        .header, .sum-card, .variant-card, .stat, .status-detail-wrap, .domain-block, .chart-card, .insight-card, .defect-accordion, .risk-wrap {{
            box-shadow: none !important;
            border-color: #D1D5DB !important;
            break-inside: avoid;
        }}
        .defect-table thead th,
        .risk-table thead th,
        table thead th {{
            position: static !important;
        }}
    }}

    @media (max-width: 1100px) {{
        .container {{ width: calc(100% - 28px); margin-top: 22px; }}
        .defect-kpis {{ grid-template-columns: repeat(3, minmax(150px, 1fr)); }}
        .adhoc-kpi-grid {{ grid-template-columns: repeat(3, minmax(150px, 1fr)); }}
        .weekly-insights {{ grid-template-columns: repeat(2, minmax(180px, 1fr)); }}
        .defect-chart-grid {{ grid-template-columns: 1fr; }}
        .adhoc-chart-grid {{ grid-template-columns: 1fr; }}
        .closure-kpi-grid {{ grid-template-columns: repeat(3, minmax(150px, 1fr)); }}
        .closure-insights {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 720px) {{
        .header {{ padding: 18px 20px; flex-direction: column; align-items: flex-start; gap: 10px; }}
        .header .meta {{ text-align: left; line-height: 1.5; }}
        .container {{ width: calc(100% - 20px); margin: 16px auto; padding-bottom: 32px; }}
        .report-section-title {{ font-size: 17px; padding: 11px 13px; }}
        .defect-kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
        .adhoc-kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
        .defect-kpi {{ min-width: 0; padding: 10px; }}
        .defect-kpi span {{ font-size: 10px; letter-spacing: 0.03em; }}
        .defect-kpi b {{ font-size: 22px; }}
        .weekly-insights {{ grid-template-columns: 1fr; }}
        .ring-grid {{ grid-template-columns: 1fr; }}
        .row-detail-grid {{ grid-template-columns: 1fr; }}
        .closure-kpi-grid {{ grid-template-columns: repeat(2, minmax(130px, 1fr)); }}
        .closure-project-rings {{ grid-template-columns: repeat(2, minmax(130px, 1fr)); }}
        .chart-card {{ min-height: 0; padding: 11px; }}
        .chart-card h3 {{ font-size: 13px; }}
        .chart-host {{ min-height: 150px; }}
        .bar-chart-host .bar-list {{ gap: 6px; }}
        .bar-row {{ grid-template-columns: minmax(90px, 1fr) 1.5fr auto; gap: 6px; }}
        .bar-label, .bar-value {{ font-size: 11px; }}
        .coverage-list {{ min-height: 170px; }}
        .coverage-chart {{ height: 130px; }}
    }}
</style>
</head>
<body>

<div class="header">
  <div>
        <h1>{report_heading}</h1>
    <div style="font-size:12px;opacity:0.8;margin-top:4px;">Projects: {projects_label}</div>
  </div>
  <div class="meta">
    Period: {start_date} &rarr; {end_date}<br>
        Domain: {domain_filter_label}<br>
    Generated: {generated_at}
  </div>
</div>

<nav class="scope-dashboard-nav" aria-label="Report scope navigation">
    <button class="scope-nav-card" data-scope="test" style="--scope-color:#0879D1" type="button" aria-controls="scope-test" aria-selected="false"><i data-lucide="clipboard-check"></i><strong>Test Scope</strong><span>Execution cycles and results</span></button>
    <button class="scope-nav-card" data-scope="defect" style="--scope-color:#7044D5" type="button" aria-controls="scope-defect" aria-selected="false"><i data-lucide="bug"></i><strong>Defect Scope</strong><span>Defect health and risk</span></button>
    <button class="scope-nav-card" data-scope="resolution" style="--scope-color:#087B50" type="button" aria-controls="scope-resolution" aria-selected="false"><i data-lucide="circle-check-big"></i><strong>Defect Resolution Scope</strong><span>Closure throughput and trends</span></button>
    <button class="scope-nav-card" data-scope="adhoc" style="--scope-color:#0B7285" type="button" aria-controls="scope-adhoc" aria-selected="false"><i data-lucide="wrench"></i><strong>Ad-Hoc Scope</strong><span>Ad-hoc effort analysis</span></button>
    <button class="scope-nav-card" data-scope="rack" style="--scope-color:#EE8A18" type="button" aria-controls="scope-rack" aria-selected="false"><i data-lucide="server"></i><strong>Rack Utilisation Scope</strong><span>Resource activity and utilisation</span></button>
    <button class="scope-nav-card" data-scope="feature" style="--scope-color:#B45309" type="button" aria-controls="scope-feature" aria-selected="false"><i data-lucide="list-checks"></i><strong>Feature Scope</strong><span>RG3/RG4 and RG4.5 SYS.5 closures</span></button>
</nav>
<section class="executive-summary" aria-label="Executive summary">
    <article class="executive-summary-card"><span>Test execution cycles</span><b>{report_summary['test_cycles']}</b></article>
    <article class="executive-summary-card"><span>Defects raised</span><b>{report_summary['defects']}</b></article>
    <article class="executive-summary-card"><span>ET defects</span><b>{report_summary['et_defects']}</b></article>
    <article class="executive-summary-card"><span>Closure records</span><b>{report_summary['closed_defects']}</b></article>
    <article class="executive-summary-card"><span>Ad-Hoc requests</span><b>{report_summary['adhoc_requests']}</b></article>
    <article class="executive-summary-card"><span>RG3/RG4 SYS.5 closed</span><b>{report_summary['feature_rg3_rg4_closed']}</b></article>
    <article class="executive-summary-card"><span>RG4.5 SYS.5 closed</span><b>{report_summary['feature_rg45_closed']}</b></article>
</section>
<div class="report-metadata"><b>Applied scope:</b> {escape(domain_filter_label)} &nbsp;|&nbsp; <b>Projects:</b> {escape(projects_label)} &nbsp;|&nbsp; <b>Period:</b> {escape(start_date)} to {escape(end_date)} &nbsp;|&nbsp; <b>Generated:</b> {escape(generated_at)}</div>
<div class="report-toolbar" aria-label="Report actions"><button id="print-report" type="button">Print report</button><button id="download-pdf" type="button">Download PDF</button><button id="expand-details" type="button">Expand details</button><button id="collapse-details" type="button">Collapse details</button></div>

<div class="container">

    <section id="scope-test" data-scope-panel="test" class="report-section scope-panel{' scope-hidden' if 'test' not in report_scopes else ''}">
        <h2 class="report-section-title"><i data-lucide="clipboard-check"></i> Test Execution Summary</h2>
        <div class="stat-bar">
            <div class="stat s-total"><div class="n">{total_cycles}</div><div class="l">Total Test Execution Cycles</div></div>
            <div class="stat s-auto"><div class="n">{total_auto}</div><div class="l">Automation Test Executions</div></div>
            <div class="stat s-manual"><div class="n">{total_manual}</div><div class="l">Manual Test Executions</div></div>
        </div>
        <details class="report-detail">
            <summary>Detail Report</summary>
            <div class="report-detail-content">
                <div class="section-title">Execution Status Split</div>
                <div class="donut-wrap">
                    <div class="donut-chart" style="background: {donut_bg};"><div class="donut-hole"><div><div class="donut-total">{status_total}</div><div class="donut-sub">Tests</div></div></div></div>
                    <div class="donut-legend">
                        <div class="legend-item"><span class="legend-dot dot-pass"></span>Pass: <b>{status_totals['pass']}</b></div>
                        <div class="legend-item"><span class="legend-dot dot-fail"></span>Failed: <b>{status_totals['failed']}</b></div>
                        <div class="legend-item"><span class="legend-dot dot-abort"></span>Aborted: <b>{status_totals['aborted']}</b></div>
                        <div class="legend-item"><span class="legend-dot dot-exec"></span>Executing: <b>{status_totals['executing']}</b></div>
                        <div class="legend-item"><span class="legend-dot dot-todo"></span>Todo: <b>{status_totals['todo']}</b></div>
                    </div>
                </div>
                <div class="section-title">Failure and Aborted Details</div>
                <div class="status-detail-wrap">{failure_abort_details_html(grouped)}</div>
                <div class="section-title">Summary by Domain</div>
                <div class="sum-cards">{domain_summary_cards(grouped)}</div>
                <div class="section-title">Product-wise Execution Summary</div>
                {product_summary_cards(grouped)}
                <div class="section-title">SOP/PU Execution Counts</div>
                {sop_pu_execution_counts(grouped)}
                <div class="cycles-toggle-bar"><button id="cycles-toggle" class="cycles-toggle-btn" type="button" aria-expanded="true" aria-controls="cycles-wrap">Hide all cycles</button></div>
                <div id="cycles-wrap" class="cycles-wrap"><div class="section-title">Detailed Execution Cycles</div>{domain_quick_jump(grouped)}{domain_sections(grouped)}</div>
            </div>
        </details>
    </section>

    <section id="scope-defect" data-scope-panel="defect" class="report-section scope-panel{' scope-hidden' if 'defect' not in report_scopes else ''}">
        <h2 class="report-section-title"><i data-lucide="bug"></i> Defect Summary</h2>
        <details class="report-detail">
            <summary>Defect Detail Report</summary>
            <div class="report-detail-content">
                <div class="defect-filter-bar" role="search"><input id="defect-search" type="search" placeholder="Search defect ID, summary, reporter..." aria-label="Search defects"><select id="defect-severity" aria-label="Filter by severity"><option value="">All severities</option><option>Critical</option><option>High</option><option>Medium</option><option>Low</option></select><select id="defect-status" aria-label="Filter by status"><option value="">All statuses</option><option>Open</option><option>Closed</option><option>Resolved</option><option>Done</option></select><span id="defect-filter-count" class="defect-filter-count"></span></div>
                <div class="data-quality-note">Defect labels are scoped to the selected domain. ET defects require the domain label, LTTS_SV, and LTTS_SV_ET.</div>
                {f'<div class="data-coverage-warning">No defect label mapping is configured for: {escape(", ".join(defects.get("unmapped_domains", [])))} - these domain(s) contributed 0 records to this report, even though they appear in the domain selection above.</div>' if defects.get('unmapped_domains') else ''}
                {build_defect_executive_section(defects, start_date, end_date, report_scopes)}
            </div>
        </details>
    </section>

    <section id="scope-adhoc" data-scope-panel="adhoc" class="report-section scope-panel{' scope-hidden' if 'adhoc' not in report_scopes else ''}">
        <h2 class="report-section-title"><i data-lucide="wrench"></i> Ad-Hoc Effort Summary</h2>
        <details class="report-detail" open>
            <summary>Ad-Hoc Detail Report</summary>
            <div class="report-detail-content">
                {build_adhoc_effort_section(adhoc_effort)}
                {build_connectivity_adhoc_section(connectivity_adhoc)}
                {'<p class="empty">No ad-hoc data is tracked for the selected domain(s).</p>' if not adhoc_effort and not connectivity_adhoc else ''}
            </div>
        </details>
    </section>

    <section id="scope-rack" data-scope-panel="rack" class="report-section scope-panel{' scope-hidden' if 'rack' not in report_scopes else ''}">
        <h2 class="report-section-title"><i data-lucide="server"></i> Test Rack Utilisation Summary</h2>
        {render_rack_utilisation_section(rack_utilisation)}
    </section>

    <section id="scope-feature" data-scope-panel="feature" class="report-section scope-panel{' scope-hidden' if 'feature' not in report_scopes else ''}">
        <h2 class="report-section-title"><i data-lucide="list-checks"></i> Feature Scope - RG3/RG4 and RG4.5 SYS.5 Closures</h2>
        {build_sys5_qualification_summary(total_cycles, status_totals, feature_scope, sys5_open_critical_defects)}
        <details class="report-detail" open>
            <summary>Feature Scope Detail Report</summary>
            <div class="report-detail-content">
                {build_feature_scope_section(feature_scope)}
            </div>
        </details>
    </section>

</div>

<div class="footer">Auto-generated by test_execution_report.py &nbsp;|&nbsp; {generated_at}</div>
<button id="back-to-top" class="back-to-top" type="button" hidden>Back to top</button>
<dialog id="kpi-info-dialog" class="kpi-info-dialog">
    <div class="kpi-info-dialog-body">
        <h3 class="kpi-info-title">Details</h3>
        <div class="kpi-info-figure" hidden></div>
        <p class="kpi-info-text"></p>
        <div class="kpi-info-rows-wrap" hidden></div>
        <button type="button" class="kpi-info-close">Close</button>
    </div>
</dialog>
<!-- v2 report libraries: CDN-hosted for this dummy preview; vendor locally before production use offline. -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/html2pdf.js@0.10.2/dist/html2pdf.bundle.min.js"></script>
<script src="https://unpkg.com/lucide@latest"></script>
<script>
(function () {{
    const scopeCards = Array.from(document.querySelectorAll(".scope-nav-card"));
    const scopePanels = [
        document.getElementById("scope-test"),
        document.getElementById("scope-defect"),
        document.getElementById("scope-adhoc"),
        document.getElementById("scope-rack"),
        document.getElementById("scope-feature"),
        document.querySelector('[data-scope-panel="resolution"]')
    ].filter(Boolean);
    const defectPanel = document.querySelector('[data-scope-panel="defect"] .scope-panel');
    const availableScopes = new Set({json.dumps(sorted(report_scopes))});
    function activateScope(scope) {{
        if (!availableScopes.has(scope)) return;
        scopeCards.forEach(card => {{
            const active = card.dataset.scope === scope;
            card.classList.toggle("is-active", active);
            card.setAttribute("aria-selected", String(active));
        }});
        scopePanels.forEach(panel => {{
            const active = panel.dataset.scopePanel === scope || (scope === "resolution" && panel.id === "scope-defect");
            panel.classList.toggle("scope-hidden", !active);
            if (active) {{
                panel.classList.remove("scope-panel");
                void panel.offsetWidth;
                panel.classList.add("scope-panel");
            }}
        }});
        if (defectPanel) defectPanel.classList.toggle("scope-hidden", scope !== "defect");
    }}
    scopeCards.forEach(card => card.addEventListener("click", () => activateScope(card.dataset.scope)));
    activateScope(availableScopes.has("test") ? "test" : Array.from(availableScopes)[0]);

    const defectSearch = document.getElementById("defect-search");
    const defectSeverity = document.getElementById("defect-severity");
    const defectStatus = document.getElementById("defect-status");
    const defectCount = document.getElementById("defect-filter-count");
    function filterDefects() {{
        const query = (defectSearch?.value || "").toLowerCase().trim();
        const severity = defectSeverity?.value || "";
        const status = defectStatus?.value || "";
        let visible = 0;
        document.querySelectorAll(".defect-table tbody tr[data-defect-search]").forEach(row => {{
            const matches = (!query || row.dataset.defectSearch.toLowerCase().includes(query)) &&
                (!severity || row.dataset.severity === severity) &&
                (!status || row.dataset.status.toLowerCase().includes(status.toLowerCase()));
            row.hidden = !matches;
            if (matches) visible += 1;
        }});
        if (defectCount) defectCount.textContent = `${{visible}} matching defect(s)`;
    }}
    [defectSearch, defectSeverity, defectStatus].forEach(control => control?.addEventListener("input", filterDefects));
    filterDefects();

    document.getElementById("print-report")?.addEventListener("click", () => window.print());
    document.getElementById("download-pdf")?.addEventListener("click", () => {{
        const target = document.querySelector(".container");
        if (!target || !window.html2pdf) {{ window.print(); return; }}
        window.html2pdf().set({{
            margin: 8,
            filename: (document.title || "report").replace(/\\s+/g, "_") + ".pdf",
            image: {{ type: "jpeg", quality: 0.95 }},
            html2canvas: {{ scale: 2, useCORS: true }},
            jsPDF: {{ unit: "mm", format: "a3", orientation: "landscape" }}
        }}).from(target).save();
    }});
    document.getElementById("expand-details")?.addEventListener("click", () => document.querySelectorAll("details").forEach(detail => detail.open = true));
    document.getElementById("collapse-details")?.addEventListener("click", () => document.querySelectorAll("details").forEach(detail => detail.open = false));
    const backToTop = document.getElementById("back-to-top");
    window.addEventListener("scroll", () => {{ if (backToTop) backToTop.hidden = window.scrollY < 500; }});
    backToTop?.addEventListener("click", () => window.scrollTo({{ top: 0, behavior: "smooth" }}));

    const kpiInfoDialog = document.getElementById("kpi-info-dialog");
    if (kpiInfoDialog) {{
        const kpiInfoFigure = kpiInfoDialog.querySelector(".kpi-info-figure");
        const kpiInfoRows = kpiInfoDialog.querySelector(".kpi-info-rows-wrap");
        document.querySelectorAll("[data-info-text]").forEach(card => {{
            card.addEventListener("click", () => {{
                kpiInfoDialog.querySelector(".kpi-info-title").textContent = card.dataset.infoTitle || "Details";
                kpiInfoDialog.querySelector(".kpi-info-text").textContent = card.dataset.infoText || "";
                if (kpiInfoRows) {{
                    kpiInfoRows.innerHTML = "";
                    let infoRows = [];
                    try {{ infoRows = card.dataset.infoRows ? JSON.parse(card.dataset.infoRows) : []; }} catch (e) {{ infoRows = []; }}
                    if (infoRows.length) {{
                        // Columns are derived from whatever keys the row objects carry, so this
                        // same renderer works for Avg Dwell Time (key/created/resolved/dwell) and
                        // Backlog Trend (type/key/date/status) without any JS changes per KPI.
                        const columns = Object.keys(infoRows[0]);
                        const table = document.createElement("table");
                        const thead = document.createElement("thead");
                        const headRow = document.createElement("tr");
                        columns.forEach(col => {{
                            const th = document.createElement("th");
                            th.textContent = col.replace(/_/g, " ").replace(/\\b\\w/g, c => c.toUpperCase());
                            headRow.appendChild(th);
                        }});
                        thead.appendChild(headRow);
                        const tbody = document.createElement("tbody");
                        infoRows.forEach(row => {{
                            const tr = document.createElement("tr");
                            columns.forEach(col => {{
                                const td = document.createElement("td");
                                td.textContent = row[col];
                                tr.appendChild(td);
                            }});
                            tbody.appendChild(tr);
                        }});
                        table.appendChild(thead);
                        table.appendChild(tbody);
                        kpiInfoRows.appendChild(table);
                        kpiInfoRows.hidden = false;
                        kpiInfoDialog.classList.add("has-table");
                    }} else {{
                        kpiInfoRows.hidden = true;
                        kpiInfoDialog.classList.remove("has-table");
                    }}
                }}
                if (kpiInfoFigure) {{
                    kpiInfoFigure.innerHTML = "";
                    const figureEl = card.querySelector("b");
                    const subEl = card.querySelector("small");
                    if (figureEl && figureEl.textContent.trim()) {{
                        const valueSpan = document.createElement("span");
                        valueSpan.textContent = figureEl.textContent.trim();
                        kpiInfoFigure.appendChild(valueSpan);
                        if (subEl && subEl.textContent.trim()) {{
                            const subSpan = document.createElement("small");
                            subSpan.textContent = subEl.textContent.trim();
                            kpiInfoFigure.appendChild(subSpan);
                        }}
                        kpiInfoFigure.hidden = false;
                    }} else {{
                        kpiInfoFigure.hidden = true;
                    }}
                }}
                if (typeof kpiInfoDialog.showModal === "function") {{
                    kpiInfoDialog.showModal();
                }} else {{
                    kpiInfoDialog.setAttribute("open", "open");
                }}
                const gap = 10;
                const cardRect = card.getBoundingClientRect();
                const dialogRect = kpiInfoDialog.getBoundingClientRect();
                let top = cardRect.top - dialogRect.height - gap;
                if (top < gap) top = Math.min(cardRect.bottom + gap, window.innerHeight - dialogRect.height - gap);
                if (top < gap) top = gap;
                let left = cardRect.left + (cardRect.width / 2) - (dialogRect.width / 2);
                const maxLeft = window.innerWidth - dialogRect.width - gap;
                left = Math.min(Math.max(left, gap), Math.max(gap, maxLeft));
                kpiInfoDialog.style.top = `${{top}}px`;
                kpiInfoDialog.style.left = `${{left}}px`;
            }});
        }});
        kpiInfoDialog.querySelector(".kpi-info-close")?.addEventListener("click", () => kpiInfoDialog.close?.());
        kpiInfoDialog.addEventListener("click", (event) => {{
            if (event.target === kpiInfoDialog) kpiInfoDialog.close?.();
        }});
    }}

    const toggleBtn = document.getElementById("cycles-toggle");
    const cyclesWrap = document.getElementById("cycles-wrap");
    if (toggleBtn && cyclesWrap) {{
        toggleBtn.addEventListener("click", () => {{
            const hidden = cyclesWrap.classList.toggle("is-hidden");
            toggleBtn.textContent = hidden ? "Show all cycles" : "Hide all cycles";
            toggleBtn.setAttribute("aria-expanded", String(!hidden));
            toggleBtn.classList.toggle("is-collapsed", hidden);
        }});
    }}

    if (window.lucide) {{
        try {{ window.lucide.createIcons(); }} catch (e) {{ /* icon set unavailable, ignore */ }}
    }}

    const dataNode = document.getElementById("defect-chart-data");
    if (!dataNode) return;

    let chartData = {{}};
    try {{
        chartData = JSON.parse(dataNode.textContent || "{{}}");
    }} catch (e) {{
        return;
    }}

    function renderRing(targetId, segments, unitLabel) {{
        const host = document.getElementById(targetId);
        if (!host) return;

        const clean = (segments || []).filter(s => Number(s.value || 0) > 0);
        if (!clean.length) {{
            host.innerHTML = '<p class="empty">No data available.</p>';
            return;
        }}

        const total = clean.reduce((acc, s) => acc + Number(s.value || 0), 0);

        if (!window.Chart) {{
            // Fallback to the original CSS conic-gradient ring if Chart.js failed to load.
            let start = 0;
            const stops = [];
            clean.forEach(seg => {{
                const pct = (Number(seg.value || 0) / total) * 100;
                stops.push(`${{seg.color}} ${{start.toFixed(2)}}% ${{(start + pct).toFixed(2)}}%`);
                start += pct;
            }});
            const legend = clean.map(seg => `<li><span class="legend-swatch" style="background:${{seg.color}}"></span>${{seg.label}}: <b>${{seg.value}}</b></li>`).join("");
            host.innerHTML = `<div class="ring-grid"><div class="ring-chart" style="background: conic-gradient(${{stops.join(",")}})"><div class="ring-hole"><div><div class="ring-total">${{total}}</div><div class="ring-sub">${{unitLabel}}</div></div></div></div><ul class="ring-legend">${{legend}}</ul></div>`;
            return;
        }}

        host.innerHTML = '<div class="chart-canvas-wrap"><canvas></canvas></div>';
        const canvas = host.querySelector("canvas");
        new window.Chart(canvas.getContext("2d"), {{
            type: "doughnut",
            data: {{
                labels: clean.map(s => s.label),
                datasets: [{{
                    data: clean.map(s => Number(s.value || 0)),
                    backgroundColor: clean.map(s => s.color),
                    borderColor: "#ffffff",
                    borderWidth: 2,
                }}],
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                cutout: "62%",
                plugins: {{
                    legend: {{ position: "right", labels: {{ boxWidth: 10, font: {{ size: 11 }} }} }},
                    tooltip: {{
                        callbacks: {{
                            label: (ctx) => `${{ctx.label}}: ${{ctx.raw}} (${{((ctx.raw / total) * 100).toFixed(1)}}%)`
                        }}
                    }}
                }}
            }},
            plugins: [{{
                id: "centerText",
                afterDraw(chart) {{
                    const {{ ctx, chartArea: {{ width, height, left, top }} }} = chart;
                    ctx.save();
                    ctx.font = "700 20px Segoe UI";
                    ctx.fillStyle = "#0F172A";
                    ctx.textAlign = "center";
                    ctx.fillText(String(total), left + width / 2, top + height / 2 - 4);
                    ctx.font = "600 11px Segoe UI";
                    ctx.fillStyle = "#4B5563";
                    ctx.fillText(unitLabel, left + width / 2, top + height / 2 + 14);
                    ctx.restore();
                }}
            }}]
        }});
    }}

    function renderBars(targetId, items, color) {{
        const host = document.getElementById(targetId);
        if (!host) return;
        const rows = (items || []).filter(s => Number(s.value || 0) > 0);
        if (!rows.length) {{
            host.innerHTML = '<p class="empty">No data available.</p>';
            return;
        }}

        const max = Math.max(...rows.map(x => Number(x.value || 0)), 1);
        host.innerHTML = '<div class="bar-list"></div>';
        const list = host.querySelector(".bar-list");
        list.style.setProperty("--bar-row-count", rows.length);

        rows.forEach(item => {{
            const widthPct = (Number(item.value || 0) / max) * 100;
            const row = document.createElement("div");
            row.className = "bar-row";
            row.title = `${{item.label}}: ${{item.value}}`;
            const defectLinks = (item.defects || []).map(defect =>
                `<a href="${{defect.url}}" target="_blank" rel="noopener">${{defect.key}}</a>`
            ).join("");
            const defectDetails = defectLinks
                ? `<details class="bar-defects"><summary>Defect IDs (${{item.defects.length}})</summary><div class="bar-defect-links">${{defectLinks}}</div></details>`
                : "";
            row.innerHTML = `
                <div class="bar-label">${{item.label}}</div>
                <div class="bar-track"><div class="bar-fill" style="background:${{color}}; width:0%"></div></div>
                <div class="bar-value">${{item.value}}</div>
                ${{defectDetails}}
            `;
            list.appendChild(row);

            requestAnimationFrame(() => {{
                const fill = row.querySelector(".bar-fill");
                if (fill) fill.style.width = `${{widthPct.toFixed(1)}}%`;
            }});
        }});
    }}

    function renderCoverageBars(targetId, items) {{
        const host = document.getElementById(targetId);
        if (!host) return;
        const rows = (items || []).filter(item => Number(item.total || 0) > 0);
        if (!rows.length) {{
            host.innerHTML = '<p class="empty">No data available.</p>';
            return;
        }}

        const maxValue = Math.max(...rows.map(item => Math.max(Number(item.with_tool || 0), Number(item.without_tool || 0), Number(item.total || 0))), 1);

        const blocks = rows.map(item => `
            <div class="coverage-row" title="${{item.label}} | With LTTS_DBCU: ${{item.with_tool}} | Without LTTS_DBCU: ${{item.without_tool}}">
                <div class="coverage-head">
                    <div class="coverage-label">${{item.label}}</div>
                    <div class="coverage-total">Total: ${{item.total}}</div>
                </div>
                <div class="coverage-chart">
                    <div class="coverage-bar">
                        <span class="coverage-fill-label">With tool</span>
                        <div class="coverage-track"><div class="coverage-fill with-tool" data-width="${{(Number(item.with_tool || 0) / maxValue) * 100}}"></div></div>
                        <span class="coverage-value">${{item.with_tool}}</span>
                    </div>
                    <div class="coverage-bar">
                        <span class="coverage-fill-label">Without tool</span>
                        <div class="coverage-track"><div class="coverage-fill without-tool" data-width="${{(Number(item.without_tool || 0) / maxValue) * 100}}"></div></div>
                        <span class="coverage-value">${{item.without_tool}}</span>
                    </div>
                </div>
            </div>
        `).join("");

        host.innerHTML = `
            <div class="coverage-list">${{blocks}}</div>
            <div class="coverage-legend">
                <span><i style="background:#B45309"></i>With LTTS_DBCU</span>
                <span><i style="background:#94A3B8"></i>Without LTTS_DBCU</span>
            </div>
            <div class="coverage-note">Counts are grouped product-wise from scoped telematics defects.</div>
        `;

        host.querySelectorAll('.coverage-fill').forEach(fill => {{
            requestAnimationFrame(() => {{
                fill.style.width = `${{Number(fill.dataset.width || 0).toFixed(1)}}%`;
            }});
        }});
    }}

    renderRing("chart-severity", chartData.severity || [], "Defects");
    renderCoverageBars("chart-similiaize-coverage", chartData.similiaize_coverage || []);
    renderBars("chart-reporters", chartData.reporters || [], "#0066B1");
    renderBars("chart-components", chartData.components || [], "#2E7D32");
    renderBars("chart-reporter-projects", chartData.reporter_projects || [], "#0F172A");
    renderBars("chart-weekly-defects", chartData.weekly_defects || [], "#0879D1");
    renderRing("chart-exploratory", chartData.exploratory || [], "Defects");
}})();
</script>
</body>
</html>"""


def main():
    generation_started = time.perf_counter()
    args = parse_args()
    ensure_jira_credentials_loaded()
    if os.getenv("JIRA_API_TOKEN", "").strip():
        resolved_mode = os.getenv("JIRA_AUTH_MODE", JIRA_AUTH_MODE).strip().lower() or "basic"
        mode_source = _JIRA_CREDENTIAL_SOURCES.get(
            "JIRA_AUTH_MODE", "a pre-existing OS/session environment variable (set before this script started)"
        )
        print(f"Jira auth mode: {resolved_mode} (from {mode_source})")
    report_scopes = parse_report_scopes(args.report_scopes)

    if args.discover_fields:
        discover_fields()
        return

    needs_jira = args.rejected_only or bool({"test", "defect", "resolution", "adhoc"} & report_scopes)
    if needs_jira:
        try:
            build_auth_and_headers()
        except ValueError as exc:
            print(f"Configuration error: {exc}")
            print("Hint: set JIRA_API_TOKEN (and JIRA_EMAIL for basic mode) in your user environment.")
            sys.exit(1)

    if args.rejected_only:
        start_date = (args.start_date or "").strip()
        end_date = (args.end_date or "").strip()
        if not start_date or not end_date:
            raise ValueError("--rejected-only requires --start-date and --end-date")
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
        defect_projects = [
            value.strip()
            for value in (args.defect_projects or "").split(",")
            if value.strip()
        ]
        closure_projects = [
            value.strip()
            for value in (args.closure_projects or args.defect_projects or "").split(",")
            if value.strip()
        ]
        defect_assigned_ecus = [
            value.strip()
            for value in (args.defect_assigned_ecu or "").split(",")
            if value.strip()
        ]
        print(f"\nFetching rejected/deficient tickets for {build_cw_label(start_date, end_date)}...")
        defects = fetch_telematics_defects(
            start_date,
            end_date,
            defect_projects=defect_projects,
            defect_domain=args.defect_domain,
            defect_assigned_ecus=defect_assigned_ecus,
            defect_variant=args.variant,
            closure_projects=closure_projects,
            closure_team=args.closure_team,
            resolution_start_date=start_date,
            resolution_end_date=end_date,
        )
        with open(REJECTED_ONLY_OUTPUT_FILE, "w", encoding="utf-8") as output:
            output.write(generate_rejected_only_html(defects["closure_metrics"], start_date, end_date))
        print(f"Rejected-only report saved: {REJECTED_ONLY_OUTPUT_FILE}")
        os.startfile(REJECTED_ONLY_OUTPUT_FILE)
        return

    print("=" * 55)
    print("  Test Execution Report")
    print("=" * 55)
    print("Tip: run with --discover-fields first to map custom field IDs.\n")

    if args.rack_only:
        today = datetime.today().date()
        week_start = today - timedelta(days=today.weekday())
        start_date = (args.start_date or week_start.strftime("%Y-%m-%d")).strip()
        end_date = (args.end_date or today.strftime("%Y-%m-%d")).strip()
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
        selected_variants = [
            value.strip()
            for value in (args.variant or "").split(",")
            if value.strip() and value.strip().lower() != "all"
        ]
        selected_projects = [
            value.strip()
            for value in (args.projects or "").split(",")
            if value.strip() and value.strip().lower() != "all"
        ]
        rack_domain_selection = (args.rack_domain or args.domain or "Telematics").strip()
        rack_rows = load_rack_activity(args.rack_activity_file)
        rack_rows = filter_active_rack_activity(rack_rows)
        if not rack_rows:
            rack_rows = filter_active_rack_activity(fetch_rack_activity_from_test_guide(
                build_rack_filters(rack_domain_selection, selected_variants, selected_projects),
                start_date,
                end_date,
                domain=rack_domain_selection,
                variants=selected_variants,
            ))
        rack_utilisation = aggregate_rack_utilisation(
            rack_rows,
            rack_domain_selection or "All",
            start_date,
            end_date,
            variants=selected_variants,
            projects=selected_projects,
        )
        if not rack_rows:
            print(
                f"No rack activity data found. Checked {args.rack_activity_file} and test.guide API. "
                "Set TEST_GUIDE_TOKEN for live retrieval."
            )
            rack_utilisation["by_resource"] = []
            rack_utilisation["data_warning"] = (
                "Rack utilisation data is unavailable. test.guide returned no activity rows "
                "for the selected scope/date or access to rack activity is not configured."
            )
        with open(RACK_ONLY_OUTPUT_FILE, "w", encoding="utf-8") as output:
            output.write(generate_rack_only_html(rack_utilisation))
        print(f"\nRack-only report saved: {RACK_ONLY_OUTPUT_FILE}")
        os.startfile(RACK_ONLY_OUTPUT_FILE)
        return

    start_date = (args.start_date or "").strip()
    end_date = (args.end_date or "").strip()

    if not start_date:
        start_date = input("Start date (YYYY-MM-DD): ").strip()
    if not end_date:
        end_date = input("End date   (YYYY-MM-DD): ").strip()

    for d in (start_date, end_date):
        datetime.strptime(d, "%Y-%m-%d")

    selected_projects = [p.strip() for p in (args.projects or "").split(",") if p.strip()]
    if not selected_projects:
        selected_projects = list(PROJECTS)

    grouped = {}
    defect_projects = [p.strip() for p in (args.defect_projects or "").split(",") if p.strip()]
    defect_assigned_ecus = [e.strip() for e in (args.defect_assigned_ecu or "").split(",") if e.strip()]
    closure_projects = [p.strip() for p in (args.closure_projects or "").split(",") if p.strip()]
    defects = {}
    adhoc_effort = {}
    feature_scope = {}
    connectivity_adhoc = {}
    parallel_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as executor:
        test_future = None
        defect_future = None
        adhoc_future = None
        connectivity_adhoc_future = None
        feature_future = None
        if "test" in report_scopes:
            print("\nFetching test executions from Jira...")
            test_future = executor.submit(fetch_executions, start_date, end_date, args.cycle_type, selected_projects)
        if "defect" in report_scopes or "resolution" in report_scopes:
            defect_future = executor.submit(
                fetch_telematics_defects,
                start_date,
                end_date,
                defect_projects,
                args.defect_domain or args.domain,
                defect_assigned_ecus,
                args.variant,
                closure_projects,
                args.closure_team,
                args.resolution_start_date,
                args.resolution_end_date,
            )
        if "adhoc" in report_scopes:
            adhoc_domains = [domain.strip() for domain in (args.adhoc_domains or "").split(",") if domain.strip()]
            adhoc_future = executor.submit(fetch_telematics_adhoc_effort, start_date, end_date, adhoc_domains)
            connectivity_adhoc_future = executor.submit(fetch_connectivity_adhoc_effort, start_date, end_date, adhoc_domains)
        if "feature" in report_scopes:
            feature_sop_pu = [value.strip() for value in (args.feature_sop_pu or "").split(",") if value.strip()]
            feature_domains = [value.strip() for value in (args.feature_domain or "").split(",") if value.strip()]
            feature_products = [value.strip() for value in (args.feature_products or "").split(",") if value.strip()]
            include_rg3_rg4 = str(args.feature_include_rg3_rg4).strip().lower() != "false"
            include_rg45 = str(args.feature_include_rg45).strip().lower() != "false"
            feature_start_date = (args.feature_resolution_start_date or start_date).strip()
            feature_end_date = (args.feature_resolution_end_date or end_date).strip()
            feature_future = executor.submit(
                fetch_feature_scope_data,
                feature_sop_pu,
                feature_domains,
                feature_start_date,
                feature_end_date,
                include_rg3_rg4,
                include_rg45,
                feature_products,
            )
        if test_future is not None:
            grouped = test_future.result()
            print(f"  test scope result ready at: {time.perf_counter() - parallel_started:.2f} seconds")
        if defect_future is not None:
            defects = defect_future.result()
            print(f"  defect/resolution scope result ready at: {time.perf_counter() - parallel_started:.2f} seconds")
        if adhoc_future is not None:
            adhoc_effort = adhoc_future.result()
            print(f"  adhoc scope result ready at: {time.perf_counter() - parallel_started:.2f} seconds")
        if connectivity_adhoc_future is not None:
            connectivity_adhoc = connectivity_adhoc_future.result()
            print(f"  connectivity adhoc scope result ready at: {time.perf_counter() - parallel_started:.2f} seconds")
        if feature_future is not None:
            feature_scope = feature_future.result()
            print(f"  feature scope result ready at: {time.perf_counter() - parallel_started:.2f} seconds")
    print(f"Parallel Jira fetch time: {time.perf_counter() - parallel_started:.2f} seconds")

    grouped = apply_cycle_filter(grouped, args.cycle_type) if "test" in report_scopes else {}

    if args.domain and "test" in report_scopes:
        grouped, selected_domain_label, invalid = apply_domain_filter(grouped, args.domain)
        if invalid:
            print(f"Ignored invalid domain entries from --domain: {', '.join(invalid)}")
        if selected_domain_label == "All" and args.domain.strip().lower() != "all":
            # Do not silently expand to all domains when user requested a specific domain.
            # This keeps summary counts scoped to the user intent.
            requested_domain = args.domain.strip()
            print("No valid domains matched from --domain. Report will be generated with 0 matching records.")
            grouped = {}
            selected_domain_label = requested_domain
        else:
            print(f"Using domain filter from --domain: {selected_domain_label}")
    elif "test" in report_scopes:
        grouped, selected_domain_label = choose_domains(grouped)
    else:
        selected_domain_label = args.domain or "All"

    if args.variant and "test" in report_scopes:
        grouped, selected_variant_label, invalid = apply_variant_filter(grouped, args.variant)
        if invalid:
            print(f"Ignored invalid variant entries from --variant: {', '.join(invalid)}")
        if selected_variant_label == "All" and args.variant.strip().lower() != "all":
            print("No valid variants matched from --variant. Falling back to All variants.")
        else:
            print(f"Using variant filter from --variant: {selected_variant_label}")

    selected_variants = [value.strip() for value in (args.variant or "").split(",") if value.strip() and value.strip().lower() != "all"]
    rack_utilisation = {}
    if "rack" in report_scopes:
        rack_started = time.perf_counter()
        rack_domain_selection = (args.rack_domain or selected_domain_label or "All").strip()
        rack_rows = filter_active_rack_activity(load_rack_activity(args.rack_activity_file))
        if not rack_rows:
            rack_rows = filter_active_rack_activity(fetch_rack_activity_from_test_guide(
                build_rack_filters(rack_domain_selection, selected_variants, selected_projects),
                start_date,
                end_date,
                domain=rack_domain_selection,
                variants=selected_variants,
            ))
        rack_utilisation = aggregate_rack_utilisation(
            rack_rows,
            rack_domain_selection,
            start_date,
            end_date,
            variants=selected_variants,
            projects=selected_projects,
        )
        if not rack_rows:
            print(
                f"  No rack activity data found. Checked {args.rack_activity_file} and test.guide API. "
                "Set TEST_GUIDE_TOKEN for live retrieval."
            )
            rack_utilisation["by_resource"] = []
            rack_utilisation["data_warning"] = (
                "Rack utilisation data is unavailable. test.guide returned no activity rows "
                "for the selected scope/date or access to rack activity is not configured."
            )
        print(f"Rack utilisation fetch time: {time.perf_counter() - rack_started:.2f} seconds")

    if "test" in report_scopes and not grouped:
        print("\nNo matching test execution records found for the selected filters.")
    if "defect" in report_scopes and not defects:
        print("\nNo matching defect records found for the selected filters.")
    if "adhoc" in report_scopes and not adhoc_effort.get("rows"):
        print("\nNo matching ad-hoc records found for the selected filters.")
    if "feature" in report_scopes:
        if not (feature_scope.get("rg3_rg4", {}).get("rows") or feature_scope.get("rg45", {}).get("rows")):
            print("\nNo matching Feature sub-task closures found for the selected filters.")
        else:
            excel_path = (args.feature_excel or "").strip() or os.path.join(
                REPORTS_DIR, "feature_sys5_test_cases.xlsx"
            )
            os.makedirs(os.path.dirname(excel_path) or ".", exist_ok=True)
            excel_started = time.perf_counter()
            try:
                saved_path = export_feature_sys5_excel(feature_scope, excel_path)
                print(f"Feature SYS.5 Excel export saved: {saved_path}")
            except Exception as exc:
                print(f"  Warning: Feature SYS.5 Excel export failed: {exc}")
            print(f"Feature Excel export time: {time.perf_counter() - excel_started:.2f} seconds")

    html_started = time.perf_counter()
    html = generate_html(
        grouped,
        defects,
        adhoc_effort,
        rack_utilisation,
        start_date,
        end_date,
        selected_domain_label,
        selected_projects=selected_projects,
        report_scopes=report_scopes,
        feature_scope=feature_scope,
        connectivity_adhoc=connectivity_adhoc,
    )
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML render + write time: {time.perf_counter() - html_started:.2f} seconds")

    print(f"\nReport saved: {OUTPUT_FILE}")
    print(f"Generation time: {time.perf_counter() - generation_started:.2f} seconds")
    os.startfile(OUTPUT_FILE)


if __name__ == "__main__":
    main()
