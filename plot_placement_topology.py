"""
Comparação de posicionamento (baseline HEFT x HEFT com a camada de
consciência de rede) sobre uma topologia pequena de 2 grupos x 2 racks x
3 servidores, usando os MESMOS workflows W1 e W2 de plot_dag_exemple.py
(idênticos aos que geram fig_dags_2workflows.png).

O objetivo é ilustrar, em escala reduzida, o mesmo raciocínio do
escalonador do projeto (scheduler_fifo/network_metrics.py): o custo de
rede de uma tarefa é a soma, sobre seus predecessores, de hops * payload
no caminho mais curto até o servidor candidato; um fluxo é cross-server,
cross-rack e/ou cross-group conforme os atributos rack_id/group dos
servidores de origem e destino diferem.

- Baseline: HEFT clássico (Topcuoglu et al. 2002), minimizando o tempo de
  término estimado (EFT) considerando apenas se a comunicação é local ao
  servidor ou não (custo médio via largura de banda), sem noção de
  topologia hierárquica.
- Network-aware: mesma ordem de prioridade (rank ascendente), mas a
  escolha do servidor combina o EFT com o custo de rede topológico
  (hops/rack/grupo), preferindo candidatos próximos aos predecessores.
"""

import math
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from plot_dag_exemple import build_dag_A, build_dag_B

TITLE_FONTSIZE = 15

# ------------------------------------------------------------------
# 1) Topologia: 2 grupos x 2 racks x 3 servidores = 12 servidores,
#    igual à topologia descrita na dissertação.
#
#    Os IDs dos servidores são atribuídos intercalando os racks (round
#    robin por "slot") em vez de sequencialmente por rack. Isso evita
#    que o desempate do escalonador (menor id livre) esgote sempre os
#    servidores do Grupo 0 antes de considerar o Grupo 1 — sem isso,
#    com 12 servidores para só 10 tarefas, o Grupo 1 nunca seria usado
#    e os fluxos entre grupos não apareceriam na ilustração.
# ------------------------------------------------------------------
GROUPS = [0, 1]
RACKS_PER_GROUP = 2
SERVERS_PER_RACK = 3


def build_small_topology():
    G = nx.Graph()
    rack_of_id = {}
    group_of_id = {}
    rack_router = {}
    rack_list = []  # [(rack_id, group), ...]

    rack_id = 0
    for group in GROUPS:
        for _ in range(RACKS_PER_GROUP):
            router = f"r{rack_id}"
            G.add_node(router, type="router", rack_id=rack_id, group=group)
            rack_router[rack_id] = router
            rack_list.append((rack_id, group))
            rack_id += 1

    racks_by_group = {}
    for rid, g in rack_list:
        racks_by_group.setdefault(g, []).append(rid)

    # roteador-roteador dentro do mesmo grupo (intra_group)
    for g, racks in racks_by_group.items():
        G.add_edge(rack_router[racks[0]], rack_router[racks[1]], type="intra_group")

    # enlace global entre grupos (inter_group)
    r_out_group0 = racks_by_group[GROUPS[0]][-1]
    r_in_group1 = racks_by_group[GROUPS[1]][0]
    G.add_edge(rack_router[r_out_group0], rack_router[r_in_group1], type="inter_group")

    # servidores: um "slot" por vez, percorrendo todos os racks antes
    # de repetir (round robin), para intercalar grupos na numeração.
    server_id = 0
    for _slot in range(SERVERS_PER_RACK):
        for rid, g in rack_list:
            G.add_node(server_id, type="compute", rack_id=rid, group=g)
            G.add_edge(server_id, rack_router[rid], type="local")
            rack_of_id[server_id] = rid
            group_of_id[server_id] = g
            server_id += 1

    return G, rack_of_id, group_of_id


TOPOLOGY, RACK_OF, GROUP_OF = build_small_topology()
SERVERS = sorted(n for n, d in TOPOLOGY.nodes(data=True) if d["type"] == "compute")

RACK_SERVERS = {}
for s in SERVERS:
    RACK_SERVERS.setdefault(RACK_OF[s], []).append(s)

GROUP_RACKS = {}
for rack_id, router in [(0, "r0"), (1, "r1"), (2, "r2"), (3, "r3")]:
    GROUP_RACKS.setdefault(TOPOLOGY.nodes[router]["group"], []).append(rack_id)


# ------------------------------------------------------------------
# 2) Workflows (mesmos de plot_dag_exemple.py / fig_dags_2workflows.png)
# ------------------------------------------------------------------
GA, TITLE_A = build_dag_A()   # W1: A0..A4, fan-in elevado
GB, TITLE_B = build_dag_B()   # W2: B0..B4, pipeline + bifurcação
DAGS = {"W1": GA, "W2": GB}
TASK_COLOR = {"W1": "#2E75B6", "W2": "#ED7D31"}

ALL_TASKS = [(dag_id, t) for dag_id, G in DAGS.items() for t in G.nodes()]


def preds(dag_id, t):
    return list(DAGS[dag_id].predecessors(t))


def succs(dag_id, t):
    return list(DAGS[dag_id].successors(t))


def duration(dag_id, t):
    return DAGS[dag_id].nodes[t]["t"]


def edge_bytes(dag_id, u, v):
    return DAGS[dag_id].edges[u, v]["bytes"]


# ------------------------------------------------------------------
# 3) Rank ascendente (HEFT) com custo médio de comunicação (bytes/bw)
# ------------------------------------------------------------------
BW = 450.0


def heft_upward_rank(dag_id):
    G = DAGS[dag_id]
    order = list(reversed(list(nx.topological_sort(G))))
    rank = {}
    for n in order:
        tcomp = G.nodes[n]["t"]
        succ = list(G.successors(n))
        if not succ:
            rank[n] = tcomp
        else:
            rank[n] = tcomp + max(edge_bytes(dag_id, n, s) / BW + rank[s] for s in succ)
    return rank


RANK = {}
for dag_id in DAGS:
    for t, r in heft_upward_rank(dag_id).items():
        RANK[(dag_id, t)] = r


# ------------------------------------------------------------------
# 4) Custo de rede (mesmo modelo de scheduler_fifo/network_metrics.py)
# ------------------------------------------------------------------
_hops_cache = {}


def hops_between(a, b):
    if a == b:
        return 0
    key = (a, b) if a < b else (b, a)
    if key not in _hops_cache:
        _hops_cache[key] = nx.shortest_path_length(TOPOLOGY, a, b)
    return _hops_cache[key]


def flow_classification(origem, destino):
    cross_server = origem != destino
    cross_rack = RACK_OF[origem] != RACK_OF[destino]
    cross_group = GROUP_OF[origem] != GROUP_OF[destino]
    return cross_server, cross_rack, cross_group


# ------------------------------------------------------------------
# 5) Pontuação network-aware = a fórmula REAL de
#    scheduler_fifo/network_aware.py (choose_server_network_aware).
#    Parâmetros do cenário "01_balanced" (scheduler_fifo/main.py -> SCENARIOS):
#      lambda_base = 0.5
#      metric_weights = cross_server=cross_rack=cross_group=comm_cost=0.25
#
#    combined_score = λ*base_score + (1-λ)*(network_score + B_hist)
#    - base_score: posição do servidor na ordenação numérica (proxy do
#      "base_order" da política base), normalizada por min-max entre os
#      candidatos (como normalizar_score_base, modo "candidates").
#    - network_score: soma ponderada das 4 métricas de tráfego,
#      normalizadas por min-max entre os candidatos (como
#      normalizar_metricas_candidatos).
#    - B_hist: mesma regra da Equação~3 do artigo, usando a EXECUÇÃO
#      BASELINE deste exemplo como histórico da execução network-aware
#      (mesmo protocolo do Algoritmo 1: primeiro roda a política base,
#      depois a network-aware consome esse traço).
# ------------------------------------------------------------------
METRIC_WEIGHTS = {"cross_server": 0.25, "cross_rack": 0.25, "cross_group": 0.25, "comm_cost": 0.25}
LAMBDA_BASE = 0.5

BASE_ORDER = sorted(SERVERS)
BASE_POS = {s: i for i, s in enumerate(BASE_ORDER)}


def compute_task_metrics(dag_id, t, candidate_server, placement):
    cross_server = cross_rack = cross_group = 0
    comm_cost = 0.0
    for p in preds(dag_id, t):
        p_server = placement[(dag_id, p)]
        cs, cr, cg = flow_classification(p_server, candidate_server)
        cross_server += int(cs)
        cross_rack += int(cr)
        cross_group += int(cg)
        comm_cost += hops_between(p_server, candidate_server) * edge_bytes(dag_id, p, t)
    return {
        "cross_server_flows": cross_server,
        "cross_rack_flows": cross_rack,
        "cross_group_flows": cross_group,
        "estimated_comm_cost": comm_cost,
    }


def normalize_candidate_metrics(metrics_by_server):
    fields = ["cross_server_flows", "cross_rack_flows", "cross_group_flows", "estimated_comm_cost"]
    normalized = {s: {} for s in metrics_by_server}
    for field in fields:
        values = [metrics_by_server[s][field] for s in metrics_by_server]
        lo, hi = min(values), max(values)
        for s in metrics_by_server:
            raw = metrics_by_server[s][field]
            normalized[s][field] = 0.0 if hi == lo else (raw - lo) / (hi - lo)
    return normalized


def normalize_base_scores(candidate_servers):
    """Score_base min-max entre os candidatos, como normalizar_score_base()."""
    indices = {s: BASE_POS[s] for s in candidate_servers}
    lo, hi = min(indices.values()), max(indices.values())
    if hi == lo:
        return {s: 0.0 for s in indices}
    return {s: (i - lo) / (hi - lo) for s, i in indices.items()}


def network_score(norm):
    return (
        norm["cross_server_flows"] * METRIC_WEIGHTS["cross_server"]
        + norm["cross_rack_flows"] * METRIC_WEIGHTS["cross_rack"]
        + norm["cross_group_flows"] * METRIC_WEIGHTS["cross_group"]
        + norm["estimated_comm_cost"] * METRIC_WEIGHTS["comm_cost"]
    )


def build_history_from_execution(reference_placement):
    """Histórico consumido pela execução network-aware, construído a
    partir da execução baseline deste mesmo exemplo (Equação 3 / B_hist)."""
    history = {}
    for dag_id, t in ALL_TASKS:
        p_list = preds(dag_id, t)
        if not p_list:
            continue
        server = reference_placement[(dag_id, t)]
        cross_rack = cross_group = 0
        for p in p_list:
            p_server = reference_placement[(dag_id, p)]
            _, cr, cg = flow_classification(p_server, server)
            cross_rack += int(cr)
            cross_group += int(cg)
        history[(dag_id, t)] = {
            "predecessor_count": len(p_list),
            "best_rack": RACK_OF[server],
            "best_group": GROUP_OF[server],
            "prev_cross_rack_flows": cross_rack,
            "prev_cross_group_flows": cross_group,
        }
    return history


def history_bonus_for(dag_id, t, candidate_server, history):
    info = history.get((dag_id, t)) if history else None
    if not info or info["predecessor_count"] == 0:
        return 0.0

    bonus = 0.0
    cand_rack = RACK_OF[candidate_server]
    cand_group = GROUP_OF[candidate_server]

    if cand_group == info["best_group"]:
        bonus -= 0.20
        if cand_rack == info["best_rack"]:
            bonus -= 0.10

    if (info["prev_cross_rack_flows"] == 0 and info["prev_cross_group_flows"] == 0
            and cand_group != info["best_group"]):
        bonus += 0.25

    return bonus


# ------------------------------------------------------------------
# 6) Escalonamento por lista (ready-queue) genérico
#
# A camada network-aware só escolhe entre os servidores que dão o
# melhor EFT possível para a tarefa (tolerância ~0). O código real
# (discrete-event, scheduler_fifo/network_aware.py) só decide entre
# servidores JÁ ociosos no instante da decisão, então a rede nunca
# "compra" tempo de espera; como este exemplo faz uma busca completa
# de EFT (não é um simulador de eventos discretos), essa restrição
# reproduz a mesma garantia por outro caminho — sem ela, o exemplo
# poderia sacrificar paralelismo/tempo por localidade.
# ------------------------------------------------------------------
EFT_TOLERANCE = 1e-9


def schedule(network_aware: bool, history: dict | None = None):
    done = set()
    finish = {}
    placement = {}
    server_free = {s: 0.0 for s in SERVERS}
    decisions = []

    # lista (não set): a ordem de iteração de um set é influenciada pelo
    # hash aleatório de strings entre execuções do processo, o que
    # tornava o desempate de tarefas com mesmo rank (ex.: A1/A2/A3, que
    # empatam por simetria do DAG) não-determinístico de uma rodada
    # para outra.
    unscheduled = list(ALL_TASKS)

    while unscheduled:
        ready = [
            (dag_id, t) for (dag_id, t) in unscheduled
            if all((dag_id, p) in done for p in preds(dag_id, t))
        ]
        # desempate explícito (ordem alfabética) para o resultado ser
        # sempre o mesmo mesmo quando o rank empata
        ready.sort(key=lambda x: (-RANK[x], x[0], x[1]))
        dag_id, t = ready[0]

        options = []
        for s in SERVERS:
            data_ready = 0.0
            for p in preds(dag_id, t):
                p_server = placement[(dag_id, p)]
                p_finish = finish[(dag_id, p)]
                transfer = 0.0 if p_server == s else edge_bytes(dag_id, p, t) / BW
                data_ready = max(data_ready, p_finish + transfer)

            start = max(server_free[s], data_ready)
            eft = start + duration(dag_id, t)
            options.append((eft, start, s))

        best_eft = min(o[0] for o in options)
        candidates = [o for o in options if o[0] <= best_eft + EFT_TOLERANCE]

        if network_aware:
            metrics_by_server = {
                o[2]: compute_task_metrics(dag_id, t, o[2], placement) for o in candidates
            }
            normalized = normalize_candidate_metrics(metrics_by_server)
            base_scores = normalize_base_scores([o[2] for o in candidates])

            def combined_score(o):
                srv = o[2]
                base_score = base_scores[srv]
                net_score = network_score(normalized[srv])
                hist_bonus = history_bonus_for(dag_id, t, srv, history)
                return LAMBDA_BASE * base_score + (1 - LAMBDA_BASE) * (net_score + hist_bonus)

            eft, start, s = min(candidates, key=lambda o: (combined_score(o), o[2]))
        else:
            eft, start, s = min(candidates, key=lambda o: o[2])

        server_free[s] = eft
        finish[(dag_id, t)] = eft
        placement[(dag_id, t)] = s
        decisions.append((dag_id, t, s, start, eft))

        unscheduled.remove((dag_id, t))
        done.add((dag_id, t))

    return placement, decisions


def compute_metrics(placement):
    """Reproduz a lógica de network_metrics.calcular_trafego_tarefa por tarefa."""
    total_hops = 0
    cross_server_flows = 0
    cross_rack_flows = 0
    cross_group_flows = 0
    comm_cost = 0.0
    flows = []

    for dag_id, t in ALL_TASKS:
        destino = placement[(dag_id, t)]
        for p in preds(dag_id, t):
            origem = placement[(dag_id, p)]
            cross_srv, cross_rk, cross_grp = flow_classification(origem, destino)
            hops = hops_between(origem, destino)
            payload = edge_bytes(dag_id, p, t) / 1000.0
            cost = hops * payload

            total_hops += hops
            cross_server_flows += int(cross_srv)
            cross_rack_flows += int(cross_rk)
            cross_group_flows += int(cross_grp)
            comm_cost += cost

            if cross_srv:
                flows.append({
                    "dag_id": dag_id, "from_task": p, "to_task": t,
                    "from_server": origem, "to_server": destino,
                    "cross_rack": cross_rk, "cross_group": cross_grp,
                })

    return {
        "total_hops": total_hops,
        "cross_server_flows": cross_server_flows,
        "cross_rack_flows": cross_rack_flows,
        "cross_group_flows": cross_group_flows,
        "estimated_comm_cost": comm_cost,
        "flows": flows,
    }


# ------------------------------------------------------------------
# 6) Desenho: grupos > racks > servidores, com tarefas e fluxos
# ------------------------------------------------------------------
def layout_positions():
    """Posição (x, y) de cada servidor e caixas de rack/grupo."""
    server_pos = {}
    rack_box = {}
    group_box = {}

    group_w, rack_w = 6.4, 2.9
    rack_h = 4.4
    gap_group = 1.0
    gap_rack = 0.35

    x = 0.0
    for group in GROUPS:
        group_x0 = x
        rack_ids = GROUP_RACKS[group]

        rx = x
        for rack_id in rack_ids:
            rack_box[rack_id] = (rx, 0.0, rack_w, rack_h)
            servers = RACK_SERVERS[rack_id]
            n = len(servers)
            top_margin, bottom_margin = 1.55, 0.55
            usable_h = rack_h - top_margin - bottom_margin
            for i, s in enumerate(servers):
                sy = (rack_h - top_margin) - i * (usable_h / max(n - 1, 1))
                server_pos[s] = (rx + rack_w / 2, sy)
            rx += rack_w + gap_rack

        group_box[group] = (group_x0, 0.0, rx - gap_rack - group_x0, rack_h)
        x = rx - gap_rack + gap_group

    return server_pos, rack_box, group_box, x - gap_group


def draw_scenario(ax, placement, decisions, metrics, title):
    server_pos, rack_box, group_box, total_w = layout_positions()

    for group, (gx, gy, gw, gh) in group_box.items():
        ax.add_patch(mpatches.FancyBboxPatch(
            (gx, gy), gw, gh, boxstyle="round,pad=0.02,rounding_size=0.05",
            facecolor="#F2F2F2", edgecolor="#999999", linewidth=1.1, zorder=0))
        ax.text(gx + gw / 2, gy + gh + 0.18, f"Grupo {group}",
                ha="center", va="bottom", fontsize=11, fontweight="bold")

    for rack_id, (rx, ry, rw, rh) in rack_box.items():
        ax.add_patch(mpatches.FancyBboxPatch(
            (rx + 0.08, ry + 0.08), rw - 0.16, rh - 0.16,
            boxstyle="round,pad=0.02,rounding_size=0.05",
            facecolor="white", edgecolor="#BBBBBB", linewidth=0.9, zorder=1))
        ax.text(rx + rw / 2, ry + rh - 0.28, f"Rack {rack_id}",
                ha="center", va="top", fontsize=9.5, color="#666666")

    # ocupantes de cada servidor (só para saber quais rótulos "servidor N"
    # ficam destacados ou apagados)
    occupants = {s: [] for s in SERVERS}
    for dag_id, t, s, start, eft in decisions:
        occupants[s].append((dag_id, t))

    for s, (sx, sy) in server_pos.items():
        used = bool(occupants[s])
        ax.text(sx, sy + 0.42, f"servidor {s}", ha="center", va="bottom",
                fontsize=7, color=("#444444" if used else "#BBBBBB"), zorder=5,
                bbox=dict(boxstyle="round,pad=0.12", facecolor="white", edgecolor="none", alpha=1.0))

    # posição x das tarefas: alinhada por rack (não por servidor), na
    # ordem cronológica real de início, para que a leitura da esquerda
    # para a direita corresponda à ordem de execução mesmo quando
    # tarefas concorrentes caem em servidores (linhas) diferentes do
    # mesmo rack.
    decisions_by_rack = {}
    for dag_id, t, s, start, eft in decisions:
        decisions_by_rack.setdefault(RACK_OF[s], []).append((dag_id, t, s, start))

    task_xy = {}
    for rack_id, items in decisions_by_rack.items():
        items_sorted = sorted(items, key=lambda d: (d[3], d[0], d[1]))
        n = len(items_sorted)
        rx, ry, rw, rh = rack_box[rack_id]
        span = min(0.62 * (n - 1), rw - 0.9)
        start_x = (rx + rw / 2) - span / 2
        step = span / max(n - 1, 1)
        for i, (dag_id, t, s, start) in enumerate(items_sorted):
            tx = start_x + i * step
            ty = server_pos[s][1]
            task_xy[(dag_id, t)] = (tx, ty)

    # fluxos cross-server (arcos coloridos por classificação)
    for f in metrics["flows"]:
        dag_id = f["dag_id"]
        x1, y1 = task_xy[(dag_id, f["from_task"])]
        x2, y2 = task_xy[(dag_id, f["to_task"])]

        if f["cross_group"]:
            color, style, rad = "#C00000", "-", 0.18
        elif f["cross_rack"]:
            color, style, rad = "#E8A33D", (0, (4, 2)), 0.22
        else:
            color, style, rad = "#808080", "-", 0.15

        ax.annotate(
            "", xy=(x2, y2), xytext=(x1, y1),
            arrowprops=dict(
                arrowstyle="-|>", color=color, linestyle=style,
                linewidth=1.4, shrinkA=9, shrinkB=9,
                connectionstyle=f"arc3,rad={rad}",
            ),
            zorder=2,
        )

    # nós das tarefas
    for (dag_id, t), (tx, ty) in task_xy.items():
        ax.add_patch(plt.Circle((tx, ty), 0.17, facecolor=TASK_COLOR[dag_id],
                                 edgecolor="black", linewidth=0.8, zorder=3))
        ax.text(tx, ty, t, ha="center", va="center", fontsize=6.6,
                color="white", fontweight="bold", zorder=4)

    ax.set_title(title, fontsize=TITLE_FONTSIZE, fontweight="bold", loc="left")
    ax.set_xlim(-0.3, total_w + 0.3)
    ax.set_ylim(-1.15, 5.2)
    ax.axis("off")

    caption = (
        f"Fluxos entre racks: {metrics['cross_rack_flows']}   |   "
        f"Fluxos entre grupos: {metrics['cross_group_flows']}   |   "
        f"Saltos: {metrics['total_hops']}   |   "
        f"Custo de comunicação: {metrics['estimated_comm_cost']:.2f}"
    )
    ax.text(total_w / 2, -0.85, caption, ha="center", va="center", fontsize=9.5,
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="#999999"))


LEGEND_HANDLES = [
    mpatches.Patch(facecolor=TASK_COLOR["W1"], edgecolor="black", label="Tarefas de W1"),
    mpatches.Patch(facecolor=TASK_COLOR["W2"], edgecolor="black", label="Tarefas de W2"),
    plt.Line2D([0], [0], color="#808080", lw=1.6, label="Fluxo entre servidores do mesmo rack"),
    plt.Line2D([0], [0], color="#E8A33D", lw=1.6, linestyle=(0, (4, 2)), label="Fluxo entre racks do mesmo grupo"),
    plt.Line2D([0], [0], color="#C00000", lw=1.6, label="Fluxo entre grupos"),
]


def save_single_scenario(placement, decisions, metrics, title, filename):
    fig, ax = plt.subplots(1, 1, figsize=(9.5, 5.6))

    draw_scenario(ax, placement, decisions, metrics, title)

    fig.legend(handles=LEGEND_HANDLES, loc="lower center", ncol=3,
               fontsize=9, frameon=False, bbox_to_anchor=(0.5, -0.06))

    plt.tight_layout(rect=[0, 0.08, 1, 1])
    plt.savefig(filename, dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(f"Imagem gerada: {filename}")


def main():
    placement_base, decisions_base = schedule(network_aware=False)
    history = build_history_from_execution(placement_base)
    placement_na, decisions_na = schedule(network_aware=True, history=history)

    metrics_base = compute_metrics(placement_base)
    metrics_na = compute_metrics(placement_na)

    save_single_scenario(
        placement_base, decisions_base, metrics_base,
        "HEFT baseline", "fig_placement_baseline.png",
    )
    save_single_scenario(
        placement_na, decisions_na, metrics_na,
        "HEFT com a camada com consciência da rede", "fig_placement_network_aware.png",
    )

    for label, m in [("baseline", metrics_base), ("network-aware", metrics_na)]:
        print(f"\n[{label}] cross_server={m['cross_server_flows']} "
              f"cross_rack={m['cross_rack_flows']} cross_group={m['cross_group_flows']} "
              f"hops={m['total_hops']} custo={m['estimated_comm_cost']:.2f}")


if __name__ == "__main__":
    main()
