from imports import json, nx
from logs import buscar_ultimo_log_execucao

def carregar_historico_network_por_task(output_dir: str, topology: nx.Graph = None) -> dict:
    ultimo_log = buscar_ultimo_log_execucao(output_dir)

    historico = {
        "enabled": False,
        "source_file": None,
        "mode": "task_based",
        "task_recommendations": {},
    }

    if ultimo_log is None:
        return historico

    with open(ultimo_log, "r", encoding="utf-8") as f:
        data = json.load(f)

    task_recommendations = {}

    for snapshot in data.get("snapshots", []):
        network_traffic = snapshot.get("state", {}).get("network_traffic", [])

        for evento in network_traffic:
            job_id = evento.get("job_id")
            task_id = evento.get("task_id")
            server = evento.get("server")

            if job_id is None or task_id is None or server is None:
                continue

            key = f"{job_id}:{task_id}"

            best_rack = None
            best_group = None

            if topology is not None:
                server_attrs = topology.nodes.get(server, {})
                best_rack = server_attrs.get("rack_id")
                best_group = server_attrs.get("group")

            task_recommendations[key] = {
                "previous_server": server,
                "best_rack_to_place": best_rack,
                "best_group_to_place": best_group,
                "comm_cost_achieved": evento.get("estimated_comm_cost", 0.0),
                "previous_has_traffic": evento.get("has_traffic", False),
                "previous_predecessor_count": evento.get("predecessor_count", 0),
                "previous_total_hops": evento.get("total_hops", 0),
                "previous_cross_server_flows": evento.get("cross_server_flows", 0),
                "previous_cross_rack_flows": evento.get("cross_rack_flows", 0),
                "previous_cross_group_flows": evento.get("cross_group_flows", 0),
                "previous_estimated_comm_cost": evento.get("estimated_comm_cost", 0.0),
            }

    historico["enabled"] = True
    historico["source_file"] = ultimo_log
    historico["task_recommendations"] = task_recommendations

    return historico

def carregar_recomendador_historico(output_dir: str, historical_weight: float = 0.25) -> dict:
    ultimo_log = buscar_ultimo_log_execucao(output_dir)

    recomendador = {
        "enabled": False,
        "source_file": None,
        "historical_weight": historical_weight,
        "server_scores": {},
    }

    if ultimo_log is None:
        return recomendador

    with open(ultimo_log, "r", encoding="utf-8") as f:
        data = json.load(f)

    acumulado_por_servidor = {}

    for snapshot in data.get("snapshots", []):
        state_snapshot = snapshot.get("state", {})
        network_traffic = state_snapshot.get("network_traffic", [])

        for evento in network_traffic:
            servidor = str(evento.get("server"))

            raw_score = (
                evento.get("cross_server_flows", 0)
                + evento.get("cross_rack_flows", 0)
                + evento.get("cross_group_flows", 0)
                + evento.get("estimated_comm_cost", 0)
            )

            if servidor not in acumulado_por_servidor:
                acumulado_por_servidor[servidor] = {
                    "total_score": 0.0,
                    "count": 0,
                }

            acumulado_por_servidor[servidor]["total_score"] += raw_score
            acumulado_por_servidor[servidor]["count"] += 1

    medias = {}

    for servidor, dados in acumulado_por_servidor.items():
        if dados["count"] > 0:
            medias[servidor] = dados["total_score"] / dados["count"]

    if not medias:
        recomendador["enabled"] = True
        recomendador["source_file"] = ultimo_log
        return recomendador

    menor = min(medias.values())
    maior = max(medias.values())

    if maior == menor:
        server_scores = {servidor: 0.0 for servidor in medias}
    else:
        server_scores = {
            servidor: (score - menor) / (maior - menor)
            for servidor, score in medias.items()
        }

    recomendador["enabled"] = True
    recomendador["source_file"] = ultimo_log
    recomendador["server_scores"] = server_scores

    return recomendador

def carregar_recomendador_historico_por_task(output_dir: str) -> dict:
    ultimo_log = buscar_ultimo_log_execucao(output_dir)

    recomendador = {
        "enabled": False,
        "source_file": None,
        "mode": "task_based",
        "task_recommendations": {},
    }

    if ultimo_log is None:
        return recomendador

    with open(ultimo_log, "r", encoding="utf-8") as f:
        data = json.load(f)

    task_recommendations = {}

    for snapshot in data.get("snapshots", []):
        network_traffic = snapshot.get("state", {}).get("network_traffic", [])

        for evento in network_traffic:
            job_id = evento.get("job_id")
            task_id = evento.get("task_id")
            server = evento.get("server")

            if job_id is None or task_id is None or server is None:
                continue

            key = f"{job_id}:{task_id}"

            task_recommendations[key] = {
                "previous_server": server,
                "previous_has_traffic": evento.get("has_traffic", False),
                "previous_predecessor_count": evento.get("predecessor_count", 0),
                "previous_total_hops": evento.get("total_hops", 0),
                "previous_cross_server_flows": evento.get("cross_server_flows", 0),
                "previous_cross_rack_flows": evento.get("cross_rack_flows", 0),
                "previous_cross_group_flows": evento.get("cross_group_flows", 0),
                "previous_estimated_comm_cost": evento.get("estimated_comm_cost", 0.0),
            }

    recomendador["enabled"] = True
    recomendador["source_file"] = ultimo_log
    recomendador["task_recommendations"] = task_recommendations

    return recomendador
