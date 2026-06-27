from imports import os, datetime, copy
from io_loaders import carregar_jobs, carregar_topologia
from topology_utils import listar_servidores_compute
from simulation import executar_simulacao
from reporting import imprimir_resumo_final
from logs import gerar_nome_arquivo_execucao, salvar_json_execucao
from comparison import (
    salvar_json_comparacao_execucoes,
    salvar_grafico_consolidado_heuristica,
)
from export_topology import exportar_topologia_dot


BASE_SCHEDULER_POLICIES = ["easy", "heft", "cpop", "peft"]
# BASE_SCHEDULER_POLICIES = ["peft"]


SCENARIOS = {
    "01_balanced": {
        "scenario_name": "01_balanced",
        "network_weight": 1.0,
        "metric_weights": {
            "cross_server": 0.25,
            "cross_rack": 0.25,
            "cross_group": 0.25,
            "comm_cost": 0.25,
        },
        "max_base_candidates": 20,
        "max_topology_candidates_per_pred": 20,
        "max_total_candidates": 100,
    },
    "02_rack_strict": {
        "scenario_name": "02_rack_strict",
        "network_weight": 1.0,
        "metric_weights": {
            "cross_server": 0.05,
            "cross_rack": 0.75,
            "cross_group": 0.10,
            "comm_cost": 0.10,
        },
        "max_base_candidates": 20,
        "max_topology_candidates_per_pred": 30,
        "max_total_candidates": 120,
    },
    "03_group_strict": {
        "scenario_name": "03_group_strict",
        "network_weight": 1.0,
        "metric_weights": {
            "cross_server": 0.05,
            "cross_rack": 0.10,
            "cross_group": 0.75,
            "comm_cost": 0.10,
        },
        "max_base_candidates": 20,
        "max_topology_candidates_per_pred": 30,
        "max_total_candidates": 120,
    },
    "04_comm_cost_strict": {
        "scenario_name": "04_comm_cost_strict",
        "network_weight": 1.0,
        "metric_weights": {
            "cross_server": 0.05,
            "cross_rack": 0.10,
            "cross_group": 0.10,
            "comm_cost": 0.75,
        },
        "max_base_candidates": 20,
        "max_topology_candidates_per_pred": 40,
        "max_total_candidates": 150,
    },
}


def inferir_rotulo_cenario(jobs_file: str, topology_file: str) -> str:
    """
    Retorna o rótulo usado nos nomes dos artefatos do artigo.
    Ex.: peft_normal_grouped_chart.png
         peft_stress_grouped_chart.png
    """
    texto = f"{jobs_file} {topology_file}".lower()

    if "stress" in texto or "stressed" in texto:
        return "stress"

    return "normal"


def executar_experimento_politica(
    base_scheduler_policy: str,
    jobs: dict,
    topology,
    topology_file: str,
    project_dir: str,
    experiment_timestamp: str,
    experiment_dataset_label: str,
) -> None:
    experiment_name = f"experiment_{base_scheduler_policy}_{experiment_timestamp}"

    experiment_dir = os.path.join(
        project_dir,
        "outputs_experiments",
        base_scheduler_policy,
        experiment_name,
    )

    graphs_dir = os.path.join(experiment_dir, "graphs")
    os.makedirs(experiment_dir, exist_ok=True)

    exportar_topologia_dot(
        topology_file=topology_file,
        output_dir=graphs_dir,
    )

    print("\n" + "=" * 80)
    print(f"Escalonador base: {base_scheduler_policy.upper()}")
    print(f"Rótulo do cenário: {experiment_dataset_label}")
    print(f"Diretório do experimento: {experiment_dir}")
    print("=" * 80)

    baseline_dir = os.path.join(
        experiment_dir,
        f"00_{base_scheduler_policy}_baseline",
    )
    os.makedirs(baseline_dir, exist_ok=True)

    print(f"\n=== Executando {base_scheduler_policy.upper()} puro ===")

    baseline_state = executar_simulacao(
        jobs=jobs,
        topology=topology,
        max_time=100000,
        scheduler_policy=base_scheduler_policy,
        base_scheduler_policy=base_scheduler_policy,
        network_weight=0.0,
        network_aware_config=None,
        output_dir=baseline_dir,
        usar_historico_network=False,
    )

    imprimir_resumo_final(baseline_state)

    nome_baseline = gerar_nome_arquivo_execucao(
        f"{base_scheduler_policy}_execution_trace"
    )
    caminho_baseline = os.path.join(baseline_dir, nome_baseline)

    salvar_json_execucao(
        state=baseline_state,
        output_path=caminho_baseline,
        policy=base_scheduler_policy,
        network_weight=0.0,
    )

    print(f"{base_scheduler_policy.upper()} baseline salvo em: {caminho_baseline}")

    comparison_paths_by_scenario = {}

    for scenario_name, scenario_config in SCENARIOS.items():
        print(
            f"\n=== Executando network-aware sobre "
            f"{base_scheduler_policy.upper()}: {scenario_name} ==="
        )

        scenario_dir = os.path.join(experiment_dir, scenario_name)
        os.makedirs(scenario_dir, exist_ok=True)

        network_aware_config = copy.deepcopy(scenario_config)
        network_aware_config["base_scheduler_policy"] = base_scheduler_policy

        state = executar_simulacao(
            jobs=jobs,
            topology=topology,
            max_time=100000,
            scheduler_policy="network_aware",
            base_scheduler_policy=base_scheduler_policy,
            network_weight=network_aware_config["network_weight"],
            network_aware_config=network_aware_config,
            output_dir=baseline_dir,
            usar_historico_network=True,
        )

        historico = state.get("historico_network", {})
        if historico.get("enabled"):
            print(f"Histórico carregado de: {historico.get('source_file')}")
            print(f"Modo do histórico: {historico.get('mode')}")
            print(f"Tasks com histórico: {len(historico.get('task_recommendations', {}))}")
        else:
            print("Histórico não carregado.")

        imprimir_resumo_final(state)

        nome_arquivo = gerar_nome_arquivo_execucao(
            "network_aware_execution_trace"
        )
        caminho_saida = os.path.join(scenario_dir, nome_arquivo)

        salvar_json_execucao(
            state=state,
            output_path=caminho_saida,
            policy="network_aware",
            network_weight=network_aware_config["network_weight"],
        )

        prefixo_artefatos = f"{base_scheduler_policy}_{experiment_dataset_label}_{scenario_name}"

        artefatos_comparacao = salvar_json_comparacao_execucoes(
            previous_execution_path=caminho_baseline,
            current_execution_path=caminho_saida,
            output_dir=scenario_dir,
            artifact_prefix=prefixo_artefatos,
        )

        comparison_json = artefatos_comparacao.get("comparison_json")
        if comparison_json:
            comparison_paths_by_scenario[scenario_name] = comparison_json

        print("Artefatos de comparação:")
        print(f"  JSON: {artefatos_comparacao.get('comparison_json')}")
        print(f"  Gráfico individual: {artefatos_comparacao.get('comparison_chart')}")
        print(f"  Resumo: {artefatos_comparacao.get('comparison_summary')}")

    images_overleaf_dir = os.path.join(project_dir, "images_overleaf")
    os.makedirs(images_overleaf_dir, exist_ok=True)

    caminho_grafico_consolidado = os.path.join(
        images_overleaf_dir,
        f"{base_scheduler_policy}_{experiment_dataset_label}_grouped_chart.png"
    )

    salvar_grafico_consolidado_heuristica(
        comparison_paths_by_scenario=comparison_paths_by_scenario,
        output_path=caminho_grafico_consolidado,
    )

    print("\nImagem consolidada gerada para o Overleaf:")
    print(f"  {caminho_grafico_consolidado}")

    print(f"\n=== Experimento {base_scheduler_policy.upper()} finalizado ===")
    print(f"Resultados em: {experiment_dir}")


def main():
    package_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(package_dir)

    # Cenário normal
    # jobs_file = os.path.join(project_dir, "datas/jobs.data")
    # topology_file = os.path.join(project_dir, "racks_spatial_distribution.md")

    # Cenário stress
    jobs_file = os.path.join(project_dir, "datas/jobs_stress.data")
    topology_file = os.path.join(project_dir, "racks_spatial_distribution_stress.md")

    experiment_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    jobs = carregar_jobs(jobs_file)
    topology = carregar_topologia(topology_file)
    experiment_dataset_label = inferir_rotulo_cenario(jobs_file, topology_file)

    print(f"Jobs carregados: {len(jobs)}")
    print(f"Nós da topologia: {topology.number_of_nodes()}")
    print(f"Arestas da topologia: {topology.number_of_edges()}")
    print(f"Servidores compute: {len(listar_servidores_compute(topology))}")
    print(f"Rótulo do cenário para artefatos: {experiment_dataset_label}")
    print(f"Políticas base: {', '.join(BASE_SCHEDULER_POLICIES)}")

    for base_scheduler_policy in BASE_SCHEDULER_POLICIES:
        executar_experimento_politica(
            base_scheduler_policy=base_scheduler_policy,
            jobs=jobs,
            topology=topology,
            topology_file=topology_file,
            project_dir=project_dir,
            experiment_timestamp=experiment_timestamp,
            experiment_dataset_label=experiment_dataset_label,
        )

    print("\n=== Todos os experimentos finalizados ===")


if __name__ == "__main__":
    main()