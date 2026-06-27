import math
import copy
import json
import os
from collections import deque
from datetime import datetime
from pathlib import Path
import matplotlib.pyplot as plt
import networkx as nx

from gvt import ler_jobs_data, agrupar_por_job, construir_grafos
from export_topology import parse_rack_data_with_coords, build_dragonfly_topology


def carregar_jobs(file_path: str) -> dict[int, nx.DiGraph]:
    dados = ler_jobs_data(file_path)
    jobs_dict = agrupar_por_job(dados)
    grafos = construir_grafos(jobs_dict)
    return grafos


def carregar_topologia(file_path: str) -> nx.Graph:
    with open(file_path, "r", encoding="utf-8") as f:
        markdown_content = f.read()

    rack_map, coord_map = parse_rack_data_with_coords(markdown_content)
    G = build_dragonfly_topology(rack_map, coord_map)
    return G


def listar_servidores_compute(topology: nx.Graph) -> list:
    servidores = [
        node for node, attrs in topology.nodes(data=True)
        if attrs.get("type") == "compute"
    ]
    return sorted(servidores, key=lambda x: int(x) if str(x).isdigit() else str(x))


def construir_network_state(topology: nx.Graph) -> dict:
    return {
        "traffic_history": [],
        "loop_traffic": [],
    }


def resumir_topologia(topology: nx.Graph) -> dict:
    compute_nodes = [n for n, d in topology.nodes(data=True) if d.get("type") == "compute"]
    router_nodes = [n for n, d in topology.nodes(data=True) if d.get("type") == "router"]

    edge_type_count = {}
    for _, _, attrs in topology.edges(data=True):
        edge_type = attrs.get("type", "unknown")
        edge_type_count[edge_type] = edge_type_count.get(edge_type, 0) + 1

    return {
        "total_nodes": topology.number_of_nodes(),
        "total_edges": topology.number_of_edges(),
        "compute_nodes_count": len(compute_nodes),
        "router_nodes_count": len(router_nodes),
        "edge_type_count": edge_type_count,
    }



def construir_indice_topologia(topology: nx.Graph) -> dict:
    servidores_por_rack = {}
    servidores_por_group = {}

    for node, attrs in topology.nodes(data=True):
        if attrs.get("type") != "compute":
            continue

        rack_id = attrs.get("rack_id")
        group_id = attrs.get("group")

        if rack_id is not None:
            servidores_por_rack.setdefault(rack_id, []).append(node)

        if group_id is not None:
            servidores_por_group.setdefault(group_id, []).append(node)

    for rack_id in servidores_por_rack:
        servidores_por_rack[rack_id] = sorted(
            servidores_por_rack[rack_id],
            key=lambda x: int(x) if str(x).isdigit() else str(x)
        )

    for group_id in servidores_por_group:
        servidores_por_group[group_id] = sorted(
            servidores_por_group[group_id],
            key=lambda x: int(x) if str(x).isdigit() else str(x)
        )

    return {
        "servers_by_rack": servidores_por_rack,
        "servers_by_group": servidores_por_group,
    }

def criar_state(jobs: dict[int, nx.DiGraph], topology: nx.Graph) -> dict:
    servidores = listar_servidores_compute(topology)

    return {
        "time": 0,
        "loop": 0,
        "pending_jobs": {job_id: G for job_id, G in jobs.items()},
        "active_jobs": {},
        "ready_tasks": deque(),
        "running_tasks": [],
        "finished_tasks": set(),
        "scheduled_tasks": set(),
        "server_status": {
            servidor: {
                "busy": False,
                "task": None,
                "job_id": None,
                "end_time": None,
            }
            for servidor in servidores
        },
        "task_placement": {},
        "network_state": construir_network_state(topology),
        "metrics": [],
        "loop_snapshots": [],
        "topology_summary": resumir_topologia(topology),
        "topology_index": construir_indice_topologia(topology),
        "hops_cache": {},
    }


def task_key(job_id: int, task_id: int) -> tuple[int, int]:
    return (job_id, task_id)


def tornar_json_serializavel(obj):
    if isinstance(obj, dict):
        return {str(k): tornar_json_serializavel(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [tornar_json_serializavel(v) for v in obj]
    if isinstance(obj, tuple):
        return [tornar_json_serializavel(v) for v in obj]
    if isinstance(obj, set):
        return [tornar_json_serializavel(v) for v in sorted(obj)]
    if isinstance(obj, deque):
        return [tornar_json_serializavel(v) for v in obj]
    return obj


def liberar_jobs_no_tempo(state: dict) -> list[int]:
    tempo = state["time"]
    liberar = []

    for job_id, G in state["pending_jobs"].items():
        sub_time = G.graph["sub_time"]
        if sub_time <= tempo:
            liberar.append(job_id)

    for job_id in liberar:
        state["active_jobs"][job_id] = state["pending_jobs"].pop(job_id)

    return liberar


def task_esta_pronta(job_id: int, task_id: int, G: nx.DiGraph, finished_tasks: set) -> bool:
    predecessores = list(G.predecessors(task_id))
    if not predecessores:
        return True

    for pred in predecessores:
        if task_key(job_id, pred) not in finished_tasks:
            return False

    return True


def atualizar_ready_tasks(state: dict) -> list[tuple[int, int]]:
    novas_ready = []

    for job_id, G in state["active_jobs"].items():
        for task_id in G.nodes():
            chave = task_key(job_id, task_id)

            if chave in state["finished_tasks"]:
                continue

            if chave in state["scheduled_tasks"]:
                continue

            if chave in state["ready_tasks"]:
                continue

            if task_esta_pronta(job_id, task_id, G, state["finished_tasks"]):
                state["ready_tasks"].append(chave)
                novas_ready.append(chave)

    return novas_ready


def atualizar_execucoes_finalizadas(state: dict) -> list[tuple[int, int]]:
    tempo = state["time"]
    finalizadas = []
    ainda_rodando = []

    for item in state["running_tasks"]:
        if item["end_time"] <= tempo:
            job_id = item["job_id"]
            task_id = item["task_id"]
            servidor = item["server"]

            chave = task_key(job_id, task_id)
            state["finished_tasks"].add(chave)

            state["server_status"][servidor]["busy"] = False
            state["server_status"][servidor]["task"] = None
            state["server_status"][servidor]["job_id"] = None
            state["server_status"][servidor]["end_time"] = None

            finalizadas.append(chave)
        else:
            ainda_rodando.append(item)

    state["running_tasks"] = ainda_rodando
    return finalizadas


def listar_servidores_livres(state: dict) -> list:
    livres = []
    for servidor, info in state["server_status"].items():
        if not info["busy"]:
            livres.append(servidor)
    return livres


def ordenar_fifo(ready_tasks: deque, jobs: dict[int, nx.DiGraph]) -> list[tuple[int, int]]:
    return sorted(
        list(ready_tasks),
        key=lambda x: (
            jobs[x[0]].graph["sub_time"],
            x[0],
            x[1],
        ),
    )


def escolher_servidor_fifo(task: tuple[int, int], servidores_livres: list, state: dict) -> str | None:
    if not servidores_livres:
        return None
    return sorted(servidores_livres, key=lambda x: int(x) if str(x).isdigit() else str(x))[0]


def calcular_duracao_execucao(job_graph: nx.DiGraph, task_id: int) -> int:
    wall_time = job_graph.nodes[task_id]["wall_time"]
    return max(1, math.ceil(wall_time))


def extrair_busy_servers_compacto(state: dict) -> dict:
    busy_servers = {}

    for servidor, info in state["server_status"].items():
        if info["busy"]:
            busy_servers[servidor] = {
                "job_id": info["job_id"],
                "task_id": info["task"],
                "end_time": info["end_time"],
            }

    total = len(state["server_status"])
    busy_count = len(busy_servers)

    return {
        "busy_count": busy_count,
        "free_count": total - busy_count,
        "busy_servers": busy_servers,
    }


def calcular_hops_entre_servidores(topology: nx.Graph, origem, destino, cache: dict | None = None) -> int:
    if origem == destino:
        return 0

    cache_key = (origem, destino)
    reverse_cache_key = (destino, origem)

    if cache is not None:
        if cache_key in cache:
            return cache[cache_key]
        if reverse_cache_key in cache:
            return cache[reverse_cache_key]

    try:
        hops = nx.shortest_path_length(topology, source=origem, target=destino)
    except nx.NetworkXNoPath:
        hops = -1

    if cache is not None:
        cache[cache_key] = hops
        cache[reverse_cache_key] = hops

    return hops


def calcular_trafego_tarefa(
    job_id: int,
    task_id: int,
    servidor_destino,
    state: dict,
    topology: nx.Graph,
    registrar_flows: bool = True
) -> dict:
    G = state["active_jobs"][job_id]
    predecessores = list(G.predecessors(task_id))

    if not predecessores:
        return {
            "job_id": job_id,
            "task_id": task_id,
            "server": servidor_destino,
            "has_traffic": False,
            "predecessor_count": 0,
            "flows": [],
            "total_hops": 0,
            "cross_server_flows": 0,
            "cross_rack_flows": 0,
            "cross_group_flows": 0,
            "estimated_comm_cost": 0.0,
        }

    flows = []
    total_hops = 0
    cross_server_flows = 0
    cross_rack_flows = 0
    cross_group_flows = 0
    estimated_comm_cost = 0.0

    hops_cache = state.setdefault("hops_cache", {})
    destino_attrs = topology.nodes[servidor_destino]
    destino_rack = destino_attrs.get("rack_id")
    destino_group = destino_attrs.get("group")

    for pred in predecessores:
        pred_key = task_key(job_id, pred)
        servidor_origem = state["task_placement"].get(pred_key)

        if servidor_origem is None:
            continue

        origem_attrs = topology.nodes[servidor_origem]
        origem_rack = origem_attrs.get("rack_id")
        origem_group = origem_attrs.get("group")

        cross_server = servidor_origem != servidor_destino
        cross_rack = origem_rack != destino_rack
        cross_group = origem_group != destino_group

        if cross_server:
            cross_server_flows += 1
        if cross_rack:
            cross_rack_flows += 1
        if cross_group:
            cross_group_flows += 1

        hops = calcular_hops_entre_servidores(
            topology,
            servidor_origem,
            servidor_destino,
            cache=hops_cache
        )

        hops_validos = max(hops, 0)
        total_hops += hops_validos

        payload = G.nodes[pred].get("resource", 1)
        comm_cost = hops_validos * payload
        estimated_comm_cost += comm_cost

        if registrar_flows:
            flows.append({
                "from_task": pred,
                "from_server": servidor_origem,
                "to_task": task_id,
                "to_server": servidor_destino,
                "hops": hops,
                "payload_estimate": payload,
                "cross_server": cross_server,
                "cross_rack": cross_rack,
                "cross_group": cross_group,
                "comm_cost": comm_cost,
            })

    return {
        "job_id": job_id,
        "task_id": task_id,
        "server": servidor_destino,
        "has_traffic": (cross_server_flows + cross_rack_flows + cross_group_flows + total_hops) > 0,
        "predecessor_count": len(predecessores),
        "flows": flows,
        "total_hops": total_hops,
        "cross_server_flows": cross_server_flows,
        "cross_rack_flows": cross_rack_flows,
        "cross_group_flows": cross_group_flows,
        "estimated_comm_cost": estimated_comm_cost,
    }


def resumir_trafego_loop(traffic_events: list[dict]) -> dict:
    total_tasks_with_traffic = sum(1 for e in traffic_events if e["has_traffic"])
    total_flows = sum(len(e["flows"]) for e in traffic_events)
    total_hops = sum(e["total_hops"] for e in traffic_events)
    total_comm_cost = sum(e["estimated_comm_cost"] for e in traffic_events)
    cross_server_flows = sum(e["cross_server_flows"] for e in traffic_events)
    cross_rack_flows = sum(e["cross_rack_flows"] for e in traffic_events)
    cross_group_flows = sum(e["cross_group_flows"] for e in traffic_events)

    return {
        "tasks_with_traffic": total_tasks_with_traffic,
        "flow_count": total_flows,
        "total_hops": total_hops,
        "cross_server_flows": cross_server_flows,
        "cross_rack_flows": cross_rack_flows,
        "cross_group_flows": cross_group_flows,
        "estimated_comm_cost": total_comm_cost,
    }


def escalonar_fifo(
    state: dict,
    topology: nx.Graph,
    server_selection_fn=None,
    network_weight: float = 1.0
) -> tuple[list[dict], list[dict]]:
    decisoes = []
    traffic_events = []
    livres = listar_servidores_livres(state)

    if not livres:
        return decisoes, traffic_events

    ordenadas = ordenar_fifo(state["ready_tasks"], state["active_jobs"])

    for chave in ordenadas:
        livres = listar_servidores_livres(state)
        if not livres:
            break

        if chave not in state["ready_tasks"]:
            continue

        job_id, task_id = chave
        G = state["active_jobs"][job_id]

        if server_selection_fn:
            servidor = server_selection_fn(chave, state, topology, network_weight)
        else:
            servidor = escolher_servidor_fifo(chave, livres, state)

        if servidor is None:
            break

        duracao = calcular_duracao_execucao(G, task_id)
        end_time = state["time"] + duracao

        trafego = calcular_trafego_tarefa(job_id, task_id, servidor, state, topology)

        state["ready_tasks"].remove(chave)
        state["scheduled_tasks"].add(chave)
        state["task_placement"][chave] = servidor

        state["server_status"][servidor]["busy"] = True
        state["server_status"][servidor]["task"] = task_id
        state["server_status"][servidor]["job_id"] = job_id
        state["server_status"][servidor]["end_time"] = end_time

        registro = {
            "job_id": job_id,
            "task_id": task_id,
            "server": servidor,
            "start_time": state["time"],
            "end_time": end_time,
        }

        state["running_tasks"].append(registro)
        decisoes.append(registro)
        traffic_events.append(trafego)

    return decisoes, traffic_events


def jobs_concluidos(state: dict) -> list[int]:
    concluidos = []

    for job_id, G in state["active_jobs"].items():
        todas = {task_key(job_id, task_id) for task_id in G.nodes()}
        if todas.issubset(state["finished_tasks"]):
            concluidos.append(job_id)

    return concluidos


def remover_jobs_concluidos(state: dict) -> list[int]:
    concluidos = jobs_concluidos(state)
    for job_id in concluidos:
        state["active_jobs"].pop(job_id, None)
    return concluidos


def coletar_metricas(state: dict) -> dict:
    ocupados = sum(1 for _, info in state["server_status"].items() if info["busy"])
    total = len(state["server_status"])

    traffic_summary = resumir_trafego_loop(state["network_state"]["loop_traffic"])

    metricas = {
        "time": state["time"],
        "active_jobs": len(state["active_jobs"]),
        "pending_jobs": len(state["pending_jobs"]),
        "ready_tasks": len(state["ready_tasks"]),
        "running_tasks": len(state["running_tasks"]),
        "finished_tasks": len(state["finished_tasks"]),
        "busy_servers": ocupados,
        "idle_servers": total - ocupados,
        "traffic": traffic_summary,
    }

    state["metrics"].append(metricas)
    return metricas


def registrar_snapshot_loop(state: dict, eventos: list[str]) -> None:
    metricas_atuais = state["metrics"][-1] if state["metrics"] else {}

    snapshot = {
        "loop": state["loop"],
        "time": state["time"],
        "timestamp": datetime.now().isoformat(),
        "events": eventos,
        "state": {
            "active_jobs": compactar_lista_em_linha(sorted(list(state["active_jobs"].keys()))),
            "pending_jobs": compactar_lista_em_linha(sorted(list(state["pending_jobs"].keys()))),
            "ready_tasks": list(state["ready_tasks"]),
            "running_tasks": copy.deepcopy(state["running_tasks"]),
            "finished_tasks_count": len(state["finished_tasks"]),
            "server_status": extrair_busy_servers_compacto(state),
            "network_traffic": copy.deepcopy(state["network_state"]["loop_traffic"]),
            "metrics": copy.deepcopy(metricas_atuais),
        },
    }

    state["loop_snapshots"].append(snapshot)


def simulacao_finalizada(state: dict) -> bool:
    return (
        len(state["pending_jobs"]) == 0
        and len(state["active_jobs"]) == 0
        and len(state["ready_tasks"]) == 0
        and len(state["running_tasks"]) == 0
    )


def gerar_nome_arquivo_execucao(prefixo: str = "fifo_execution_trace") -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{prefixo}_{timestamp}.json"


def salvar_json_execucao(
    state: dict,
    output_path: str,
    policy: str = "fifo",
    network_weight: float = 1.0
) -> None:
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    historico_network = state.get("historico_network", {})

    payload = {
        "metadata": {
            "policy": policy,
            "network_weight": network_weight,
            "external_recommender_enabled": False,
            "historical_network_enabled": historico_network.get("enabled", False),
            "historical_network_mode": historico_network.get("mode"),
            "historical_network_source_file": historico_network.get("source_file"),
            "generated_at": datetime.now().isoformat(),
            "total_loops": len(state["loop_snapshots"]),
            "final_time": state["time"],
        },
        "topology_summary": state["topology_summary"],
        "snapshots": state["loop_snapshots"],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            tornar_json_serializavel(payload),
            f,
            ensure_ascii=False,
            indent=2
        )

    print(f"JSON da execução salvo em: {os.path.abspath(output_path)}")


def executar_simulacao_fifo(
    jobs: dict[int, nx.DiGraph],
    topology: nx.Graph,
    max_time: int = 100000,
    scheduler_policy: str = "fifo",
    network_weight: float = 1.0,
    output_dir: str = "outputs",
    usar_historico_network: bool = True
) -> dict:
    if scheduler_policy not in {"fifo", "network_aware"}:
        raise ValueError("scheduler_policy deve ser 'fifo' ou 'network_aware'")

    state = criar_state(jobs, topology)

    if scheduler_policy == "network_aware" and usar_historico_network:
        state["historico_network"] = carregar_historico_network_por_task(output_dir, topology)
    else:
        state["historico_network"] = {
            "enabled": False,
            "source_file": None,
            "mode": "disabled",
            "task_recommendations": {},
        }

    if scheduler_policy == "network_aware":
        server_selection_fn = escolher_servidor_network_aware
    else:
        server_selection_fn = None

    while state["time"] <= max_time:
        eventos = []
        state["network_state"]["loop_traffic"] = []

        liberados = liberar_jobs_no_tempo(state)
        if liberados:
            eventos.append(f"jobs_liberados:{liberados}")

        finalizadas = atualizar_execucoes_finalizadas(state)
        if finalizadas:
            eventos.append(f"tasks_finalizadas:{finalizadas}")

        novas_ready = atualizar_ready_tasks(state)
        if novas_ready:
            eventos.append(f"tasks_prontas:{novas_ready}")

        decisoes, traffic_events = escalonar_fifo(
            state,
            topology,
            server_selection_fn=server_selection_fn,
            network_weight=network_weight
        )

        if decisoes:
            eventos.append(
                f"tasks_escalonadas:{[(d['job_id'], d['task_id'], d['server']) for d in decisoes]}"
            )
            state["network_state"]["loop_traffic"] = traffic_events
            state["network_state"]["traffic_history"].extend(traffic_events)

        concluidos = remover_jobs_concluidos(state)
        if concluidos:
            eventos.append(f"jobs_concluidos:{concluidos}")

        coletar_metricas(state)
        registrar_snapshot_loop(state, eventos)

        if simulacao_finalizada(state):
            break

        state["time"] += 1
        state["loop"] += 1

    return state

def imprimir_resumo_final(state: dict) -> None:
    print("\n=== RESUMO FINAL ===")
    print(f"Tempo final: {state['time']}")
    print(f"Tasks finalizadas: {len(state['finished_tasks'])}")
    print(f"Loops salvos: {len(state['loop_snapshots'])}")
    print(f"Métricas coletadas: {len(state['metrics'])}")

    ocupacoes = {}
    for chave, servidor in state["task_placement"].items():
        ocupacoes.setdefault(servidor, 0)
        ocupacoes[servidor] += 1

    top_servidores = sorted(ocupacoes.items(), key=lambda x: x[1], reverse=True)[:10]
    print("Top 10 servidores mais usados:")
    for servidor, qtd in top_servidores:
        print(f"  servidor={servidor} tasks={qtd}")

    traffic_history = state["network_state"]["traffic_history"]
    total_flows = sum(len(e["flows"]) for e in traffic_history)
    total_hops = sum(e["total_hops"] for e in traffic_history)
    total_comm_cost = sum(e["estimated_comm_cost"] for e in traffic_history)

    print("Resumo de tráfego estimado:")
    print(f"  eventos de tráfego: {len(traffic_history)}")
    print(f"  fluxos: {total_flows}")
    print(f"  hops totais: {total_hops}")
    print(f"  custo de comunicação estimado: {total_comm_cost:.4f}")


def diagnosticar_cross_rack_flows(state: dict, topology: nx.Graph) -> None:
    print("\n=== DIAGNÓSTICO CROSS-RACK ===")
    for evento in state["network_state"]["traffic_history"]:
        if evento.get("cross_rack_flows", 0) == 0:
            continue

        job_id = evento["job_id"]
        task_id = evento["task_id"]
        servidor_destino = evento["server"]
        destino_rack = topology.nodes[servidor_destino].get("rack_id")

        G = state["active_jobs"].get(job_id) or {}
        pred_racks = []

        for flow in evento.get("flows", []):
            if flow.get("cross_rack"):
                origem = flow["from_server"]
                origem_rack = topology.nodes[origem].get("rack_id")
                pred_racks.append(origem_rack)

        print(f"  job={job_id} task={task_id} destino_rack={destino_rack} pred_racks={pred_racks}")


def compactar_lista_em_linha(valores) -> str:
    return ",".join(str(v) for v in valores)



def buscar_ultimo_log_execucao(output_dir: str) -> str | None:
    output_path = Path(output_dir)

    if not output_path.exists():
        return None

    network_aware_logs = list(output_path.glob("network_aware_execution_trace_*.json"))
    fifo_logs = list(output_path.glob("fifo_execution_trace_*.json"))

    if network_aware_logs:
        ultimo = max(network_aware_logs, key=lambda p: p.stat().st_mtime)
        return str(ultimo)

    if fifo_logs:
        ultimo = max(fifo_logs, key=lambda p: p.stat().st_mtime)
        return str(ultimo)

    return None


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


def calcular_score_rede_metricas(metrics: dict, metric_weights: dict) -> float:
    return (
        metrics.get("cross_server_flows", 0) * metric_weights["cross_server"]
        + metrics.get("cross_rack_flows", 0) * metric_weights["cross_rack"]
        + metrics.get("cross_group_flows", 0) * metric_weights["cross_group"]
        + metrics.get("estimated_comm_cost", 0) * metric_weights["comm_cost"]
    )


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


def calcular_metricas_trafego_tarefa_compacta(
    job_id: int,
    task_id: int,
    servidor_destino,
    state: dict,
    topology: nx.Graph
) -> dict:
    trafego = calcular_trafego_tarefa(
        job_id=job_id,
        task_id=task_id,
        servidor_destino=servidor_destino,
        state=state,
        topology=topology,
        registrar_flows=False
    )

    return {
        "cross_server_flows": trafego.get("cross_server_flows", 0),
        "cross_rack_flows": trafego.get("cross_rack_flows", 0),
        "cross_group_flows": trafego.get("cross_group_flows", 0),
        "estimated_comm_cost": trafego.get("estimated_comm_cost", 0.0),
    }


def selecionar_candidatos_network_aware(
    job_id: int,
    task_id: int,
    livres: list,
    fifo_order: list,
    state: dict,
    topology: nx.Graph,
    max_fifo_candidates: int = 20,
    max_topology_candidates_per_pred: int = 20,
    max_total_candidates: int = 100
) -> list:
    if not livres:
        return []

    livres_set = set(livres)
    candidatos = []

    def adicionar(servidor):
        if servidor in livres_set and servidor not in candidatos:
            candidatos.append(servidor)

    for servidor in fifo_order[:max_fifo_candidates]:
        adicionar(servidor)

    historico = state.get("historico_network", {})
    task_recommendations = historico.get("task_recommendations", {})
    task_history = task_recommendations.get(f"{job_id}:{task_id}", {})
    previous_server = task_history.get("previous_server")
    if previous_server is not None:
        adicionar(previous_server)

    G = state["active_jobs"][job_id]
    predecessores = list(G.predecessors(task_id))

    servidores_origem = []
    for pred in predecessores:
        servidor_origem = state["task_placement"].get(task_key(job_id, pred))
        if servidor_origem is not None and servidor_origem not in servidores_origem:
            servidores_origem.append(servidor_origem)

    if not servidores_origem:
        return [fifo_order[0]]

    topology_index = state.get("topology_index", {})
    servers_by_rack = topology_index.get("servers_by_rack", {})
    servers_by_group = topology_index.get("servers_by_group", {})

    for servidor_origem in servidores_origem:
        adicionar(servidor_origem)

        origem_attrs = topology.nodes[servidor_origem]
        origem_rack = origem_attrs.get("rack_id")
        origem_group = origem_attrs.get("group")

        for servidor in servers_by_rack.get(origem_rack, [])[:max_topology_candidates_per_pred]:
            adicionar(servidor)

        for servidor in servers_by_group.get(origem_group, [])[:max_topology_candidates_per_pred]:
            adicionar(servidor)

    fifo_pos = {server: idx for idx, server in enumerate(fifo_order)}
    candidatos = sorted(candidatos, key=lambda server: fifo_pos.get(server, len(fifo_order)))

    if previous_server in candidatos:
        candidatos_limitados = [s for s in candidatos[:max_total_candidates] if s != previous_server]
        candidatos = [previous_server] + candidatos_limitados
    else:
        candidatos = candidatos[:max_total_candidates]

    return candidatos

def escolher_servidor_network_aware(
    task: tuple[int, int],
    state: dict,
    topology: nx.Graph,
    network_weight: float = 1.0
):
    livres = listar_servidores_livres(state)

    if not livres:
        return None

    fifo_order = sorted(livres, key=lambda x: int(x) if str(x).isdigit() else str(x))

    job_id, task_id = task

    candidatos = selecionar_candidatos_network_aware(
        job_id=job_id,
        task_id=task_id,
        livres=livres,
        fifo_order=fifo_order,
        state=state,
        topology=topology
    )

    if not candidatos:
        return fifo_order[0]

    if len(candidatos) == 1:
        return candidatos[0]

    traffic_metrics = {}

    for servidor in candidatos:
        traffic_metrics[servidor] = calcular_metricas_trafego_tarefa_compacta(
            job_id=job_id,
            task_id=task_id,
            servidor_destino=servidor,
            state=state,
            topology=topology
        )

    historico = state.get("historico_network", {})
    task_recommendations = historico.get("task_recommendations", {})
    task_history = task_recommendations.get(f"{job_id}:{task_id}", {})

    servidor = choose_server_network_aware(
        task={"job_id": job_id, "task_id": task_id},
        free_servers=candidatos,
        fifo_order=fifo_order,
        traffic_metrics=traffic_metrics,
        network_weight=network_weight,
        task_history=task_history,
        topology=topology,          # <- adiciona isso
    )

    return servidor


def choose_server_network_aware(
    task,
    free_servers,
    fifo_order,
    traffic_metrics,
    metric_weights=None,
    network_weight: float = 1.0,
    task_history=None,
    topology: nx.Graph = None,
):
    if metric_weights is None:
        metric_weights = {
            "cross_server": 0.25,   # agora todos fazem sentido em [0,1]
            "cross_rack":   0.25,
            "cross_group":  0.25,
            "comm_cost":    0.25,
        }

    if task_history is None:
        task_history = {}

    # Normaliza os 4 componentes entre os candidatos desta decisão
    normalized_metrics = normalizar_metricas_candidatos(traffic_metrics)

    best_rack = task_history.get("best_rack_to_place")
    best_group = task_history.get("best_group_to_place")
    prev_cross_rack = task_history.get("previous_cross_rack_flows", 0)
    prev_cross_group = task_history.get("previous_cross_group_flows", 0)
    prev_predecessor_count = task_history.get("previous_predecessor_count", 0)

    historico_util = (
        task_history
        and prev_predecessor_count > 0
        and best_rack is not None
        and best_group is not None
    )

    best_server = None
    best_score = float("inf")
    fifo_size = max(1, len(fifo_order))
    fifo_pos = {server: idx for idx, server in enumerate(fifo_order)}

    for server in free_servers:
        # Score de rede: soma ponderada dos 4 componentes normalizados → já em [0,1]
        metrics = normalized_metrics.get(server, {
            "cross_server_flows": 0.1,
            "cross_rack_flows":   0.3,
            "cross_group_flows":  0.4,
            "estimated_comm_cost": 0.2,
        })
        network_score = calcular_score_rede_metricas(metrics, metric_weights)
        # network_score agora está em [0, 1] também

        # Score FIFO: posição normalizada → já em [0,1]
        fifo_index = fifo_pos.get(server, len(fifo_order))
        fifo_score = fifo_index / fifo_size

        # Recomendador histórico: bônus em [0,1] baseado em rack/grupo
        history_bonus = 0.0
        if historico_util and topology is not None:
            server_attrs = topology.nodes.get(server, {})
            server_rack = server_attrs.get("rack_id")
            server_group = server_attrs.get("group")

            if server_group == best_group:
                history_bonus -= 0.20
                if server_rack == best_rack:
                    history_bonus -= 0.10

            if prev_cross_rack == 0 and prev_cross_group == 0:
                if server_group != best_group:
                    history_bonus += 0.25

        # Fórmula final: todos os componentes agora têm escala comparável
        # fifo_score    ∈ [0, 1]
        # network_score ∈ [0, 1]  (com network_weight controlando o peso relativo)
        # history_bonus ∈ [-0.30, +0.25]
        combined_score = fifo_score + network_weight * (network_score + history_bonus)

        if combined_score < best_score:
            best_score = combined_score
            best_server = server

    return best_server


def extrair_resumo_execucao_json(data: dict) -> dict:
    metadata = data.get("metadata", {})
    topology_summary = data.get("topology_summary", {})
    snapshots = data.get("snapshots", [])

    final_snapshot = snapshots[-1] if snapshots else {}
    final_state = final_snapshot.get("state", {})
    final_metrics = final_state.get("metrics", {})

    network_events = []
    busy_values = []
    running_values = []
    ready_values = []

    for snapshot in snapshots:
        state_snapshot = snapshot.get("state", {})
        metrics = state_snapshot.get("metrics", {})

        network_events.extend(state_snapshot.get("network_traffic", []))

        if "busy_servers" in metrics:
            busy_values.append(metrics.get("busy_servers", 0))

        if "running_tasks" in metrics:
            running_values.append(metrics.get("running_tasks", 0))

        if "ready_tasks" in metrics:
            ready_values.append(metrics.get("ready_tasks", 0))

    total_traffic_events = len(network_events)
    tasks_with_traffic = sum(1 for e in network_events if e.get("has_traffic"))
    total_flows = sum(len(e.get("flows", [])) for e in network_events)
    total_hops = sum(e.get("total_hops", 0) for e in network_events)
    total_comm_cost = sum(e.get("estimated_comm_cost", 0.0) for e in network_events)
    cross_server_flows = sum(e.get("cross_server_flows", 0) for e in network_events)
    cross_rack_flows = sum(e.get("cross_rack_flows", 0) for e in network_events)
    cross_group_flows = sum(e.get("cross_group_flows", 0) for e in network_events)

    compute_nodes = topology_summary.get("compute_nodes_count", 0)

    avg_busy_servers = sum(busy_values) / len(busy_values) if busy_values else 0.0
    max_busy_servers = max(busy_values) if busy_values else 0
    avg_running_tasks = sum(running_values) / len(running_values) if running_values else 0.0
    avg_ready_tasks = sum(ready_values) / len(ready_values) if ready_values else 0.0

    avg_cluster_utilization = (
        avg_busy_servers / compute_nodes
        if compute_nodes
        else 0.0
    )

    avg_comm_cost_per_scheduled_task = (
        total_comm_cost / total_traffic_events
        if total_traffic_events
        else 0.0
    )

    avg_hops_per_flow = (
        total_hops / total_flows
        if total_flows
        else 0.0
    )

    return {
        "policy": metadata.get("policy"),
        "recomendador_factor": metadata.get("recomendador_factor"),
        "generated_at": metadata.get("generated_at"),
        "total_loops": metadata.get("total_loops", len(snapshots)),
        "final_time": metadata.get("final_time", final_snapshot.get("time")),
        "finished_tasks": final_metrics.get(
            "finished_tasks",
            final_state.get("finished_tasks_count", 0)
        ),
        "traffic_events": total_traffic_events,
        "tasks_with_traffic": tasks_with_traffic,
        "flow_count": total_flows,
        "total_hops": total_hops,
        "cross_server_flows": cross_server_flows,
        "cross_rack_flows": cross_rack_flows,
        "cross_group_flows": cross_group_flows,
        "estimated_comm_cost": total_comm_cost,
        "avg_comm_cost_per_scheduled_task": avg_comm_cost_per_scheduled_task,
        "avg_hops_per_flow": avg_hops_per_flow,
        "avg_busy_servers": avg_busy_servers,
        "max_busy_servers": max_busy_servers,
        "avg_running_tasks": avg_running_tasks,
        "avg_ready_tasks": avg_ready_tasks,
        "avg_cluster_utilization": avg_cluster_utilization,
    }


def calcular_delta_metrica(previous_value, current_value, lower_is_better: bool = True) -> dict:
    if previous_value is None:
        previous_value = 0

    if current_value is None:
        current_value = 0

    absolute_delta = current_value - previous_value

    if previous_value == 0:
        percent_delta = None
    else:
        percent_delta = (absolute_delta / previous_value) * 100

    if lower_is_better:
        improvement_absolute = previous_value - current_value
        improvement_percent = None if percent_delta is None else -percent_delta
    else:
        improvement_absolute = current_value - previous_value
        improvement_percent = percent_delta

    return {
        "previous": previous_value,
        "current": current_value,
        "absolute_delta": absolute_delta,
        "percent_delta": percent_delta,
        "lower_is_better": lower_is_better,
        "improvement_absolute": improvement_absolute,
        "improvement_percent": improvement_percent,
    }


def comparar_resumos_execucao(previous_summary: dict, current_summary: dict) -> dict:
    lower_is_better_metrics = [
        "final_time",
        "total_loops",
        "traffic_events",
        "flow_count",
        "total_hops",
        "cross_server_flows",
        "cross_rack_flows",
        "cross_group_flows",
        "estimated_comm_cost",
        "avg_comm_cost_per_scheduled_task",
        "avg_hops_per_flow",
        "avg_ready_tasks",
    ]

    neutral_metrics = [
        "finished_tasks",
        "avg_busy_servers",
        "max_busy_servers",
        "avg_running_tasks",
        "avg_cluster_utilization",
    ]

    comparison = {}

    for metric in lower_is_better_metrics:
        comparison[metric] = calcular_delta_metrica(
            previous_summary.get(metric),
            current_summary.get(metric),
            lower_is_better=True
        )

    for metric in neutral_metrics:
        comparison[metric] = calcular_delta_metrica(
            previous_summary.get(metric),
            current_summary.get(metric),
            lower_is_better=False
        )

    return comparison


def formatar_valor_comparacao(valor) -> str:
    if valor is None:
        return "-"

    if isinstance(valor, float):
        return f"{valor:.4f}"

    return str(valor)


def formatar_percentual_comparacao(valor) -> str:
    if valor is None:
        return "-"

    return f"{valor:.2f}%"


def salvar_resumo_markdown_comparacao(payload: dict, output_path: str) -> None:
    previous_summary = payload.get("previous_summary", {})
    current_summary = payload.get("current_summary", {})
    deltas = payload.get("deltas", {})

    metricas = [
        "final_time",
        "total_loops",
        "finished_tasks",
        "traffic_events",
        "flow_count",
        "total_hops",
        "cross_server_flows",
        "cross_rack_flows",
        "cross_group_flows",
        "estimated_comm_cost",
        "avg_comm_cost_per_scheduled_task",
        "avg_hops_per_flow",
        "avg_busy_servers",
        "max_busy_servers",
        "avg_running_tasks",
        "avg_ready_tasks",
        "avg_cluster_utilization",
    ]

    nomes = {
        "final_time": "Tempo final",
        "total_loops": "Total de loops",
        "finished_tasks": "Tasks finalizadas",
        "traffic_events": "Eventos de tráfego",
        "flow_count": "Fluxos",
        "total_hops": "Hops totais",
        "cross_server_flows": "Cross-server flows",
        "cross_rack_flows": "Cross-rack flows",
        "cross_group_flows": "Cross-group flows",
        "estimated_comm_cost": "Custo estimado de comunicação",
        "avg_comm_cost_per_scheduled_task": "Custo médio por task com tráfego",
        "avg_hops_per_flow": "Hops médios por fluxo",
        "avg_busy_servers": "Média de servidores ocupados",
        "max_busy_servers": "Pico de servidores ocupados",
        "avg_running_tasks": "Média de tasks em execução",
        "avg_ready_tasks": "Média de tasks prontas",
        "avg_cluster_utilization": "Utilização média do cluster",
    }

    linhas = []
    linhas.append("# Comparação entre execuções\n")
    linhas.append(f"- Execução anterior: `{payload['metadata'].get('previous_execution_path')}`")
    linhas.append(f"- Execução atual: `{payload['metadata'].get('current_execution_path')}`")
    linhas.append(f"- Política anterior: `{payload['metadata'].get('previous_policy')}`")
    linhas.append(f"- Política atual: `{payload['metadata'].get('current_policy')}`")
    linhas.append("")
    linhas.append("| Métrica | Anterior | Atual | Delta | Melhoria |")
    linhas.append("|---|---:|---:|---:|---:|")

    for metrica in metricas:
        delta_info = deltas.get(metrica, {})

        anterior = previous_summary.get(metrica)
        atual = current_summary.get(metrica)
        delta = delta_info.get("absolute_delta")
        melhoria = delta_info.get("improvement_percent")

        linhas.append(
            "| "
            f"{nomes.get(metrica, metrica)} | "
            f"{formatar_valor_comparacao(anterior)} | "
            f"{formatar_valor_comparacao(atual)} | "
            f"{formatar_valor_comparacao(delta)} | "
            f"{formatar_percentual_comparacao(melhoria)} |"
        )

    linhas.append("")
    linhas.append("## Regra de leitura")
    linhas.append("")
    linhas.append(
        "Para métricas de custo, tempo, hops e tráfego, melhoria positiva significa que a execução atual reduziu o valor em relação à anterior."
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))

    print(f"Resumo Markdown salvo em: {os.path.abspath(output_path)}")


def salvar_grafico_comparacao(payload: dict, output_path: str) -> None:
    deltas = payload.get("deltas", {})

    metricas = [
        ("final_time", "Tempo"),
        ("total_loops", "Loops"),
        ("estimated_comm_cost", "Custo comunicação"),
        ("total_hops", "Hops"),
        ("flow_count", "Fluxos"),
        ("cross_server_flows", "Cross-server"),
        ("cross_rack_flows", "Cross-rack"),
        ("cross_group_flows", "Cross-group"),
        ("avg_hops_per_flow", "Hops/fluxo"),
    ]

    labels = []
    valores = []

    for chave, label in metricas:
        improvement_percent = deltas.get(chave, {}).get("improvement_percent")

        if improvement_percent is not None:
            labels.append(label)
            valores.append(improvement_percent)

    if not labels:
        return

    plt.figure(figsize=(12, 6))
    plt.bar(labels, valores)
    plt.axhline(0)
    plt.title("Melhoria percentual da execução atual em relação à anterior")
    plt.ylabel("Melhoria (%)")
    plt.xticks(rotation=35, ha="right")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()

    print(f"Gráfico de comparação salvo em: {os.path.abspath(output_path)}")


def salvar_json_comparacao_execucoes(
    previous_execution_path: str | None,
    current_execution_path: str,
    output_dir: str
) -> dict:
    comparison_dir = os.path.join(output_dir, "comparison")
    os.makedirs(comparison_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    with open(current_execution_path, "r", encoding="utf-8") as f:
        current_data = json.load(f)

    current_summary = extrair_resumo_execucao_json(current_data)

    if previous_execution_path is None or not os.path.exists(previous_execution_path):
        payload = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "comparison_available": False,
                "reason": "Nenhuma execução anterior encontrada para comparação.",
                "previous_execution_path": previous_execution_path,
                "current_execution_path": current_execution_path,
            },
            "current_summary": current_summary,
        }

        caminho_json = os.path.join(
            comparison_dir,
            f"comparison_no_previous_execution_{timestamp}.json"
        )

        with open(caminho_json, "w", encoding="utf-8") as f:
            json.dump(
                tornar_json_serializavel(payload),
                f,
                ensure_ascii=False,
                indent=2
            )

        print(f"JSON de comparação salvo em: {os.path.abspath(caminho_json)}")

        return {
            "comparison_json": caminho_json,
            "comparison_chart": None,
            "comparison_summary": None,
        }

    with open(previous_execution_path, "r", encoding="utf-8") as f:
        previous_data = json.load(f)

    previous_summary = extrair_resumo_execucao_json(previous_data)
    deltas = comparar_resumos_execucao(previous_summary, current_summary)

    previous_policy = previous_summary.get("policy", "unknown")
    current_policy = current_summary.get("policy", "unknown")

    payload = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "comparison_available": True,
            "previous_execution_path": previous_execution_path,
            "current_execution_path": current_execution_path,
            "previous_policy": previous_policy,
            "current_policy": current_policy,
        },
        "previous_summary": previous_summary,
        "current_summary": current_summary,
        "deltas": deltas,
        "interpretation": {
            "lower_is_better_metrics": [
                "final_time",
                "total_loops",
                "traffic_events",
                "flow_count",
                "total_hops",
                "cross_server_flows",
                "cross_rack_flows",
                "cross_group_flows",
                "estimated_comm_cost",
                "avg_comm_cost_per_scheduled_task",
                "avg_hops_per_flow",
                "avg_ready_tasks",
            ],
            "neutral_metrics": [
                "finished_tasks",
                "avg_busy_servers",
                "max_busy_servers",
                "avg_running_tasks",
                "avg_cluster_utilization",
            ],
            "reading_rule": "Para métricas lower_is_better, improvement_absolute positivo indica melhoria da execução atual em relação à anterior.",
        },
    }

    prefixo = f"{previous_policy}_to_{current_policy}"

    caminho_json = os.path.join(
        comparison_dir,
        f"comparison_{prefixo}_{timestamp}.json"
    )

    caminho_grafico = os.path.join(
        comparison_dir,
        f"comparison_chart_{prefixo}_{timestamp}.png"
    )

    caminho_markdown = os.path.join(
        comparison_dir,
        f"comparison_summary_{prefixo}_{timestamp}.md"
    )

    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump(
            tornar_json_serializavel(payload),
            f,
            ensure_ascii=False,
            indent=2
        )

    print(f"JSON de comparação salvo em: {os.path.abspath(caminho_json)}")

    salvar_grafico_comparacao(payload, caminho_grafico)
    salvar_resumo_markdown_comparacao(payload, caminho_markdown)

    return {
        "comparison_json": caminho_json,
        "comparison_chart": caminho_grafico,
        "comparison_summary": caminho_markdown,
    }


def normalizar_metricas_candidatos(traffic_metrics: dict) -> dict:
    """Normaliza cada métrica para [0,1] entre os candidatos disponíveis."""
    servidores = list(traffic_metrics.keys())
    
    campos = ["cross_server_flows", "cross_rack_flows", "cross_group_flows", "estimated_comm_cost"]
    
    normalized = {s: {} for s in servidores}
    
    for campo in campos:
        valores = [traffic_metrics[s].get(campo, 0) for s in servidores]
        minv = min(valores)
        maxv = max(valores)
        
        for s in servidores:
            raw = traffic_metrics[s].get(campo, 0)
            if maxv == minv:
                normalized[s][campo] = 0.0  # todos iguais → sem diferença
            else:
                normalized[s][campo] = (raw - minv) / (maxv - minv)
    
    return normalized


def main():
    jobs_file = "datas/jobs.data"
    topology_file = "racks_spatial_distribution_90_nodes.md"

    scheduler_policy = "network_aware"
    network_weight = 1.0
    usar_historico_network = True

    if scheduler_policy == "fifo":
        network_weight = 0.0
        usar_historico_network = False

    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "outputs")

    jobs = carregar_jobs(jobs_file)
    topology = carregar_topologia(topology_file)

    print(f"Jobs carregados: {len(jobs)}")
    print(f"Nós da topologia: {topology.number_of_nodes()}")
    print(f"Arestas da topologia: {topology.number_of_edges()}")
    print(f"Servidores compute: {len(listar_servidores_compute(topology))}")
    print(f"Política solicitada: {scheduler_policy}")
    print(f"Network weight: {network_weight}")

    previous_execution_path = buscar_ultimo_log_execucao(output_dir)

    if scheduler_policy == "network_aware" and previous_execution_path is None:
        print("Nenhuma execução anterior encontrada.")
        print("Executando FIFO baseline automaticamente antes do network-aware.")

        fifo_state = executar_simulacao_fifo(
            jobs=jobs,
            topology=topology,
            max_time=100000,
            scheduler_policy="fifo",
            network_weight=0.0,
            output_dir=output_dir,
            usar_historico_network=False
        )

        imprimir_resumo_final(fifo_state)

        nome_fifo = gerar_nome_arquivo_execucao("fifo_execution_trace")
        caminho_fifo = os.path.join(output_dir, nome_fifo)

        salvar_json_execucao(
            state=fifo_state,
            output_path=caminho_fifo,
            policy="fifo",
            network_weight=0.0
        )

        previous_execution_path = caminho_fifo

        print(f"Baseline FIFO gerado em: {caminho_fifo}")

    state = executar_simulacao_fifo(
        jobs=jobs,
        topology=topology,
        max_time=100000,
        scheduler_policy=scheduler_policy,
        network_weight=network_weight,
        output_dir=output_dir,
        usar_historico_network=usar_historico_network
    )

    historico = state.get("historico_network", {})
    if historico.get("enabled"):
        print(f"Histórico de rede carregado de: {historico.get('source_file')}")
        print(f"Modo do histórico: {historico.get('mode')}")
        print(f"Tasks com histórico: {len(historico.get('task_recommendations', {}))}")
    else:
        print("Histórico de rede não carregado. Execução sem histórico anterior.")

    imprimir_resumo_final(state)

    diagnosticar_cross_rack_flows(state, topology)

    if scheduler_policy == "fifo":
        prefixo_arquivo = "fifo_execution_trace"
    else:
        prefixo_arquivo = "network_aware_execution_trace"

    nome_arquivo = gerar_nome_arquivo_execucao(prefixo_arquivo)
    caminho_saida = os.path.join(output_dir, nome_arquivo)

    salvar_json_execucao(
        state=state,
        output_path=caminho_saida,
        policy=scheduler_policy,
        network_weight=network_weight
    )

    if "salvar_json_comparacao_execucoes" in globals():
        artefatos_comparacao = salvar_json_comparacao_execucoes(
            previous_execution_path=previous_execution_path,
            current_execution_path=caminho_saida,
            output_dir=output_dir
        )

        print("Artefatos de comparação:")
        print(f"  JSON: {artefatos_comparacao.get('comparison_json')}")
        print(f"  Gráfico: {artefatos_comparacao.get('comparison_chart')}")
        print(f"  Resumo: {artefatos_comparacao.get('comparison_summary')}")


if __name__ == "__main__":
    main()