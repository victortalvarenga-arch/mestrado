from imports import nx, ler_jobs_data, agrupar_por_job, construir_grafos, parse_rack_data_with_coords, build_dragonfly_topology

def carregar_jobs(file_path: str) -> dict[int, nx.DiGraph]:
    dados = ler_jobs_data(file_path)
    jobs_dict = agrupar_por_job(dados)
    grafos = construir_grafos(jobs_dict)
    return grafos

def carregar_topologia(file_path: str) -> nx.Graph:
    with open(file_path, "r", encoding="utf-8") as f:
        markdown_content = f.read()

    rack_map, coord_map = parse_rack_data_with_coords(markdown_content)
    G = build_dragonfly_topology(rack_map, coord_map)
    return G
