import networkx as nx
import json
import os
from itertools import combinations
from collections import defaultdict
from typing import Dict, List, Tuple


def parse_rack_data_with_coords(markdown_content: str) -> Tuple[Dict[int, List[int]], Dict[int, Tuple[int, int]]]:
    rack_to_nodes = {}
    rack_to_coords = {}
    lines = markdown_content.strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('|Rack'):
            continue

        parts = [p.strip() for p in line.split('|') if p.strip()]

        if len(parts) >= 4:
            try:
                rack_id = int(parts[0])
                x = int(parts[1])
                y = int(parts[2])
                node_ids_str = parts[3]
                nodes = [int(node_id.strip()) for node_id in node_ids_str.split(',') if node_id.strip()]

                if nodes:
                    rack_to_nodes[rack_id] = nodes
                    rack_to_coords[rack_id] = (x, y)
            except (ValueError, IndexError):
                continue

    return rack_to_nodes, rack_to_coords


def build_dragonfly_topology(rack_info: dict, rack_coords: dict = None) -> nx.Graph:
    """
    Dragonfly topology:
    - Each rack has one router node
    - Compute nodes connect only to their rack's router (local edges)
    - Routers in same group (same Y coordinate) form full mesh (intra-group edges)
    - Routers in different groups have global links to ALL other groups (inter-group edges)
    """
    G = nx.Graph()

    # Create all compute nodes 
    for rack_id, nodes in rack_info.items():
        for node_id in nodes:
            G.add_node(node_id, type='compute', rack_id=rack_id)

    # Step 2: Determine groups 
    if rack_coords is not None:
        y_to_racks = defaultdict(list)
        for rack_id, (x, y) in rack_coords.items():
            y_to_racks[y].append(rack_id)

        # Sort groups by Y coordinate, sort racks within each group by rack_id
        sorted_y_values = sorted(y_to_racks.keys())
        groups = []
        y_to_group_id = {}
        for group_id, y_val in enumerate(sorted_y_values):
            sorted_racks = sorted(y_to_racks[y_val])
            groups.append(sorted_racks)
            y_to_group_id[y_val] = group_id
    else:
        print('NO COORDINATES')

    # Step 3: Create router nodes 
    for rack_id in rack_info.keys():
        router_id = f"R{rack_id}"

        # Determine group_id
        if rack_coords:
            x, y = rack_coords.get(rack_id, (0, 0))
            group_id = y_to_group_id.get(y, 0)
        else:
            group_id = 0
            for gid, group_racks in enumerate(groups):
                if rack_id in group_racks:
                    group_id = gid
                    break

        G.add_node(
            router_id,
            type='router',
            rack_id=rack_id,
            group_id=group_id,
            x=rack_coords.get(rack_id, (0, 0))[0] if rack_coords else 0,
            y=rack_coords.get(rack_id, (0, 0))[1] if rack_coords else 0
        )

    # Set group attribute on compute nodes based on their router's group_id
    for rack_id, nodes in rack_info.items():
        router_id = f"R{rack_id}"
        router_group_id = G.nodes[router_id]['group_id']
        for node_id in nodes:
            G.nodes[node_id]['group'] = router_group_id

    # Connect compute nodes to their rack's router (local edges)
    for rack_id, nodes in rack_info.items():
        router_id = f"R{rack_id}"
        for node_id in nodes:
            G.add_edge(node_id, router_id, type='local')

    # Create intra-group edges (full mesh within each group)
    for group_racks in groups:
        router_ids = [f"R{rack_id}" for rack_id in group_racks]
        for r1, r2 in combinations(router_ids, 2):
            G.add_edge(r1, r2, type='intra_group')

    # Create inter-group edges (global links to ALL other groups)
    # Each router connects to one router in EACH other group
    num_groups = len(groups)
    
    for g, group_racks in enumerate(groups):
        for i, rack_id in enumerate(group_racks):
            router1 = f"R{rack_id}"
            
            # Connect to ALL other groups, not just the next one
            for other_g in range(num_groups):
                if other_g == g:
                    continue  # Skip own group
                
                other_group_racks = groups[other_g]
                # Deterministic mapping: router i in group g connects to router i % len(other_group) in other_g
                target_i = i % len(other_group_racks)
                target_rack_id = other_group_racks[target_i]
                router2 = f"R{target_rack_id}"
                
                if not G.has_edge(router1, router2):
                    G.add_edge(router1, router2, type='inter_group')

    return G


def export_dot(G, output_path='graphs/dragonfly_topology.dot'):
    """Export graph to DOT format for Graphviz visualization."""
    try:
        from networkx.drawing.nx_pydot import write_dot
        write_dot(G, output_path)
        print(f"Exported DOT to {output_path}")
    except ImportError:
        with open(output_path, 'w') as f:
            f.write("graph DragonFlyTopology {\n")
            f.write("  // Node definitions\n")
            
            for node, attrs in G.nodes(data=True):
                node_type = attrs.get('type', 'unknown')
                group_id = attrs.get('group_id', attrs.get('group', 'N/A'))
                rack_id = attrs.get('rack_id', 'N/A')
                
                if node_type == 'router':
                    f.write(f'  "{node}" [shape=box, color=blue, label="{node}\\nGroup:{group_id}"];\n')
                else:
                    f.write(f'  "{node}" [shape=circle, color=gray, label="{node}"];\n')
            
            f.write("\n  // Edge definitions\n")
            for u, v, attrs in G.edges(data=True):
                edge_type = attrs.get('type', 'unknown')
                if edge_type == 'intra_group':
                    f.write(f'  "{u}" -- "{v}" [color=blue, penwidth=2];\n')
                elif edge_type == 'inter_group':
                    f.write(f'  "{u}" -- "{v}" [color=red, style=dashed];\n')
                else:
                    f.write(f'  "{u}" -- "{v}" [color=gray];\n')
            
            f.write("}\n")
        print(f"Exported DOT to {output_path}")


def export_dot_routers_only(G, output_path='graphs/dragonfly_routers.dot'):
    """Export only router subgraph to DOT format."""
    router_nodes = [n for n, attr in G.nodes(data=True) if attr.get('type') == 'router']
    
    with open(output_path, 'w') as f:
        f.write("graph DragonFlyRouters {\n")
        f.write("  // Graph settings\n")
        f.write("  overlap=false;\n")
        f.write("  splines=true;\n")
        f.write("\n  // Node definitions\n")
        
        for node in router_nodes:
            attrs = G.nodes[node]
            group_id = attrs.get('group_id', 0)
            rack_id = attrs.get('rack_id', 'N/A')
            
            # Different colors for different groups
            colors = ['blue', 'green', 'red', 'purple', 'orange']
            color = colors[group_id % len(colors)]
            
            f.write(f'  "{node}" [shape=box, style=filled, fillcolor={color}, ')
            f.write(f'label="{node}\\nG{group_id}"];\n')
        
        f.write("\n  // Edge definitions\n")
        for u, v, attrs in G.edges(data=True):
            # Only router-to-router edges
            if G.nodes[u].get('type') != 'router' or G.nodes[v].get('type') != 'router':
                continue
                
            edge_type = attrs.get('type', 'unknown')
            if edge_type == 'intra_group':
                f.write(f'  "{u}" -- "{v}" [color=blue, penwidth=2];\n')
            elif edge_type == 'inter_group':
                f.write(f'  "{u}" -- "{v}" [color=red, style=dashed, penwidth=1];\n')
        
        f.write("}\n")
    print(f"Exported routers-only DOT to {output_path}")


def exportar_topologia_dot(
    topology_file: str,
    output_dir: str = "graphs"
) -> dict:
    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(topology_file):
        raise FileNotFoundError(f"Arquivo de topologia não encontrado: {topology_file}")

    print(f"Loading topology from '{topology_file}'...")

    with open(topology_file, "r", encoding="utf-8") as f:
        markdown_content = f.read()

    rack_map, coord_map = parse_rack_data_with_coords(markdown_content)

    print(f"Parsed {len(rack_map)} racks")
    print("Building Dragonfly topology...")

    G = build_dragonfly_topology(rack_map, coord_map)

    router_nodes = [
        n for n, attr in G.nodes(data=True)
        if attr.get("type") == "router"
    ]

    compute_nodes = [
        n for n, attr in G.nodes(data=True)
        if attr.get("type") == "compute"
    ]

    print(f"\nGraph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print(f"  Routers: {len(router_nodes)}, Compute: {len(compute_nodes)}")

    full_dot_path = os.path.join(output_dir, "dragonfly_topology.dot")
    routers_dot_path = os.path.join(output_dir, "dragonfly_routers.dot")

    export_dot(G, full_dot_path)
    export_dot_routers_only(G, routers_dot_path)

    return {
        "graph": G,
        "full_dot": full_dot_path,
        "routers_dot": routers_dot_path,
        "routers": len(router_nodes),
        "compute_nodes": len(compute_nodes),
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
    }


def main():
    exportar_topologia_dot(
        topology_file="racks_spatial_distribution.md",
        output_dir="graphs"
    )


if __name__ == "__main__":
    main()