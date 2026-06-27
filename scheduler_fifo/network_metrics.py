from imports import nx
from serialization import task_key

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
