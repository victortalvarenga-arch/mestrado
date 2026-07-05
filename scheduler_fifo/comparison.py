from imports import os, json, datetime, plt, math
from serialization import tornar_json_serializavel
from execution_metrics import calcular_makespan_json
from network_metrics import extrair_eventos_trafego_por_tarefa
from statistical_tests import analisar_significancia_estatistica, salvar_significancia_markdown


def sanitizar_nome_arquivo(valor: str) -> str:
    """Normaliza um texto para uso seguro em nomes de arquivos."""
    permitido = []
    for caractere in str(valor).lower():
        if caractere.isalnum():
            permitido.append(caractere)
        elif caractere in {"_", "-"}:
            permitido.append(caractere)
        elif caractere.isspace():
            permitido.append("_")

    nome = "".join(permitido).strip("_")

    while "__" in nome:
        nome = nome.replace("__", "_")

    return nome or "comparison"

def extrair_resumo_execucao_json(data: dict) -> dict:
    metadata = data.get("metadata", {})
    topology_summary = data.get("topology_summary", {})
    workload_summary = data.get("workload_summary", {})
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
        "network_weight": metadata.get("network_weight"),
        "network_aware_parameters": metadata.get("network_aware_parameters"),

        "generated_at": metadata.get("generated_at"),
        "makespan": calcular_makespan_json(data),
        "total_loops": metadata.get("total_loops", len(snapshots)),
        "final_time": metadata.get("final_time", final_snapshot.get("time")),

        "jobs_count": metadata.get("jobs_count", workload_summary.get("jobs_count")),
        "tasks_count": metadata.get("tasks_count", workload_summary.get("tasks_count")),
        "topology_total_nodes": metadata.get("topology_total_nodes", topology_summary.get("total_nodes")),
        "topology_compute_nodes": metadata.get("topology_compute_nodes", topology_summary.get("compute_nodes_count")),
        "topology_router_nodes": metadata.get("topology_router_nodes", topology_summary.get("router_nodes_count")),

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

def calcular_distribuicao_ganho_percentual_tarefa(
    previous_events: dict,
    current_events: dict,
    metric_key: str,
    lower_is_better: bool = True
) -> dict | None:
    """
    Calcula, tarefa a tarefa, o ganho percentual de uma métrica entre a execução
    anterior (baseline) e a atual, dentro da própria execução (sem repetir simulações).

    O desvio-padrão é ponderado pela magnitude da métrica no baseline: uma tarefa
    que já tinha pouquíssimo custo/hops pode "melhorar" 100% trivialmente, então
    seu ganho percentual pesa menos do que o de uma tarefa que concentrava mais
    custo de comunicação.
    """
    pares_peso_ganho = []

    for chave, evento_atual in current_events.items():
        evento_anterior = previous_events.get(chave)

        if evento_anterior is None:
            continue

        if metric_key == "avg_hops_per_flow":
            if evento_anterior["flow_count"] == 0 or evento_atual["flow_count"] == 0:
                continue
            valor_anterior = evento_anterior["total_hops"] / evento_anterior["flow_count"]
            valor_atual = evento_atual["total_hops"] / evento_atual["flow_count"]
        else:
            valor_anterior = evento_anterior.get(metric_key, 0)
            valor_atual = evento_atual.get(metric_key, 0)

        if valor_anterior == 0:
            continue

        delta_percentual = ((valor_atual - valor_anterior) / valor_anterior) * 100
        ganho_percentual = -delta_percentual if lower_is_better else delta_percentual
        pares_peso_ganho.append((valor_anterior, ganho_percentual))

    if not pares_peso_ganho:
        return None

    peso_total = sum(peso for peso, _ in pares_peso_ganho)

    if peso_total == 0:
        return None

    media_ponderada = sum(peso * ganho for peso, ganho in pares_peso_ganho) / peso_total
    variancia_ponderada = sum(
        peso * (ganho - media_ponderada) ** 2 for peso, ganho in pares_peso_ganho
    ) / peso_total

    return {
        "mean_weighted": media_ponderada,
        "std_weighted": math.sqrt(variancia_ponderada),
        "n": len(pares_peso_ganho),
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
        "makespan",
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
        "makespan",
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
        "makespan": "Makespan",
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

    linhas.append("## Caracterização dos cenários")
    linhas.append("")
    linhas.append("| Campo | Execução anterior | Execução atual |")
    linhas.append("|---|---:|---:|")
    linhas.append(f"| Jobs | {formatar_valor_comparacao(previous_summary.get('jobs_count'))} | {formatar_valor_comparacao(current_summary.get('jobs_count'))} |")
    linhas.append(f"| Tasks | {formatar_valor_comparacao(previous_summary.get('tasks_count'))} | {formatar_valor_comparacao(current_summary.get('tasks_count'))} |")
    linhas.append(f"| Nós totais da topologia | {formatar_valor_comparacao(previous_summary.get('topology_total_nodes'))} | {formatar_valor_comparacao(current_summary.get('topology_total_nodes'))} |")
    linhas.append(f"| Nós compute | {formatar_valor_comparacao(previous_summary.get('topology_compute_nodes'))} | {formatar_valor_comparacao(current_summary.get('topology_compute_nodes'))} |")
    linhas.append(f"| Roteadores | {formatar_valor_comparacao(previous_summary.get('topology_router_nodes'))} | {formatar_valor_comparacao(current_summary.get('topology_router_nodes'))} |")
    linhas.append("")

    linhas.append("## Parâmetros network-aware")
    linhas.append("")

    current_network_params = current_summary.get("network_aware_parameters")

    if current_network_params:
        linhas.append("| Parâmetro | Valor |")
        linhas.append("|---|---:|")
        for chave, valor in current_network_params.items():
            linhas.append(f"| `{chave}` | `{formatar_valor_comparacao(valor)}` |")
    else:
        linhas.append("A execução atual não utilizou a política `network_aware`.")

    linhas.append("")
    linhas.append("## Métricas comparativas")
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
        "Para métricas de custo, makespan, hops e tráfego, melhoria positiva significa que a execução atual reduziu o valor em relação à anterior."
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))

    print(f"Resumo Markdown salvo em: {os.path.abspath(output_path)}")


def salvar_grafico_comparacao(payload: dict, output_path: str) -> None:
    deltas = payload.get("deltas", {})

    metricas = [
        ("makespan", "Makespan"),
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
    desvios_padrao = []
    possui_distribuicao = False

    for chave, label in metricas:
        metric_delta = deltas.get(chave, {})
        improvement_percent = metric_delta.get("improvement_percent")

        if improvement_percent is None:
            continue

        labels.append(label)
        valores.append(improvement_percent)

        distribuicao = metric_delta.get("distribution")
        if distribuicao is not None:
            desvios_padrao.append(distribuicao["std_weighted"])
            possui_distribuicao = True
        else:
            desvios_padrao.append(0)

    if not labels:
        return

    posicoes = list(range(len(labels)))

    plt.figure(figsize=(12, 6))
    plt.bar(posicoes, valores, width=0.55)

    if possui_distribuicao:
        plt.errorbar(
            posicoes, valores, yerr=desvios_padrao,
            fmt="none", ecolor="black", elinewidth=2.2, capsize=5,
            label="Desvio padrão (ponderado por tarefa)"
        )
        plt.legend(fontsize=10, loc="best")

    plt.axhline(0, color="black", linewidth=0.8)
    plt.ylabel("Melhoria (%)", fontsize=13)
    plt.xticks(posicoes, labels, rotation=30, ha="right", fontsize=11)
    plt.yticks(fontsize=11)
    plt.grid(axis="y", linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()

    print(f"Gráfico de comparação salvo em: {os.path.abspath(output_path)}")


SCENARIO_ORDER = ["01_balanced", "02_rack_strict", "03_group_strict", "04_comm_cost_strict"]
SCENARIO_LABELS = {
    "01_balanced": "Balanced",
    "02_rack_strict": "Rack Strict",
    "03_group_strict": "Group Strict",
    "04_comm_cost_strict": "Comm Cost Strict",
}


def salvar_grafico_consolidado_heuristica(comparison_paths_by_scenario: dict, output_path: str) -> None:
    """
    Gera um gráfico consolidado por heurística/cenário, mantendo todas as métricas
    no eixo X e barras coloridas para cada configuração.
    Ajusta o fontsize e rotaciona as labels do eixo X para melhor visualização.
    Eixo Y é fixo em 0-100 para consistência entre todas as heurísticas.
    """
    scenario_order = SCENARIO_ORDER
    scenario_labels = SCENARIO_LABELS
    scenario_colors = {
        "01_balanced": "#B3CDE3",
        "02_rack_strict": "#6497B1",
        "03_group_strict": "#005B96",
        "04_comm_cost_strict": "#03396C"
    }

    metricas = [
        # ("makespan", "Makespan"),
        ("estimated_comm_cost", "Custo comunicação"),
        ("total_hops", "Hops"),
        # ("flow_count", "Fluxos"),
        ("cross_server_flows", "Cross-server"),
        ("cross_rack_flows", "Cross-rack"),
        ("cross_group_flows", "Cross-group"),
        ("avg_hops_per_flow", "Hops/fluxo"),
    ]

    scenario_values = {}
    scenario_distributions = {}

    for scenario_name in scenario_order:
        comparison_json_path = comparison_paths_by_scenario.get(scenario_name)
        if comparison_json_path is None or not os.path.exists(comparison_json_path):
            # preenche com zeros se não houver arquivo
            scenario_values[scenario_name] = [0.0]*len(metricas)
            scenario_distributions[scenario_name] = [None]*len(metricas)
            continue
        with open(comparison_json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        deltas = payload.get("deltas", {})
        valores_metricas = []
        distribuicoes_metricas = []
        for metric_key, _ in metricas:
            metric_delta = deltas.get(metric_key, {})
            value = metric_delta.get("improvement_percent")
            if value is None:
                value = 0.0
            valores_metricas.append(float(value))
            distribuicoes_metricas.append(metric_delta.get("distribution"))
        scenario_values[scenario_name] = valores_metricas
        scenario_distributions[scenario_name] = distribuicoes_metricas

    fig, ax = plt.subplots(figsize=(16,7.5))
    base_positions = list(range(len(metricas)))
    bar_width = 0.18
    offsets = [-1.5*bar_width, -0.5*bar_width, 0.5*bar_width, 1.5*bar_width]
    legenda_erro_adicionada = False

    for idx, scenario_name in enumerate(scenario_order):
        positions = [x + offsets[idx] for x in base_positions]
        values = scenario_values[scenario_name]
        distribuicoes = scenario_distributions[scenario_name]
        ax.bar(
            positions,
            values,
            width=bar_width,
            color=scenario_colors[scenario_name],
            label=scenario_labels[scenario_name],
            edgecolor="black",
            linewidth=0.5
        )

        desvios_padrao = []
        possui_distribuicao = False

        for distribuicao in distribuicoes:
            if distribuicao is not None:
                desvios_padrao.append(distribuicao["std_weighted"])
                possui_distribuicao = True
            else:
                desvios_padrao.append(0)

        if possui_distribuicao:
            ax.errorbar(
                positions, values, yerr=desvios_padrao,
                fmt="none", ecolor="black", elinewidth=1.5, capsize=4, zorder=6,
                label=None if legenda_erro_adicionada else "Desvio padrão (ponderado por tarefa)"
            )
            legenda_erro_adicionada = True

    ax.axhline(0, color="black", linewidth=0.8)
    # Força eixo Y fixo para todos
    ax.set_ylim(0,100)

    # Configura fontes globais
    plt.rcParams.update({
        "font.size": 18,
        "axes.titlesize": 22,
        "axes.labelsize": 20,
        "ytick.labelsize": 18,
        "legend.fontsize": 22
    })

    # Ajusta fontsize do eixo X e rotaciona
    num_labels = len(metricas)
    fig_width = 16
    fontsize_x = 20  # fixo maior como pediu
    ax.set_xticks(base_positions)
    ax.set_xticklabels([label for _, label in metricas], rotation=20, ha="right", fontsize=fontsize_x)

    ax.set_ylabel("Melhoria (%)", fontsize=22)
    ax.tick_params(axis="y", labelsize=22)
    ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.legend(ncol=5, frameon=False, loc="upper center", bbox_to_anchor=(0.5,1.18), fontsize=20)

    plt.tight_layout(rect=[0,0,1,0.90])
    plt.savefig(output_path, dpi=300, bbox_inches="tight")


def salvar_json_comparacao_execucoes(
    previous_execution_path: str | None,
    current_execution_path: str,
    output_dir: str,
    artifact_prefix: str | None = None,
) -> dict:
    os.makedirs(output_dir, exist_ok=True)

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

        prefixo = artifact_prefix or f"comparison_no_previous_execution_{timestamp}"

        caminho_json = os.path.join(
            output_dir,
            f"{prefixo}.json"
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

    previous_events = extrair_eventos_trafego_por_tarefa(previous_data)
    current_events = extrair_eventos_trafego_por_tarefa(current_data)

    metricas_com_distribuicao = [
        "estimated_comm_cost",
        "total_hops",
        "cross_server_flows",
        "cross_rack_flows",
        "cross_group_flows",
        "avg_hops_per_flow",
    ]

    for metrica in metricas_com_distribuicao:
        distribuicao = calcular_distribuicao_ganho_percentual_tarefa(
            previous_events=previous_events,
            current_events=current_events,
            metric_key=metrica,
            lower_is_better=True,
        )
        if distribuicao is not None:
            deltas[metrica]["distribution"] = distribuicao

    try:
        resultado_estatistico = analisar_significancia_estatistica(
            previous_execution_path=previous_execution_path,
            current_execution_path=current_execution_path,
        )
    except Exception as erro:
        print(f"Aviso: falha ao calcular significância estatística: {erro}")
        resultado_estatistico = None

    previous_policy = previous_summary.get("policy", "unknown")
    current_policy = current_summary.get("policy", "unknown")

    scenario_name = current_summary.get("network_aware_parameters", {}).get(
        "scenario_name",
        current_policy
    )

    payload = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "comparison_available": True,
            "scenario_name": scenario_name,
            "previous_execution_path": previous_execution_path,
            "current_execution_path": current_execution_path,
            "previous_policy": previous_policy,
            "current_policy": current_policy,
        },
        "previous_summary": previous_summary,
        "current_summary": current_summary,
        "deltas": deltas,
        "statistical_significance": resultado_estatistico,
        "interpretation": {
            "lower_is_better_metrics": [
                "makespan",
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

    prefixo = artifact_prefix or f"{scenario_name}_vs_fifo"

    caminho_json = os.path.join(
        output_dir,
        f"{prefixo}_comparison.json"
    )

    caminho_grafico = os.path.join(
        output_dir,
        f"{prefixo}_chart.png"
    )

    caminho_markdown = os.path.join(
        output_dir,
        f"{prefixo}_summary.md"
    )

    caminho_significancia = os.path.join(
        output_dir,
        f"{prefixo}_statistical_significance.md"
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

    if resultado_estatistico is not None:
        try:
            salvar_significancia_markdown(resultado_estatistico, caminho_significancia)
        except Exception as erro:
            print(f"Aviso: falha ao salvar relatório de significância estatística: {erro}")
            caminho_significancia = None
    else:
        caminho_significancia = None

    return {
        "comparison_json": caminho_json,
        "comparison_chart": caminho_grafico,
        "comparison_summary": caminho_markdown,
        "statistical_significance_summary": caminho_significancia,
    }