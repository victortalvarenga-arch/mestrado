import sys
import platform
import multiprocessing
import psutil
import networkx
import matplotlib
import pandas

print("=== Informações do ambiente de simulação ===")

# Sistema
print(f"Sistema operacional: {platform.system()} {platform.release()} ({platform.version()})")
print(f"Arquitetura: {platform.machine()}")

# Python
print(f"Python: {platform.python_version()}")

# Processador
try:
    import cpuinfo
    info = cpuinfo.get_cpu_info()
    print(f"Processador: {info['brand_raw']} ({multiprocessing.cpu_count()} núcleos)")
except ImportError:
    print(f"Processador: Modelo não disponível (núcleos: {multiprocessing.cpu_count()})")

# Memória
mem = psutil.virtual_memory()
print(f"Memória RAM: {mem.total / (1024 ** 3):.1f} GB")

# Bibliotecas
print(f"NetworkX: {networkx.__version__}")
print(f"Matplotlib: {matplotlib.__version__}")
print(f"Pandas: {pandas.__version__}")