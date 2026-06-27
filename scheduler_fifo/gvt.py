import ast
import os
from collections import defaultdict

import matplotlib.pyplot as plt
import networkx as nx


def ler_jobs_data(file_path: str) -> list[dict]:
    dados = []

    with open(file_path, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()

            if not linha:
                continue

            parte_fixa, deps_str = linha.split("[", 1)
            deps_str = "[" + deps_str
            campos = parte_fixa.strip().split()

            registro = {
                "id_job": int(campos[0]),
                "id_task": int(campos[1]),
                "resource": float(campos[2]),
                "sub_time": float(campos[3]),
                "wall_time": float(campos[4]),
                "dep_tasks": ast.literal_eval(deps_str),
            }

            dados.append(registro)

    return dados


def imprimir_amostra_registros(dados: list[dict], limite: int = 20) -> None:
    print("\n=== Amostra dos registros lidos ===")
    for r in dados[:limite]:
        print(
            f"id_job={r['id_job']}, "
            f"id_task={r['id_task']}, "
            f"resource={r['resource']}, "
            f"sub_time={r['sub_time']}, "
            f"wall_time={r['wall_time']}, "
            f"dep_tasks={r['dep_tasks']}"
        )


def resumir_dataset(dados: list[dict]) -> None:
    jobs = {r["id_job"] for r in dados}
    print("\n=== Resumo do dataset ===")
    print(f"Total de registros: {len(dados)}")
    print(f"Total de jobs: {len(jobs)}")


def agrupar_por_job(dados: list[dict]) -> dict[int, dict]:
    jobs_dict = defaultdict(lambda: {"sub_time": None, "tasks": {}})

    for r in dados:
        id_job = r["id_job"]
        id_task = r["id_task"]

        if jobs_dict[id_job]["sub_time"] is None:
            jobs_dict[id_job]["sub_time"] = r["sub_time"]

        jobs_dict[id_job]["tasks"][id_task] = {
            "resource": r["resource"],
            "wall_time": r["wall_time"],
            "dep_tasks": r["dep_tasks"],
        }

    return dict(jobs_dict)


def construir_grafo_job(id_job: int, job_data: dict) -> nx.DiGraph:
    G = nx.DiGraph()
    G.graph["id_job"] = id_job
    G.graph["sub_time"] = job_data["sub_time"]

    for id_task, task_data in job_data["tasks"].items():
        G.add_node(
            id_task,
            resource=task_data["resource"],
            wall_time=task_data["wall_time"],
        )

    for id_task, task_data in job_data["tasks"].items():
        for dep_task in task_data["dep_tasks"]:
            G.add_edge(dep_task, id_task)

    return G


def construir_grafos(jobs_dict: dict[int, dict]) -> dict[int, nx.DiGraph]:
    grafos = {}

    for id_job, job_data in jobs_dict.items():
        grafos[id_job] = construir_grafo_job(id_job, job_data)

    return grafos


def validar_grafos(grafos: dict[int, nx.DiGraph]) -> None:
    print("\n=== Validação dos grafos ===")
    total_dags = 0
    total_nao_dags = 0

    for id_job, G in grafos.items():
        if nx.is_directed_acyclic_graph(G):
            total_dags += 1
        else:
            total_nao_dags += 1
            print(f"Job {id_job} NÃO é DAG")

    print(f"Grafos válidos como DAG: {total_dags}")
    print(f"Grafos inválidos: {total_nao_dags}")


def imprimir_resumo_grafo(id_job: int, G: nx.DiGraph) -> None:
    print(f"\n=== Resumo do Job {id_job} ===")
    print(f"sub_time: {G.graph['sub_time']}")
    print(f"nós: {G.number_of_nodes()}")
    print(f"arestas: {G.number_of_edges()}")
    print(f"é DAG: {nx.is_directed_acyclic_graph(G)}")
    print("tasks:")

    for node, attrs in G.nodes(data=True):
        preds = list(G.predecessors(node))
        print(
            f"  task={node}, "
            f"resource={attrs['resource']}, "
            f"wall_time={attrs['wall_time']}, "
            f"dep_tasks={preds}"
        )


def imprimir_amostra_grafos(grafos: dict[int, nx.DiGraph], limite: int = 3) -> None:
    ids = sorted(grafos.keys())[:limite]
    for id_job in ids:
        imprimir_resumo_grafo(id_job, grafos[id_job])


def gerar_posicao_hierarquica(G: nx.DiGraph) -> dict:
    try:
        camadas = list(nx.topological_generations(G))
    except Exception:
        return nx.spring_layout(G, seed=42)

    espacamento_x = 3.0
    espacamento_y = 2.0

    pos = {}
    for x, camada in enumerate(camadas):
        altura = len(camada)
        for y, node in enumerate(camada):
            pos[node] = (
                x * espacamento_x,
                -(y - (altura - 1) / 2) * espacamento_y
            )

    return pos


def garantir_pasta_grafos() -> str:
    pasta = os.path.join(os.getcwd(), "grafos")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def salvar_grafo(G: nx.DiGraph, pasta_saida: str) -> None:
    id_job = G.graph["id_job"]
    pos = gerar_posicao_hierarquica(G)

    labels = {
        node: f"{node}\nwt={G.nodes[node]['wall_time']}\nr={G.nodes[node]['resource']}"
        for node in G.nodes()
    }

    plt.figure(figsize=(12, 7))
    nx.draw(
        G,
        pos,
        with_labels=False,
        node_size=1800,
        arrows=True,
    )
    nx.draw_networkx_labels(G, pos, labels=labels, font_size=8)

    plt.title(
        f"Job {id_job} | sub_time={G.graph['sub_time']} | nós={G.number_of_nodes()} | arestas={G.number_of_edges()}"
    )
    plt.axis("off")
    plt.tight_layout()

    caminho_arquivo = os.path.join(pasta_saida, f"grafo[{id_job}].png")
    plt.savefig(caminho_arquivo, dpi=200, bbox_inches="tight")
    plt.close()

    print(f"Grafo salvo em: {caminho_arquivo}")


def salvar_dois_primeiros_grafos(grafos: dict[int, nx.DiGraph]) -> None:
    ids = sorted(grafos.keys())[:2]
    pasta_saida = garantir_pasta_grafos()

    print("\n=== Salvando os 2 primeiros grafos ===")
    for id_job in ids:
        salvar_grafo(grafos[id_job], pasta_saida)


def main():
    file_path = "datas/jobs_stress_20x.data"

    dados = ler_jobs_data(file_path)
    imprimir_amostra_registros(dados, limite=20)
    resumir_dataset(dados)

    jobs_dict = agrupar_por_job(dados)
    grafos = construir_grafos(jobs_dict)

    print(f"\nTotal de grafos montados: {len(grafos)}")

    validar_grafos(grafos)
    imprimir_amostra_grafos(grafos, limite=3)
    salvar_dois_primeiros_grafos(grafos)


if __name__ == "__main__":
    main()