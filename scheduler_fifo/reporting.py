from imports import nx
from execution_metrics import calcular_makespan_state

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

def imprimir_resumo_final(state: dict) -> None:
    print("\n=== RESUMO FINAL ===")
    print(f"Makespan: {calcular_makespan_state(state):.0f}")
    print(f"Tasks finalizadas: {len(state['finished_tasks'])}")
    print(f"Snapshots salvos: {len(state['loop_snapshots'])}")
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
