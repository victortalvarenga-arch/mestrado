from imports import deque

def task_key(job_id: int, task_id: int) -> tuple[int, int]:
    return (job_id, task_id)

def tornar_json_serializavel(obj):
    if isinstance(obj, dict):
        return {str(k): tornar_json_serializavel(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [tornar_json_serializavel(v) for v in obj]
    if isinstance(obj, tuple):
        return [tornar_json_serializavel(v) for v in obj]
    if isinstance(obj, set):
        return [tornar_json_serializavel(v) for v in sorted(obj)]
    if isinstance(obj, deque):
        return [tornar_json_serializavel(v) for v in obj]
    return obj

def compactar_lista_em_linha(valores) -> str:
    return ",".join(str(v) for v in valores)
