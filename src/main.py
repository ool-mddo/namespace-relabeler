import json
import os
import sys
from logging import getLogger, Formatter, StreamHandler
import requests
from flask import Flask, request, Response
from prometheus_client import parser, Metric

# logger config
# convert log-level string (from env var) to log-level value, default: warning
log_level_str = os.getenv("NAMESPACE_RELABELER_LOG_LEVEL", "WARNING").upper()
log_level = getattr(sys.modules["logging"], log_level_str)

logger = getLogger("root")
logger.setLevel(log_level)
formatter = Formatter("[{asctime}: {message} ({funcName}:{lineno}]) ", style="{")
sh = StreamHandler(sys.stdout)
sh.setFormatter(formatter)
sh.setLevel(log_level)
logger.addHandler(sh)

# flask application
app = Flask(__name__)

# constants
CADVISOR_URL = os.environ.get("CADVISOR_URL")
logger.info(f"CADVISOR_URL: {CADVISOR_URL}")

NETOMOX_EXP_HOST = os.environ.get("NETOMOX_EXP_HOST")
logger.info(f"NETOMOX_EXP_HOST: {NETOMOX_EXP_HOST}")

TARGET_METRICS = ["container_network_receive_bytes", "container_network_transmit_bytes"]
mappings = None


def update_mappings(network_name: str):
    # try to get ns_convert_table
    ns_convert_table = get_ns_convert_table(network_name)
    if ns_convert_table is None:
        logger.error(f"Can not fetch ns_convert_table for network:{network_name}")
        return

    # check mappings key existence
    if "tp_name_table" not in ns_convert_table:
        logger.error(f"ns_convert_table (for network:{network_name}) does not have tp_name_table")
        return

    # update mappings
    logger.warning(f"Update tp name table mapping for network:{network_name}")
    global mappings
    mappings = ns_convert_table.get("tp_name_table")


@app.route("/relabel/network", methods=["POST"])
def post_network():
    params = request.json
    if params and "network_name" in params:
        update_mappings(params["network_name"])
        return f'Network name is {params["network_name"]}', 200

    return "Network name is missing", 400


@app.get("/metrics")
def metrics():
    response = requests.get(CADVISOR_URL)

    relabeled_metrics = relabel(response.text)

    if relabeled_metrics:
        relabeled_metrics += "\nrelabel_success 1"
    else:
        relabeled_metrics += "\nrelabel_success 0"

    return Response(relabeled_metrics, content_type="text/plain", status=200)


def get_ns_convert_table(network_name: str) -> list | dict | None:
    ns_convert_table_url = f"http://{NETOMOX_EXP_HOST}/topologies/{network_name}/ns_convert_table"
    response = requests.get(ns_convert_table_url)
    if response.status_code != 200:
        logger.error(f"Failed to get ns_convert_table from {ns_convert_table_url}")
        return None

    return json.loads(response.text)


def relabel(metrics_text: str) -> str:
    if mappings is None:
        return ""

    metrics = list(parser.text_string_to_metric_families(metrics_text))
    for m in metrics:
        if m.name not in TARGET_METRICS:
            logger.debug(f"skipped {m.name}")
            continue

        logger.info(f"relabeling {m.name}")
        for sample in m.samples:
            node_name = sample.labels["name"].replace("clab-emulated-", "")
            if node_name in mappings.keys():
                if_maps = mappings[node_name]
                if_name_emu = f"{sample.labels['interface']}.0"
                if if_name_emu not in if_maps.keys():
                    continue
                sample.labels["interface"] = if_maps[if_name_emu]["l3_model"]
                logger.info(f'converted {node_name}.{if_name_emu} to {sample.labels["interface"]}')

    return build_metrics_string(metrics)


def build_metrics_string(metrics: list[Metric]) -> str:
    metric_lines = []
    for m in metrics:
        metric_lines.append(f"# {m.name} {m.documentation}")
        metric_lines.append(f"# {m.name} {m.type}")
        for s in m.samples:
            label = ",".join([f'{key}="{value}"' for key, value in s.labels.items()])
            metric_lines.append(f"{s.name}{{{label}}} {s.value}")

    return "\n".join(metric_lines)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
