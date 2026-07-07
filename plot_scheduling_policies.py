"""
Comparação de escalonamento dos workflows de exemplo (W1, W2, W3, W4 —
ver plot_workflows.py) sob as 4 heurísticas de base do simulador
(EASY, HEFT, CPOP, PEFT — ver scheduler_fifo/scheduler_dispatcher.py).

Os 4 workflows são tratados como jobs independentes submetidos ao mesmo
tempo, disputando 3 servidores homogêneos. Cada painel mostra o Gantt
chart resultante de uma heurística, usando o mesmo padrão de cores por
workflow do plot_workflows.py (tamanho dos blocos proporcional a T).

Este script implementa um escalonador por lista (ready-queue) simples e
determinístico para cada heurística — não é o simulador completo do
projeto, mas respeita as mesmas regras de precedência (DAG) e os mesmos
critérios de prioridade/atribuição de servidor descritos na dissertação.
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

TITLE_FONTSIZE = 20
LABEL_FONTSIZE = 12
NUM_SERVERS = 3

# ----------------------------------------------------------------------
# Definição dos workflows (mesmas tarefas/durações/cores de plot_workflows.py)
# ----------------------------------------------------------------------
WORKFLOWS = {
    "W1": {
        "durations": {"t0": 2},
        "edges": [],
        "color": "skyblue",
    },
    "W2": {
        "durations": {"t0": 3},
        "edges": [],
        "color": "khaki",
    },
    "W3": {
        "durations": {"t0": 1, "t1": 1, "t2": 1, "t3": 1, "t4": 1, "t5": 1, "t6": 1},
        "edges": [
            ("t0", "t1"), ("t0", "t2"),
            ("t1", "t3"), ("t1", "t4"), ("t1", "t5"),
            ("t2", "t3"), ("t2", "t4"), ("t2", "t5"),
            ("t3", "t6"), ("t4", "t6"), ("t5", "t6"),
        ],
        "color": "lightcoral",
    },
    "W4": {
        "durations": {"t0": 1, "t1": 1, "t2": 1, "t3": 2, "t4": 1},
        "edges": [
            ("t0", "t2"), ("t0", "t3"),
            ("t1", "t2"), ("t1", "t3"),
            ("t2", "t4"), ("t3", "t4"),
        ],
        "color": "mediumaquamarine",
    },
}
JOB_ORDER = ["W1", "W2", "W3", "W4"]

# ----------------------------------------------------------------------
# Monta o conjunto global de tarefas (job, task) com predecessores/sucessores
# ----------------------------------------------------------------------
ALL_TASKS = []
DURATION = {}
PREDS = {}
SUCCS = {}
JOB_INDEX = {}
TASK_INDEX = {}

for job in JOB_ORDER:
    wf = WORKFLOWS[job]
    for t, dur in wf["durations"].items():
        key = (job, t)
        ALL_TASKS.append(key)
        DURATION[key] = dur
        PREDS[key] = set()
        SUCCS[key] = set()
        JOB_INDEX[key] = JOB_ORDER.index(job)
        TASK_INDEX[key] = int(t[1:])
    for a, b in wf["edges"]:
        PREDS[(job, b)].add((job, a))
        SUCCS[(job, a)].add((job, b))


def upward_rank(task, memo={}):
    if task in memo:
        return memo[task]
    succs = SUCCS[task]
    rank = DURATION[task] + (max((upward_rank(s, memo) for s in succs), default=0))
    memo[task] = rank
    return rank


def downward_rank(task, memo={}):
    if task in memo:
        return memo[task]
    preds = PREDS[task]
    rank = max((downward_rank(p, memo) + DURATION[p] for p in preds), default=0)
    memo[task] = rank
    return rank


UP = {t: upward_rank(t) for t in ALL_TASKS}
DOWN = {t: downward_rank(t) for t in ALL_TASKS}


def critical_path_set():
    """Um caminho crítico por job (prioridade up+down == comprimento do
    caminho crítico do job), usado pela heurística CPOP."""
    critical = set()
    for job in JOB_ORDER:
        job_tasks = [t for t in ALL_TASKS if t[0] == job]
        cp_len = max(UP[t] + DOWN[t] for t in job_tasks)
        entries = [t for t in job_tasks if not PREDS[t]]
        current = min(
            (t for t in entries if UP[t] + DOWN[t] == cp_len),
            key=lambda t: (JOB_INDEX[t], TASK_INDEX[t]),
        )
        critical.add(current)
        while True:
            candidates = [s for s in SUCCS[current] if UP[s] + DOWN[s] == cp_len]
            if not candidates:
                break
            current = min(candidates, key=lambda t: (JOB_INDEX[t], TASK_INDEX[t]))
            critical.add(current)
    return critical


CRITICAL_SET = critical_path_set()


# ----------------------------------------------------------------------
# Simulador genérico por lista (ready-queue), parametrizado por
# critério de prioridade e por regra de escolha de servidor
# ----------------------------------------------------------------------
def simulate(priority_key, assign_fn, num_servers=NUM_SERVERS):
    done = set()
    finish = {}
    server_free = [0.0] * num_servers
    server_load = [0.0] * num_servers
    schedule = {}

    while len(done) < len(ALL_TASKS):
        ready = [t for t in ALL_TASKS if t not in done and PREDS[t] <= done]
        chosen = min(ready, key=priority_key)
        pred_finish = max((finish[p] for p in PREDS[chosen]), default=0.0)
        server = assign_fn(chosen, pred_finish, server_free, server_load)
        start = max(pred_finish, server_free[server])
        end = start + DURATION[chosen]
        server_free[server] = end
        server_load[server] += DURATION[chosen]
        finish[chosen] = end
        schedule[chosen] = (server, start, end)
        done.add(chosen)

    return schedule


def eft_assign(excluded_servers=()):
    def _assign(task, pred_finish, server_free, server_load):
        candidates = [s for s in range(len(server_free)) if s not in excluded_servers]
        return min(candidates, key=lambda s: (max(pred_finish, server_free[s]), s))
    return _assign


def peft_assign(task, pred_finish, server_free, server_load):
    candidates = range(len(server_free))
    return min(candidates, key=lambda s: (max(pred_finish, server_free[s]), server_load[s], s))


def cpop_assign(critical_server=0):
    def _assign(task, pred_finish, server_free, server_load):
        if task in CRITICAL_SET:
            return critical_server
        others = [s for s in range(len(server_free)) if s != critical_server]
        return min(others, key=lambda s: (max(pred_finish, server_free[s]), s))
    return _assign


def easy_key(t):
    return (JOB_INDEX[t], TASK_INDEX[t])


def heft_key(t):
    return (-UP[t], JOB_INDEX[t], TASK_INDEX[t])


def cpop_key(t):
    return (-(UP[t] + DOWN[t]), JOB_INDEX[t], TASK_INDEX[t])


SCHEDULES = {
    "EASY": simulate(easy_key, eft_assign()),
    "HEFT": simulate(heft_key, eft_assign()),
    "CPOP": simulate(cpop_key, cpop_assign()),
    "PEFT": simulate(heft_key, peft_assign),
}

# ----------------------------------------------------------------------
# Sanidade: nenhuma tarefa começa antes do fim de suas predecessoras, e
# nenhum servidor executa duas tarefas ao mesmo tempo
# ----------------------------------------------------------------------
for name, schedule in SCHEDULES.items():
    per_server = {}
    for task, (server, start, end) in schedule.items():
        for pred in PREDS[task]:
            _, _, pred_end = schedule[pred]
            assert start >= pred_end - 1e-9, f"{name}: {task} viola precedência de {pred}"
        per_server.setdefault(server, []).append((start, end))
    for server, intervals in per_server.items():
        intervals.sort()
        for (s0, e0), (s1, e1) in zip(intervals, intervals[1:]):
            assert s1 >= e0 - 1e-9, f"{name}: conflito no servidor {server}"

MAKESPAN = max(end for schedule in SCHEDULES.values() for _, _, end in schedule.values())

# ----------------------------------------------------------------------
# Desenho dos painéis (mesmo padrão visual de plot_workflows.py)
# ----------------------------------------------------------------------
def draw_schedule(ax, schedule, title):
    ax.set_title(title, fontsize=TITLE_FONTSIZE, fontweight="bold", loc="left")

    for server in range(NUM_SERVERS):
        ax.axhline(server, color="gray", linestyle="--", linewidth=0.8, zorder=0)

    bar_h = 0.6
    gap = 0.08
    for (job, task), (server, start, end) in schedule.items():
        color = WORKFLOWS[job]["color"]
        dur = end - start - gap
        rect = mpatches.FancyBboxPatch(
            (start + gap / 2, server - bar_h / 2), dur, bar_h,
            boxstyle="round,pad=0,rounding_size=0.08",
            facecolor=color, edgecolor="black", linewidth=1.1, zorder=2,
        )
        ax.add_patch(rect)
        ax.text(start + (end - start) / 2, server, task,
                ha="center", va="center", fontsize=LABEL_FONTSIZE,
                fontweight="bold", zorder=3)

    axis_y = -1.0
    ax.annotate("", xy=(MAKESPAN + 1.2, axis_y), xytext=(-0.3, axis_y),
                arrowprops=dict(arrowstyle="-|>", color="black", lw=1.2),
                annotation_clip=False, zorder=1)
    for x in range(0, int(MAKESPAN) + 2):
        ax.plot([x, x], [axis_y - 0.08, axis_y + 0.08], color="black", linewidth=1.0, zorder=1)
        ax.text(x, axis_y - 0.22, str(x), fontsize=10, ha="center", va="top")
    ax.text(MAKESPAN + 1.2, axis_y - 0.32, "time", fontsize=11, ha="center", va="top")

    ax.set_xlim(-0.3, MAKESPAN + 1.2)
    ax.set_ylim(axis_y - 0.65, NUM_SERVERS - 1 + 0.7)
    ax.set_yticks(range(NUM_SERVERS))
    ax.set_yticklabels([f"server {s}" for s in range(NUM_SERVERS)], fontsize=11, fontweight="bold")
    ax.set_xticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


fig, axes = plt.subplots(2, 2, figsize=(16, 9))
panel_order = [("(a) EASY", "EASY"), ("(b) HEFT", "HEFT"),
               ("(c) CPOP", "CPOP"), ("(d) PEFT", "PEFT")]

for ax, (title, key) in zip(axes.flat, panel_order):
    draw_schedule(ax, SCHEDULES[key], title)

legend_handles = [
    mpatches.Patch(facecolor=WORKFLOWS[job]["color"], edgecolor="black", label=job)
    for job in JOB_ORDER
]
fig.legend(handles=legend_handles, loc="lower center", ncol=4,
           fontsize=13, frameon=False, bbox_to_anchor=(0.5, -0.02))

plt.subplots_adjust(left=0.06, right=0.98, top=0.93, bottom=0.09,
                     wspace=0.18, hspace=0.35)
plt.savefig("scheduling_policies_exemplo.png", dpi=200, bbox_inches="tight")
print("Figura salva com sucesso. Makespans:",
      {name: max(e for _, _, e in s.values()) for name, s in SCHEDULES.items()})
