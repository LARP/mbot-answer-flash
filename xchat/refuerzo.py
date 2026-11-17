"""Capa G: factor Beta y decaimiento de contadores."""
from .config import SEMIVIDA_REFUERZO


def fac_beta(a, f):
    """Factor de refuerzo: 1.0 sin datos, <1 con fallos, hasta 1.08 con muchos aciertos."""
    return min(1.08, 0.5 + (a + 1.0) / (a + f + 2.0))


def decaer(a, f, ts, ahora):
    k = 0.5 ** (max(0.0, ahora - ts) / SEMIVIDA_REFUERZO)
    return a * k, f * k
