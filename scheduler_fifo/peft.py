from imports import nx
from scheduler_utils import ordenar_servidores


def calcular_oct_job(G: nx.DiGraph) -> dict:
    """
    Calcula uma versão simplificada da Optimistic Cost Table (OCT).

    No modelo atual, os servidores são tratados de forma homogênea. Assim, a OCT é
    calculada por tarefa, estimando o maior custo futuro otimista a partir dos sucessores.
    """
    memo = {}

    def oct(task_id):
        if task_id in memo:
            return memo[task_id]

        sucessores = list(G.successors(task_id))
        if not sucessores:
            memo[task_id] = 0
            return memo[task_id]

        maior_sucessor = max(
            G.nodes[sucessor].get("wall_time", 1)
            + G.nodes[task_id].get("resource", 1)
            + oct(sucessor)
            for sucessor in sucessores
        )

        memo[task_id] = maior_sucessor
        return memo[task_id]

    for task_id in G.nodes():
        oct(task_id)

    return memo


def obter_peft_oct_state(state: dict) -> dict:
    if "peft_oct" in state:
        return state["peft_oct"]

    oct_por_task = {}
    todos_jobs = {}
    todos_jobs.update(state.get("pending_jobs", {}))
    todos_jobs.update(state.get("active_jobs", {}))

    for job_id, G in todos_jobs.items():
        job_oct = calcular_oct_job(G)
        for task_id, valor in job_oct.items():
            oct_por_task[(job_id, task_id)] = valor

    state["peft_oct"] = oct_por_task
    return oct_por_task


def ordenar_peft(ready_tasks, jobs: dict[int, nx.DiGraph], state: dict) -> list[tuple[int, int]]:
    oct_por_task = obter_peft_oct_state(state)

    return sorted(
        list(ready_tasks),
        key=lambda task: (
            -(jobs[task[0]].nodes[task[1]].get("wall_time", 1) + oct_por_task.get(task, 0)),
            jobs[task[0]].graph["sub_time"],
            task[0],
            task[1],
        ),
    )


def escolher_servidor_peft(
    task: tuple[int, int],
    servidores_livres: list,
    state: dict,
    topology: nx.Graph | None = None
):
    """
    Seleciona o servidor que minimiza uma estimativa PEFT simplificada.

    Como o simulador não diferencia velocidade entre servidores, todos os servidores
    livres produzem o mesmo término local. A política mantém desempate determinístico.
    """
    if not servidores_livres:
        return None

    return ordenar_servidores(servidores_livres)[0]
