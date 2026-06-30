from imports import os, datetime, copy
from io_loaders import carregar_jobs, carregar_topologia
from topology_utils import listar_servidores_compute
from simulation import executar_simulacao
from reporting import imprimir_resumo_final
from logs import gerar_nome_arquivo_execucao, salvar_json_execucao
from comparison import salvar_json_comparacao_execucoes, salvar_grafico_consolidado_heuristica
from export_topology import exportar_topologia_dot
import glob


# Configurações principais
# HEURISTICS_TO_RUN = ["easy", "heft", "cpop", "peft"]  # selecione as heurísticas
HEURISTICS_TO_RUN = ["peft"]
SCENARIO_TYPE = "stress"  # "normal" ou "stress"


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
    Junta todos os arquivos *_summary.md de todos os diretórios de heurísticas e cenários.
    """
    outputs_dir = os.path.join(project_dir, "outputs_experiments")
    summary_file = os.path.join(outputs_dir, f"summary_consolidado_{scenario_label}.md")
    os.makedirs(outputs_dir, exist_ok=True)

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

def executar_experimento_politica(base_scheduler_policy: str, jobs: dict, topology,
                                  topology_file: str, project_dir: str,
                                  experiment_timestamp: str, experiment_dataset_label: str):
    import copy
    experiment_name = f"experiment_{base_scheduler_policy}_{experiment_timestamp}"
    experiment_dir = os.path.join(project_dir, "outputs_experiments", base_scheduler_policy, experiment_name)
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

    comparison_paths_by_scenario = {}
    for scenario_name, scenario_config in SCENARIOS.items():
        scenario_dir = os.path.join(experiment_dir, scenario_name)
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

    # gera gráfico consolidado
    images_overleaf_dir = os.path.join(project_dir, "images_overleaf")
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
    jobs = carregar_jobs(jobs_file)
    topology = carregar_topologia(topology_file)
    experiment_dataset_label = inferir_rotulo_cenario(jobs_file)

    print(f"Scenario: {SCENARIO_TYPE}, Heurísticas: {', '.join(HEURISTICS_TO_RUN)}")
    print(f"Jobs carregados: {len(jobs)}")
    print(f"Nós da topologia: {topology.number_of_nodes()}")
    print(f"Arestas da topologia: {topology.number_of_edges()}")
    print(f"Servidores compute: {len(listar_servidores_compute(topology))}")
    print(f"Rótulo do cenário: {experiment_dataset_label}")

    for base_scheduler_policy in HEURISTICS_TO_RUN:
        executar_experimento_politica(
            base_scheduler_policy=base_scheduler_policy,
            jobs=jobs,
            topology=topology,
            topology_file=topology_file,
            project_dir=project_dir,
            experiment_timestamp=experiment_timestamp,
            experiment_dataset_label=experiment_dataset_label
        )

    print("\n=== Todos os experimentos finalizados ===")

if __name__ == "__main__":
    main()