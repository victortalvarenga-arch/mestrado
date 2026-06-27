from imports import math


def ordenar_servidores(servidores: list) -> list:
    return sorted(
        servidores,
        key=lambda x: int(x) if str(x).isdigit() else str(x)
    )


def listar_servidores_livres(state: dict) -> list:
    livres = []
    for servidor, info in state["server_status"].items():
        if not info["busy"]:
            livres.append(servidor)
    return ordenar_servidores(livres)


def calcular_duracao_execucao(job_graph, task_id: int) -> int:
    wall_time = job_graph.nodes[task_id].get("wall_time", 1)
    return max(1, math.ceil(wall_time))


def normalizar_nome_politica(policy: str) -> str:
    policy = (policy or "easy").lower().strip()

    aliases = {
        "fifo": "easy",
        "fcfs": "easy",
        "easy_backfilling": "easy",
        "easy-backfilling": "easy",
        "easy backfilling": "easy",
    }

    return aliases.get(policy, policy)


SUPPORTED_BASE_POLICIES = {"easy", "heft", "cpop", "peft"}
