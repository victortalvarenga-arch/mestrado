from imports import nx
from scheduler_utils import listar_servidores_livres, ordenar_servidores
from scheduler_dispatcher import escolher_servidor_base
from serialization import task_key
from network_metrics import calcular_metricas_trafego_tarefa_compacta

def calcular_score_rede_metricas(metrics: dict, metric_weights: dict) -> float:
    return (
        metrics.get("cross_server_flows", 0) * metric_weights["cross_server"]
        + metrics.get("cross_rack_flows", 0) * metric_weights["cross_rack"]
        + metrics.get("cross_group_flows", 0) * metric_weights["cross_group"]
        + metrics.get("estimated_comm_cost", 0) * metric_weights["comm_cost"]
    )

def selecionar_candidatos_network_aware(
    job_id: int,
    task_id: int,
    livres: list,
    base_order: list,
    state: dict,
    topology: nx.Graph,
    base_preferred_server=None,
    max_base_candidates: int = 20,
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

    if base_preferred_server is not None:
        adicionar(base_preferred_server)

    for servidor in base_order[:max_base_candidates]:
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
        return [base_order[0]]

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

    base_pos = {server: idx for idx, server in enumerate(base_order)}
    candidatos = sorted(candidatos, key=lambda server: base_pos.get(server, len(base_order)))

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
    network_aware_config: dict | None = None
):
    if network_aware_config is None:
        network_aware_config = {}

    network_weight = network_aware_config.get("network_weight", 1.0)
    metric_weights = network_aware_config.get("metric_weights", {
        "cross_server": 0.25,
        "cross_rack": 0.25,
        "cross_group": 0.25,
        "comm_cost": 0.25,
    })

    base_scheduler_policy = network_aware_config.get(
        "base_scheduler_policy",
        state.get("base_scheduler_policy", "easy")
    )
    max_base_candidates = network_aware_config.get(
        "max_base_candidates",
        network_aware_config.get("max_fifo_candidates", 20)
    )
    max_topology_candidates_per_pred = network_aware_config.get("max_topology_candidates_per_pred", 20)
    max_total_candidates = network_aware_config.get("max_total_candidates", 100)

    livres = listar_servidores_livres(state)

    if not livres:
        return None

    base_order = ordenar_servidores(livres)

    job_id, task_id = task

    base_preferred_server = escolher_servidor_base(
        policy=base_scheduler_policy,
        task=task,
        servidores_livres=livres,
        state=state,
        topology=topology,
    )

    candidatos = selecionar_candidatos_network_aware(
        job_id=job_id,
        task_id=task_id,
        livres=livres,
        base_order=base_order,
        state=state,
        topology=topology,
        base_preferred_server=base_preferred_server,
        max_base_candidates=max_base_candidates,
        max_topology_candidates_per_pred=max_topology_candidates_per_pred,
        max_total_candidates=max_total_candidates
    )

    if not candidatos:
        return base_order[0]

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
        fifo_order=base_order,
        traffic_metrics=traffic_metrics,
        metric_weights=metric_weights,
        network_weight=network_weight,
        task_history=task_history,
        topology=topology,
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
            "cross_server": 0.1,   # agora todos fazem sentido em [0,1]
            "cross_rack":   0.2,
            "cross_group":  0.5,
            "comm_cost":    0.2,
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
