import networkx as nx
import matplotlib.pyplot as plt


# ============================================================
# 1) Funções auxiliares
# ============================================================
def add_task(graph, task, execution_time):
    """Adiciona uma tarefa à DAG."""
    graph.add_node(task, t=float(execution_time))


def add_edge(graph, source, target, bytes_):
    """Adiciona uma dependência entre duas tarefas."""
    graph.add_edge(source, target, bytes=float(bytes_))


def topological_levels(graph):
    """
    Organiza os nós em níveis topológicos para posicioná-los
    corretamente na imagem.
    """
    layers = list(nx.topological_generations(graph))
    positions = {}

    for level, layer in enumerate(layers):
        for index, node in enumerate(layer):
            positions[node] = (level, -index)

    return positions


# ============================================================
# 2) Construção das duas DAGs
# ============================================================
def build_dag_A():
    """
    W1: workflow com fan-in elevado.
    As tarefas A1, A2 e A3 convergem para a tarefa A4.
    """
    graph = nx.DiGraph()

    add_task(graph, "A0", 3)
    add_task(graph, "A1", 2)
    add_task(graph, "A2", 2)
    add_task(graph, "A3", 2)
    add_task(graph, "A4", 3)

    add_edge(graph, "A0", "A1", 400)
    add_edge(graph, "A0", "A2", 400)
    add_edge(graph, "A0", "A3", 400)

    add_edge(graph, "A1", "A4", 2200)
    add_edge(graph, "A2", "A4", 2200)
    add_edge(graph, "A3", "A4", 2200)

    title = "W1: fan-in elevado (join / incast)"
    return graph, title


def build_dag_B():
    """
    W2: workflow em pipeline com bifurcação.
    """
    graph = nx.DiGraph()

    add_task(graph, "B0", 2)
    add_task(graph, "B1", 6)
    add_task(graph, "B2", 2)
    add_task(graph, "B3", 2)
    add_task(graph, "B4", 3)

    add_edge(graph, "B0", "B1", 250)
    add_edge(graph, "B1", "B2", 700)
    add_edge(graph, "B1", "B3", 700)
    add_edge(graph, "B2", "B4", 500)
    add_edge(graph, "B3", "B4", 500)

    title = "W2: pipeline + bifurcação"
    return graph, title


# ============================================================
# 3) Geração da imagem com as duas DAGs
# ============================================================
def plot_two_dags(
    dag_a,
    title_a,
    dag_b,
    title_b,
    filename="fig_dags_2workflows.png",
):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    dags = [
        (dag_a, title_a),
        (dag_b, title_b),
    ]

    for axis, (graph, title) in zip(axes, dags):
        positions = topological_levels(graph)

        labels = {
            node: f"{node}\nt={graph.nodes[node]['t']}"
            for node in graph.nodes()
        }

        nx.draw_networkx_nodes(
            graph,
            positions,
            ax=axis,
            node_size=1800,
        )

        nx.draw_networkx_edges(
            graph,
            positions,
            ax=axis,
            arrows=True,
            arrowstyle="-|>",
            arrowsize=22,
            width=1.8,
            min_source_margin=18,
            min_target_margin=18,
            connectionstyle="arc3,rad=0.03",
        )

        nx.draw_networkx_labels(
            graph,
            positions,
            labels=labels,
            ax=axis,
            font_size=9,
        )

        axis.set_title(title)
        axis.axis("off")

    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches="tight")
    plt.show()

    print(f"Imagem gerada: {filename}")


# ============================================================
# 4) Execução
# ============================================================
if __name__ == "__main__":
    dag_a, title_a = build_dag_A()
    dag_b, title_b = build_dag_B()

    plot_two_dags(
        dag_a,
        title_a,
        dag_b,
        title_b,
        filename="fig_dags_2workflows.png",
    )