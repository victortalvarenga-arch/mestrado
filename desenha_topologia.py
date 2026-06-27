import os
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import pydot

from export_topology import exportar_topologia_dot


def carregar_topologia(caminho_dot: str) -> nx.Graph:
    graphs = pydot.graph_from_dot_file(caminho_dot)
    pydot_graph = graphs[0]
    G = nx.nx_pydot.from_pydot(pydot_graph)
    return nx.Graph(G)


def desenhar_topologia(
    G: nx.Graph,
    caminho_saida: str,
    titulo: str,
    node_size: int = 200,
    font_size: int = 6,
    figsize: tuple = (18, 12),
) -> None:
    plt.figure(figsize=figsize)

    pos = nx.spring_layout(G, seed=42)

    nx.draw(
        G,
        pos,
        with_labels=True,
        node_size=node_size,
        font_size=font_size,
    )

    plt.title(titulo)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(caminho_saida, dpi=200, bbox_inches="tight")
    plt.close()

    print(f"Imagem salva em: {caminho_saida}")


def gerar_imagem_dot(
    pasta: str,
    arquivo_dot: str,
    arquivo_png: str,
    titulo: str,
    node_size: int = 200,
    font_size: int = 6,
    figsize: tuple = (18, 12),
) -> None:
    caminho_dot = os.path.join(pasta, arquivo_dot)
    caminho_saida = os.path.join(pasta, arquivo_png)

    G = carregar_topologia(caminho_dot)

    print(f"\nArquivo: {arquivo_dot}")
    print(f"Nós: {G.number_of_nodes()}")
    print(f"Arestas: {G.number_of_edges()}")

    desenhar_topologia(
        G=G,
        caminho_saida=caminho_saida,
        titulo=titulo,
        node_size=node_size,
        font_size=font_size,
        figsize=figsize,
    )


def main():
    base_dir = Path(__file__).resolve().parent

    topology_file = base_dir / "racks_spatial_distribution.md"
    if not topology_file.exists():
        topology_file = base_dir.parent / "racks_spatial_distribution.md"

    output_dir = base_dir / "graphs"
    output_dir.mkdir(parents=True, exist_ok=True)

    exportar_topologia_dot(
        topology_file=str(topology_file),
        output_dir=str(output_dir),
    )

    gerar_imagem_dot(
        pasta=str(output_dir),
        arquivo_dot="dragonfly_routers.dot",
        arquivo_png="dragonfly_routers.png",
        titulo="Topologia Dragonfly - Roteadores",
        node_size=500,
        font_size=8,
        figsize=(16, 10),
    )

    gerar_imagem_dot(
        pasta=str(output_dir),
        arquivo_dot="dragonfly_topology.dot",
        arquivo_png="dragonfly_topology.png",
        titulo="Topologia Dragonfly - Completa",
        node_size=120,
        font_size=5,
        figsize=(22, 14),
    )


if __name__ == "__main__":
    main()