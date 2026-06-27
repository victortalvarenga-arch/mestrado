from imports import deque, nx
from scheduler_utils import ordenar_servidores


def ordenar_easy(ready_tasks: deque, jobs: dict[int, nx.DiGraph], state: dict | None = None) -> list[tuple[int, int]]:
    """
    Ordenação base do tipo EASY/FCFS simplificada para o simulador.

    Como o simulador trabalha com tarefas prontas de DAGs e servidores unitários,
    esta política preserva a ordem de submissão do job e desempata por job_id e task_id.
    """
    return sorted(
        list(ready_tasks),
        key=lambda x: (
            jobs[x[0]].graph["sub_time"],
            x[0],
            x[1],
        ),
    )


def escolher_servidor_easy(task: tuple[int, int], servidores_livres: list, state: dict, topology: nx.Graph | None = None):
    if not servidores_livres:
        return None
    return ordenar_servidores(servidores_livres)[0]
