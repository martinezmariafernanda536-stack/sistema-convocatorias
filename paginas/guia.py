"""Página: cómo se usa el sistema, en lenguaje sencillo, para personas que lo abren por primera vez."""
import streamlit as st

import ui

st.markdown(ui.ESTILOS, unsafe_allow_html=True)
YO = ui.usuario()

st.title("Cómo se usa")
st.caption("Guía rápida del sistema de convocatorias internacionales de la DGDCI. Léela una vez y vuelve cuando tengas una duda.")

st.markdown("### Para qué sirve")
st.write("El sistema **busca solo** becas, subvenciones, cooperación técnica y premios internacionales abiertos a Colombia en "
         "los sitios oficiales de los oferentes. Una persona **revisa** cada convocatoria antes de que entre a la **base**, "
         "y con la base se hacen el **dashboard** y los **informes**.")

c = st.columns(4)
pasos = [("1", "Buscar", "El sistema revisa más de 200 sitios oficiales y trae lo nuevo.", "paginas/mapeo.py", "Buscar convocatorias"),
         ("2", "Revisar", "Una persona abre cada convocatoria, corrige lo que falte y la aprueba o la descarta.",
          "paginas/bandeja.py", "Revisar convocatorias"),
         ("3", "Consultar", "Lo aprobado queda en la base, donde se puede filtrar, corregir y exportar a Excel.",
          "paginas/base.py", "Base de convocatorias"),
         ("4", "Informar", "El dashboard y los informes en Word o PDF salen de la base.", "paginas/tablero.py", "Dashboard e informes")]
for col, (n, titulo, texto, pagina, etiqueta) in zip(c, pasos):
    with col.container(border=True):
        st.markdown(f"<div style='font-size:1.8rem;font-weight:700;color:#0B2545'>{n}</div>"
                    f"<div style='font-weight:600'>{titulo}</div>"
                    f"<div style='color:#5b6472;font-size:.88rem;min-height:4.2em'>{texto}</div>", unsafe_allow_html=True)
        st.page_link(pagina, label=etiqueta, icon=":material/arrow_forward:")

st.markdown("### Tareas paso a paso")

with st.expander("🔎 Buscar convocatorias nuevas", expanded=True):
    st.markdown("""
1. En el menú, abre **Buscar convocatorias**.
2. Pulsa **Buscar convocatorias nuevas**. No hace falta cambiar ninguna opción.
3. La búsqueda corre en el servidor: puedes cerrar la pestaña o seguir trabajando. La barra muestra cuántas fuentes lleva.
4. Lo que encuentra **en español y completo** va llegando a **Revisar convocatorias**. Lo que esté en otro idioma o
   incompleto queda **Por completar** (fuera de la bandeja) y el sistema lo reintenta en la siguiente búsqueda.
5. Lo que ya está registrado este año (aunque tenga otro enlace o el nombre traducido) no vuelve a entrar.

**Cada cuánto:** una vez por semana es suficiente. La primera vez tarda más, porque todavía no conoce ninguna convocatoria;
después solo abre lo nuevo y es mucho más rápida.
""")

with st.expander("✅ Revisar una convocatoria"):
    st.markdown("""
1. En **Revisar convocatorias**, pestaña **Por revisar**, marca una fila de la tabla. Abajo se abre su ficha.
2. Pulsa **Abrir la página oficial** y compara: nombre, fechas, monto, requisitos y si Colombia puede postularse.
3. A la derecha, en **Qué falta corregir**, lo rojo es obligatorio y lo amarillo es un aviso. Corrige en el formulario de la izquierda.
4. Marca la **lista de chequeo** (11 puntos del procedimiento de validación).
5. Pulsa **Aprobar y enviar a la base**. Si falta algo, el sistema te dice qué.

**Para avanzar rápido:** ordena por *Cierre más próximo* para revisar primero lo que vence pronto, y usa el filtro
*Solo las completas* para aprobar primero las que ya están completas.
""")

with st.expander("🗑️ Descartar varias convocatorias a la vez"):
    st.markdown("""
1. En **Por revisar**, filtra por ejemplo **Cierre → Ya cerró**.
2. Marca varias filas en la tabla (la casilla al inicio de cada fila).
3. Elige el motivo y pulsa **Descartar seleccionadas**.

Las descartadas no se borran: quedan en la pestaña **Descartadas** y el sistema no las vuelve a traer ese año.
""")

with st.expander("✍️ Registrar a mano una convocatoria que llegó por correo u otro medio"):
    st.markdown("""
1. En **Revisar convocatorias**, abre la pestaña **Registrar convocatoria**.
2. Llena el formulario. Mientras escribes, el sistema muestra qué falta.
3. Pulsa **Enviar a revisión**. Queda en *Por revisar* como cualquier otra.
""")

with st.expander("🏢 La convocatoria quedó «en espera de actor»"):
    st.markdown("""
Pasa cuando el oferente todavía no existe en CICLOPE. La revisión queda guardada y la convocatoria espera.

1. En **Revisar convocatorias → Actores pendientes**, descarga la lista para pedir la creación del actor.
2. Cuando el actor esté creado en CICLOPE, márcalo en la tabla y pulsa **Marcar como creado en CICLOPE**.
3. Las convocatorias que esperaban entran solas a la base.
""")

with st.expander("📊 Sacar un informe o el Excel de la base"):
    st.markdown("""
- **Dashboard e informes:** elige el periodo y descarga el informe en Word o PDF.
- **Base de convocatorias:** filtra por año, modalidad o estado y descarga el Excel.
""")

st.markdown("### Qué significa cada cosa")
glosario = {
    "Por completar": "Convocatorias que la búsqueda encontró pero que todavía no están en español o les faltan datos "
                     "obligatorios. No llegan a la bandeja: el sistema las reintenta sola con Gemini en cada búsqueda. Se ven en "
                     "Buscar convocatorias.",
    "Bandeja / Por revisar": "Convocatorias que llegaron (de la búsqueda o registradas a mano) y todavía nadie ha aprobado.",
    "Base de convocatorias": "Las convocatorias ya revisadas y aprobadas. Es la información oficial para informes.",
    "Semáforo de cierre": "🔴 cierra en menos de 15 días · 🟠 en 37 días o menos · 🟢 con más plazo · ⚪ permanente · ⚫ sin fecha.",
    "Elegibilidad automática": "Lo que el sistema leyó sobre si Colombia puede postularse. *Elegible*: lo dice claramente. "
                               "*Probable*: está abierta a extranjeros o a todos los países y no excluye a Colombia. "
                               "*Revisar*: no se encontró; hay que leer la página.",
    "Rojo (error) / amarillo (aviso)": "Rojo: hay que corregirlo antes de aprobar. Amarillo: conviene mirarlo, pero no impide aprobar.",
    "Nueva edición": "La misma convocatoria ya estaba en la base en un año anterior. Es normal: muchas se abren cada año. "
                     "Dos veces en el mismo año no se permite.",
    "Fuente oficial": "Página del propio oferente (gobierno, agencia, organismo, fundación, universidad). No sirven agregadores, "
                      "boletines de otras entidades, acortadores de enlaces ni ICETEX.",
    "Socialización": "Sugerencia aparte de la revisión: indica si conviene, además, difundirla por los canales institucionales. "
                     "No todas las convocatorias de la base se socializan, y esto nunca impide aprobar.",
    "Completar con Gemini": "Opción de la búsqueda: una inteligencia artificial lee la página oficial de cada convocatoria nueva y "
                            "llena campos como objetivos, poblaciones y requisitos. Solo usa lo que dice la página; igual se revisa.",
}
for termino, texto in glosario.items():
    st.markdown(f"**{termino}.** {texto}")

st.markdown("### Preguntas frecuentes")
faq = {
    "La búsqueda se está demorando mucho, ¿está pegada?":
        "Si la barra sigue avanzando, está trabajando. Con más de 200 sitios, la primera búsqueda puede tardar una hora o más. "
        "Puedes cerrar la pestaña: sigue en el servidor y lo encontrado va llegando a la bandeja.",
    "La app se reinició y me sacó de la sesión.":
        "Streamlit reinicia la app cuando lleva un rato sin uso o cuando se actualiza el código. Vuelve a entrar. "
        "Si había una búsqueda en curso, lo que alcanzó a encontrar ya está en la bandeja; puedes volver a ejecutarla "
        "y no repite lo que ya existe.",
    "Olvidé mi contraseña.":
        "En la pantalla de ingreso pulsa **¿Olvidaste tu contraseña?** y usa uno de tus códigos de recuperación. "
        "Si no los tienes, pídele al administrador que te asigne una contraseña temporal.",
    "¿Por qué una convocatoria no aparece?":
        "Puede estar en *Descartadas*, en *Actores pendientes* (esperando al actor en CICLOPE) o ya en la base del mismo año. "
        "Usa el buscador de cada pestaña.",
    "¿Por qué una convocatoria encontrada no llegó a la bandeja?":
        "Porque no estaba en español o le faltaban datos obligatorios (objetivos, requisitos, temáticas…): queda en la "
        "lista **Por completar** de Buscar convocatorias, con lo que le falta. O porque ya estaba registrada ese año.",
    "¿El sistema puede equivocarse?":
        "Sí. Por eso nada entra a la base sin revisión de una persona. Compara siempre con la página oficial antes de aprobar.",
}
for pregunta, respuesta in faq.items():
    with st.expander(pregunta):
        st.write(respuesta)

if YO and YO.get("rol") == "admin":
    st.markdown("### Solo para el administrador")
    st.markdown("""
- **Usuarios** (menú *Mi cuenta*): crear cuentas, asignar el rol y dar contraseñas temporales.
- **Buscar convocatorias → Mantenimiento de fuentes:** validar los sitios una vez al mes y editar la configuración (fuentes,
  palabras de cada modalidad, reglas de elegibilidad).
- **Catálogo de actores** (en *Revisar convocatorias*): tipo de actor y estado en CICLOPE.
- El detalle técnico de la instalación está en el archivo `LEEME.md` del repositorio.
""")
