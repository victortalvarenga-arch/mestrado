from imports import nx, deque
from topology_utils import (
    listar_servidores_compute,
    construir_network_state,
    resumir_topologia,
    construir_indice_topologia,
)

def criar_state(jobs: dict[int, nx.DiGraph], topology: nx.Graph) -> dict:
    servidores = listar_servidores_compute(topology)

    workload_summary = {
        "jobs_count": len(jobs),
        "tasks_count": sum(G.number_of_nodes() for G in jobs.values()),
    }

    return {
        "time": 0,
        "loop": 0,
        "pending_jobs": {job_id: G for job_id, G in jobs.items()},
        "active_jobs": {},
        "ready_tasks": deque(),
        "running_tasks": [],
        "finished_tasks": set(),
        "scheduled_tasks": set(),
        "server_status": {
            servidor: {
                "busy": False,
                "task": None,
                "job_id": None,
                "end_time": None,
            }
            for servidor in servidores
        },
        "task_placement": {},
        "network_state": construir_network_state(topology),
        "metrics": [],
        "loop_snapshots": [],
        "topology_summary": resumir_topologia(topology),
        "workload_summary": workload_summary,
        "topology_index": construir_indice_topologia(topology),
        "hops_cache": {},
    }
