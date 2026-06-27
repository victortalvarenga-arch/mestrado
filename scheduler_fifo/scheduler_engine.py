from imports import nx
from network_metrics import calcular_trafego_tarefa
from scheduler_utils import listar_servidores_livres, calcular_duracao_execucao
from scheduler_dispatcher import ordenar_tarefas_prontas, escolher_servidor_base, validar_politica_base


def escalonar_tarefas(
    state: dict,
    topology: nx.Graph,
    server_selection_fn=None,
    network_weight: float = 1.0,
    network_aware_config: dict | None = None,
    base_scheduler_policy: str = "easy"
) -> tuple[list[dict], list[dict]]:
    decisoes = []
    traffic_events = []
    base_scheduler_policy = validar_politica_base(base_scheduler_policy)

    livres = listar_servidores_livres(state)
    if not livres:
        return decisoes, traffic_events

    ordenadas = ordenar_tarefas_prontas(
        policy=base_scheduler_policy,
        ready_tasks=state["ready_tasks"],
        jobs=state["active_jobs"],
        state=state,
    )

    for chave in ordenadas:
        livres = listar_servidores_livres(state)

        if not livres:
            break

        if chave not in state["ready_tasks"]:
            continue

        job_id, task_id = chave
        G = state["active_jobs"][job_id]

        if server_selection_fn:
            servidor = server_selection_fn(
                chave,
                state,
                topology,
                network_aware_config
            )
        else:
            servidor = escolher_servidor_base(
                policy=base_scheduler_policy,
                task=chave,
                servidores_livres=livres,
                state=state,
                topology=topology,
            )

        if servidor is None:
            break

        duracao = calcular_duracao_execucao(G, task_id)
        end_time = state["time"] + duracao

        trafego = calcular_trafego_tarefa(
            job_id,
            task_id,
            servidor,
            state,
            topology
        )

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
