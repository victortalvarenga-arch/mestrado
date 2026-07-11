from imports import os, json, datetime, copy
from io_loaders import carregar_jobs, carregar_topologia
from topology_utils import listar_servidores_compute
from simulation import executar_simulacao
from reporting import imprimir_resumo_final
from logs import gerar_nome_arquivo_execucao, salvar_json_execucao, buscar_ultimo_log_execucao
from comparison import (
    salvar_json_comparacao_execucoes,
    salvar_grafico_consolidado_heuristica,
    SCENARIO_ORDER,
    SCENARIO_LABELS,
)
from statistical_tests import salvar_tabela_latex_significancia_consolidada
from export_topology import exportar_topologia_dot
import glob


# Configurações principais
HEURISTICS_TO_RUN = ["easy", "heft", "cpop", "peft"]  # selecione as heurísticas
# HEURISTICS_TO_RUN = ["peft"]
SCENARIO_TYPE = "stress"  # "normal" ou "stress"
REEXECUTAR_SIMULACOES = False  # False = reaproveita dados salvos e só regenera relatórios/gráficos


SCENARIOS = {
    "01_balanced": {
        "scenario_name": "01_balanced",
        "network_weight": 1.0,
        "metric_weights": {"cross_server": 0.25, "cross_rack": 0.25, "cross_group": 0.25, "comm_cost": 0.25},
        "max_base_candidates": 20,
        "max_topology_candidates_per_pred": 20,
        "max_total_candidates": 100,
    },
    "02_rack_strict": {
        "scenario_name": "02_rack_strict",
        "network_weight": 1.0,
        "metric_weights": {"cross_server": 0.05, "cross_rack": 0.75, "cross_group": 0.10, "comm_cost": 0.10},
        "max_base_candidates": 20,
        "max_topology_candidates_per_pred": 30,
        "max_total_candidates": 120,
    },
    "03_group_strict": {
        "scenario_name": "03_group_strict",
        "network_weight": 1.0,
        "metric_weights": {"cross_server": 0.05, "cross_rack": 0.10, "cross_group": 0.75, "comm_cost": 0.10},
        "max_base_candidates": 20,
        "max_topology_candidates_per_pred": 30,
        "max_total_candidates": 120,
    },
    "04_comm_cost_strict": {
        "scenario_name": "04_comm_cost_strict",
        "network_weight": 1.0,
        "metric_weights": {"cross_server": 0.05, "cross_rack": 0.10, "cross_group": 0.10, "comm_cost": 0.75},
        "max_base_candidates": 20,
        "max_topology_candidates_per_pred": 40,
        "max_total_candidates": 150,
    },
}

def inferir_rotulo_cenario(jobs_file: str) -> str:
    return "stress" if "stress" in os.path.basename(jobs_file).lower() else "normal"

def gerar_summary_consolidado(project_dir: str, scenario_label: str):
    """
    Junta todos os arquivos *_summary.md do cenário informado (normal ou stress),
    em todos os diretórios de heurísticas e cenários network-aware.
    """
    outputs_dir = os.path.join(project_dir, "outputs_experiments", scenario_label)
    summary_file = os.path.join(project_dir, "outputs_experiments", f"summary_consolidado_{scenario_label}.md")
    os.makedirs(os.path.dirname(summary_file), exist_ok=True)

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


def executar_experimento_politica(base_scheduler_policy: str, jobs: dict, topology,
                                  topology_file: str, project_dir: str,
                                  experiment_timestamp: str, experiment_dataset_label: str,
                                  reexecutar_simulacoes: bool = True):
    import copy

    if reexecutar_simulacoes:
        experiment_name = f"experiment_{base_scheduler_policy}_{experiment_timestamp}"
        experiment_dir = os.path.join(
            project_dir, "outputs_experiments", experiment_dataset_label,
            base_scheduler_policy, experiment_name
        )
        graphs_dir = os.path.join(experiment_dir, "graphs")
        os.makedirs(experiment_dir, exist_ok=True)
        exportar_topologia_dot(topology_file=topology_file, output_dir=graphs_dir)

        print(f"\n=== Executando {base_scheduler_policy.upper()} ===")
        baseline_dir = os.path.join(experiment_dir, f"00_{base_scheduler_policy}_baseline")
        os.makedirs(baseline_dir, exist_ok=True)

        baseline_state = executar_simulacao(
            jobs=jobs, topology=topology, max_time=100000,
            scheduler_policy=base_scheduler_policy,
            base_scheduler_policy=base_scheduler_policy,
            network_weight=0.0, network_aware_config=None,
            output_dir=baseline_dir, usar_historico_network=False
        )
        imprimir_resumo_final(baseline_state)
        nome_baseline = gerar_nome_arquivo_execucao(f"{base_scheduler_policy}_execution_trace")
        caminho_baseline = os.path.join(baseline_dir, nome_baseline)
        salvar_json_execucao(state=baseline_state, output_path=caminho_baseline,
                             policy=base_scheduler_policy, network_weight=0.0)
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
        scenario_dir = os.path.join(experiment_dir, scenario_name)

        if reexecutar_simulacoes:
            os.makedirs(scenario_dir, exist_ok=True)
            network_aware_config = copy.deepcopy(scenario_config)
            network_aware_config["base_scheduler_policy"] = base_scheduler_policy
            state = executar_simulacao(
                jobs=jobs, topology=topology, max_time=100000,
                scheduler_policy="network_aware",
                base_scheduler_policy=base_scheduler_policy,
                network_weight=network_aware_config["network_weight"],
                network_aware_config=network_aware_config,
                output_dir=baseline_dir, usar_historico_network=True
            )
            imprimir_resumo_final(state)
            nome_arquivo = gerar_nome_arquivo_execucao("network_aware_execution_trace")
            caminho_saida = os.path.join(scenario_dir, nome_arquivo)
            salvar_json_execucao(state=state, output_path=caminho_saida,
                                 policy="network_aware", network_weight=network_aware_config["network_weight"])
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

    # gera summary consolidado sempre, separado por cenário
    gerar_summary_consolidado(project_dir, experiment_dataset_label)

    # gera gráfico consolidado, também separado por cenário
    images_overleaf_dir = os.path.join(project_dir, "images_overleaf", experiment_dataset_label)
    os.makedirs(images_overleaf_dir, exist_ok=True)
    caminho_grafico_consolidado = os.path.join(
        images_overleaf_dir, f"{base_scheduler_policy}_{experiment_dataset_label}_grouped_chart.png"
    )
    salvar_grafico_consolidado_heuristica(
        comparison_paths_by_scenario=comparison_paths_by_scenario,
        output_path=caminho_grafico_consolidado
    )
    print(f"Gráfico consolidado gerado: {caminho_grafico_consolidado}")
    print(f"\n=== Experimento {base_scheduler_policy.upper()} finalizado ===")
    print(f"Resultados em: {experiment_dir}")

    # resultados estatísticos por cenário, usados depois para a tabela LaTeX consolidada
    resultados_estatisticos_por_cenario = {}
    for scenario_name, comparison_json_path in comparison_paths_by_scenario.items():
        with open(comparison_json_path, "r", encoding="utf-8") as f:
            resultados_estatisticos_por_cenario[scenario_name] = json.load(f).get("statistical_significance")

    return resultados_estatisticos_por_cenario


def main():
    package_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(package_dir)

    if SCENARIO_TYPE.lower() == "stress":
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

    print(f"Scenario: {SCENARIO_TYPE}, Heurísticas: {', '.join(HEURISTICS_TO_RUN)}")
    print(f"Reexecutar simulações: {REEXECUTAR_SIMULACOES}")

    if REEXECUTAR_SIMULACOES:
        print(f"Jobs carregados: {len(jobs)}")
        print(f"Nós da topologia: {topology.number_of_nodes()}")
        print(f"Arestas da topologia: {topology.number_of_edges()}")
        print(f"Servidores compute: {len(listar_servidores_compute(topology))}")

    print(f"Rótulo do cenário: {experiment_dataset_label}")

    resultados_estatisticos_por_heuristica = {}

    for base_scheduler_policy in HEURISTICS_TO_RUN:
        resultados_estatisticos_por_heuristica[base_scheduler_policy] = executar_experimento_politica(
            base_scheduler_policy=base_scheduler_policy,
            jobs=jobs,
            topology=topology,
            topology_file=topology_file,
            project_dir=project_dir,
            experiment_timestamp=experiment_timestamp,
            experiment_dataset_label=experiment_dataset_label,
            reexecutar_simulacoes=REEXECUTAR_SIMULACOES
        )

    images_overleaf_dir = os.path.join(project_dir, "images_overleaf", experiment_dataset_label)
    os.makedirs(images_overleaf_dir, exist_ok=True)
    caminho_tabela_consolidada = os.path.join(
        images_overleaf_dir, f"significance_table_{experiment_dataset_label}.tex"
    )
    salvar_tabela_latex_significancia_consolidada(
        resultados_por_heuristica_cenario=resultados_estatisticos_por_heuristica,
        heuristica_order=HEURISTICS_TO_RUN,
        scenario_order=SCENARIO_ORDER,
        scenario_labels=SCENARIO_LABELS,
        caption=f"Significância estatística (baseline vs.\\ network-aware, por tarefa) no cenário {experiment_dataset_label}.",
        label=f"tab:significancia_{experiment_dataset_label}",
        output_path=caminho_tabela_consolidada,
    )
    print(f"Tabela LaTeX consolidada gerada: {caminho_tabela_consolidada}")

    print("\n=== Todos os experimentos finalizados ===")

if __name__ == "__main__":
    main()
