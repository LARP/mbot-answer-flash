"""Acciones confiables: ejecutar con validacion, verificacion posterior, registro de estados, detector de bucles y planes-borrador.

Flujo de `correr(cmd)`:  validar rutas -> detector de bucles -> preparar verificacion -> ejecutar -> registrar paso ->
verificar (sincrono en las pruebas, en un hilo con timeout ~3 s en la consola) -> refuerzo G (un fallo verificado resta).
"""
import os, queue, time
from dataclasses import dataclass

from . import herramientas as H
from .conocimiento import Conocimiento
from .registro import DetectorBucles, Registro
from .verificacion import Verificador

TTL_PLAN = 120.0                 # un plan de la capa F es un borrador: 2 minutos para confirmarlo


@dataclass
class Corrida:
    estado: str                  # ok | parcial | fallo | desconocido | rechazado | bloqueado | cancelado
    res: object = None
    id: int = 0
    detalle: object = ""


class Borrador:
    def __init__(self, id_, plan, frase, ts):
        self.id, self.plan, self.frase, self.ts, self.expira, self.estado = id_, plan, frase, ts, ts + TTL_PLAN, "pendiente"


class AccionesMixin:
    def _init_acciones(self, ruta_herr, ruta_ejec, ruta_notas, herramientas, plugins, ruta_conocimiento=None):
        self.usar_herramientas = herramientas
        self.reloj_ts = time.time
        self.ctx = H.Ctx(notas_path=ruta_notas, carpetas=self.carpetas)
        from .tools_locales import _leer_notas
        # buscador de conocimiento: la base se abre al primer uso (no se crea ningun archivo hasta entonces)
        self.conocimiento = Conocimiento(ruta_conocimiento or os.path.join(os.path.dirname(ruta_ejec), "conocimiento.db"),
                                         notas_fn=lambda: _leer_notas(self.ctx), hechos_fn=lambda: self.personal.hechos,
                                         tareas_fn=lambda: self.tareas, reloj=lambda: self.ctx.reloj())
        self.ctx.conocimiento = self.conocimiento
        self.herr = H.GestorHerramientas(ruta_herr)
        self.registro = Registro(ruta_ejec, reloj=lambda: self.reloj_ts())
        self.bucles = DetectorBucles(reloj=lambda: self.reloj_ts())
        self.verificador = Verificador()
        self.cola_verif = queue.Queue()
        self.borrador, self._n_borrador = None, 0
        self.plugins_errores = []
        if herramientas and plugins:
            _n, self.plugins_errores = H.cargar_plugins(plugins)

    # ---------------------------------------------------------------- preguntas abiertas (paso posterior a decidir())
    def responder_pregunta(self, d):
        """Si `d` es una pregunta abierta sin comando (accion "ensenar" y d.abierta), la contesta con la mejor frase del indice de
        conocimiento: accion "responder", `d.respuesta` con el texto y la fuente. NO ejecuta nada. Si no hay un trozo con buena
        puntuacion BM25 normalizada, `d` queda como estaba (sigue el flujo de "ensenar", sin comando).
        La consulta al indice vive aqui y no en decidir() para que decidir() siga por debajo de 3 ms (una consulta FTS5 cuesta 1-10 ms)."""
        if not getattr(d, "abierta", False) or d.accion != "ensenar" or not self.conocimiento.disponible:
            return d
        try:
            r = self.conocimiento.responder(d.texto, ahora=self.ctx.reloj())
        except Exception:
            r = None
        if r is not None:
            d.accion, d.respuesta, d.capa = "responder", r, "K"
        return d

    # ---------------------------------------------------------------- validacion
    def validar_decision(self, d):
        """(ok, motivo, cmd) para una decision de comando de cmd: rutas resueltas con realpath, existencia y rutas de sistema."""
        if d.herr:
            return True, "", d.cmd
        return H.validar_comando(d.cmd)

    # ---------------------------------------------------------------- herramientas internas
    def ejecutar_herramienta(self, d, frase=None):
        """Ejecuta la herramienta elegida en `d` (el usuario ya confirmo si era peligrosa). Registra y alimenta el detector de bucles."""
        h = H.REGISTRO.get(d.herr)
        if h is None:
            return H.Resultado(False, "herramienta desconocida")
        if self.herr.estado(h.nombre)[0] != "habilitada":
            return H.Resultado(False, f"@{h.nombre} esta {self.herr.estado(h.nombre)[0]}")
        vals, faltan = H.resolver_slots(h, d.hslots)
        if faltan:
            return H.Resultado(False, "Falta: " + ", ".join(f.nombre for f in faltan))
        clave = H.formato_cmd(h, vals)
        rem = self.bucles.bloqueado(clave)
        if rem:
            return H.Resultado(False, f"{clave} fallo 3 veces seguidas; bloqueada {rem:.0f} s")
        rid = self.registro.iniciar(frase or d.texto)
        t0 = time.perf_counter()
        r = H.ejecutar(h, vals, self.ctx)
        self.registro.paso(rid, clave, "ok" if r.ok else "fallo", (time.perf_counter() - t0) * 1000)
        self.registro.cerrar(rid)
        self.bucles.registrar(clave, r.ok)
        return r

    def completar_herramienta(self, d, respuestas):
        """Rellena los slots que faltaban (respuestas: {nombre: texto}) y devuelve (ok, motivo)."""
        h = H.REGISTRO[d.herr]
        for f in d.faltan:
            v = (respuestas.get(f.nombre) or "").strip().strip('"')
            if not v:
                return False, f"falta {f.nombre}"
            d.hslots[f.nombre] = int(v) if f.tipo == "n" and v.isdigit() else v
        d.falta, d.faltan = [], []
        return True, ""

    # ---------------------------------------------------------------- comandos de cmd
    def correr(self, cmd, frase=None, d=None, runner=None, asincrono=False):
        if runner is None:
            from .ejecucion import ejecutar_ex
            runner = ejecutar_ex
        frase = frase or (d.texto if d else cmd)
        rid = self.registro.iniciar(frase)
        return self._paso(rid, cmd, d, runner, asincrono, cerrar=True)

    def _paso(self, rid, cmd, d, runner, asincrono, cerrar):
        ok, motivo, cmd2 = H.validar_comando(cmd)
        if not ok:
            self.registro.paso(rid, cmd, "rechazado", 0)
            if cerrar:
                self.registro.cerrar(rid)
            return Corrida("rechazado", None, rid, motivo)
        rem = self.bucles.bloqueado(cmd2)
        if rem:
            self.registro.paso(rid, cmd2, "rechazado", 0)
            if cerrar:
                self.registro.cerrar(rid)
            return Corrida("bloqueado", None, rid, rem)
        spec = self.verificador.preparar(cmd2, self.desc.get("apps", []))
        t0 = time.perf_counter()
        res = runner(cmd2)
        ms = (time.perf_counter() - t0) * 1000
        if getattr(res, "cancelado", False):
            self.registro.paso(rid, cmd2, "cancelado", ms)
            if cerrar:
                self.registro.cerrar(rid)
            return Corrida("cancelado", res, rid)
        if asincrono:
            k = self.registro.paso(rid, cmd2, "running", ms)
            if cerrar:
                self.registro.cerrar(rid)
            self.verificador.verificar_async(spec, res, lambda est, det: self.cola_verif.put((rid, k, cmd2, d, est, det)))
            return Corrida("desconocido", res, rid, "verificando")
        est, det = self.verificador.verificar(spec, res)
        self.registro.paso(rid, cmd2, est, ms)
        if cerrar:
            self.registro.cerrar(rid)
        self._efectos(cmd2, d, est)
        return Corrida(est, res, rid, det)

    def _efectos(self, cmd, d, est):
        self.bucles.registrar(cmd, est != "fallo")
        self.aplicar_verificacion(d, est)

    def aplicar_verificacion(self, d, estado):
        """Alimenta el refuerzo G: un fallo verificado resta; ok / parcial / desconocido no cambian nada."""
        if estado == "fallo" and d is not None and not d.herr:
            return self.penalizar_verificado(d)
        return False

    def procesar_verificaciones(self):
        """Aplica los resultados de verificaciones hechas en hilos (se llama al principio de cada turno). Devuelve avisos."""
        avisos = []
        while True:
            try:
                rid, k, cmd, d, est, det = self.cola_verif.get_nowait()
            except queue.Empty:
                return avisos
            self.registro.actualizar_paso(rid, k, est)
            self._efectos(cmd, d, est)
            if est == "fallo":
                avisos.append(f"  ✗ No se pudo verificar '{cmd}': {det}. Cuenta como fallo.")
            elif est == "parcial":
                avisos.append(f"  ? '{cmd}': {det}.")

    # ---------------------------------------------------------------- planes (capa F) como borrador con TTL
    def proponer_plan(self, frase):
        """Planea y deja el resultado como borrador (2 min para confirmarlo). None si no hay plan."""
        plan = self.planear(frase)
        if not plan:
            return None
        if self.borrador is not None and self.borrador.estado == "pendiente":
            self.borrador.estado = "descartado"
        self._n_borrador += 1
        self.borrador = Borrador(self._n_borrador, plan, frase, self.reloj_ts())
        return self.borrador

    def confirmar_plan(self, id_=None):
        """(estado, plan): 'ok' solo UNA vez y dentro del TTL; despues 'repetido', 'expirado', 'descartado' o 'inexistente'."""
        b = self.borrador
        if b is None or (id_ is not None and b.id != id_):
            return ("descartado" if id_ is not None and id_ < self._n_borrador else "inexistente"), None
        if b.estado == "confirmado":
            return "repetido", None
        if b.estado != "pendiente":
            return b.estado, None
        if self.reloj_ts() > b.expira:
            b.estado = "expirado"
            return "expirado", None
        b.estado = "confirmado"
        return "ok", b.plan

    def correr_plan(self, ds, frase, runner=None, asincrono=False, aprender=True, mostrar=None):
        """Ejecuta los pasos de un plan ya confirmado y lo registra como una sola ejecucion. Se detiene en el primer fallo."""
        if runner is None:
            from .ejecucion import ejecutar_ex
            runner = ejecutar_ex
        rid = self.registro.iniciar(frase)
        for p in ds:
            if p.herr:
                r = H.ejecutar(H.REGISTRO[p.herr], H.resolver_slots(H.REGISTRO[p.herr], p.hslots)[0], self.ctx)
                self.registro.paso(rid, p.cmd, "ok" if r.ok else "fallo", 0)
                if mostrar:
                    mostrar("  " + r.texto)
                if not r.ok:
                    break
                continue
            c = self._paso(rid, p.cmd, p, runner, asincrono, cerrar=False)
            if c.estado in ("rechazado", "bloqueado", "cancelado", "fallo"):
                break
            if aprender:
                self.aprender(p.texto, p.cmd)
        self.registro.cerrar(rid)
        return rid

    # ---------------------------------------------------------------- comandos de consola
    def comando_acciones(self, frase):
        """!herramientas, !herramienta on|off X, !historial -> texto; None si no es de este modulo."""
        p = frase.strip().split(None, 1)
        if not p:
            return None
        c, arg = p[0].lower(), (p[1] if len(p) > 1 else "")
        if c == "!herramientas":
            return self.herr.texto() + ("\n" + "\n".join(f"  plugin con error: {f}: {e}" for f, e in self.plugins_errores) if self.plugins_errores else "")
        if c == "!herramienta":
            r = self.herr.comando(arg)
            self._cache_an.clear()
            return r
        if c == "!historial":
            return self.registro.texto_historial(10)
        if c in ("!indexar", "!reindexar", "!fuentes", "!desindexar", "!buscar"):
            return self._comando_conocimiento(c, arg)
        return None

    def _comando_conocimiento(self, c, arg):
        """!indexar <carpeta>  !reindexar  !fuentes  !desindexar <carpeta>  !buscar <consulta>"""
        K = self.conocimiento
        arg = arg.strip().strip('"')
        if not K.disponible:
            return "  Este SQLite no tiene FTS5: el buscador de conocimiento no esta disponible."
        if c == "!fuentes":
            return K.texto_fuentes()
        if c == "!buscar":
            return "\n".join("  " + x for x in K.buscar(arg).texto().splitlines()) if arg else "  Uso: !buscar <consulta>  (ej. !buscar \"red inalambrica\" -router ext:md)"
        if c == "!reindexar":
            t0 = time.perf_counter()
            st = K.reindexar()
            return (f"  Reindexado en {time.perf_counter() - t0:.2f} s: {st['nuevos']} nuevos, {st['modificados']} modificados, {st['tocados']} solo con otra fecha, "
                    f"{st['borrados']} borrados, {st['sin_cambios']} sin cambios" + (f", {st['omitidos']} omitidos (tamano o ilegibles)" if st["omitidos"] else "")
                    + (" (tope de archivos)" if st["tope"] else "") + ".")
        if not arg:
            return f"  Uso: {c} <carpeta>"
        if c == "!indexar":
            t0 = time.perf_counter()
            try:
                st = K.indexar_carpeta(arg)
            except ValueError as e:
                return f"  {e}"
            return (f"  Indexada en {time.perf_counter() - t0:.2f} s: {st['archivos']} archivos, {st['trozos']} trozos"
                    + (f", {st['omitidos']} omitidos (mas de {K.max_archivo // 1024 // 1024} MB o ilegibles)" if st["omitidos"] else "")
                    + (f" (tope de {K.max_archivos} archivos)" if st["tope"] else "") + ". Usa !reindexar para refrescarla.")
        n = K.desindexar(arg)                                    # !desindexar
        return f"  Esa carpeta no estaba indexada (!fuentes)." if n is None else f"  Carpeta desindexada: {n} archivos quitados del indice."
