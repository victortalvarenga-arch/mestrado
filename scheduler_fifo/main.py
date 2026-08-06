from imports import os, json, datetime, copy
from io_loaders import carregar_jobs, carregar_topologia
from topology_utils import listar_servidores_compute
from simulation import executar_simulacao
from reporting import imprimir_resumo_final
from logs import gerar_nome_arquivo_execucao, salvar_json_execucao, buscar_ultimo_log_execucao
from comparison import (
    salvar_json_comparacao_execucoes,
    salvar_grafico_consolidado_heuristica,
)
from statistical_tests import salvar_tabela_latex_significancia_consolidada
from export_topology import exportar_topologia_dot
import glob


# Configurações principais
HEURISTICS_TO_RUN = ["easy", "heft", "cpop", "peft"]  # selecione as heurísticas
# HEURISTICS_TO_RUN = ["peft"]
SCENARIO_TYPE = "normal"  # "normal" ou "stress"
REEXECUTAR_SIMULACOES = True  # False = reaproveita dados salvos e só regenera relatórios/gráficos

# Retomada de campanha interrompida (queda de energia, processo morto).
# Com True, continua o experimento mais recente de cada heurística: simula apenas
# os cenários sem trace íntegro em disco e reaproveita os já concluídos.
# Traces truncados são detectados e refeitos. Não tem efeito quando
# REEXECUTAR_SIMULACOES=False.
RETOMAR_CAMPANHA = True


# ---------------------------------------------------------------------------
# λ da Equação 1 do artigo:
#     Score(t, s) = λ * Score_base(s) + (1 - λ) * (Score_net(t, s) + B_hist(t, s))
#
# λ rege a importância da política base frente à camada consciente da rede:
#   λ = 1,0 → decisão inteiramente da heurística tradicional (igual ao baseline);
#   λ = 0,5 → base e rede com o mesmo peso;
#   λ = 0,0 → decisão inteiramente network-aware.
#
# Cada valor de LAMBDA_VALUES gera a campanha completa: as quatro configurações
# de pesos de métrica são executadas para todas as heurísticas naquele λ, com
# resultados, gráficos e tabela LaTeX próprios em uma subpasta por λ.
# ---------------------------------------------------------------------------
LAMBDA_VALUES = [0.0, 0.25, 0.50, 0.75, 1.0]

# Normalização de Score_base antes da Equação 1:
#   "candidates" → min-max entre os candidatos da decisão, mesma convenção de
#                  Score_net, mantendo os dois termos em [0,1];
#   "global"     → posição na fila de servidores livres dividida pelo total de
#                  livres (comportamento das execuções anteriores).
BASE_SCORE_MODE = "candidates"

PESOS_BALANCEADOS = {"cross_server": 0.25, "cross_rack": 0.25, "cross_group": 0.25, "comm_cost": 0.25}


WEIGHT_SCENARIOS = {
    "01_balanced": {
        "scenario_name": "01_balanced",
        "metric_weights": dict(PESOS_BALANCEADOS),
        "max_base_candidates": 20,
        "max_topology_candidates_per_pred": 20,
        "max_total_candidates": 100,
    },
    "02_rack_strict": {
        "scenario_name": "02_rack_strict",
        "metric_weights": {"cross_server": 0.05, "cross_rack": 0.75, "cross_group": 0.10, "comm_cost": 0.10},
        "max_base_candidates": 20,
        "max_topology_candidates_per_pred": 30,
        "max_total_candidates": 120,
    },
    "03_group_strict": {
        "scenario_name": "03_group_strict",
        "metric_weights": {"cross_server": 0.05, "cross_rack": 0.10, "cross_group": 0.75, "comm_cost": 0.10},
        "max_base_candidates": 20,
        "max_topology_candidates_per_pred": 30,
        "max_total_candidates": 120,
    },
    "04_comm_cost_strict": {
        "scenario_name": "04_comm_cost_strict",
        "metric_weights": {"cross_server": 0.05, "cross_rack": 0.10, "cross_group": 0.10, "comm_cost": 0.75},
        "max_base_candidates": 20,
        "max_topology_candidates_per_pred": 40,
        "max_total_candidates": 150,
    },
}


SCENARIO_LABELS = {
    "01_balanced": "Balanced",
    "02_rack_strict": "Rack Strict",
    "03_group_strict": "Group Strict",
    "04_comm_cost_strict": "Comm Cost Strict",
}

WEIGHT_SCENARIO_ORDER = list(WEIGHT_SCENARIOS.keys())


def formatar_lambda_latex(valor: float) -> str:
    """Formata λ com vírgula decimal, no padrão numérico usado no artigo."""
    return f"{valor:.2f}".replace(".", "{,}")


def rotulo_lambda(valor_lambda: float) -> str:
    """
    Identificador de diretório para um λ, ex.: 0,25 → "lambda_025".

    Sem vírgula nem ponto de propósito: o caminho entra em \\includegraphics no
    Overleaf, e vírgula no nome do arquivo quebra o parser do graphicx.
    """
    return f"lambda_{int(round(valor_lambda * 100)):03d}"


def construir_cenarios(valores_lambda: list) -> dict:
    """
    Monta a matriz completa de cenários: cada valor de λ recebe as quatro
    configurações de pesos de métrica, de modo que toda a campanha existente
    seja reproduzida integralmente em cada λ.

    A chave é única por combinação (λ, pesos) e o campo `output_subdir` define
    a subpasta λ em que os artefatos daquele cenário são gravados.
    """
    cenarios = {}

    for valor_lambda in sorted(valores_lambda):
        lambda_key = rotulo_lambda(valor_lambda)

        for weight_key, config_pesos in WEIGHT_SCENARIOS.items():
            chave = f"{lambda_key}_{weight_key}"

            config = copy.deepcopy(config_pesos)
            config.update({
                "scenario_name": chave,
                "lambda_base": float(valor_lambda),
                "base_score_mode": BASE_SCORE_MODE,
                "weight_scenario": weight_key,
                "lambda_key": lambda_key,
                "output_subdir": os.path.join(lambda_key, weight_key),
            })

            cenarios[chave] = config

    return cenarios


SCENARIOS = construir_cenarios(LAMBDA_VALUES)

# λ → chaves de cenário daquele λ, na ordem das configurações de pesos
CENARIOS_POR_LAMBDA = {
    rotulo_lambda(valor): [
        f"{rotulo_lambda(valor)}_{weight_key}"
        for weight_key in WEIGHT_SCENARIO_ORDER
    ]
    for valor in sorted(LAMBDA_VALUES)
}

LAMBDA_POR_ROTULO = {rotulo_lambda(valor): valor for valor in sorted(LAMBDA_VALUES)}

def inferir_rotulo_cenario(jobs_file: str) -> str:
    return "stress" if "stress" in os.path.basename(jobs_file).lower() else "normal"

def gerar_summary_consolidado(project_dir: str, scenario_label: str,
                              experiment_dirs: list | None = None):
    """
    Junta os arquivos *_summary.md do cenário informado (normal ou stress).

    Quando `experiment_dirs` é informado, agrega apenas os experimentos daquela
    campanha; caso contrário, varre todos os experimentos já gravados em disco.
    Restringir à campanha atual evita misturar execuções antigas, com outra
    parametrização, no mesmo resumo.
    """
    outputs_dir = os.path.join(project_dir, "outputs_experiments", scenario_label)
    summary_file = os.path.join(project_dir, "outputs_experiments", f"summary_consolidado_{scenario_label}.md")
    os.makedirs(os.path.dirname(summary_file), exist_ok=True)

    if experiment_dirs:
        md_files = []
        for experiment_dir in experiment_dirs:
            md_files.extend(
                glob.glob(os.path.join(experiment_dir, "**", "*_summary.md"), recursive=True)
            )
    else:
        md_files = glob.glob(os.path.join(outputs_dir, "**", "*_summary.md"), recursive=True)

    if not md_files:
        print("Nenhum summary individual encontrado. O summary consolidado ficará vazio.")
        return

    with open(summary_file, "w", encoding="utf-8") as outfile:
        outfile.write(f"# Resumo Consolidado de Todas as Execuções ({scenario_label})\n\n")
        for md_file in md_files:
            parts = md_file.replace(outputs_dir, "").strip(os.sep).split(os.sep)
            heur = parts[0]
            experiment = parts[1] if len(parts) > 2 else "unknown"
            outfile.write(f"\n## {heur} - {experiment} - {os.path.basename(md_file)}\n\n")
            with open(md_file, "r", encoding="utf-8") as infile:
                outfile.write(infile.read())
                outfile.write("\n\n---\n\n")

    print(f"Resumo consolidado criado em: {summary_file}")


def localizar_experimento_mais_recente(project_dir: str, scenario_label: str, base_scheduler_policy: str) -> str | None:
    """
    Localiza o diretório do experimento mais recente já executado para uma
    combinação de cenário (normal/stress) e heurística base.

    Usado quando REEXECUTAR_SIMULACOES=False, para reaproveitar dados já
    salvos em disco sem rodar a simulação novamente.
    """
    policy_dir = os.path.join(project_dir, "outputs_experiments", scenario_label, base_scheduler_policy)

    if not os.path.isdir(policy_dir):
        return None

    experimentos = [
        os.path.join(policy_dir, nome)
        for nome in os.listdir(policy_dir)
        if os.path.isdir(os.path.join(policy_dir, nome))
        and nome.startswith(f"experiment_{base_scheduler_policy}_")
    ]

    if not experimentos:
        return None

    return max(experimentos, key=lambda p: os.path.getmtime(p))


def experimento_compativel(experiment_dir: str, base_scheduler_policy: str) -> bool:
    """
    Verifica se um experimento em disco pertence à estrutura de cenários atual.

    Campanhas antigas gravavam os cenários direto na raiz do experimento
    ("01_balanced/"), enquanto a atual os agrupa por λ ("lambda_025/01_balanced/").
    Retomar um experimento antigo misturaria execuções de parametrizações
    diferentes no mesmo diretório, então qualquer subpasta fora do layout
    esperado invalida a retomada.
    """
    if not os.path.isdir(experiment_dir):
        return False

    permitidos = {"graphs", f"00_{base_scheduler_policy}_baseline"}
    permitidos.update(CENARIOS_POR_LAMBDA.keys())

    for nome in os.listdir(experiment_dir):
        if os.path.isdir(os.path.join(experiment_dir, nome)) and nome not in permitidos:
            return False

    return True


def localizar_experimento_retomavel(project_dir: str, scenario_label: str,
                                    base_scheduler_policy: str) -> str | None:
    """Experimento mais recente que pode ser continuado com a configuração atual."""
    experiment_dir = localizar_experimento_mais_recente(
        project_dir=project_dir,
        scenario_label=scenario_label,
        base_scheduler_policy=base_scheduler_policy
    )

    if experiment_dir is None:
        return None

    if not experimento_compativel(experiment_dir, base_scheduler_policy):
        print(
            f"  Experimento existente ignorado na retomada (estrutura antiga): "
            f"{os.path.basename(experiment_dir)}"
        )
        return None

    return experiment_dir


def trace_utilizavel(output_dir: str) -> str | None:
    """
    Retorna o trace mais recente de um diretório apenas se ele estiver completo.

    Uma campanha interrompida no meio da escrita (queda de energia, processo
    morto) deixa um JSON truncado, que quebraria a etapa de comparação. A
    verificação lê só o final do arquivo: `json.dump` fecha o objeto com "}",
    então um arquivo que não termina assim foi cortado.
    """
    caminho = buscar_ultimo_log_execucao(output_dir)

    if caminho is None:
        return None

    try:
        tamanho = os.path.getsize(caminho)
        if tamanho < 1024:
            return None

        with open(caminho, "rb") as f:
            f.seek(max(0, tamanho - 64))
            fim = f.read().strip()

        if not fim.endswith(b"}"):
            print(f"  Aviso: trace truncado, será refeito: {os.path.basename(caminho)}")
            return None
    except OSError:
        return None

    return caminho


def executar_experimento_politica(base_scheduler_policy: str, jobs: dict, topology,
                                  topology_file: str, project_dir: str,
                                  experiment_timestamp: str, experiment_dataset_label: str,
                                  reexecutar_simulacoes: bool = True,
                                  retomar_campanha: bool = False):
    import copy

    if reexecutar_simulacoes:
        experiment_dir = None

        # Retomada: continua o experimento mais recente desta heurística em vez
        # de abrir um novo, para aproveitar as simulações já concluídas.
        if retomar_campanha:
            experiment_dir = localizar_experimento_retomavel(
                project_dir=project_dir,
                scenario_label=experiment_dataset_label,
                base_scheduler_policy=base_scheduler_policy
            )

        if experiment_dir is None:
            experiment_name = f"experiment_{base_scheduler_policy}_{experiment_timestamp}"
            experiment_dir = os.path.join(
                project_dir, "outputs_experiments", experiment_dataset_label,
                base_scheduler_policy, experiment_name
            )

        graphs_dir = os.path.join(experiment_dir, "graphs")
        os.makedirs(experiment_dir, exist_ok=True)
        exportar_topologia_dot(topology_file=topology_file, output_dir=graphs_dir)

        print(f"\n=== Executando {base_scheduler_policy.upper()} ===")
        print(f"Diretório do experimento: {experiment_dir}")
        baseline_dir = os.path.join(experiment_dir, f"00_{base_scheduler_policy}_baseline")
        os.makedirs(baseline_dir, exist_ok=True)

        caminho_baseline = trace_utilizavel(baseline_dir) if retomar_campanha else None

        if caminho_baseline is not None:
            print(f"  baseline: reaproveitando {os.path.basename(caminho_baseline)}")
        else:
            baseline_state = executar_simulacao(
                jobs=jobs, topology=topology, max_time=100000,
                scheduler_policy=base_scheduler_policy,
                base_scheduler_policy=base_scheduler_policy,
                lambda_base=1.0, network_aware_config=None,
                output_dir=baseline_dir, usar_historico_network=False
            )
            imprimir_resumo_final(baseline_state)
            nome_baseline = gerar_nome_arquivo_execucao(f"{base_scheduler_policy}_execution_trace")
            caminho_baseline = os.path.join(baseline_dir, nome_baseline)
            salvar_json_execucao(state=baseline_state, output_path=caminho_baseline,
                                 policy=base_scheduler_policy, lambda_base=1.0)
    else:
        experiment_dir = localizar_experimento_mais_recente(
            project_dir=project_dir,
            scenario_label=experiment_dataset_label,
            base_scheduler_policy=base_scheduler_policy
        )

        if experiment_dir is None:
            raise FileNotFoundError(
                f"Nenhum experimento existente encontrado para '{base_scheduler_policy}' "
                f"no cenário '{experiment_dataset_label}'. "
                f"Rode com REEXECUTAR_SIMULACOES=True pelo menos uma vez antes."
            )

        print(f"\n=== Reaproveitando dados existentes de {base_scheduler_policy.upper()} ===")
        print(f"Diretório: {experiment_dir}")

        baseline_dir = os.path.join(experiment_dir, f"00_{base_scheduler_policy}_baseline")
        caminho_baseline = buscar_ultimo_log_execucao(baseline_dir)

        if caminho_baseline is None:
            raise FileNotFoundError(f"Nenhum trace de baseline encontrado em: {baseline_dir}")

        print(f"Baseline reaproveitado: {caminho_baseline}")

    comparison_paths_by_scenario = {}

    for scenario_name, scenario_config in SCENARIOS.items():
        scenario_dir = os.path.join(experiment_dir, scenario_config["output_subdir"])

        if reexecutar_simulacoes:
            os.makedirs(scenario_dir, exist_ok=True)

            caminho_saida = trace_utilizavel(scenario_dir) if retomar_campanha else None

            if caminho_saida is not None:
                print(f"  {scenario_name}: reaproveitando {os.path.basename(caminho_saida)}")
            else:
                network_aware_config = copy.deepcopy(scenario_config)
                network_aware_config["base_scheduler_policy"] = base_scheduler_policy
                lambda_cenario = network_aware_config["lambda_base"]
                print(f"  {scenario_name}: lambda = {lambda_cenario}")
                state = executar_simulacao(
                    jobs=jobs, topology=topology, max_time=100000,
                    scheduler_policy="network_aware",
                    base_scheduler_policy=base_scheduler_policy,
                    lambda_base=lambda_cenario,
                    network_aware_config=network_aware_config,
                    output_dir=baseline_dir, usar_historico_network=True
                )
                imprimir_resumo_final(state)
                nome_arquivo = gerar_nome_arquivo_execucao("network_aware_execution_trace")
                caminho_saida = os.path.join(scenario_dir, nome_arquivo)
                salvar_json_execucao(state=state, output_path=caminho_saida,
                                     policy="network_aware", lambda_base=lambda_cenario)
        else:
            caminho_saida = buscar_ultimo_log_execucao(scenario_dir)
            if caminho_saida is None:
                print(f"Aviso: nenhum trace encontrado para o cenário '{scenario_name}' em {scenario_dir}. Pulando.")
                continue

            print(f"  {scenario_name}: reaproveitando {caminho_saida}")

        artefatos_comparacao = salvar_json_comparacao_execucoes(
            previous_execution_path=caminho_baseline,
            current_execution_path=caminho_saida,
            output_dir=scenario_dir,
            artifact_prefix=f"{base_scheduler_policy}_{experiment_dataset_label}_{scenario_name}"
        )
        comparison_json = artefatos_comparacao.get("comparison_json")
        if comparison_json:
            comparison_paths_by_scenario[scenario_name] = comparison_json

    # um gráfico consolidado por λ, com as quatro configurações de pesos,
    # gravado na subpasta daquele λ
    for lambda_key, chaves_do_lambda in CENARIOS_POR_LAMBDA.items():
        caminhos_do_lambda = {
            weight_key: comparison_paths_by_scenario[chave]
            for weight_key, chave in zip(WEIGHT_SCENARIO_ORDER, chaves_do_lambda)
            if chave in comparison_paths_by_scenario
        }

        if not caminhos_do_lambda:
            continue

        lambda_images_dir = os.path.join(
            project_dir, "images_overleaf", experiment_dataset_label, lambda_key
        )
        os.makedirs(lambda_images_dir, exist_ok=True)

        caminho_grafico_consolidado = os.path.join(
            lambda_images_dir,
            f"{base_scheduler_policy}_{experiment_dataset_label}_grouped_chart.png"
        )
        salvar_grafico_consolidado_heuristica(
            comparison_paths_by_scenario=caminhos_do_lambda,
            output_path=caminho_grafico_consolidado,
            scenario_order=WEIGHT_SCENARIO_ORDER,
            scenario_labels=SCENARIO_LABELS,
        )
        print(f"Gráfico consolidado gerado: {caminho_grafico_consolidado}")

    print(f"\n=== Experimento {base_scheduler_policy.upper()} finalizado ===")
    print(f"Resultados em: {experiment_dir}")

    # resultados estatísticos organizados por λ e configuração de pesos, usados
    # depois para gerar uma tabela LaTeX consolidada por λ
    resultados_estatisticos_por_lambda = {}

    for lambda_key, chaves_do_lambda in CENARIOS_POR_LAMBDA.items():
        por_configuracao = {}

        for weight_key, chave in zip(WEIGHT_SCENARIO_ORDER, chaves_do_lambda):
            comparison_json_path = comparison_paths_by_scenario.get(chave)

            if comparison_json_path is None:
                continue

            with open(comparison_json_path, "r", encoding="utf-8") as f:
                por_configuracao[weight_key] = json.load(f).get("statistical_significance")

        resultados_estatisticos_por_lambda[lambda_key] = por_configuracao

    return resultados_estatisticos_por_lambda, experiment_dir


def main(scenario_type: str | None = None):
    package_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(package_dir)

    scenario_type = scenario_type or SCENARIO_TYPE

    if scenario_type.lower() == "stress":
        jobs_file = os.path.join(project_dir, "datas/jobs_stress.data")
        topology_file = os.path.join(project_dir, "racks_spatial_distribution_stress.md")
    else:
        jobs_file = os.path.join(project_dir, "datas/jobs.data")
        topology_file = os.path.join(project_dir, "racks_spatial_distribution.md")

    experiment_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    experiment_dataset_label = inferir_rotulo_cenario(jobs_file)

    jobs = None
    topology = None

    if REEXECUTAR_SIMULACOES:
        jobs = carregar_jobs(jobs_file)
        topology = carregar_topologia(topology_file)

    print(f"Scenario: {scenario_type}, Heurísticas: {', '.join(HEURISTICS_TO_RUN)}")
    print(f"Reexecutar simulações: {REEXECUTAR_SIMULACOES}")
    print(f"Retomar campanha interrompida: {RETOMAR_CAMPANHA}")

    if REEXECUTAR_SIMULACOES:
        print(f"Jobs carregados: {len(jobs)}")
        print(f"Nós da topologia: {topology.number_of_nodes()}")
        print(f"Arestas da topologia: {topology.number_of_edges()}")
        print(f"Servidores compute: {len(listar_servidores_compute(topology))}")

    print(f"Rótulo do cenário: {experiment_dataset_label}")

    print(f"Valores de lambda avaliados: {LAMBDA_VALUES}")
    print(f"Configurações de pesos por lambda: {', '.join(WEIGHT_SCENARIO_ORDER)}")

    resultados_estatisticos_por_heuristica = {}
    experiment_dirs = []

    for base_scheduler_policy in HEURISTICS_TO_RUN:
        resultados, experiment_dir = executar_experimento_politica(
            base_scheduler_policy=base_scheduler_policy,
            jobs=jobs,
            topology=topology,
            topology_file=topology_file,
            project_dir=project_dir,
            experiment_timestamp=experiment_timestamp,
            experiment_dataset_label=experiment_dataset_label,
            reexecutar_simulacoes=REEXECUTAR_SIMULACOES,
            retomar_campanha=RETOMAR_CAMPANHA
        )
        resultados_estatisticos_por_heuristica[base_scheduler_policy] = resultados
        experiment_dirs.append(experiment_dir)

    gerar_summary_consolidado(project_dir, experiment_dataset_label, experiment_dirs)

    # uma tabela LaTeX consolidada por λ, na mesma subpasta dos gráficos daquele λ
    for lambda_key, valor_lambda in LAMBDA_POR_ROTULO.items():
        resultados_do_lambda = {
            heuristica: (resultados or {}).get(lambda_key, {})
            for heuristica, resultados in resultados_estatisticos_por_heuristica.items()
        }

        lambda_images_dir = os.path.join(
            project_dir, "images_overleaf", experiment_dataset_label, lambda_key
        )
        os.makedirs(lambda_images_dir, exist_ok=True)

        caminho_tabela_consolidada = os.path.join(
            lambda_images_dir, f"significance_table_{experiment_dataset_label}.tex"
        )
        salvar_tabela_latex_significancia_consolidada(
            resultados_por_heuristica_cenario=resultados_do_lambda,
            heuristica_order=HEURISTICS_TO_RUN,
            scenario_order=WEIGHT_SCENARIO_ORDER,
            scenario_labels=SCENARIO_LABELS,
            caption=(
                f"Significância estatística (baseline vs.\\ network-aware, por tarefa) "
                f"no cenário {experiment_dataset_label}, com "
                f"$\\lambda = {formatar_lambda_latex(valor_lambda)}$."
            ),
            label=f"tab:significancia_{experiment_dataset_label}_{lambda_key}",
            output_path=caminho_tabela_consolidada,
        )
        print(f"Tabela LaTeX consolidada gerada: {caminho_tabela_consolidada}")

    print("\n=== Todos os experimentos finalizados ===")

if __name__ == "__main__":
    # `python main.py` usa SCENARIO_TYPE; `python main.py stress` sobrepõe
    # apenas o conjunto de carga/topologia, sem alterar o arquivo.
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)
