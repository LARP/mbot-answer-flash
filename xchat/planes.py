"""Capa F: planes de varios pasos."""
import re

from .herramientas import REGISTRO
from .texto import sin_tildes


class PlanesMixin:
    VERBOS = ("abre abri abras abrir ejecuta ejecutar inicia iniciar lanza lanzar arranca arrancar corre correr pon "
              "cierra cerrar mata matar termina terminar finaliza muestra mostrar ver lista listar dime ensena revisa "
              "revisar consulta haz hacer crea crear busca buscar copia copiar limpia limpiar ping tracert espera esperar "
              "abreme muestrame cierrame").split()
    _RE_CONN = None

    def dividir(self, texto):
        if PlanesMixin._RE_CONN is None:
            v = "|".join(self.VERBOS)
            PlanesMixin._RE_CONN = re.compile(
                r"\s*(?:;|,?\s*\by\s+(?:luego|despues|tambien)\b|,?\s*\b(?:luego|despues|ademas)\b"
                r"|,\s*(?:y\s+)?(?=(?:%s)\b)|\s\by\s+(?=(?:%s)\b))\s*" % (v, v), re.I)
        partes = []
        for seg in re.findall(r'"[^"]*"|[^"]+', texto):
            if seg.startswith('"'):
                partes.append(seg)
                continue
            plano = sin_tildes(seg)
            ult = 0
            for m in PlanesMixin._RE_CONN.finditer(plano):
                partes.append(seg[ult:m.start()]); partes.append(None)
                ult = m.end()
            partes.append(seg[ult:])
        cl, act = [], ""
        for p in partes:
            if p is None:
                cl.append(act); act = ""
            else:
                act += p
        cl.append(act)
        cl = [re.sub(r"^\s*(?:primero|y|entonces)\s+", "", c.strip(" ,;.")).strip(" ,;.") for c in cl]
        cl = [c for c in cl if c]
        vs = set(self.VERBOS)
        for k in range(1, len(cl)):                       # "abre notepad y luego calculadora" -> hereda "abre"
            pri = sin_tildes(cl[k].split()[0].lower())
            if pri not in vs and len(cl[k].split()) <= 3:
                v0 = sin_tildes(cl[0].split()[0].lower())
                if v0 in vs:
                    cl[k] = cl[0].split()[0] + " " + cl[k]
        return cl

    def planear(self, texto):
        """Devuelve [Decision,...] si la frase son >=2 pasos resueltos; None en otro caso."""
        cl = self.dividir(texto)
        if len(cl) < 2:
            return None
        ds = [self.decidir(c) for c in cl]
        if any(d.accion == "ensenar" or d.ayuda or d.falta or (d.herr and REGISTRO[d.herr].peligro) for d in ds):
            return None
        return ds
