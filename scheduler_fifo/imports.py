"""
Imports centralizados do projeto.

Este arquivo concentra os imports que existiam no monolito original.
Os módulos usam apenas os nomes necessários a partir daqui.
"""

import math
import copy
import json
import os
from collections import deque
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
from scipy import stats as scipy_stats

from gvt import ler_jobs_data, agrupar_por_job, construir_grafos
from export_topology import parse_rack_data_with_coords, build_dragonfly_topology
