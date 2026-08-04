from imports import nx
from scheduler_utils import listar_servidores_livres, ordenar_servidores
from scheduler_dispatcher import escolher_servidor_base
from serialization import task_key
from network_metrics import calcular_metricas_trafego_tarefa_compacta

# λ da Equação 1 do artigo:
#     Score(t, s) = λ * Score_base(s) + (1 - λ) * (Score_net(t, s) + B_hist(t, s))
#
# λ controla o peso relativo entre a preferência da política base e a camada
# consciente da rede:
#   λ = 1,0 → decisão inteiramente da política base (equivale ao baseline);
#   λ = 0,0 → decisão inteiramente network-aware (custo de rede + histórico).
LAMBDA_BASE_PADRAO = 0.5

# Como Score_base(s) é normalizado antes de entrar na Equação 1.
# "candidates" mantém Score_base e Score_net na mesma escala [0,1], condição
# para que λ pondere grandezas comparáveis. Ver normalizar_score_base().
MODO_SCORE_BASE_PADRAO = "candidates"


def normalizar_lambda_base(valor) -> float:
    """Restringe λ ao intervalo [0, 1], com fallback para o valor padrão."""
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return LAMBDA_BASE_PADRAO

    return min(1.0, max(0.0, valor))


def resolver_lambda_base(network_aware_config: dict | None) -> float:
    """
    Obtém o λ da Equação 1 a partir da configuração do cenário.

    Execuções anteriores parametrizavam a decisão por um peso de rede w, na forma
    Score = Score_base + w * (Score_net + B_hist). Essa expressão é proporcional a
    λ * Score_base + (1 - λ) * (Score_net + B_hist) com λ = 1 / (1 + w), de modo que
    a conversão preserva exatamente a mesma ordenação de candidatos: w = 1,0 ⇔
    λ = 0,5 e w = 0,0 ⇔ λ = 1,0 (baseline).
    """
    if not network_aware_config:
        return LAMBDA_BASE_PADRAO

    if network_aware_config.get("lambda_base") is not None:
        return normalizar_lambda_base(network_aware_config["lambda_base"])

    network_weight = network_aware_config.get("network_weight")
    if network_weight is not None:
        try:
            return normalizar_lambda_base(1.0 / (1.0 + float(network_weight)))
        except (TypeError, ValueError, ZeroDivisionError):
            return LAMBDA_BASE_PADRAO

    return LAMBDA_BASE_PADRAO


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

    lambda_base = resolver_lambda_base(network_aware_config)
    base_score_mode = network_aware_config.get("base_score_mode", MODO_SCORE_BASE_PADRAO)
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

    # λ = 1,0 anula a camada consciente da rede: a decisão é integralmente da
    # política base, o que reproduz o baseline sem custo de avaliação de candidatos.
    if lambda_base >= 1.0:
        return base_preferred_server

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
        base_order=base_order,
        traffic_metrics=traffic_metrics,
        metric_weights=metric_weights,
        lambda_base=lambda_base,
        base_score_mode=base_score_mode,
        task_history=task_history,
        topology=topology,
    )

    return servidor

def choose_server_network_aware(
    task,
    free_servers,
    base_order,
    traffic_metrics,
    metric_weights=None,
    lambda_base: float | None = None,
    network_weight: float | None = None,
    base_score_mode: str = MODO_SCORE_BASE_PADRAO,
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

    if lambda_base is None:
        lambda_base = resolver_lambda_base(
            {"network_weight": network_weight} if network_weight is not None else None
        )
    else:
        lambda_base = normalizar_lambda_base(lambda_base)

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
    base_pos = {server: idx for idx, server in enumerate(base_order)}
    base_scores = normalizar_score_base(free_servers, base_pos, len(base_order), base_score_mode)

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

        # Score da política base: posição do servidor na ordenação preferida
        # pela heurística base, normalizada → já em [0,1]
        base_score = base_scores.get(server, 1.0)

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

        # Equação 1 do artigo, com todos os componentes em escala comparável:
        #   base_score    ∈ [0, 1]
        #   network_score ∈ [0, 1]
        #   history_bonus ∈ [-0.30, +0.25]
        # λ (lambda_base) rege quanta importância a política base mantém frente
        # à camada consciente da rede.
        combined_score = (
            lambda_base * base_score
            + (1.0 - lambda_base) * (network_score + history_bonus)
        )

        if combined_score < best_score:
            best_score = combined_score
            best_server = server

    return best_server

def normalizar_score_base(free_servers, base_pos: dict, total_servidores: int,
                          base_score_mode: str = MODO_SCORE_BASE_PADRAO) -> dict:
    """
    Calcula Score_base(s) para cada candidato, em [0,1].

    - "global": posição do servidor na ordenação da política base dividida pelo
      número de servidores livres. Em clusters pouco carregados o denominador é
      grande, então todos os candidatos ficam comprimidos perto de 0 e o termo
      da política base perde influência frente ao custo de rede.
    - "candidates": normalização min-max da posição entre os próprios candidatos
      da decisão, a mesma convenção usada em Score_net. Os dois termos da
      Equação 1 passam a ocupar toda a faixa [0,1], de modo que λ pondera
      grandezas comparáveis independentemente da carga do cluster.
    """
    indices = {
        server: base_pos.get(server, total_servidores)
        for server in free_servers
    }

    if base_score_mode == "candidates":
        valores = list(indices.values())
        minimo = min(valores)
        maximo = max(valores)

        if maximo == minimo:
            return {server: 0.0 for server in indices}

        return {
            server: (indice - minimo) / (maximo - minimo)
            for server, indice in indices.items()
        }

    denominador = max(1, total_servidores)
    return {
        server: indice / denominador
        for server, indice in indices.items()
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
