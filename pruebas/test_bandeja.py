"""Pruebas de calidad del dato y de la bandeja: python -m pytest pruebas -q"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from bandeja import flujo as F  # noqa: E402
from bandeja import usuarios as U  # noqa: E402
from bandeja.almacen import AlmacenSQLite, Conflicto  # noqa: E402
from calidad import reglas as R  # noqa: E402
from calidad.actores import Actor, Catalogo, construir_desde_base, limpiar_nombre  # noqa: E402

HOY = date(2026, 11, 9)
CHEQUEO = {c: True for c in F.LISTA_CHEQUEO}


def valida(**cambios):
    d = {
        "VERIFICACIÓN: Colombia hace parte de los países beneficiarios": "checked",
        "VERIFICACIÓN: Página web correcta y activa": "checked",
        "Nombre de la Convocatoria": "Becas de excelencia para maestría (Excellence Scholarships)",
        "Modalidad": "Beca", "Fecha de Registro": "9/11/2026", "Reportado por": "Natalia",
        "¿La convocatoria es permanente?": "No", "Fecha Límite de Aplicación": "1/2/2027",
        "Nombre de la Fuente": "AECID - Agencia Española de Cooperación Internacional para el Desarrollo",
        "Descripción": "Programa de becas para que profesionales de América Latina cursen estudios de maestría en España.",
        "Objetivos General y Específicos": "Fortalecer capacidades de profesionales latinoamericanos.",
        "Dirigida a (tipo de publico)": "Ciudadanos", "Áreas temáticas de interés": "Educación",
        "Financiación": "50000", "Tipo de monto": "Por beneficiario o proyecto",
        "Observaciones sobre el financiamiento": "Cubre matrícula y manutención.", "Ámbito Geográfico": "Regional",
        "Cómo aplicar": "https://www.aecid.es/becas-2027", "Idioma/s": "Español",
        "Observaciones a la fecha límite de aplicación": "Cierre a las 23:59 hora de España.",
        "Email para mayor información": "becas@aecid.es", "Link de la Fuente Oferente": "https://www.aecid.es",
        "Linea Prioritaria ENCI": "4. Fortalecer las capacidades institucionales para la gestión de la cooperación",
        "Plan Marco de Implementación": "No Aplica", "Sector Gobierno": "Educación Nacional",
        "ODS": "4. Educación de Calidad", "Metas PND": "6. Seguridad Humana y Justicia Social",
        "Comite de Ayuda al Desarrollo": "Educación", "Oficial / No Oficial": "No Oficial",
        "¿Se puede publicar en la web?": "checked",
        "Requisitos y condiciones de participación": (
            "Perfil de los aspirantes: profesionales de América Latina\nNivel de formación: maestría\n"
            "Requisitos académicos: título universitario\nCobertura: matrícula y manutención\n"
            "Condiciones de participación: no estar matriculado en España\nProcedimiento de postulación: formulario en línea"),
    }
    d.update(cambios)
    return d


@pytest.fixture()
def almacen(tmp_path):
    a = AlmacenSQLite(tmp_path / "base.db")
    a.reemplazar_catalogo(construir_desde_base(pd.read_csv(RAIZ / "datos" / "airtable_actual.csv")))
    return a


# --- reglas -------------------------------------------------------------------
def test_registro_valido_sin_errores(almacen):
    norm, h = R.validar(valida(), almacen.catalogo(), [], hoy=HOY)
    assert not [x for x in h if x.nivel == "Error"], [x.__dict__ for x in h]
    assert norm["Oficial / No Oficial"] == "Oficial"          # se corrige según el tipo de actor
    assert norm["Tiempo de vencimiento es mayor a un mes y una semana"] == "checked"


@pytest.mark.parametrize("cambio,regla", [
    ({"Áreas temáticas de interés": "Educación,Salud,Paz,Género"}, "R04"),
    ({"Nombre de la Fuente": "*NUEVO", "Nombre de actor en CICLOPE": ""}, "R05"),
    ({"¿La convocatoria es permanente?": "Si"}, "R09"),
    ({"Fecha Límite de Aplicación": ""}, "R09"),
    ({"Fecha Límite de Aplicación": "1/1/2026"}, "R09"),
    ({"Link de la Fuente Oferente": "https//ffngos.org/x"}, "R11"),
    ({"Email para mayor información": "https://www.aecid.es/contacto"}, "R12"),
    ({"Financiación": "cincuenta mil"}, "R13"),
    ({"Tipo de monto": ""}, "R13"),
    ({"Modalidad": "Becas"}, "R03"),
    ({"VERIFICACIÓN: Colombia hace parte de los países beneficiarios": ""}, "R01"),
    ({"Descripción": ""}, "R02"),
])
def test_cada_regla_detecta_su_error(almacen, cambio, regla):
    _, h = R.validar(valida(**cambio), almacen.catalogo(), [], hoy=HOY)
    assert any(x.regla == regla and x.nivel == "Error" for x in h), [x.__dict__ for x in h]


def test_duplicado_por_enlace(almacen):
    base = [valida()]
    _, h = R.validar(valida(**{"Nombre de la Convocatoria": "Otra"}), almacen.catalogo(), base, hoy=HOY)
    assert any(x.regla == "R16" and x.nivel == "Error" for x in h)


def test_limpieza_de_nombres_de_actor():
    assert limpiar_nombre("THE BRITISH ACADEMY (No está creado)") == "THE BRITISH ACADEMY"
    assert limpiar_nombre("Earthshot Prize (Creado)") == "Earthshot Prize"
    assert limpiar_nombre("Universidad de Twente/University Twente (Creado)") == "Universidad de Twente/University Twente"


# --- flujo --------------------------------------------------------------------
def test_aprobar_exige_lista_de_chequeo(almacen):
    item, _ = F.ingresar(almacen, valida(), "Registro manual", "Ana", hoy=HOY)
    with pytest.raises(F.ErrorFlujo, match="lista de chequeo"):
        F.aprobar(almacen, item, item["datos"], "Ana", {}, hoy=HOY)


def test_aprobar_bloquea_con_errores(almacen):
    item, _ = F.ingresar(almacen, valida(**{"Descripción": ""}), "Registro manual", "Ana", hoy=HOY)
    with pytest.raises(F.ErrorFlujo, match="Corrige primero"):
        F.aprobar(almacen, item, item["datos"], "Ana", CHEQUEO, hoy=HOY)
    assert almacen.items("Por revisar")


def test_aprobada_entra_a_la_base(almacen):
    antes = len(almacen.base())
    item, _ = F.ingresar(almacen, valida(), "Registro manual", "Ana", hoy=HOY)
    estado, _ = F.aprobar(almacen, item, item["datos"], "Ana", CHEQUEO, hoy=HOY)
    assert estado == "Aprobada"
    assert len(almacen.base()) == antes + 1
    assert almacen.base()[-1]["Oficial / No Oficial"] == "Oficial"


def test_actor_nuevo_espera_y_se_libera_al_crearlo(almacen):
    F.agregar_actor(almacen, "Fundación Ejemplo / Example Foundation", "Fundación / filantropía", "Ana")
    datos = valida(**{"Nombre de la Fuente": "Fundación Ejemplo / Example Foundation", "Cómo aplicar": "https://example.org/call"})
    item, _ = F.ingresar(almacen, datos, "Mapeo automático · CAM-DE", "Mapeo automático", hoy=HOY)
    antes = len(almacen.base())
    estado, _ = F.aprobar(almacen, item, item["datos"], "Ana", CHEQUEO, hoy=HOY)
    assert estado == "Actor pendiente de crear"
    assert len(almacen.base()) == antes                       # no entra a la base todavía
    actor, res = F.registrar_actor_creado(almacen, "Fundación Ejemplo / Example Foundation",
                                          "Fundación Ejemplo / Example Foundation", "Luis", hoy=HOY)
    assert actor.estado_ciclope == "Creado en CICLOPE"
    assert res and res[0][1] == "Aprobada"
    nueva = almacen.base()[-1]
    assert nueva["Oficial / No Oficial"] == "No Oficial"


def test_descartar_exige_motivo(almacen):
    item, _ = F.ingresar(almacen, valida(), "Registro manual", "Ana", hoy=HOY)
    with pytest.raises(F.ErrorFlujo):
        F.descartar(almacen, item, "Ana", " ")
    F.descartar(almacen, item, "Ana", "Duplicada")
    assert almacen.items("Descartada")[0]["observacion"] == "Duplicada"


# --- usuarios -----------------------------------------------------------------
def test_usuarios(almacen):
    clave = U.crear(almacen, "Nata", "Natalia Gómez", "admin")
    sesion, _ = U.verificar(almacen, "NATA", clave)
    assert sesion["rol"] == "admin" and sesion["debe_cambiar"] and sesion["sin_codigos"]
    assert U.verificar(almacen, "nata", "otra-clave")[0] is None
    almacen.activar_usuario("nata", False)
    assert U.verificar(almacen, "nata", clave)[0] is None
    with pytest.raises(ValueError):
        U.crear(almacen, "xyz", "X", "registrador")


@pytest.mark.parametrize("clave,motivo", [
    ("Corta#1a", "menos de 10"),
    ("sinmayuscula#2027", "mayúscula"),
    ("SINMINUSCULA#2027", "minúscula"),
    ("SinNumero#Bogota", "número"),
    ("SinSimbolo2027Ab", "símbolo"),
    ("Natalia#2027xy", "usuario o tu nombre"),
    ("MiColombia#2027", "palabra común"),
    ("Segura#1234Ab", "secuencia"),
    ("Seguraaaa#27B", "secuencia"),
])
def test_politica_de_contrasenas(clave, motivo):
    assert any(motivo in p for p in U.problemas_clave(clave, "nata", "Natalia Gómez")), U.problemas_clave(clave, "nata", "Natalia Gómez")


def test_contrasenas_generadas_cumplen_la_politica():
    for _ in range(200):
        c = U.generar_clave()
        assert len(c) >= 10 and not U.problemas_clave(c)
    assert not U.problemas_clave("Río-Magdalena#58", "nata", "Natalia Gómez")


def test_cambio_obligatorio_y_bloqueo(almacen):
    temporal = U.crear(almacen, "ana", "Ana Pérez", "revisor")
    with pytest.raises(U.ErrorClave):
        U.cambiar_clave(almacen, "ana", temporal, "debil", "debil")
    with pytest.raises(U.ErrorClave, match="no coinciden"):
        U.cambiar_clave(almacen, "ana", temporal, "Cafetal#Verde58", "Cafetal#Verde59")
    U.cambiar_clave(almacen, "ana", temporal, "Cafetal#Verde58", "Cafetal#Verde58")
    sesion, _ = U.verificar(almacen, "ana", "Cafetal#Verde58")
    assert sesion and not sesion["debe_cambiar"]
    for i in range(U.INTENTOS_MAXIMOS):
        sesion, msg = U.verificar(almacen, "ana", "mala")
    assert sesion is None and "bloqueada" in msg
    sesion, msg = U.verificar(almacen, "ana", "Cafetal#Verde58")  # ni con la correcta mientras está bloqueada
    assert sesion is None and "bloqueada" in msg
    nueva = U.restablecer(almacen, "ana")  # el administrador la restablece y la desbloquea
    assert U.verificar(almacen, "ana", nueva)[0]["debe_cambiar"]


def test_recuperar_con_codigo(almacen):
    U.crear(almacen, "ana", "Ana Pérez", "revisor", clave="Cafetal#Verde58", temporal=False)
    codigos = U.generar_codigos(almacen, "ana")
    assert len(codigos) == 10 and len(set(codigos)) == 10
    with pytest.raises(U.ErrorClave):
        U.recuperar(almacen, "ana", "AAAAA-BBBBB", "Montaña#Azul73", "Montaña#Azul73")
    quedan = U.recuperar(almacen, "ana", codigos[0].lower(), "Montaña#Azul73", "Montaña#Azul73")
    assert quedan == 9
    assert U.verificar(almacen, "ana", "Montaña#Azul73")[0]
    with pytest.raises(U.ErrorClave):  # cada código sirve una sola vez
        U.recuperar(almacen, "ana", codigos[0], "Otra#Clave9xQ", "Otra#Clave9xQ")
    nada_en_claro = almacen.todos_los_usuarios()[0]
    assert "hash" not in nada_en_claro and nada_en_claro["codigos"] == 9


def test_cuentas_cifradas_en_repositorio_publico(tmp_path):
    import sqlite3
    from bandeja.almacen import ErrorCuentas, SincronizadorGitHub
    gh = GitHubFalso(privado=False)
    with pytest.raises(ErrorCuentas, match="USUARIOS_CLAVE"):
        AlmacenSQLite(tmp_path / "a.db", sincronizador=SincronizadorGitHub("apc/convocatorias-datos", "t", sesion=gh),
                      clave_cuentas="")
    secreto = "x" * 20 + "clave-larga-y-aleatoria-1234"
    a = AlmacenSQLite(tmp_path / "b.db", sincronizador=SincronizadorGitHub("apc/convocatorias-datos", "t", sesion=gh),
                      refresco_segundos=0, clave_cuentas=secreto)
    clave = U.crear(a, "nata", "Natalia Gómez", "admin")
    publicado = gh.contenido
    assert b"nata" not in publicado and b"Natalia" not in publicado  # en el archivo público no se ve la cuenta
    destino = tmp_path / "publico.db"
    destino.write_bytes(publicado)
    con = sqlite3.connect(destino)
    assert con.execute("SELECT valor FROM privado WHERE clave='cuentas'").fetchone()[0].startswith("fernet:")
    con.close()
    # otra instancia con la misma clave entra; con otra clave no puede leer las cuentas
    b = AlmacenSQLite(tmp_path / "c.db", sincronizador=SincronizadorGitHub("apc/convocatorias-datos", "t", sesion=gh),
                      refresco_segundos=0, clave_cuentas=secreto)
    assert U.verificar(b, "nata", clave)[0]
    otra = AlmacenSQLite(tmp_path / "d.db", sincronizador=SincronizadorGitHub("apc/convocatorias-datos", "t", sesion=gh),
                         refresco_segundos=0, clave_cuentas="y" * 40)
    with pytest.raises(ErrorCuentas, match="no coincide"):
        otra.cuentas()


def test_usuarios_de_version_anterior_se_protegen(tmp_path):
    import sqlite3
    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE usuarios (usuario TEXT PRIMARY KEY, nombre TEXT, rol TEXT, sal TEXT, hash TEXT, activo INTEGER DEFAULT 1)")
    con.execute("INSERT INTO usuarios VALUES ('viejo','Usuario Viejo','admin','00','abcdef0123456789',1)")
    con.commit()
    con.close()
    a = AlmacenSQLite(ruta, clave_cuentas="z" * 40)
    assert "viejo" in a.cuentas()
    contenido = ruta.read_bytes()
    assert b"abcdef0123456789" not in contenido and b"Usuario Viejo" not in contenido


# --- sincronización con Hugging Face (simulada) ---------------------------------
class RemotoFalso:
    """Repositorio de datos compartido por varias instancias, como el de Hugging Face."""
    def __init__(self):
        self.datos, self.version = None, 0


class SincronizadorFalso:
    def __init__(self, remoto):
        self.r, self.sha, self.revisado = remoto, None, 0.0

    def remoto(self):
        return str(self.r.version)

    def existe(self):
        return self.r.datos is not None

    def descargar(self, destino):
        if self.r.datos is not None:
            Path(destino).write_bytes(self.r.datos)
        self.sha = str(self.r.version)

    def subir(self, origen, mensaje):
        if self.sha != str(self.r.version):
            raise Conflicto("otra versión")
        self.r.datos = Path(origen).read_bytes()
        self.r.version += 1
        self.sha = str(self.r.version)


def test_dos_personas_guardando_a_la_vez(tmp_path):
    remoto = RemotoFalso()
    ana = AlmacenSQLite(tmp_path / "ana.db", SincronizadorFalso(remoto), refresco_segundos=3600)
    luis = AlmacenSQLite(tmp_path / "luis.db", SincronizadorFalso(remoto), refresco_segundos=3600)
    ana.reemplazar_catalogo(Catalogo([Actor("AECID - Agencia Española de Cooperación Internacional para el Desarrollo",
                                            "Gobierno / agencia bilateral", "Creado en CICLOPE")]))
    # Luis tiene una copia vieja (no ha leído); al guardar debe incorporar lo de Ana, no borrarlo
    F.ingresar(luis, valida(), "Registro manual", "Luis", hoy=HOY)
    F.ingresar(ana, valida(**{"Cómo aplicar": "https://www.aecid.es/otra"}), "Registro manual", "Ana", hoy=HOY)
    nueva = AlmacenSQLite(tmp_path / "nueva.db", SincronizadorFalso(remoto))
    assert len(nueva.items("Por revisar")) == 2
    assert len(nueva.catalogo()) == 1


def test_cambiar_tipo_de_actor_actualiza_sus_convocatorias(almacen):
    item, _ = F.ingresar(almacen, valida(), "Registro manual", "Ana", hoy=HOY)
    F.aprobar(almacen, item, item["datos"], "Ana", CHEQUEO, hoy=HOY)
    actor = almacen.catalogo().buscar("AECID - Agencia Española de Cooperación Internacional para el Desarrollo")
    actor.tipo = "Fundación / filantropía"
    almacen.guardar_actor(actor)
    assert almacen.items("Aprobada")[0]["datos"]["Oficial / No Oficial"] == "No Oficial"


def test_migracion_corrige_la_base(tmp_path):
    from analitica.datos import desde_almacen
    from calidad import migracion as MG
    a = AlmacenSQLite(tmp_path / "m.db")
    crudo = pd.read_csv(RAIZ / "datos" / "airtable_actual.csv")
    catalogo, items, cambios, pendientes = MG.migrar(crudo, a, hoy=date(2026, 11, 8))
    aprobadas = a.items("Aprobada")
    por_revisar = a.items("Por revisar")
    total = crudo["Nombre de la Convocatoria"].notna().sum()
    assert len(aprobadas) + len(por_revisar) == total
    assert len(aprobadas) == sum(MG.revisada_en_airtable(r) for r in crudo[crudo["Nombre de la Convocatoria"].notna()].to_dict("records"))
    assert por_revisar and all(i["origen"].endswith("revisión incompleta") for i in por_revisar)
    datos = [i["datos"] for i in aprobadas + por_revisar]
    assert not any(d["Nombre de la Fuente"].upper().startswith("*NUEVO") for d in datos if d["Nombre de la Fuente"])
    assert not any(str(d.get("Email para mayor información", "")).startswith("http") for d in datos)
    # un mismo actor tiene un solo carácter
    por_actor = {}
    for d in datos:
        por_actor.setdefault(d["Nombre de la Fuente"], set()).add(d["Oficial / No Oficial"])
    assert all(len(v) == 1 for v in por_actor.values())
    assert len(cambios) > 0
    df = desde_almacen(a)
    assert len(df) == len(aprobadas) and df["Tipo de actor"].notna().all()
    with pytest.raises(RuntimeError):
        MG.migrar(crudo, a)  # no se migra dos veces sin --reemplazar


def test_importacion_masiva_solo_agrega_lo_nuevo(tmp_path):
    from calidad import migracion as MG
    a = AlmacenSQLite(tmp_path / "i.db")
    crudo = pd.read_csv(RAIZ / "datos" / "airtable_actual.csv")
    MG.migrar(crudo, a, hoy=date(2026, 11, 8))
    antes = len(a.items())
    nueva = crudo.iloc[[0]].copy()
    nueva["Nombre de la Convocatoria"] = "Convocatoria nueva de prueba para importación"
    nueva["Cómo aplicar"] = "https://ejemplo.org/convocatoria-nueva"
    nueva["Nombre de la Fuente"] = "Fundación Nueva de Prueba"
    nueva["Nombre de actor en CICLOPE"] = "Fundación Nueva de Prueba"
    otro = pd.concat([crudo, nueva], ignore_index=True)
    tabla, nuevos = MG.importar(otro, a, hoy=date(2026, 11, 8), todo_a_revision=True)
    assert (tabla["Resultado"] == "Enviada a la bandeja de revisión").sum() == 1
    assert (tabla["Resultado"] == "Ya estaba en el sistema").sum() == len(crudo.dropna(subset=["Nombre de la Convocatoria"]))
    assert len(a.items()) == antes + 1
    assert any(x.nombre == "Fundación Nueva de Prueba" for x in nuevos)


def test_excel_completo_trae_todos_los_estados(tmp_path):
    from calidad import migracion as MG
    from calidad.exportacion import excel_completo
    import io
    a = AlmacenSQLite(tmp_path / "e.db")
    MG.migrar(pd.read_csv(RAIZ / "datos" / "airtable_actual.csv"), a, hoy=date(2026, 11, 8))
    libro = pd.ExcelFile(io.BytesIO(excel_completo(a)))
    assert libro.sheet_names == ["Base", "Por revisar", "Actor pendiente", "Por completar", "Descartadas", "Actores"]
    base = pd.read_excel(libro, "Base")
    assert len(base) == len(a.items("Aprobada"))
    for col in ("Estado", "Tipo de actor", "Tipo de monto", "Nombre de la Convocatoria", "ODS", "Errores de calidad pendientes"):
        assert col in base.columns


# --- enlaces oficiales (R17) ---------------------------------------------------
def test_clasificacion_de_enlaces():
    from calidad import dominios as DOM
    assert DOM.clasificar("https://bit.ly/3XrN9s2")[0] == "Acortador"
    assert DOM.clasificar("https//ffngos.org/hid0uD", "https://ibro.org")[0] == "Acortador"
    assert DOM.clasificar("https://onglink.org/oportunidad", "https://www.hss.de")[0] == "Agregador / intermediario"
    assert DOM.clasificar("https://web.icetex.gov.co/es/-/beca")[0] == "ICETEX"
    assert DOM.clasificar("https://form.jotform.com/123", "https://www.caf.com")[0] == "Plataforma de postulación"
    assert DOM.clasificar("https://bogota.aics.gov.it/x", "https://www.aics.gov.it")[0] == "Oficial del oferente"
    assert DOM.clasificar("https://fondo-cooperacion-triangular.net/x",
                          "https://www.giz.de; https://fondo-cooperacion-triangular.net")[0] == "Oficial del oferente"
    assert DOM.clasificar("https://fundacionpasoslibres.org/x", "https://co.usembassy.gov")[0] == "Otro sitio"
    assert DOM.quitar_rastreo("https://wphfund.org/es/rrw/?utm_source=chatgpt.com") == "https://wphfund.org/es/rrw/"
    assert DOM.enlaces("A través de https://fundacionlacaixa.org/es/x. Luego www.iberescena.org") == [
        "https://fundacionlacaixa.org/es/x", "www.iberescena.org"]


def test_regla_enlaces_oficiales():
    from calidad.actores import Actor, Catalogo
    cat = Catalogo()
    cat.agregar(Actor(nombre="IBRO", tipo="Academia / investigación", estado_ciclope="Creado en CICLOPE", web="https://ibro.org"))
    base = {"Nombre de la Fuente": "IBRO", "Modalidad": "Beca", "Nombre de la Convocatoria": "Beca IBRO (IBRO grant)"}
    _, h = R.validar(base | {"Link de la Fuente Oferente": "https://ffngos.org/hid0uD"}, cat)
    assert any(x.regla == "R17" and x.nivel == "Error" and "Acortador" in x.problema for x in h)
    _, h = R.validar(base | {"Cómo aplicar": "https://web.icetex.gov.co/es/-/beca-ibro"}, cat)
    assert any(x.regla == "R17" and "ICETEX" in x.problema for x in h)
    norm, h = R.validar(base | {"Cómo aplicar": "Aplicar en https://ibro.org/grants/?utm_source=chatgpt.com"}, cat)
    assert norm["Cómo aplicar"] == "Aplicar en https://ibro.org/grants/"
    assert not [x for x in h if x.regla == "R17" and x.nivel != "Corregido"]



# --- procedimiento de validación de la DGDCI ---------------------------------------
def _reglas(h, regla):
    return [x for x in h if x.regla == regla and x.nivel != "Corregido"]


def test_boletin_de_otra_entidad_no_es_fuente():
    cat = Catalogo()
    cat.agregar(Actor(nombre="GIZ", tipo="Gobierno / agencia bilateral", estado_ciclope="Creado en CICLOPE", web="https://www.giz.de"))
    base = {"Nombre de la Fuente": "GIZ", "Modalidad": "Subvención"}
    _, h = R.validar(base | {"Link de la Fuente Oferente": "https://bogota.gov.co/internacional/boletin-oferta-internacional"}, cat)
    assert any(x.nivel == "Error" and "Boletín de otra entidad" in x.problema for x in _reglas(h, "R17"))
    _, h = R.validar(base | {"Cómo aplicar": "https://www.fundsforngos.org/x"}, cat)
    assert any(x.nivel == "Error" for x in _reglas(h, "R17"))


def test_apertura_anunciada_sin_cierre_es_alerta():
    _, h = R.validar(valida(**{"Fecha Límite de Aplicación": "", "Fecha de apertura": "15/1/2027"}), hoy=HOY)
    r09 = _reglas(h, "R09")
    assert r09 and all(x.nivel == "Alerta" for x in r09)
    _, h = R.validar(valida(**{"Fecha Límite de Aplicación": ""}), hoy=HOY)
    assert any(x.nivel == "Error" for x in _reglas(h, "R09"))
    _, h = R.validar(valida(**{"Fecha de apertura": "1/3/2027"}), hoy=HOY)  # apertura después del cierre
    assert any("posterior a la fecha límite" in x.problema for x in _reglas(h, "R09"))


def test_monto_o_beneficios():
    _, h = R.validar(valida(**{"Financiación": "", "Tipo de monto": ""}), hoy=HOY)
    assert not _reglas(h, "R13") and not [x for x in h if x.campo == "Financiación" and x.nivel == "Error"]
    _, h = R.validar(valida(**{"Financiación": "", "Observaciones sobre el financiamiento": ""}), hoy=HOY)
    assert any(x.nivel == "Error" for x in _reglas(h, "R13"))


def test_requisitos_segun_modalidad():
    _, h = R.validar(valida(**{"Requisitos y condiciones de participación": R.plantilla("Beca")}), hoy=HOY)
    assert any(x.nivel == "Error" for x in _reglas(h, "R18"))
    _, h = R.validar(valida(**{"Requisitos y condiciones de participación": "Perfil de los aspirantes: profesionales\nCobertura: No se indica"}), hoy=HOY)
    alerta = _reglas(h, "R18")
    assert alerta and alerta[0].nivel == "Alerta" and "Nivel de formación" in alerta[0].problema
    # la base histórica no tenía el campo: no se exige
    _, h = R.validar(valida(**{"Requisitos y condiciones de participación": ""}), hoy=HOY, nuevo=False)
    assert not _reglas(h, "R18")
    assert R.plantilla("Subvención").startswith("Organizaciones elegibles:")


@pytest.mark.parametrize("cambios,sugerida", [
    ({"Modalidad": "Subvención", "Financiación": "80000"}, True),
    ({"Modalidad": "Subvención", "Financiación": "30000"}, False),
    ({"Modalidad": "Subvención", "Financiación": ""}, False),
    ({"Modalidad": "Beca"}, True),
    ({"Modalidad": "Premio", "Financiación": "20000"}, False),
    ({"Modalidad": "Subvención", "Financiación": "80000", "Fecha Límite de Aplicación": "1/12/2026"}, False),  # plazo corto
    ({"Modalidad": "Premio", "Financiación": "1000", "Fecha Límite de Aplicación": "1/12/2026",
      "Solicitud expresa del cooperante": "checked"}, True),
])
def test_criterios_de_socializacion(cambios, sugerida):
    norm, h = R.validar(valida(**cambios), hoy=HOY)
    assert (norm["Se sugiere para priorización"] == "checked") is sugerida, norm["Motivo de la sugerencia de priorización"]
    assert not [x for x in h if x.campo == "Se sugiere para priorización"]  # no es una regla de calidad


def test_lista_de_chequeo_cubre_el_procedimiento():
    texto = " ".join(F.LISTA_CHEQUEO).lower()
    for clave in ("agregador", "boletín", "apertura", "colombia", "cooperante", "modalidad", "requisitos",
                  "beneficios", "fuente oficial", "enlaces", "icetex", "duplicado"):
        assert clave in texto, clave



def test_socializacion_no_decide_que_entra_a_la_base(almacen):
    """Una subvención pequeña con plazo corto no se sugiere para socializar, pero se aprueba y entra a la base igual."""
    datos = valida(**{"Modalidad": "Subvención", "Financiación": "5000", "Fecha Límite de Aplicación": "1/12/2026"})
    item, _ = F.ingresar(almacen, datos, "Registro manual", "Natalia", hoy=HOY)
    estado, _ = F.aprobar(almacen, item, datos, "Natalia", CHEQUEO, hoy=HOY)
    assert estado == "Aprobada"
    guardada = almacen.base()[0]
    assert guardada["Se sugiere para priorización"] == ""
    assert "50.000" in guardada["Motivo de la sugerencia de priorización"] or "plazo" in guardada["Motivo de la sugerencia de priorización"]
    assert not any("socializ" in c.lower() or "prioriz" in c.lower() for c in F.LISTA_CHEQUEO)


# --- base guardada en un repositorio privado de GitHub (simulado) -----------------
class GitHubFalso:
    """Imita la API de contenidos de GitHub: un archivo, su sha y respuesta 409 si el sha no coincide."""

    def __init__(self, privado=True):
        self.privado, self.contenido, self.sha, self.commits = privado, None, None, 0
        self.headers = {}

    class R:
        def __init__(self, codigo, datos=None, contenido=b"", texto=""):
            self.status_code, self._d, self.content, self.text = codigo, datos, contenido, texto

        def json(self):
            return self._d

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    def get(self, url, params=None, timeout=None, headers=None):
        if url.endswith("/repos/apc/convocatorias-datos"):
            return self.R(200, {"private": self.privado})
        if self.contenido is None:
            return self.R(404)
        if headers and "raw" in headers.get("Accept", ""):
            return self.R(200, contenido=self.contenido)
        return self.R(200, {"sha": self.sha})

    def put(self, url, json=None, timeout=None, headers=None):
        import base64
        import hashlib
        if self.sha and json.get("sha") != self.sha:
            return self.R(409, texto="sha does not match")
        self.contenido = base64.b64decode(json["content"])
        self.commits += 1
        self.sha = hashlib.sha1(self.contenido + str(self.commits).encode()).hexdigest()
        return self.R(201, {"content": {"sha": self.sha}})


def test_base_en_github_privado(tmp_path):
    from bandeja.almacen import SincronizadorGitHub
    gh = GitHubFalso()
    s1 = SincronizadorGitHub("apc/convocatorias-datos", "token", sesion=gh)
    a1 = AlmacenSQLite(tmp_path / "servidor1.db", sincronizador=s1, refresco_segundos=0)
    assert gh.commits == 1  # base inicial
    item, _ = F.ingresar(a1, valida(), "Registro manual", "Natalia", hoy=HOY)
    # otro servidor (o la app después de reiniciar) ve el cambio
    s2 = SincronizadorGitHub("apc/convocatorias-datos", "token", sesion=gh)
    a2 = AlmacenSQLite(tmp_path / "servidor2.db", sincronizador=s2, refresco_segundos=0)
    assert [i["id"] for i in a2.items("Por revisar")] == [item["id"]]
    # dos personas guardan al mismo tiempo: no se pierde ninguno de los dos cambios
    i2, _ = F.ingresar(a2, valida(**{"Nombre de la Convocatoria": "Premio de prueba (Test Prize)"}), "Registro manual", "Revisor", hoy=HOY)
    i3, _ = F.ingresar(a1, valida(**{"Nombre de la Convocatoria": "Otra beca (Another scholarship)"}), "Registro manual", "Natalia", hoy=HOY)
    s3 = SincronizadorGitHub("apc/convocatorias-datos", "token", sesion=gh)
    a3 = AlmacenSQLite(tmp_path / "servidor3.db", sincronizador=s3, refresco_segundos=0)
    assert {i["id"] for i in a3.items("Por revisar")} == {item["id"], i2["id"], i3["id"]}


def test_github_publico_se_detecta():
    from bandeja.almacen import SincronizadorGitHub
    assert SincronizadorGitHub("apc/convocatorias-datos", "token", sesion=GitHubFalso(privado=False)).publico
    assert not SincronizadorGitHub("apc/convocatorias-datos", "token", sesion=GitHubFalso()).publico



def test_instalacion_en_linea(tmp_path):
    from bandeja.almacen import SincronizadorGitHub
    semilla = AlmacenSQLite(tmp_path / "semilla.db")
    F.ingresar(semilla, valida(), "Migración", "Sistema", hoy=HOY)
    gh = GitHubFalso(privado=False)
    secreto, instal = "c" * 48, "i" * 48
    a = AlmacenSQLite(tmp_path / "nube.db", sincronizador=SincronizadorGitHub("apc/convocatorias-datos", "t", sesion=gh),
                      refresco_segundos=0, clave_cuentas=secreto, base_inicial=tmp_path / "semilla.db")
    assert len(a.items()) == 1 and gh.commits >= 1  # la base inicial se copió al repositorio de datos
    with pytest.raises(U.ErrorClave, match="instalación"):
        U.crear_primer_administrador(a, "mala", instal, "nata", "Natalia Gómez", "Cafetal#Verde58", "Cafetal#Verde58")
    U.crear_primer_administrador(a, instal, instal, "nata", "Natalia Gómez", "Cafetal#Verde58", "Cafetal#Verde58")
    sesion, _ = U.verificar(a, "nata", "Cafetal#Verde58")
    assert sesion["rol"] == "admin" and not sesion["debe_cambiar"]
    with pytest.raises(U.ErrorClave, match="Ya existe"):
        U.crear_primer_administrador(a, instal, instal, "otro", "Otro", "Cafetal#Verde58", "Cafetal#Verde58")
    U.recuperar_administrador(a, instal, instal, "nata", "Montaña#Azul73", "Montaña#Azul73")
    assert U.verificar(a, "nata", "Montaña#Azul73")[0]
    # una segunda instancia no vuelve a copiar la base inicial
    b = AlmacenSQLite(tmp_path / "nube2.db", sincronizador=SincronizadorGitHub("apc/convocatorias-datos", "t", sesion=gh),
                      refresco_segundos=0, clave_cuentas=secreto, base_inicial=tmp_path / "semilla.db")
    assert len(b.items()) == 1 and "nata" in b.cuentas()



def test_sesion_sobrevive_reconexion_y_se_anula(almacen):
    U.crear(almacen, "ana", "Ana Pérez", "revisor", clave="Cafetal#Verde58", temporal=False)
    ficha = U.emitir_sesion(almacen, "ana")
    assert U.leer_sesion(almacen, ficha)["usuario"] == "ana"          # reconexión: entra sin contraseña
    alterada = ficha[:-1] + ("1" if ficha[-1] == "0" else "0")        # (cambia siempre el último carácter)
    assert U.leer_sesion(almacen, alterada) is None                    # ficha alterada
    assert U.leer_sesion(almacen, U.emitir_sesion(almacen, "ana", horas=-1)) is None  # vencida
    U.cambiar_clave(almacen, "ana", "Cafetal#Verde58", "Montaña#Azul73", "Montaña#Azul73")
    assert U.leer_sesion(almacen, ficha) is None                       # cambiar la contraseña la anula
    ficha = U.emitir_sesion(almacen, "ana")
    U.cerrar_sesion(almacen, "ana")
    assert U.leer_sesion(almacen, ficha) is None                       # cerrar sesión la anula


# --- duplicados por año ----------------------------------------------------------
def test_misma_convocatoria_otro_anio_es_nueva_edicion():
    url = "https://www.daad.co/es/becas/epos"
    e2026 = {"Nombre de la Convocatoria": "Becas EPOS 2026 (EPOS Scholarships)", "Cómo aplicar": url,
             "Fecha Límite de Aplicación": "15/9/2026", "¿La convocatoria es permanente?": "No"}
    e2027 = e2026 | {"Nombre de la Convocatoria": "Becas EPOS 2027 (EPOS Scholarships)", "Fecha Límite de Aplicación": "15/9/2027"}
    assert R.buscar_duplicado(e2027, [e2026])[0] == "edicion_anterior"
    assert R.buscar_duplicado(e2026 | {"Nombre de la Convocatoria": "Otra forma de llamarla"}, [e2026])[0] == "mismo_año"
    assert R.buscar_duplicado(e2027 | {"Cómo aplicar": "https://otra.org/x"}, [e2027 | {"Cómo aplicar": "https://x.org/y"}])[0] == "nombre_mismo_año"
    # en la validación: otro año no es error; el mismo año sí
    _, h = R.validar(valida(**{"Cómo aplicar": url, "Fecha Límite de Aplicación": "1/3/2027"}), base=[e2026 | {"Fecha Límite de Aplicación": "1/3/2026"}], hoy=HOY)
    assert not [x for x in h if x.regla == "R16"]
    _, h = R.validar(valida(**{"Cómo aplicar": url, "Fecha Límite de Aplicación": "1/3/2027"}), base=[e2026 | {"Fecha Límite de Aplicación": "20/2/2027"}], hoy=HOY)
    assert any(x.regla == "R16" and x.nivel == "Error" for x in h)
    # una permanente es la misma mientras siga abierta
    p = {"Nombre de la Convocatoria": "Fondo permanente", "Cómo aplicar": "https://f.org/p", "¿La convocatoria es permanente?": "Si"}
    assert R.buscar_duplicado(p | {"Fecha de Registro": "1/2/2027"}, [p | {"Fecha de Registro": "1/2/2026"}])[0] == "mismo_año"



def test_descartar_varias_en_una_sola_version(tmp_path):
    from bandeja.almacen import SincronizadorGitHub
    gh = GitHubFalso()
    a = AlmacenSQLite(tmp_path / "x.db", sincronizador=SincronizadorGitHub("apc/convocatorias-datos", "t", sesion=gh),
                      refresco_segundos=0)
    items = [F.ingresar(a, valida(**{"Nombre de la Convocatoria": f"Beca {n} (Scholarship {n})",
                                    "Cómo aplicar": f"https://www.fundacioncarolina.es/beca-{n}"}), "Registro manual", "N", hoy=HOY)[0]
             for n in range(5)]
    antes = gh.commits
    assert F.descartar_varias(a, items, "Natalia", "Ya cerró") == 5
    assert gh.commits == antes + 1
    assert len(a.items("Descartada")) == 5 and a.items("Descartada")[0]["observacion"] == "Ya cerró"
    assert F.pendientes(a.items("Descartada")[0]) is not None



def test_enlaces_iguales_escritos_distinto_y_ediciones():
    url = "https://www.daad.de/en/epos/"
    a = {"Nombre de la Convocatoria": "Becas EPOS", "Cómo aplicar": url, "Fecha Límite de Aplicación": "1/3/2027"}
    for otra in ("http://daad.de/es/epos", "https://daad.de/epos/index.html", "https://www.daad.de/en/epos/?utm_source=chatgpt.com#top"):
        assert R.buscar_duplicado(a | {"Cómo aplicar": otra}, [a])[0] == "mismo_año", otra
    # traducida al español y con el original entre paréntesis sigue siendo la misma
    b = {"Nombre de la Convocatoria": "Premio Earthshot (The Earthshot Prize)", "Cómo aplicar": "https://e.org/a", "Fecha Límite de Aplicación": "1/3/2027"}
    assert R.buscar_duplicado(b | {"Nombre de la Convocatoria": "The Earthshot Prize", "Cómo aplicar": "https://e.org/b"}, [b])[0] == "nombre_mismo_año"
    # 28ª y 29ª convocatoria en la misma página son distintas
    c = {"Nombre de la Convocatoria": "28ª Convocatoria de Propuestas Agricultores", "Cómo aplicar": "https://f.org/c", "Fecha Límite de Aplicación": "1/3/2027"}
    assert R.buscar_duplicado(c | {"Nombre de la Convocatoria": "29ª Convocatoria de Propuestas Agricultores"}, [c])[0] == ""
    # dos universidades distintas no son la misma beca
    d = {"Nombre de la Convocatoria": "Becas de máster en la Universidad de Alcalá", "Cómo aplicar": "https://g.org/1", "Fecha Límite de Aplicación": "1/3/2027"}
    assert R.buscar_duplicado(d | {"Nombre de la Convocatoria": "Becas de máster en la Universidad de Santiago", "Cómo aplicar": "https://g.org/2"}, [d])[0] == ""


def test_control_de_entrada_idioma():
    from calidad import entrada as E
    assert not E.en_espanol("The CRI Fellowship Program supports young scientists at institutions who wish to train.")
    assert not E.en_espanol("Training Week", "Nombre de la Convocatoria")
    assert E.en_espanol("Semana de formación (Training Week)", "Nombre de la Convocatoria")
    assert E.en_espanol("Premio CRI IGNITE", "Nombre de la Convocatoria")
    assert not E.en_espanol("O edital oferece bolsas para pesquisadores com projetos")
    assert E.en_espanol("El programa apoya a jóvenes investigadores que deseen formarse.")


def test_migra_datos_desde_el_repo_del_codigo(tmp_path, monkeypatch):
    """Si los datos quedaron en el repositorio del código, al pasar a un repositorio de datos aparte se copian (no se
    parte de la base inicial)."""
    from bandeja import almacen as AL
    raiz = tmp_path / "src" / "sistema-convocatorias"
    raiz.mkdir(parents=True)
    vieja = AL.AlmacenSQLite(raiz / "convocatorias.db")
    vieja.guardar_archivo("historial_mapeo.json", b'{"x": 1}')
    monkeypatch.setattr(AL, "RAIZ", raiz)

    class RepoVacio:
        sha, publico, revisado = None, False, 1e18

        def remoto(self):
            return self.sha

        def descargar(self, destino):
            pass

        def existe(self):
            return False

        def subir(self, ruta, mensaje):
            self.subido = Path(ruta).read_bytes()
            self.sha = "x"
    nuevo = AL.AlmacenSQLite(tmp_path / "local.db", sincronizador=RepoVacio(), base_inicial=AL.BASE_INICIAL)
    assert nuevo.leer_archivo("historial_mapeo.json") == b'{"x": 1}'
    monkeypatch.delenv("GITHUB_DATA_BRANCH", raising=False)
    monkeypatch.setenv("GITHUB_DATA_REPO", "usuaria/sistema-convocatorias")
    assert AL.rama_de_datos() == "datos" and not AL.datos_en_repo_de_codigo()   # mismo repo: rama aparte, sola
    monkeypatch.setenv("GITHUB_DATA_BRANCH", "main")
    assert AL.datos_en_repo_de_codigo()                                         # fijada a mano en main: aviso
    monkeypatch.delenv("GITHUB_DATA_BRANCH")
    monkeypatch.setenv("GITHUB_DATA_REPO", "usuaria/convocatorias-datos")
    assert AL.rama_de_datos() == "main" and not AL.datos_en_repo_de_codigo()


def test_crea_la_rama_de_datos_si_no_existe():
    from bandeja.almacen import SincronizadorGitHub

    class R:
        def __init__(self, codigo, datos=None):
            self.status_code, self._d, self.text = codigo, datos or {}, ""

        def json(self):
            return self._d

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    class Sesion:
        headers = {}
        creada = None

        def get(self, url, **kw):
            if url.endswith("/repos/u/sistema-convocatorias"):
                return R(200, {"private": False, "default_branch": "main"})
            if "/branches/datos" in url:
                return R(404)
            if url.endswith("/git/ref/heads/main"):
                return R(200, {"object": {"sha": "abc123"}})
            return R(404)

        def post(self, url, json=None, **kw):
            Sesion.creada = json
            return R(201)
    SincronizadorGitHub("u/sistema-convocatorias", "t", rama="datos", sesion=Sesion())
    assert Sesion.creada == {"ref": "refs/heads/datos", "sha": "abc123"}


def test_actualizar_desde_airtable_sin_borrar_nada(almacen):
    """Export nuevo de Airtable: agrega lo nuevo, actualiza lo que nadie tocó, respeta lo editado aquí y no duplica."""
    from calidad import migracion as MG
    from bandeja import flujo
    df = pd.read_csv(Path(__file__).resolve().parents[1] / "datos" / "airtable_actual.csv", dtype=str)
    MG.migrar(df, almacen)
    total = len(almacen.items())
    editada = almacen.items()[0]
    flujo.guardar_cambios(almacen, editada, editada["datos"] | {"Descripción": "Corregida en el sistema"}, "Natalia")
    nombre_editada = editada["datos"]["Nombre de la Convocatoria"]
    df2 = df.copy()
    fila_ed = df2.index[df2["Nombre de la Convocatoria"].str.strip() == nombre_editada.strip()]
    if len(fila_ed):
        df2.loc[fila_ed[0], "Descripción"] = "Airtable dice otra cosa"
    otra = 1 if not len(fila_ed) or fila_ed[0] != 1 else 2
    df2.loc[otra, "Observaciones sobre el financiamiento"] = "Monto actualizado en Airtable"
    nueva = df.iloc[3].copy()
    nueva["Nombre de la Convocatoria"] = "Convocatoria registrada después en Airtable 2027"
    nueva["Fecha de Registro"] = "2026-11-20"
    nueva["Cómo aplicar"] = "https://ejemplo-nuevo.org/convocatoria-2027"
    df2 = pd.concat([df2, pd.DataFrame([nueva])], ignore_index=True)
    prev = MG.revisar_actualizacion(df2, almacen)
    assert prev["nuevas"] == 1 and prev["editadas_aqui"] == 1
    res, det = MG.actualizar(df2, almacen)
    assert res["nuevas"] == 1 and res["actualizadas"] >= 1 and res["editadas_aqui"] == 1
    assert len(almacen.items()) == total + 1                                      # nada se borró ni se duplicó
    por_nombre = {i["datos"]["Nombre de la Convocatoria"]: i for i in almacen.items()}
    assert por_nombre[nombre_editada]["datos"]["Descripción"] == "Corregida en el sistema"   # manda lo del sistema
    cambiada = por_nombre[str(df.loc[otra, "Nombre de la Convocatoria"]).strip()]
    assert "Monto actualizado en Airtable" in cambiada["datos"]["Observaciones sobre el financiamiento"]
    res2, _ = MG.actualizar(df2, almacen)                                           # cargarlo otra vez no cambia nada
    assert res2["nuevas"] == 0 and res2["actualizadas"] == 0 and len(almacen.items()) == total + 1


def test_completar_a_mano_restaurar_y_recuperar_anuladas(almacen):
    from bandeja import flujo as F
    datos = {"Nombre de la Convocatoria": "Premio Antonio Nariño 2026", "Modalidad": "Premio",
             "Cómo aplicar": "https://ejemplo.org/premio", "Nombre de la Fuente": "Embajada de Francia"}
    F.ingresar(almacen, datos, "Mapeo automático · OFE-1", "Sistema", {"faltantes": ["Fecha Límite de Aplicación: vacía"]},
               estado="Por completar")
    F.ingresar(almacen, datos | {"Nombre de la Convocatoria": "Otra"}, "Mapeo automático · OFE-1", "Sistema",
               {"faltantes": ["Requisitos"]}, estado="Por completar")
    a, b = almacen.items("Por completar")
    # «Completar a mano»: pasa a Por revisar con todo lo mapeado y marcada para completar
    F.enviar_a_completar_a_mano(almacen, [a], "Natalia")
    (r,) = almacen.items("Por revisar")
    assert r["datos"]["Cómo aplicar"] == "https://ejemplo.org/premio" and r["meta"]["completar_a_mano"]
    assert F.tocada_por_persona(r)                       # la limpieza automática ya no la mueve
    # descartar y restaurar: vuelve a donde estaba
    F.descartar(almacen, b, "Natalia", "No sirve")
    assert F.restaurar(almacen, almacen.items("Descartada")[0], "Natalia") == "Por completar"
    # anular (borrar) y recuperar
    b = almacen.items("Por completar")[0]
    F.anular(almacen, [b], "Natalia", "Se vació la lista")
    assert almacen.items("Por completar") == [] and len(F.anuladas(almacen)) == 1
    assert F.recuperar_anuladas(almacen, [b["id"]], "Natalia") == 1
    assert len(almacen.items("Por completar")) == 1 and F.anuladas(almacen) == []
    rec = almacen.items("Por completar")[0]
    assert rec["historial"][-1]["accion"] == "Recuperada de anuladas"


def test_busqueda_cortada_por_reinicio_se_reanuda_una_vez(almacen, monkeypatch):
    import json
    import tareas
    from datetime import datetime
    lanzadas = []
    monkeypatch.setattr(tareas, "iniciar", lambda A, c, e, x, u, cfg, reanudada=False: lanzadas.append((c, e, x, reanudada)) or True)
    reg = {"comando": "mapear", "etiqueta": "Búsqueda de convocatorias", "usuario": "Natalia", "estado": "En curso",
           "inicio": datetime.now().strftime("%Y-%m-%d %H:%M"), "extra": ["--maximo-nuevas", "20"], "reanudada": False}
    almacen.guardar_archivo(tareas.REGISTRO, json.dumps(reg).encode())
    assert tareas.reanudar_si_se_corto(almacen, b"cfg")
    assert lanzadas == [("mapear", "Búsqueda de convocatorias (reanudada)", ["--maximo-nuevas", "20"], True)]
    # si la reanudada también se corta, no se relanza otra vez (nunca queda en un ciclo)
    almacen.guardar_archivo(tareas.REGISTRO, json.dumps(reg | {"reanudada": True}).encode())
    assert tareas.reanudar_si_se_corto(almacen, b"cfg") is None
    # una antigua (más de 6 horas) tampoco: decide la persona
    almacen.guardar_archivo(tareas.REGISTRO, json.dumps(reg | {"inicio": "2026-01-01 08:00"}).encode())
    assert tareas.reanudar_si_se_corto(almacen, b"cfg") is None


def test_recargar_el_modulo_no_pierde_la_busqueda_en_curso(almacen):
    """Si Streamlit vuelve a cargar los archivos mientras corre una búsqueda, no debe creer que se cortó ni lanzar otra."""
    import importlib
    import json
    import sys
    import threading
    import tareas
    from datetime import datetime
    sigue = threading.Event()
    hilo = threading.Thread(target=sigue.wait, name="tarea-mapear", daemon=True)
    hilo.start()
    t = tareas.Tarea("mapear", "Búsqueda", "Natalia")
    t.hilo = hilo
    tareas._ESTADO["actual"] = t
    almacen.guardar_archivo(tareas.REGISTRO, json.dumps(t.resumen()).encode())
    del sys.modules["tareas"]
    nuevo = importlib.import_module("tareas")
    try:
        assert nuevo.en_curso() and nuevo.interrumpida(almacen) is None
        assert nuevo.reanudar_si_se_corto(almacen, b"cfg") is None
    finally:
        sigue.set()
        hilo.join(5)
        nuevo._ESTADO["actual"] = None


def test_manifiesto_del_paquete_coincide_con_los_archivos():
    """El paquete trae la huella de cada archivo; si en el servidor queda uno de otro paquete, se detecta."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "herramientas"))
    import manifiesto
    version, distintos = manifiesto.revisar()
    assert version and distintos == [], f"Regenerar el manifiesto (python herramientas/manifiesto.py): {distintos}"


def test_manifiesto_detecta_archivos_mezclados(tmp_path, monkeypatch):
    import shutil
    import sys
    raiz = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(raiz / "herramientas"))
    import manifiesto
    copia = tmp_path / "app"
    for nombre, ruta in manifiesto.archivos():
        (copia / nombre).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ruta, copia / nombre)
    shutil.copy(manifiesto.RUTA, copia / "manifiesto.json")
    (copia / "calidad" / "reglas.py").write_text("# versión anterior\\n", encoding="utf-8")
    monkeypatch.setattr(manifiesto, "RAIZ", copia)
    monkeypatch.setattr(manifiesto, "RUTA", copia / "manifiesto.json")
    assert manifiesto.revisar()[1] == ["calidad/reglas.py"]


def test_historial_se_sube_a_github_como_mucho_cada_dos_minutos(monkeypatch, tmp_path):
    """Durante la búsqueda el historial cambia cientos de veces; subirlo cada vez hacía lenta la búsqueda."""
    import tareas
    import mapeo as programa
    subidas = []

    class Falso:
        def leer_archivo(self, n):
            return None

        def guardar_archivo(self, n, b):
            subidas.append(n)

    capturado = {}
    monkeypatch.setenv("MAPEO_HISTORIAL", str(tmp_path / "otro.json"))  # _correr la cambia: se restaura al terminar
    monkeypatch.setattr(programa, "main", lambda args: capturado.setdefault("f", programa.AL_GUARDAR) and None)
    monkeypatch.setattr(tareas, "_guardar_registro", lambda *a: None)
    monkeypatch.setattr(tareas, "modulos_desactualizados", lambda: [])
    t = tareas.Tarea("mapear", "Búsqueda", "Natalia")
    tareas._correr(Falso(), t, [], open(RAIZ / "config" / "configuracion_mapeo_becas.xlsx", "rb").read())
    assert "f" in capturado, t.lineas[-5:]
    f = capturado["f"]
    h = tmp_path / "h.json"
    h.write_text("{}")
    for _ in range(50):
        f("historial", h)
    assert subidas.count("historial_mapeo.json") == 1
