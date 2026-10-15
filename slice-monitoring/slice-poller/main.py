import logging, os, signal, tempfile, threading, requests, yaml
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth
from pathlib import Path


load_dotenv()

logging.basicConfig(format="%(module)-20s:%(levelname)-10s| %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

_shutdown = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: _shutdown.set())
signal.signal(signal.SIGINT, lambda *_: _shutdown.set())

# Grafana 12.x serves v0alpha1, v1beta1, v2alpha1 and v2beta1 (no v1). v1beta1 is its preferred version.
DASHBOARD_API_VERSION = "dashboard.grafana.app/v1beta1"


def fetch_slice_imsis(slice_id: str, base_url: str, auth: HTTPBasicAuth) -> list[str] | None:
    """IMSI (ue_id) of each UE associated with the slice, sorted and without duplicates."""
    api_url = f"{base_url}/core/slices/{slice_id}/ues"
    logger.info("GET %s [slice_id=%s]", api_url, slice_id)
    try:
        r = requests.get(api_url, auth=auth, timeout=10)
        r.raise_for_status()
        imsis = set()
        for assoc in r.json()["associations"]:
            ue_id = assoc.get("ue_id")
            if assoc.get("slice_id") == slice_id and ue_id:
                imsis.add(ue_id)
        return sorted(imsis)  # stable order: unchanged associations never rewrite the config/dashboards
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as e:
        logger.error("Failed to fetch slice UEs [slice_id=%s]: %s", slice_id, e)
        return None


class NoPduSession(Exception):
    """The UE has no PDU session in the core (e.g. it is not attached), so it has no IP."""


def fetch_ue_ip(imsi: str, base_url: str, auth: HTTPBasicAuth) -> str:
    """Current IP of the UE, taken from its PDU session in the SMF. Raises NoPduSession if it has none."""
    api_url = f"{base_url}/core/ues/{imsi}/user-plane-info"
    r = requests.get(api_url, params={"detailed": "true"}, auth=auth, timeout=10)
    if r.status_code == 404:
        raise NoPduSession(imsi)
    r.raise_for_status()
    ip = r.json()["pdu_session"].get("user_ip")
    if not ip:
        raise NoPduSession(imsi)
    return ip


def fetch_ue_ips(slice_id: str, base_url: str, auth: HTTPBasicAuth) -> dict[str, str] | None:
    """Current IP of each UE associated with the slice, keyed by IMSI. UEs without a PDU session are left out.
    Returns None if any lookup fails, so a transient error never drops a UE from the config/dashboards."""
    imsis = fetch_slice_imsis(slice_id, base_url, auth)
    if imsis is None:
        return None

    ue_ips = {}
    for imsi in imsis:
        try:
            ue_ips[imsi] = fetch_ue_ip(imsi, base_url, auth)
        except NoPduSession:
            logger.info("UE %s has no PDU session, skipped [slice_id=%s]", imsi, slice_id)
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as e:
            logger.error("Failed to fetch IP of UE %s [slice_id=%s]: %s", imsi, slice_id, e)
            return None
    return ue_ips


# ---------------------------------------------------------------- prober config

def select_probed_ues(ue_ips: dict[str, str], probe_imsis: list[str], slice_id: str) -> dict[str, str]:
    """Keep only the UEs listed in probeIMSIs. Listed IMSIs not found in the slice are logged and skipped."""
    probed_ue_ips = {}
    for imsi in probe_imsis:
        if imsi in ue_ips:
            probed_ue_ips[imsi] = ue_ips[imsi]
        else:
            logger.warning("IMSI %s not in the slice or without a PDU session, not probed [slice_id=%s]", imsi, slice_id)
    return probed_ue_ips


def render_prober_config(base_path: Path, imsi_ips: dict[str, str], slice_id: str, source_ip: str | None) -> str:
    """Base network_exporter config (conf/icmp settings from the chart) + one ICMP target per probed UE."""
    config = yaml.safe_load(base_path.read_text()) or {}
    targets = []
    for imsi, ip in imsi_ips.items():
        target = {"name": f"{imsi}-{slice_id}-icmp", "type": "ICMP", "host": ip, "labels": {"slice": slice_id, "imsi": imsi}}
        if source_ip:
            target["source_ip"] = source_ip
        targets.append(target)
    config["targets"] = targets
    return yaml.safe_dump(config, default_flow_style=False, sort_keys=False)


def update_prober_config(imsi_ips: dict[str, str], slice_id: str, base_path: Path, output_path: Path, source_ip: str | None) -> None:
    """Write the config to the volume shared with the prober, which reloads it by itself (conf.refresh)."""
    try:
        content = render_prober_config(base_path, imsi_ips, slice_id, source_ip)
        # Compare with the file on disk rather than in-memory state, so a recreated volume gets rewritten
        if output_path.exists() and output_path.read_text() == content:
            logger.info("Prober config unchanged [slice_id=%s]", slice_id)
            return
        # temp file + rename so the prober never reads a half-written config
        with tempfile.NamedTemporaryFile("w", dir=output_path.parent, delete=False, suffix=".tmp") as tmp:
            tmp.write(content)
        os.chmod(tmp.name, 0o644)
        os.replace(tmp.name, output_path)
        logger.info("Prober config written with %d targets to %s [slice_id=%s]", len(imsi_ips), output_path, slice_id)
    except Exception as e:  # must never stop the dashboard update
        logger.error("Prober config update failed [slice_id=%s]: %s", slice_id, e)


# ---------------------------------------------------------------- dashboards

def list_dashboards(api_url: str, auth: tuple[str, str]) -> list[dict]:
    """All dashboards of the Grafana instance namespace, following the `continue` pagination token."""
    items, cont = [], None
    while True:
        params = {"limit": 100} | ({"continue": cont} if cont else {})
        r = requests.get(api_url, params=params, auth=auth, timeout=10)
        r.raise_for_status()
        body = r.json()
        items += body.get("items", [])
        cont = body.get("metadata", {}).get("continue")
        if not cont:
            return items


def get_variable(spec: dict, name: str) -> dict | None:
    """Dashboard variable `name`, or None if the dashboard doesn't define it."""
    for var in spec.get("templating", {}).get("list", []):
        if var.get("name") == name:
            return var
    return None


def set_variable(spec: dict, name: str, value: str) -> bool:
    """Set dashboard variable `name` to `value`. Returns True if the dashboard changed."""
    var = get_variable(spec, name)
    if var is None:
        return False
    if var.get("query") == value and var.get("current", {}).get("value") == value:
        return False
    var["query"] = value
    var["current"] = {"selected": False, "text": value, "value": value}
    var["options"] = [{"selected": True, "text": value, "value": value}]
    return True


def add_ue_ips(spec: dict, ue_ips: set[str]) -> bool:
    """Add `ue_ips` to the UE_IPS variable (regex alternation). IPs already there are kept, even if the UE left the slice."""
    var = get_variable(spec, "UE_IPS")
    if var is None:
        return False
    query = var.get("query", "")
    current_ips = set(query.split("|")) if query else set()
    all_ips = current_ips | ue_ips
    return set_variable(spec, "UE_IPS", "|".join(sorted(all_ips)))


def update_dashboards(ue_ips: set[str], slice_id: str, api_url: str, auth: tuple[str, str]) -> None:
    """Add new slice UE IPs to UE_IPS and set SLICE_ID in every dashboard. One PUT per changed dashboard."""
    try:
        dashboards = list_dashboards(api_url, auth)
    except Exception as e:
        logger.error("Failed to list dashboards [slice_id=%s]: %s", slice_id, e)
        return

    for dashboard in dashboards:
        name = dashboard.get("metadata", {}).get("name")
        try:
            spec = dashboard.get("spec", {})
            ue_ips_set = add_ue_ips(spec, ue_ips)
            slice_id_set = set_variable(spec, "SLICE_ID", slice_id)
            if not (ue_ips_set or slice_id_set):
                continue
            dashboard["apiVersion"] = DASHBOARD_API_VERSION
            dashboard["kind"] = "Dashboard"
            # metadata.resourceVersion is sent back, so a concurrent edit fails with 409 and is retried next iteration
            r = requests.put(f"{api_url}/{name}", json=dashboard, auth=auth, timeout=10)
            r.raise_for_status()
            logger.info("Dashboard %s: UE_IPS set to %s [slice_id=%s]",
                        name, (get_variable(spec, "UE_IPS") or {}).get("query"), slice_id)
        except Exception as e:  # one bad dashboard must not block the others
            logger.error("Failed to update dashboard %s [slice_id=%s]: %s", name, slice_id, e)


def main():
    required = ["SLICE_MANAGER_URL", "SLICE_MANAGER_USERNAME", "SLICE_MANAGER_PASSWORD", "POLL_INTERVAL_SECONDS", "SLICE_ID",
                "PROBER_BASE_CONFIG", "PROBER_CONFIG_PATH", "GRAFANA_HOST", "GRAFANA_USER", "GRAFANA_PASS"]
    if missing := [k for k in required if not os.getenv(k)]:
        logger.error("Missing environment variables: %s", ", ".join(missing))
        return

    interval = int(os.getenv("POLL_INTERVAL_SECONDS"))
    slice_id = os.getenv("SLICE_ID")

    slice_manager_url = os.getenv("SLICE_MANAGER_URL").rstrip("/")
    slice_manager_auth = HTTPBasicAuth(os.getenv("SLICE_MANAGER_USERNAME"), os.getenv("SLICE_MANAGER_PASSWORD"))

    prober_base_config = Path(os.getenv("PROBER_BASE_CONFIG"))
    prober_config_path = Path(os.getenv("PROBER_CONFIG_PATH"))
    prober_source_ip = os.getenv("PROBER_SOURCE_IP") or None
    probe_imsis = [i.strip() for i in os.getenv("PROBER_IMSIS", "").split(",") if i.strip()]

    grafana_namespace = os.getenv("GRAFANA_NAMESPACE", "default")
    dashboards_api = f"{os.getenv('GRAFANA_HOST').rstrip('/')}/apis/{DASHBOARD_API_VERSION}/namespaces/{grafana_namespace}/dashboards"
    grafana_auth = (os.getenv("GRAFANA_USER"), os.getenv("GRAFANA_PASS"))
    logger.info("Starting slice-poller — interval %ds, prober config: %s, probed IMSIs: %s, dashboards: %s [slice_id=%s]",
                interval, prober_config_path, probe_imsis or "none", dashboards_api, slice_id)

    while not _shutdown.is_set():
        # 1. Current IP (from the PDU session) of every UE in the slice, keyed by IMSI
        ue_ips = fetch_ue_ips(slice_id, slice_manager_url, slice_manager_auth)
        if ue_ips is None:
            logger.warning("Could not fetch UE IPs [slice_id=%s], will retry after interval", slice_id)
        else:
            update_dashboards(set(ue_ips.values()), slice_id, dashboards_api, grafana_auth)
            probed_ue_ips = select_probed_ues(ue_ips, probe_imsis, slice_id)
            update_prober_config(probed_ue_ips, slice_id, prober_base_config, prober_config_path, prober_source_ip)
        _shutdown.wait(interval)

    logger.info("slice-poller stopped cleanly [slice_id=%s]", slice_id)


if __name__ == "__main__":
    main()