from imports import os, json, math, scipy_stats
from network_metrics import extrair_eventos_trafego_por_tarefa

METRICAS_TRAFEGO = [
    "total_hops",
    "cross_server_flows",
    "cross_rack_flows",
    "cross_group_flows",
    "estimated_comm_cost",
]

NOMES_METRICAS = {
    "total_hops": "Hops totais",
    "cross_server_flows": "Cross-server flows",
    "cross_rack_flows": "Cross-rack flows",
    "cross_group_flows": "Cross-group flows",
    "estimated_comm_cost": "Custo estimado de comunicação",
}


def extrair_pares_metricas_tarefa(previous_events: dict, current_events: dict, metric_key: str) -> tuple[list, list]:
    """
    Alinha, tarefa a tarefa (mesma chave job_id/task_id), os valores de uma
    métrica entre a execução baseline e a execução network-aware. Tarefas que
    não existem nas duas execuções são descartadas do par.
    """
    baseline_valores = []
    atual_valores = []

    for chave, evento_atual in current_events.items():
        evento_anterior = previous_events.get(chave)

        if evento_anterior is None:
            continue

        baseline_valores.append(evento_anterior.get(metric_key, 0))
        atual_valores.append(evento_atual.get(metric_key, 0))

    return baseline_valores, atual_valores


def calcular_cohen_d_pareado(diferencas: list) -> float:
    n = len(diferencas)
    media = sum(diferencas) / n
    variancia = sum((d - media) ** 2 for d in diferencas) / (n - 1)
    desvio = math.sqrt(variancia)

    if desvio == 0:
        return 0.0

    return media / desvio


def rodar_teste_pareado(
    baseline_valores: list,
    atual_valores: list,
    metric_key: str,
    lower_is_better: bool = True
) -> dict:
    """
    Compara baseline x network-aware para uma métrica, pareado por tarefa:
    Shapiro-Wilk nas diferenças para checar normalidade, depois teste t
    pareado (se normal) ou Wilcoxon signed-rank (se não normal).
    """
    n = len(baseline_valores)

    if n < 3:
        return {
            "metric": metric_key,
            "n": n,
            "aviso": "Amostra insuficiente (n < 3) para teste de normalidade/significância.",
        }

    diferencas = [b - a for b, a in zip(baseline_valores, atual_valores)]

    if all(d == 0 for d in diferencas):
        return {
            "metric": metric_key,
            "n": n,
            "aviso": "Nenhuma diferença entre baseline e network-aware para esta métrica.",
        }

    shapiro_stat, shapiro_p = scipy_stats.shapiro(diferencas)
    normal = bool(shapiro_p >= 0.05)

    if normal:
        estatistica_teste, p_value = scipy_stats.ttest_rel(baseline_valores, atual_valores)
        teste_usado = "t_pareado"
        effect_size = calcular_cohen_d_pareado(diferencas)
    else:
        try:
            estatistica_teste, p_value = scipy_stats.wilcoxon(baseline_valores, atual_valores)
        except ValueError as erro:
            return {
                "metric": metric_key,
                "n": n,
                "aviso": f"Wilcoxon não pôde ser calculado: {erro}",
            }
        teste_usado = "wilcoxon"
        z_aproximado = scipy_stats.norm.isf(p_value / 2)
        effect_size = z_aproximado / math.sqrt(n)

    media_baseline = sum(baseline_valores) / n
    media_atual = sum(atual_valores) / n

    ganho_percentual_medio = None
    if media_baseline != 0:
        delta_percentual = ((media_atual - media_baseline) / media_baseline) * 100
        ganho_percentual_medio = -delta_percentual if lower_is_better else delta_percentual

    return {
        "metric": metric_key,
        "n": n,
        "shapiro_statistic": float(shapiro_stat),
        "shapiro_p_value": float(shapiro_p),
        "normal": normal,
        "teste_usado": teste_usado,
        "estatistica_teste": float(estatistica_teste),
        "p_value": float(p_value),
        "significativo": bool(p_value < 0.05),
        "effect_size": float(effect_size),
        "media_baseline": media_baseline,
        "media_network_aware": media_atual,
        "ganho_percentual_medio": ganho_percentual_medio,
    }


def analisar_significancia_estatistica(previous_execution_path: str, current_execution_path: str) -> dict:
    """
    Carrega os dois JSONs de execução já salvos em disco (baseline e
    network-aware) e roda, para cada métrica de tráfego, o teste pareado
    apropriado (t pareado ou Wilcoxon) tarefa a tarefa.
    """
    with open(previous_execution_path, "r", encoding="utf-8") as f:
        previous_data = json.load(f)

    with open(current_execution_path, "r", encoding="utf-8") as f:
        current_data = json.load(f)

    previous_events = extrair_eventos_trafego_por_tarefa(previous_data)
    current_events = extrair_eventos_trafego_por_tarefa(current_data)

    resultados = {}

    for metrica in METRICAS_TRAFEGO:
        baseline_valores, atual_valores = extrair_pares_metricas_tarefa(
            previous_events, current_events, metrica
        )

        if not baseline_valores:
            resultados[metrica] = {
                "metric": metrica,
                "n": 0,
                "aviso": "Nenhuma tarefa em comum entre as duas execuções para esta métrica.",
            }
            continue

        resultados[metrica] = rodar_teste_pareado(
            baseline_valores, atual_valores, metrica, lower_is_better=True
        )

    return resultados


def salvar_significancia_markdown(resultados: dict, output_path: str) -> None:
    linhas = []
    linhas.append("# Significância estatística (baseline vs network-aware, por tarefa)\n")
    linhas.append("| Métrica | n | Normal (Shapiro-Wilk) | Teste usado | p-valor | Significativo | Tamanho de efeito | Ganho médio |")
    linhas.append("|---|---:|---|---|---:|---:|---:|---:|")

    for metrica in METRICAS_TRAFEGO:
        nome = NOMES_METRICAS[metrica]
        resultado = resultados.get(metrica, {})

        if "aviso" in resultado:
            linhas.append(f"| {nome} | {resultado.get('n', '-')} | - | - | - | - | - | {resultado['aviso']} |")
            continue

        ganho = resultado["ganho_percentual_medio"]
        ganho_str = "-" if ganho is None else f"{ganho:.2f}%"

        linhas.append(
            "| "
            f"{nome} | "
            f"{resultado['n']} | "
            f"{'Sim' if resultado['normal'] else 'Não'} (p={resultado['shapiro_p_value']:.4f}) | "
            f"{resultado['teste_usado']} | "
            f"{resultado['p_value']:.4f} | "
            f"{'Sim' if resultado['significativo'] else 'Não'} | "
            f"{resultado['effect_size']:.4f} | "
            f"{ganho_str} |"
        )

    linhas.append("")
    linhas.append("## Interpretação")
    linhas.append("")
    linhas.append(
        "Cada linha compara, tarefa a tarefa (mesmo conjunto de tarefas nas duas execuções), o valor "
        "da métrica entre a execução baseline e a execução network-aware. O teste de Shapiro-Wilk "
        "verifica se as diferenças por tarefa seguem distribuição normal; se seguem, usa-se o teste t "
        "pareado, senão o teste de Wilcoxon (não-paramétrico). \"Significativo\" (p < 0.05) indica que "
        "a diferença observada dificilmente é fruto do acaso — ou seja, a melhoria (ou piora) da "
        "política network-aware para essa métrica é consistente entre as tarefas, e não apenas puxada "
        "por poucos casos isolados."
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))

    print(f"Relatório de significância estatística salvo em: {os.path.abspath(output_path)}")


def escapar_latex(texto: str) -> str:
    return str(texto).replace("_", "\\_")


def formatar_numero_pt_br(valor: float, casas_decimais: int) -> str:
    texto = f"{valor:.{casas_decimais}f}"
    if texto.startswith("-") and float(texto) == 0:
        texto = texto[1:]
    return texto.replace(".", ",")


NOMES_METRICAS_CURTOS = {
    "total_hops": "Hops",
    "cross_server_flows": "Cross-srv",
    "cross_rack_flows": "Cross-rack",
    "cross_group_flows": "Cross-grp",
    "estimated_comm_cost": "Custo",
}


def formatar_celula_ganho(resultado: dict | None) -> str:
    if not resultado or "aviso" in resultado:
        return "--"

    ganho = resultado.get("ganho_percentual_medio")
    if ganho is None:
        return "--"

    valor_str = formatar_numero_pt_br(ganho, 2) + "\\%"
    if resultado.get("significativo"):
        valor_str += "$^{*}$"

    return valor_str


def gerar_tabela_latex_significancia_consolidada(
    resultados_por_heuristica_cenario: dict,
    heuristica_order: list,
    scenario_order: list,
    scenario_labels: dict,
    caption: str,
    label: str,
) -> str:
    """
    Gera uma única tabela LaTeX (formato largo) consolidando, para um tipo de
    cenário (normal ou stress), todas as heurísticas x cenários network-aware
    nas linhas e uma coluna por métrica nas colunas. Cada célula mostra o
    ganho médio (%) tarefa a tarefa, com asterisco quando estatisticamente
    significativo (p < 0,05).
    """
    linhas = []
    linhas.append("\\begin{table}[htbp]")
    linhas.append("\\centering")
    linhas.append("\\small")
    linhas.append(f"\\caption{{{caption}}}")
    linhas.append(f"\\label{{{label}}}")
    linhas.append("\\begin{tabular}{ll" + "r" * len(NOMES_METRICAS_CURTOS) + "}")
    linhas.append("\\toprule")

    cabecalho_metricas = " & ".join(NOMES_METRICAS_CURTOS.values())
    linhas.append(f"Heurística & Cenário & {cabecalho_metricas} \\\\")
    linhas.append("\\midrule")

    for heuristica in heuristica_order:
        resultados_por_cenario = resultados_por_heuristica_cenario.get(heuristica, {})

        for scenario_name in scenario_order:
            resultado_cenario = resultados_por_cenario.get(scenario_name)
            rotulo_cenario = escapar_latex(scenario_labels.get(scenario_name, scenario_name))

            celulas = [
                formatar_celula_ganho(resultado_cenario.get(metric_key) if resultado_cenario else None)
                for metric_key in NOMES_METRICAS_CURTOS
            ]

            linhas.append(
                f"{heuristica.upper()} & {rotulo_cenario} & " + " & ".join(celulas) + " \\\\"
            )

        linhas.append("\\addlinespace")

    linhas.append("\\bottomrule")
    linhas.append("\\end{tabular}")
    linhas.append("")
    linhas.append("\\vspace{2mm}")
    linhas.append(
        "\\footnotesize Ganho médio percentual por tarefa (baseline vs.\\ network-aware). "
        "$^{*}$ indica significância estatística ($p<0{,}05$): a normalidade das diferenças foi "
        "avaliada via Shapiro-Wilk, com teste $t$ pareado quando normal e Wilcoxon signed-rank caso "
        "contrário. ``--'' indica dados insuficientes (nenhuma diferença entre as execuções ou menos "
        "de 3 pares de tarefas válidos)."
    )
    linhas.append("\\end{table}")

    return "\n".join(linhas)


def salvar_tabela_latex_significancia_consolidada(
    resultados_por_heuristica_cenario: dict,
    heuristica_order: list,
    scenario_order: list,
    scenario_labels: dict,
    caption: str,
    label: str,
    output_path: str,
) -> None:
    tex = gerar_tabela_latex_significancia_consolidada(
        resultados_por_heuristica_cenario, heuristica_order, scenario_order, scenario_labels, caption, label
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(tex + "\n")

    print(f"Tabela LaTeX consolidada de significância salva em: {os.path.abspath(output_path)}")
