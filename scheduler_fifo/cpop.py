from imports import nx
from heft import calcular_rank_upward_job
from scheduler_utils import ordenar_servidores


def calcular_rank_downward_job(G: nx.DiGraph) -> dict:
    """
    Calcula uma aproximação do rank descendente por tarefa.

    O valor representa o maior custo acumulado dos predecessores até a tarefa.
    Essa informação é combinada com o rank ascendente para priorizar tarefas
    associadas ao caminho crítico do DAG.
    """
    memo = {}

    def rank(task_id):
        if task_id in memo:
            return memo[task_id]

        predecessores = list(G.predecessors(task_id))
        if not predecessores:
            memo[task_id] = 0
            return memo[task_id]

        maior_predecessor = max(
            rank(pred)
            + G.nodes[pred].get("wall_time", 1)
            + G.nodes[pred].get("resource", 1)
            for pred in predecessores
        )

        memo[task_id] = maior_predecessor
        return memo[task_id]

    for task_id in G.nodes():
        rank(task_id)

    return memo


def calcular_cpop_prioridades_job(G: nx.DiGraph) -> dict:
    rank_up = calcular_rank_upward_job(G)
    rank_down = calcular_rank_downward_job(G)

    return {
        task_id: rank_up.get(task_id, 0) + rank_down.get(task_id, 0)
        for task_id in G.nodes()
    }


def obter_cpop_prioridades_state(state: dict) -> dict:
    if "cpop_priorities" in state:
        return state["cpop_priorities"]

    prioridades = {}
    todos_jobs = {}
    todos_jobs.update(state.get("pending_jobs", {}))
    todos_jobs.update(state.get("active_jobs", {}))

    for job_id, G in todos_jobs.items():
        job_prioridades = calcular_cpop_prioridades_job(G)
        for task_id, valor in job_prioridades.items():
            prioridades[(job_id, task_id)] = valor

    state["cpop_priorities"] = prioridades
    return prioridades


def ordenar_cpop(ready_tasks, jobs: dict[int, nx.DiGraph], state: dict) -> list[tuple[int, int]]:
    prioridades = obter_cpop_prioridades_state(state)

    return sorted(
        list(ready_tasks),
        key=lambda task: (
            -prioridades.get(task, 0),
            jobs[task[0]].graph["sub_time"],
            task[0],
            task[1],
        ),
    )


def escolher_servidor_cpop(
    task: tuple[int, int],
    servidores_livres: list,
    state: dict,
    topology: nx.Graph | None = None
):
    """
    Seleção de servidor da política CPOP no simulador.

    A prioridade principal do CPOP fica na ordenação das tarefas pelo caminho crítico.
    Como o ambiente simulado não modela velocidades heterogêneas por servidor,
    o desempate de servidor preserva ordem determinística dos servidores livres.
    """
    if not servidores_livres:
        return None

    return ordenar_servidores(servidores_livres)[0]
