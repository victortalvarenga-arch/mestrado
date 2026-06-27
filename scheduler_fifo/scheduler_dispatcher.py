from imports import nx
from scheduler_utils import SUPPORTED_BASE_POLICIES, normalizar_nome_politica
from easy import ordenar_easy, escolher_servidor_easy
from heft import ordenar_heft, escolher_servidor_heft
from cpop import ordenar_cpop, escolher_servidor_cpop
from peft import ordenar_peft, escolher_servidor_peft


def validar_politica_base(policy: str) -> str:
    policy = normalizar_nome_politica(policy)

    if policy not in SUPPORTED_BASE_POLICIES:
        permitidas = ", ".join(sorted(SUPPORTED_BASE_POLICIES))
        raise ValueError(f"base_scheduler_policy inválida: {policy}. Use uma de: {permitidas}")

    return policy


def ordenar_tarefas_prontas(
    policy: str,
    ready_tasks,
    jobs: dict[int, nx.DiGraph],
    state: dict
) -> list[tuple[int, int]]:
    policy = validar_politica_base(policy)

    if policy == "easy":
        return ordenar_easy(ready_tasks, jobs, state)

    if policy == "heft":
        return ordenar_heft(ready_tasks, jobs, state)

    if policy == "cpop":
        return ordenar_cpop(ready_tasks, jobs, state)

    if policy == "peft":
        return ordenar_peft(ready_tasks, jobs, state)

    raise ValueError(f"Política não suportada: {policy}")


def escolher_servidor_base(
    policy: str,
    task: tuple[int, int],
    servidores_livres: list,
    state: dict,
    topology: nx.Graph
):
    policy = validar_politica_base(policy)

    if policy == "easy":
        return escolher_servidor_easy(task, servidores_livres, state, topology)

    if policy == "heft":
        return escolher_servidor_heft(task, servidores_livres, state, topology)

    if policy == "cpop":
        return escolher_servidor_cpop(task, servidores_livres, state, topology)

    if policy == "peft":
        return escolher_servidor_peft(task, servidores_livres, state, topology)

    raise ValueError(f"Política não suportada: {policy}")
