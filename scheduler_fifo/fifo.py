"""
Compatibilidade com versões anteriores.

O artigo passa a tratar a política FIFO/FCFS simplificada como EASY no contexto
experimental. Este arquivo mantém aliases para evitar quebrar imports antigos.
"""
from easy import ordenar_easy, escolher_servidor_easy
from scheduler_utils import listar_servidores_livres, calcular_duracao_execucao
from scheduler_engine import escalonar_tarefas


ordenar_fifo = ordenar_easy
escolher_servidor_fifo = escolher_servidor_easy
escalonar_fifo = escalonar_tarefas
