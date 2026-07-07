"""
Reconstrução da figura com os workflows de exemplo (W1, W2, W3, W4)
usados na dissertação (Seção 2.3.2).

Cada workflow é desenhado como um DAG simples: tarefas representadas
como retângulos coloridos (com nome, tempo de execução T e consumo de
rede/recurso), e dependências representadas como setas.
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch

TITLE_FONTSIZE = 20
LABEL_FONTSIZE = 15
LABEL_FONTSIZE_SMALL = 12

# ----------------------------------------------------------------------
# Função auxiliar para desenhar uma "tarefa" (nó do DAG) como um retângulo
# ----------------------------------------------------------------------
def draw_task(ax, x, y, w, h, label, color, fontsize=LABEL_FONTSIZE):
    rect = mpatches.Rectangle((x, y), w, h, facecolor=color,
                               edgecolor="black", linewidth=1.4, zorder=2)
    ax.add_patch(rect)
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            fontsize=fontsize, fontweight="bold", zorder=3)
    # retorna os pontos de ancoragem (centro esquerdo/direito) para as setas
    return {
        "left":   (x, y + h / 2),
        "right":  (x + w, y + h / 2),
        "top":    (x + w / 2, y + h),
        "bottom": (x + w / 2, y),
        "center": (x + w / 2, y + h / 2),
        "bbox":   (x, y, w, h),
    }


def draw_edge(ax, p_from, p_to):
    arrow = FancyArrowPatch(p_from, p_to,
                             arrowstyle="-|>", mutation_scale=18,
                             linewidth=1.4, color="black", zorder=1,
                             shrinkA=2, shrinkB=2)
    ax.add_patch(arrow)


def fit_axes(ax, nodes, pad=0.5):
    """Ajusta xlim/ylim do painel para o menor retângulo que envolve
    todos os nós, com uma margem pequena — remove espaço em branco."""
    xs0 = [n["bbox"][0] for n in nodes]
    ys0 = [n["bbox"][1] for n in nodes]
    xs1 = [n["bbox"][0] + n["bbox"][2] for n in nodes]
    ys1 = [n["bbox"][1] + n["bbox"][3] for n in nodes]
    ax.set_xlim(min(xs0) - pad, max(xs1) + pad)
    ax.set_ylim(min(ys0) - pad, max(ys1) + pad)


# ----------------------------------------------------------------------
# Figura com 2x2 painéis (W1, W2, W3, W4)
# ----------------------------------------------------------------------
fig, axes = plt.subplots(2, 2, figsize=(16, 10))

# ============================== W1 =====================================
ax = axes[0, 0]
ax.set_title("W1: Fluxo com 1 tarefa (T=2; Consumo=2)", fontsize=TITLE_FONTSIZE, fontweight="bold", loc="left")
n1 = draw_task(ax, 1, 1, 4, 2, "t0\nT=2s\nConsumo=2", "skyblue")
fit_axes(ax, [n1])
ax.axis("off")

# ============================== W2 =====================================
ax = axes[0, 1]
ax.set_title("W2: Fluxo com 1 tarefa (T=3; Consumo=1)", fontsize=TITLE_FONTSIZE, fontweight="bold", loc="left")
n2 = draw_task(ax, 1, 1, 6, 1.4, "t0\nT=3s\nConsumo=1", "khaki")
fit_axes(ax, [n2])
ax.axis("off")

# ============================== W3 =====================================
# 7 tarefas leves com dependências em padrão fork-join de 2 níveis:
#   t0 -> {t1, t2}
#   {t1, t2} -> {t3, t4, t5}   (conexão completa / cruzada)
#   {t3, t4, t5} -> t6
ax = axes[1, 0]
ax.set_title("W3: 7 tarefas leves e dependências\n(fork-join em 2 níveis)",
             fontsize=TITLE_FONTSIZE, fontweight="bold", loc="left")

color3 = "lightcoral"
w3_w, w3_h = 2.0, 1.4

nodes3 = {}
nodes3["t0"] = draw_task(ax, 0.5, 4.0, w3_w, w3_h, "t0\nT=1s\nConsumo=1", color3, LABEL_FONTSIZE_SMALL)
nodes3["t1"] = draw_task(ax, 3.5, 4.7, w3_w, w3_h, "t1\nT=1s\nConsumo=1", color3, LABEL_FONTSIZE_SMALL)
nodes3["t2"] = draw_task(ax, 3.5, 1.6, w3_w, w3_h, "t2\nT=1s\nConsumo=1", color3, LABEL_FONTSIZE_SMALL)
nodes3["t3"] = draw_task(ax, 7.2, 4.7, w3_w, w3_h, "t3\nT=1s\nConsumo=1", color3, LABEL_FONTSIZE_SMALL)
nodes3["t4"] = draw_task(ax, 7.2, 2.5, w3_w, w3_h, "t4\nT=1s\nConsumo=1", color3, LABEL_FONTSIZE_SMALL)
nodes3["t5"] = draw_task(ax, 7.2, 0.2, w3_w, w3_h, "t5\nT=1s\nConsumo=1", color3, LABEL_FONTSIZE_SMALL)
nodes3["t6"] = draw_task(ax, 10.9, 4.0, w3_w, w3_h, "t6\nT=1s\nConsumo=1", color3, LABEL_FONTSIZE_SMALL)

edges3 = [
    ("t0", "t1"), ("t0", "t2"),
    ("t1", "t3"), ("t1", "t4"), ("t1", "t5"),
    ("t2", "t3"), ("t2", "t4"), ("t2", "t5"),
    ("t3", "t6"), ("t4", "t6"), ("t5", "t6"),
]
for a, b in edges3:
    draw_edge(ax, nodes3[a]["right"], nodes3[b]["left"])

fit_axes(ax, list(nodes3.values()))
ax.axis("off")

# ============================== W4 =====================================
# 5 tarefas (t3 mais longa) com dependências cruzadas:
#   {t0, t1} -> {t2, t3}   (conexão completa / cruzada)
#   {t2, t3} -> t4
ax = axes[1, 1]
ax.set_title("W4: 5 tarefas (uma mais longa) e dependências", fontsize=TITLE_FONTSIZE, fontweight="bold", loc="left")

color4 = "mediumaquamarine"
w4_w, w4_h = 2.0, 1.4

nodes4 = {}
nodes4["t0"] = draw_task(ax, 0.5, 4.2, w4_w, w4_h, "t0\nT=1s\nConsumo=1", color4, LABEL_FONTSIZE_SMALL)
nodes4["t1"] = draw_task(ax, 0.5, 1.2, w4_w, w4_h, "t1\nT=1s\nConsumo=1", color4, LABEL_FONTSIZE_SMALL)
nodes4["t2"] = draw_task(ax, 5.0, 4.2, w4_w, w4_h, "t2\nT=1s\nConsumo=1", color4, LABEL_FONTSIZE_SMALL)
nodes4["t3"] = draw_task(ax, 5.0, 0.9, w4_w * 1.4, w4_h, "t3\nT=2s\nConsumo=1", color4, LABEL_FONTSIZE_SMALL)
nodes4["t4"] = draw_task(ax, 9.6, 4.2, w4_w, w4_h, "t4\nT=1s\nConsumo=1", color4, LABEL_FONTSIZE_SMALL)

edges4 = [
    ("t0", "t2"), ("t0", "t3"),
    ("t1", "t2"), ("t1", "t3"),
    ("t2", "t4"), ("t3", "t4"),
]
for a, b in edges4:
    draw_edge(ax, nodes4[a]["right"], nodes4[b]["left"])

fit_axes(ax, list(nodes4.values()))
ax.axis("off")

plt.subplots_adjust(left=0.02, right=0.98, top=0.94, bottom=0.02,
                     wspace=0.12, hspace=0.25)
plt.savefig("workflows_exemplo.png", dpi=200, bbox_inches="tight")
print("Figura salva com sucesso.")
