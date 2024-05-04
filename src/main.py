from flask import Flask, request, Response
from logging import getLogger, Formatter, StreamHandler, ERROR
from prometheus_client import parser, Metric
import sys
import requests
import json
import os


logger = getLogger('root')
logger.setLevel(ERROR)
formatter = Formatter("[{asctime}: {message} ({funcName}:{lineno}]) ", style="{")

sh = StreamHandler(sys.stdout)
sh.setFormatter(formatter)
sh.setLevel(ERROR)
logger.addHandler(sh)

app = Flask(__name__)

CADVISOR_URL = os.environ.get("CADVISOR_URL")
logger.info(f"CADVISOR_URL: {CADVISOR_URL}")

NETOMOX_EXP_HOST = os.environ.get("NETOMOX_EXP_HOST")
logger.info(f"NETOMOX_EXP_HOST: {NETOMOX_EXP_HOST}")
NS_CONVERT_TABLE_URL = f"http://{ NETOMOX_EXP_HOST }/topologies/mddo-bgp/ns_convert_table"
logger.info(f"NS_CONVERT_TABLE_URL: {NS_CONVERT_TABLE_URL}")

TARGET_METRICS = ['container_network_receive_bytes', 'container_network_transmit_bytes']

@app.get('/metrics')
def metrics():
    response = requests.get(CADVISOR_URL)

    relabeled_metrics = relabel(response.text)

    if relabeled_metrics:
        relabeled_metrics += "\nrelabel_success 1"
    else:
        relabeled_metrics += "\nrelabel_success 0"

    return Response(relabeled_metrics, content_type='text/plain', status=200)

def get_ns_convert_table() -> list|dict|None:
    response = requests.get(NS_CONVERT_TABLE_URL)
    if response.status_code != 200:
        logger.error(f"Failed to get ns_convert_table from {NS_CONVERT_TABLE_URL}")
        return None
    return json.loads(response.text)

def relabel(metrics_text: str) -> str:

    mappings = get_ns_convert_table().get("tp_name_table")

    if mappings is None:
        return ""

    metrics = list(parser.text_string_to_metric_families(metrics_text))
    for m in metrics:
        if m.name not in TARGET_METRICS:
            logger.debug(f'skipped {m.name}')
            continue

        logger.info(f'relabeling {m.name}')
        for sample in m.samples:
            node_name = sample.labels['name'].replace('clab-emulated-', '')
            if node_name in mappings.keys():
                if_maps = mappings[node_name]
                if_name_emu = f"{sample.labels['interface']}.0"
                if if_name_emu not in if_maps.keys():
                    continue
                sample.labels['interface'] = if_maps[if_name_emu]['l3_model']
                logger.info(f'converted {node_name}.{if_name_emu} to {sample.labels["interface"]}')

    return build_metrics_string(metrics)

def build_metrics_string(metrics: list[Metric]) -> str:

    metric_lines = []
    for m in metrics:
        metric_lines.append(f'# {m.name} {m.documentation}')
        metric_lines.append(f'# {m.name} {m.type}')
        for s in m.samples:
            label = ','.join([f'{key}="{value}"' for key, value in s.labels.items()])
            if s.timestamp != None:
                metric_lines.append(f'{s.name}{{{label}}} {s.value} {str(s.timestamp).replace(".", "")}')
            else:
                metric_lines.append(f'{s.name}{{{label}}} {s.value}')

    return '\n'.join(metric_lines)

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)

