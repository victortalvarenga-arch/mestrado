from imports import copy, datetime, nx
from state import criar_state
from serialization import task_key, compactar_lista_em_linha
from scheduler_engine import escalonar_tarefas
from scheduler_dispatcher import validar_politica_base
from network_aware import escolher_servidor_network_aware
from history import carregar_historico_network_por_task
from network_metrics import resumir_trafego_loop
from reporting import extrair_busy_servers_compacto
import os
import matplotlib.pyplot as plt

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
    import ast

    metricas_atuais = state["metrics"][-1] if state["metrics"] else {}

    def compactar_evento(evento: str, limite: int = 50) -> str:
        if ":" not in evento:
            return evento

        prefixo, valor = evento.split(":", 1)

        try:
            lista = ast.literal_eval(valor)
        except Exception:
            return evento

        if not isinstance(lista, list):
            return evento

        if len(lista) <= limite:
            return evento

        amostra = lista[:limite]
        return (
            f"{prefixo}:count={len(lista)},"
            f"sample={amostra},"
            f"truncated=True"
        )

    eventos_compactados = [
        compactar_evento(evento)
        for evento in eventos
    ]

    ready_tasks_count = len(state["ready_tasks"])
    ready_tasks_sample = list(state["ready_tasks"])[:50]

    snapshot = {
        "loop": state["loop"],
        "time": state["time"],
        "timestamp": datetime.now().isoformat(),
        "events": eventos_compactados,
        "state": {
            "active_jobs": compactar_lista_em_linha(sorted(list(state["active_jobs"].keys()))),
            "pending_jobs": compactar_lista_em_linha(sorted(list(state["pending_jobs"].keys()))),
            "ready_tasks": {
                "count": ready_tasks_count,
                "sample": ready_tasks_sample,
                "truncated": ready_tasks_count > 50,
            },
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

def executar_simulacao(
    jobs: dict[int, nx.DiGraph],
    topology: nx.Graph,
    max_time: int = 100000,
    scheduler_policy: str = "easy",
    base_scheduler_policy: str = "easy",
    network_weight: float = 1.0,
    network_aware_config: dict | None = None,
    output_dir: str = "outputs",
    usar_historico_network: bool = True
) -> dict:
    base_scheduler_policy = validar_politica_base(base_scheduler_policy)

    if scheduler_policy != "network_aware":
        scheduler_policy = validar_politica_base(scheduler_policy)

    state = criar_state(jobs, topology)

    state["scheduler_policy"] = scheduler_policy
    state["base_scheduler_policy"] = base_scheduler_policy

    if scheduler_policy == "network_aware":
        if network_aware_config is None:
            network_aware_config = {
                "scenario_name": "network_aware_default",
                "base_scheduler_policy": base_scheduler_policy,
                "network_weight": network_weight,
                "metric_weights": {
                    "cross_server": 0.25,
                    "cross_rack": 0.25,
                    "cross_group": 0.25,
                    "comm_cost": 0.25,
                },
                "max_base_candidates": 20,
                "max_topology_candidates_per_pred": 20,
                "max_total_candidates": 100,
            }

        network_aware_config["base_scheduler_policy"] = base_scheduler_policy
        state["network_aware_config"] = network_aware_config
    else:
        state["network_aware_config"] = None

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

        decisoes, traffic_events = escalonar_tarefas(
            state,
            topology,
            server_selection_fn=server_selection_fn,
            network_weight=network_weight,
            network_aware_config=network_aware_config,
            base_scheduler_policy=base_scheduler_policy
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

# Compatibilidade com chamadas antigas do projeto.
def executar_simulacao_fifo(*args, **kwargs) -> dict:
    return executar_simulacao(*args, **kwargs)
