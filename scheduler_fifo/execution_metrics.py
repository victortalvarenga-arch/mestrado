def _coletar_intervalos_de_snapshots(snapshots: list[dict]) -> tuple[list[float], list[float]]:
    start_times = []
    end_times = []
    vistos = set()

    for snapshot in snapshots or []:
        state_snapshot = snapshot.get("state", {})
        running_tasks = state_snapshot.get("running_tasks", [])

        for task in running_tasks:
            job_id = task.get("job_id")
            task_id = task.get("task_id")
            server = task.get("server")
            start_time = task.get("start_time")
            end_time = task.get("end_time")

            if start_time is None or end_time is None:
                continue

            chave = (job_id, task_id, server, start_time, end_time)
            if chave in vistos:
                continue

            vistos.add(chave)
            start_times.append(float(start_time))
            end_times.append(float(end_time))

    return start_times, end_times


def calcular_makespan_de_snapshots(snapshots: list[dict]) -> float:
    start_times, end_times = _coletar_intervalos_de_snapshots(snapshots)

    if not end_times:
        return 0.0

    inicio = min(start_times) if start_times else 0.0
    fim = max(end_times)
    return fim - inicio


def calcular_makespan_state(state: dict) -> float:
    return calcular_makespan_de_snapshots(state.get("loop_snapshots", []))


def calcular_makespan_json(data: dict) -> float:
    metadata = data.get("metadata", {})

    if metadata.get("makespan") is not None:
        return float(metadata.get("makespan"))

    makespan = calcular_makespan_de_snapshots(data.get("snapshots", []))
    if makespan > 0:
        return makespan

    if metadata.get("final_time") is not None:
        return float(metadata.get("final_time"))

    snapshots = data.get("snapshots", [])
    if snapshots:
        return float(snapshots[-1].get("time", 0))

    return 0.0
