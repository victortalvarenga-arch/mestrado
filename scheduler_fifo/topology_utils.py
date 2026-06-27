from imports import nx

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
