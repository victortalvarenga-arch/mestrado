from imports import os, json, datetime, plt
from serialization import tornar_json_serializavel
from execution_metrics import calcular_makespan_json


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
    output_dir: str,
    artifact_prefix: str | None = None
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

        prefixo_sem_comparacao = sanitizar_nome_arquivo(
            artifact_prefix or f"comparison_no_previous_execution_{timestamp}"
        )

        caminho_json = os.path.join(
            output_dir,
            f"{prefixo_sem_comparacao}_no_previous_execution.json"
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

    base_policy_for_name = current_summary.get("network_aware_parameters", {}).get(
        "base_scheduler_policy",
        previous_policy
    )

    prefixo = sanitizar_nome_arquivo(
        artifact_prefix or f"{base_policy_for_name}_{scenario_name}"
    )

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

    for chave, label in metricas:
        improvement_percent = deltas.get(chave, {}).get("improvement_percent")

        if improvement_percent is not None:
            labels.append(label)
            valores.append(improvement_percent)

    if not labels:
        return

    plt.figure(figsize=(12, 6))
    plt.bar(labels, valores, width=0.55)
    plt.axhline(0, color="black", linewidth=0.8)
    plt.ylabel("Melhoria (%)", fontsize=13)
    plt.xticks(rotation=30, ha="right", fontsize=11)
    plt.yticks(fontsize=11)
    plt.grid(axis="y", linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()

    print(f"Gráfico de comparação salvo em: {os.path.abspath(output_path)}")


def salvar_grafico_consolidado_heuristica(
    comparison_paths_by_scenario: dict,
    output_path: str,
) -> None:
    """
    Gera 1 gráfico consolidado por heurística/cenário (normal ou stress),
    mantendo todas as métricas no eixo X e colocando 4 barras por métrica:
    - Balanced
    - Rack Strict
    - Group Strict
    - Comm Cost Strict
    """

    scenario_order = [
        "01_balanced",
        "02_rack_strict",
        "03_group_strict",
        "04_comm_cost_strict",
    ]

    scenario_labels = {
        "01_balanced": "Balanced",
        "02_rack_strict": "Rack Strict",
        "03_group_strict": "Group Strict",
        "04_comm_cost_strict": "Comm Cost Strict",
    }

    scenario_colors = {
        "01_balanced": "#4C78A8",
        "02_rack_strict": "#F58518",
        "03_group_strict": "#54A24B",
        "04_comm_cost_strict": "#E45756",
    }

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

    scenario_values = {}

    for scenario_name in scenario_order:
        comparison_json_path = comparison_paths_by_scenario.get(scenario_name)

        if comparison_json_path is None or not os.path.exists(comparison_json_path):
            raise FileNotFoundError(
                f"Arquivo de comparação não encontrado para o cenário '{scenario_name}'."
            )

        with open(comparison_json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        deltas = payload.get("deltas", {})

        valores_metricas = []
        for metric_key, _ in metricas:
            improvement_percent = deltas.get(metric_key, {}).get("improvement_percent")
            if improvement_percent is None:
                improvement_percent = 0.0
            valores_metricas.append(improvement_percent)

        scenario_values[scenario_name] = valores_metricas

    fig, ax = plt.subplots(figsize=(16, 7))

    base_positions = list(range(len(metricas)))
    bar_width = 0.18
    offsets = [-1.5 * bar_width, -0.5 * bar_width, 0.5 * bar_width, 1.5 * bar_width]

    for idx, scenario_name in enumerate(scenario_order):
        positions = [x + offsets[idx] for x in base_positions]
        values = scenario_values[scenario_name]

        ax.bar(
            positions,
            values,
            width=bar_width,
            color=scenario_colors[scenario_name],
            label=scenario_labels[scenario_name],
            edgecolor="black",
            linewidth=0.5,
        )

    ax.axhline(0, color="black", linewidth=0.8)

    ax.set_ylabel("Melhoria (%)", fontsize=16)
    ax.set_xticks(base_positions)
    ax.set_xticklabels(
        [label for _, label in metricas],
        rotation=25,
        ha="right",
        fontsize=13,
    )
    ax.tick_params(axis="y", labelsize=13)

    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.legend(fontsize=12, ncol=2, frameon=False)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Gráfico consolidado salvo em: {os.path.abspath(output_path)}")


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