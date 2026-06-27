from imports import nx


def calcular_rank_upward_job(G: nx.DiGraph) -> dict:
    memo = {}

    def rank(task_id):
        if task_id in memo:
            return memo[task_id]

        wall_time = G.nodes[task_id].get("wall_time", 1)
        resource = G.nodes[task_id].get("resource", 1)

        sucessores = list(G.successors(task_id))

        if not sucessores:
            memo[task_id] = wall_time
            return memo[task_id]

        maior_sucessor = max(
            resource + rank(sucessor)
            for sucessor in sucessores
        )

        memo[task_id] = wall_time + maior_sucessor
        return memo[task_id]

    for task_id in G.nodes():
        rank(task_id)

    return memo


def obter_heft_ranks_state(state: dict) -> dict:
    if "heft_ranks" in state:
        return state["heft_ranks"]

    ranks = {}

    todos_jobs = {}
    todos_jobs.update(state.get("pending_jobs", {}))
    todos_jobs.update(state.get("active_jobs", {}))

    for job_id, G in todos_jobs.items():
        job_ranks = calcular_rank_upward_job(G)

        for task_id, rank_value in job_ranks.items():
            ranks[(job_id, task_id)] = rank_value

    state["heft_ranks"] = ranks
    return ranks


def ordenar_heft(
    ready_tasks,
    jobs: dict[int, nx.DiGraph],
    state: dict
) -> list[tuple[int, int]]:
    ranks = obter_heft_ranks_state(state)

    return sorted(
        list(ready_tasks),
        key=lambda task: (
            -ranks.get(task, 0),
            jobs[task[0]].graph["sub_time"],
            task[0],
            task[1],
        ),
    )


def escolher_servidor_heft(
    task: tuple[int, int],
    servidores_livres: list,
    state: dict,
    topology: nx.Graph
):
    if not servidores_livres:
        return None

    job_id, task_id = task
    G = state["active_jobs"][job_id]
    wall_time = G.nodes[task_id].get("wall_time", 1)

    melhor_servidor = None
    melhor_end_time = float("inf")

    for servidor in servidores_livres:
        end_time = state["time"] + wall_time

        if end_time < melhor_end_time:
            melhor_end_time = end_time
            melhor_servidor = servidor

        elif end_time == melhor_end_time:
            atual = str(servidor)
            melhor = str(melhor_servidor)

            if atual < melhor:
                melhor_servidor = servidor

    return melhor_servidor