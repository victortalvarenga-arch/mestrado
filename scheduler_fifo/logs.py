from imports import os, json, datetime, Path
from serialization import tornar_json_serializavel
from execution_metrics import calcular_makespan_state


def gerar_nome_arquivo_execucao(prefixo: str = "execution_trace") -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{prefixo}_{timestamp}.json"


def salvar_json_execucao(
    state: dict,
    output_path: str,
    policy: str = "easy",
    network_weight: float = 1.0
) -> None:
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    historico_network = state.get("historico_network", {})
    topology_summary = state.get("topology_summary", {})
    workload_summary = state.get("workload_summary", {})
    network_aware_config = state.get("network_aware_config")

    metadata = {
        "policy": policy,
        "scheduler_policy": state.get("scheduler_policy", policy),
        "base_scheduler_policy": state.get("base_scheduler_policy"),
        "network_weight": (
            network_aware_config.get("network_weight")
            if network_aware_config
            else network_weight
        ),
        "external_recommender_enabled": False,
        "historical_network_enabled": historico_network.get("enabled", False),
        "historical_network_mode": historico_network.get("mode"),
        "historical_network_source_file": historico_network.get("source_file"),
        "generated_at": datetime.now().isoformat(),
        "total_loops": len(state["loop_snapshots"]),
        "final_time": state["time"],

        "jobs_count": workload_summary.get("jobs_count"),
        "tasks_count": workload_summary.get("tasks_count"),
        "topology_total_nodes": topology_summary.get("total_nodes"),
        "topology_compute_nodes": topology_summary.get("compute_nodes_count"),
        "topology_router_nodes": topology_summary.get("router_nodes_count"),

        "network_aware_parameters": (
            network_aware_config
            if policy == "network_aware"
            else None
        ),
    }

    payload = {
        "metadata": metadata,
        "topology_summary": topology_summary,
        "workload_summary": workload_summary,
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


def buscar_ultimo_log_execucao(output_dir: str) -> str | None:
    output_path = Path(output_dir)

    if not output_path.exists():
        return None

    logs = list(output_path.glob("*_execution_trace_*.json"))

    if not logs:
        return None

    ultimo = max(logs, key=lambda p: p.stat().st_mtime)
    return str(ultimo)
