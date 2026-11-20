# Sistema de convocatorias internacionales

DGDCI · APC-Colombia

Este sistema reemplaza a Airtable. Sirve para tres cosas: **encontrar** convocatorias (mapeo automático), **revisarlas** antes de que entren a la base, y **ver los indicadores y generar informes**. La publicación en APC te Proyecta se sigue haciendo por fuera del sistema.

| Página | Para qué |
|---|---|
| **Inicio** | Lo que requiere atención hoy: por revisar, actores por crear, errores en la base, convocatorias que cierran pronto, lo último que llegó y la última búsqueda, con acceso directo a cada tarea |
| **Dashboard e informes** | Indicadores, gráficos y el informe automático en Word y PDF |
| **Revisar convocatorias** (antes «Bandeja de revisión») | Toda convocatoria nueva, mapeada o registrada a mano, se revisa aquí antes de entrar a la base |
| **Base de convocatorias** (antes «Base de convocatorias») | La base revisada. Muestra «qué falta por corregir» por tipo de pendiente; al marcar uno se filtra la tabla. Tiene filtros por año, modalidad y texto. Al marcar una fila se corrige; varias marcadas se retiran en bloque. También descarga todo en Excel e importa exports de Airtable |
| **Buscar convocatorias** (antes «Mapeo automático») | Un botón para buscar lo nuevo; opciones avanzadas, búsqueda con Gemini y mantenimiento de fuentes más abajo |
| **Cómo se usa** | Guía para usuarios nuevos: tareas paso a paso, glosario y preguntas frecuentes |
| **Usuarios** | Crear usuarios y asignar perfiles (solo el administrador) |

**Perfiles:**

| Perfil | Puede |
|---|---|
| Administrador del sistema | Todo lo del revisor, y además: usuarios, edición del catálogo de actores, configuración del mapeo, importación masiva y copia de seguridad |
| Revisor | Revisar y aprobar convocatorias, registrar convocatorias a mano, corregir la base, registrar actores creados en CICLOPE, ejecutar el mapeo, ver el dashboard, generar informes y descargar la base en Excel |

```
Mapeo automático ─┐
                  ├─► Bandeja: por revisar ──► revisor aprueba ──► ¿actor creado en CICLOPE? ──sí──► Base ──► Dashboard e informes
Registro manual ──┘          │                                          │no
                             └─► Descartada                             └─► Actor pendiente de crear ──(se crea en CICLOPE)──► Base
```

## Dónde viven los datos

La base es un archivo SQLite (`datos/convocatorias.db`) con las convocatorias, el catálogo de actores, los usuarios y la configuración del mapeo.

- **En un computador:** queda en la carpeta `datos/`.
- **En la nube:** el disco del servidor se borra cuando la app se reinicia o se suspende. Por eso la base se guarda en un **repositorio de datos**: la aplicación la descarga al iniciar y guarda una versión nueva con cada cambio. Cada versión queda en el historial y sirve de copia de seguridad. Si dos personas guardan al mismo tiempo, el segundo cambio se aplica sobre el primero y no se pierde ninguno.
  - **GitHub** (`GITHUB_DATA_REPO` y `GITHUB_TOKEN`): la opción actual. El repositorio puede ser **público**, porque las convocatorias son información pública, pero debe ser **distinto del repositorio del código**. Streamlit reinicia la app cada vez que cambia el repositorio del código; si la base estuviera ahí, la app se reiniciaría con cada guardado.
  - **Cuentas de usuario:** se guardan **cifradas** dentro de la base con el secreto `USUARIOS_CLAVE`. En un repositorio público no se ven ni los usuarios, ni los nombres, ni las contraseñas cifradas, ni los códigos de recuperación, y los mensajes de cada guardado no nombran a nadie. Si el repositorio es público y falta `USUARIOS_CLAVE`, la app no arranca.
  - **Lo que sí queda público:** las convocatorias, los actores, la configuración del mapeo y el historial de cada convocatoria, que incluye el nombre de quien la revisó.
  - **Hugging Face** (`HF_DATASET_REPO` y `HF_TOKEN`): para cuando haya plan pago. Se cambian los secretos, se ejecuta `python mapeo.py publicar-base` y los datos pasan tal cual.
- Cada guardado es una versión nueva del archivo, de menos de 2 MB. Conviene revisar el tamaño del repositorio de datos cada semestre (en GitHub: *Settings → General*).

## Instalación en un computador

```bash
pip install -r requirements.txt
python -m pytest pruebas -q        # debe decir "102 passed"
```

## Puesta en marcha (una sola vez)

### 1. La base ya viene migrada y corregida

`datos/convocatorias.db` trae las 176 convocatorias del export de Airtable, con las correcciones automáticas aplicadas, y el catálogo de 104 actores:

- **104 en la base:** tenían las tres verificaciones marcadas en Airtable (Colombia elegible, página activa e información completa).
- **72 en la bandeja de revisión:** les faltaba alguna verificación, así que se revisan en este sistema.

Para volver a migrar desde cero: `python mapeo.py migrar ruta/al/export.csv --reemplazar`.

### Importación masiva posterior

Si más adelante necesitas traer otro export de Airtable, usa la página **Base de convocatorias → Importación masiva desde Airtable** (administrador), o el comando `python mapeo.py importar export.csv`. Solo se agregan las convocatorias que aún no están en el sistema, comparadas por enlace y por nombre, y se corrigen igual que en la migración. Por defecto todas van a la bandeja de revisión.

### Descargar la base

En **Base de convocatorias → Todo lo registrado en Excel** se descarga un libro con todos los campos y una hoja por estado:
- Base,
- Por revisar,
- Actor pendiente,
- Descartadas,
- Actores.

Cada convocatoria trae su estado, origen, quién la revisó, su tipo de actor y cuántos pendientes de calidad tiene.

### 2. Crear el primer administrador

```bash
python mapeo.py crear-usuario --usuario nata --nombre "Natalia Gómez" --rol admin
```

El comando muestra una contraseña temporal. Los revisores se crean desde la página **Usuarios**.

### 3. Probar en el computador

```bash
streamlit run app.py
```

## Montarlo en Streamlit Community Cloud con GitHub (opción actual, todo en línea)

No hay que instalar nada ni ejecutar comandos.

1. **GitHub, repositorio del código:** *New repository* → `sistema-convocatorias`, **Public** (puede ser público: no tiene claves; todas van en los Secrets de Streamlit), con README. Luego *Add file → Upload files*: arrastra **todo el contenido** de la carpeta `mapeo_becas` y pulsa *Commit changes*. Incluye `datos/base_inicial.db`, que trae las 176 convocatorias sin usuarios, pero no `datos/convocatorias.db`.
2. **GitHub, repositorio de los datos:** *New repository* → `convocatorias-datos`, **Public**, con README. Déjalo así: la app lo llena sola.
3. **Gemini, clave (gratuita):** en aistudio.google.com, entra con una cuenta de Google → *Get API key* → *Create API key*. Copia la clave. Activa la búsqueda con Gemini en sitios oficiales que no están entre las fuentes, y el completado automático de campos. Sin ella, todo lo demás funciona.
4. **GitHub, token:** *Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token*.
   - Vencimiento de 1 año.
   - *Only select repositories* → `convocatorias-datos`.
   - *Contents: Read and write*.
5. **Streamlit:** share.streamlit.io → *Create app*.
   - Repositorio `sistema-convocatorias`, rama `main`, archivo `app.py`.
   - En *Advanced settings*, Python 3.12.
   - Pulsa *Deploy*.
6. **Al abrir la app** aparece **Configuración inicial del sistema** con el texto de los Secrets listo, incluidas las claves `USUARIOS_CLAVE` y `CLAVE_INSTALACION` ya generadas.
   - Cópialo, completa `GITHUB_DATA_REPO`, `GITHUB_TOKEN` y `GEMINI_API_KEY` y pégalo en *Manage app → Settings → Secrets → Save*.
   - **Guarda las dos claves en un lugar seguro.**
7. **La app se reinicia, copia la base inicial al repositorio de datos y pide crear el primer administrador** con la clave de instalación. Luego entregas los códigos de recuperación.
8. **En Usuarios**, crea a los revisores.

Si un administrador pierde el acceso y no tiene códigos, en la pantalla de ingreso está **«Soy administrador y perdí el acceso»**, que funciona con la clave de instalación.

### Recomendaciones para Community Cloud

- **No se instala LibreOffice**, para que la app sea liviana: el informe sale en Word y el PDF se guarda desde Word. Si más adelante se quiere el PDF directo, se renombra `packages.txt.opcional` a `packages.txt` (sube el uso de disco y el tiempo de arranque).

**Para no llegar a los límites de uso de Community Cloud:**
- Probar primero en el computador (`streamlit run app.py`) y subir cuando funcione: varios despliegues seguidos son una de las causas de bloqueo.
- Ejecutar el mapeo por grupos, no las 217 fuentes de una vez, y bajar *Fuentes en paralelo* a 3 en la hoja Parametros.
- Medido en el computador de desarrollo, la app usa cerca de 300 MB de memoria, incluso generando el informe. No carga modelos de IA: Gemini corre en los servidores de Google.

**Comparación con Hugging Face:** en Community Cloud las apps se suspenden cuando no se usan, y un mapeo largo se corta si se cierra la pestaña (conviene ejecutarlo por grupos). Hugging Face con Docker es más estable cuando esté el plan.

## Desplegar en Hugging Face (cuando haya plan)

**Para pasar los datos de GitHub a Hugging Face:**
1. En **Base de convocatorias**, descargar la *copia de seguridad de la base (.db)*.
2. Ponerla en `datos/convocatorias.db`.
3. Seguir los pasos de abajo.

Desde ese momento se usan los secretos de Hugging Face en lugar de los de GitHub.

Requiere una cuenta u organización de Hugging Face que permita Spaces con Docker. Con la cuenta gratuita actual solo se pueden publicar Spaces estáticos, así que se necesita el plan que se está gestionando con TI.

1. **Crear el repositorio de datos privado** (por ejemplo `organizacion/convocatorias-datos`) y un **token** con permiso de escritura sobre él.
2. **Subir la base inicial** desde el computador, después de crear el administrador:

```bash
# Windows (PowerShell)
$env:HF_DATASET_REPO="organizacion/convocatorias-datos"; $env:HF_TOKEN="hf_..."
python mapeo.py publicar-base
```

3. **Crear el Space** con *SDK: Docker* y subir todo el contenido de esta carpeta. El `Dockerfile` y el `README.md` ya están listos; el Dockerfile instala LibreOffice para que el informe salga también en PDF.
4. En el Space, en *Settings → Variables and secrets*, agregar los secretos `HF_DATASET_REPO` y `HF_TOKEN`.
5. Abrir el Space e ingresar con el usuario administrador.

Si el Space arranca sin `HF_DATASET_REPO`, la aplicación muestra un aviso en rojo: los cambios se perderían al reiniciar.

## Usuarios, contraseñas y recuperación

- **Política de contraseñas:**
  - mínimo 10 caracteres, con al menos una mayúscula, una minúscula, un número y un símbolo;
  - no puede contener el usuario ni el nombre;
  - no puede tener secuencias (1234, abcd) ni el mismo carácter cuatro veces seguidas;
  - no puede contener palabras comunes («contraseña», «colombia», «apccolombia»…).
- **Contraseñas temporales:** las que entrega el sistema tienen 14 caracteres aleatorios y se cambian obligatoriamente al primer ingreso.
- **Bloqueo:** después de 5 intentos fallidos, la cuenta se bloquea 15 minutos.
- **Cifrado:** las contraseñas se guardan con PBKDF2-SHA256 (600.000 iteraciones), y las cuentas completas se cifran con `USUARIOS_CLAVE`.
- **Recuperar la contraseña (sin correo):**
  1. **Códigos de recuperación:** cada persona recibe 10 al activar su cuenta y puede generar códigos nuevos en **Mi cuenta**. Se usan en la pantalla de ingreso, en «¿Olvidaste tu contraseña?». Cada código sirve una sola vez.
  2. **El administrador restablece la contraseña** en **Usuarios**. Esto también desbloquea la cuenta y deja una contraseña temporal.
  3. **Si el único administrador pierde el acceso:** en el computador, con los mismos secretos, se ejecuta `python mapeo.py restablecer-clave --usuario nata`.
- **Mi cuenta:** cada persona cambia ahí su contraseña y genera códigos nuevos.
- **Sesión:**
  - No se cierra sola por tiempo de uso.
  - Si se corta la conexión o la app se reinicia, al volver a la misma dirección se entra sin escribir la contraseña, durante 12 horas. Esto funciona con una ficha firmada en la dirección de la página, así que no se debe compartir la dirección con `?s=` al final: para compartir la app se usa la dirección sin ese final.
  - **Cerrar sesión** o cambiar la contraseña anulan la ficha en todos los navegadores.

## Calidad del dato

### Qué cambió frente al formulario de Airtable

| Antes | Ahora |
|---|---|
| Actor escrito a mano o *NUEVO, con "(Creado)" al final | Actor elegido del **catálogo**; si no existe, se agrega como "Pendiente de crear" |
| Oficial / No Oficial elegido en cada convocatoria | Sale del **tipo de actor**: gobiernos, agencias, ONU y banca multilateral = Oficial; fundaciones, ONG, academia y empresas = No Oficial. Si cambia el tipo de un actor, se actualizan todas sus convocatorias |
| Casilla "más de un mes y una semana" marcada a mano | Se calcula con las fechas |
| Monto sin contexto | Campo **Tipo de monto**: por beneficiario o proyecto / presupuesto total |
| Sin controles | **16 reglas**: listas controladas, máximo 3 temáticas, fechas coherentes, enlaces y correo válidos, duplicados… |
| El formulario escribía directo en la base | Todo pasa por la **bandeja** y una **lista de chequeo** de 11 puntos, según el procedimiento de validación |

### Corregir lo que quedó pendiente

Las correcciones que no tenían duda se aplicaron solas al migrar. Lo que necesita criterio quedó marcado en cada convocatoria, por ejemplo:
- campos vacíos,
- más de 3 temáticas,
- convocatorias marcadas como permanentes pero con fecha límite,
- posibles duplicados.

En la página **Base de convocatorias** se filtran por regla y se corrigen una por una; el panel de calidad se actualiza mientras se edita. Las duplicadas se retiran con un motivo.

### Auditar un export antes de migrar

```bash
python mapeo.py auditar ruta/al/export.csv
```

## Duplicados por año

Muchas becas y subvenciones abren cada año con el mismo enlace. **Cada año es una edición nueva y se registra.** Lo que el sistema impide es registrar dos veces la misma convocatoria **en el mismo año**:
- **Año de la convocatoria:** se toma de la fecha límite; si no hay, de la fecha de apertura; si tampoco, de la fecha de registro.
- **Mismo enlace y mismo año:** es un duplicado. El enlace se compara «limpio»: sin http/https, sin www., sin #ancla, sin
  parámetros de rastreo (utm_…), sin prefijo de idioma (/en/, /es/…) ni index.html. Si se registra a mano es un error.
- **Nombre casi igual en el mismo año (y del mismo oferente):** se compara el nombre completo, el nombre en español y el original entre paréntesis
  (así «Premio Earthshot (The Earthshot Prize)» coincide con «The Earthshot Prize»). Si se registra a mano sale una alerta;
  lo que llega solo (mapeo y Gemini) **no entra**.
- **Ediciones o rondas distintas:** «28ª convocatoria» y «29ª convocatoria», o «Ronda 1» y «Ronda 2», no son duplicados.
- **Limpieza automática:** al empezar cada búsqueda se descartan, con el motivo «Duplicado», las copias del mismo año que
  llegaron solas y que nadie ha editado.
- **Mismo enlace de otro año:** es una **nueva edición** y se permite. En la bandeja queda marcada como «Nueva edición» con el año de la anterior.
- **Permanentes:** una convocatoria permanente es la misma mientras siga abierta.
- **Descartadas:** lo descartado este año tampoco vuelve a llegar a la bandeja.

## Páginas que reúnen varias convocatorias

Muchas páginas («Becas», «Convocatorias abiertas») muestran cada convocatoria en un **desplegable, una pestaña o una sección**
de la misma página, sin una página aparte (por ejemplo, https://tec.mx/es/profesional/becas). El mapeo las detecta y **separa
cada convocatoria**: la analiza con su propio título, sus fechas, sus requisitos y su elegibilidad, y la registra con el enlace
de la página más el ancla de la sección (`…/becas#beca-al-talento-academico`). La página general no se registra.

- Las secciones generales (fechas importantes, calendario, cómo aplicar) se le pasan a Gemini como contexto; no reemplazan
  las fechas propias de cada convocatoria.
- Las secciones que no son convocatorias (requisitos, preguntas frecuentes, contacto…) se ignoran.
- Una sección que exige **otra nacionalidad** («Nacionalidad mexicana», «must be a US citizen») se descarta como no
  elegible, salvo que la misma convocatoria nombre a Colombia o a América Latina.
- Si el contenido de los desplegables solo aparece al hacer clic (se carga con JavaScript), la página tiene que leerse con
  navegador: marcar la fuente con «Requiere navegador» en la configuración (necesita Playwright en el servidor).

## Control de entrada: lo automático llega en español y completo

Lo que encuentra el sistema solo (mapeo y búsqueda con Gemini) **solo pasa a la bandeja si llega en español y con los campos
obligatorios completos**, con las mismas reglas de validación que se aplican al revisar. Si no, queda en el estado
**Por completar**, que no aparece en la bandeja, con la lista de lo que le falta.

- **Qué se exige:** nombre, descripción, objetivos, requisitos (al menos dos criterios con contenido), observaciones de la fecha
  y del financiamiento en español; ninguna regla en rojo, salvo las que siempre confirma una persona (las verificaciones de la
  lista de chequeo y el actor en CICLOPE); y nombre traducido con el original entre paréntesis.
- **Gemini traduce y completa:** lee la página oficial y escribe todo en español; los textos que el sistema leyó en otro idioma
  se reemplazan por su traducción.
- **Reintentos:** al empezar cada búsqueda, el sistema reintenta las «Por completar» (hasta 4 veces); las que quedan completas
  pasan a la bandeja. También se puede pulsar **Reintentar ahora** en *Buscar convocatorias*, o
  `python mapeo.py completar-pendientes`.
- **Sin Gemini** (sin clave, sin cupo o con el interruptor apagado) lo que está en otro idioma no puede pasar: espera.
- **Lo que ya llegó a la bandeja** solo, en otro idioma o incompleto, y que nadie ha editado, vuelve a «Por completar» en la
  siguiente búsqueda. Lo que una persona ya editó no se mueve. Lo migrado de Airtable no se toca.

## Bandeja de revisión

| Pestaña | Qué se hace |
|---|---|
| Por revisar | Vista de trabajo, con estas partes: <ul><li>**Indicadores:** por revisar, llegadas en los últimos 7 días, cierran en 30 días, sin errores y nuevas ediciones.</li><li>**Filtros:** origen (mapeo automático, Gemini, manual, Airtable), modalidad, cierre, elegibilidad, texto y «solo sin errores».</li><li>**Tabla:** con semáforo de cierre y enlace a la página oficial. Una fila marcada abre su revisión completa; varias marcadas se **descartan en bloque** con un motivo de la lista.</li></ul> Para aprobar hay que marcar la lista de chequeo de 11 puntos y no tener errores |
| Actores pendientes | Actores que faltan en CICLOPE, con descarga de sus datos para el sistema de creación de actores. Al registrar uno como creado, sus convocatorias ya revisadas entran solas a la base |
| Registrar convocatoria | Reemplaza el formulario de Airtable, con las mismas listas y validaciones |
| En la base | Convocatorias ya aprobadas (se corrigen en "Base de convocatorias") |
| Descartadas | Convocatorias descartadas y su motivo |
| Catálogo de actores | Consultarlo; el administrador edita tipo, estado y alias |

## Procedimiento de validación de convocatorias (DGDCI)

Cómo aplica el sistema cada criterio del procedimiento:

| Criterio | Cómo lo aplica el sistema |
|---|---|
| **1. Fuente oficial y verificable** | El mapeo solo lee el dominio oficial de cada fuente. La regla **R17** bloquea acortadores, agregadores (FundsforNGOs…) y **boletines de otras entidades** (Boletín de Oferta Internacional de la Alcaldía de Bogotá, Cancillería y demás dominios .gov.co que difunden). Gemini tiene la misma prohibición y el sistema la vuelve a revisar |
| Abierta o con apertura anunciada | **R09**: si ya cerró, error. Campo **Fecha de apertura**: una apertura anunciada sin fecha de cierre queda como alerta, no como error |
| Colombia elegible | Puntaje de elegibilidad (sirve que esté abierta a extranjeros sin excluir a Colombia), verificación **R01** y lista de chequeo |
| Información suficiente | **R18**: campo **Requisitos y condiciones de participación**, obligatorio en convocatorias nuevas |
| **2. Cooperante** | Actor del catálogo (**R05-R07**) |
| Modalidad | Lista controlada |
| Población objetivo | «Dirigida a», poblaciones priorizadas y elegibilidad |
| Áreas temáticas | Lista controlada, máximo 3 (**R04**) |
| Vigencia | Fechas de apertura y cierre (**R09**) |
| Requisitos y procedimiento de postulación | **R18**: cada modalidad incluye el renglón «Procedimiento de postulación» |
| Monto o beneficios | **R13**: el monto en USD cuando se conoce; si no, la descripción de los beneficios |
| Fuente de información | Enlace oficial de información y de postulación (**R11**, **R17**) |
| **3. Criterios según la modalidad** | **R18** con una plantilla por modalidad. Subvención: organizaciones elegibles, experiencia, contrapartida, gastos financiables. Beca: perfil, nivel, requisitos académicos, cobertura, condiciones. Premio: público, criterios, reconocimiento, selección. Cooperación técnica: tipo de asistencia, entidades beneficiarias, áreas, requisitos. Si un criterio falta, alerta; si la convocatoria no lo dice, se escribe «No se indica» |
| **4. Antes de publicar** | Lista de chequeo de 11 puntos. Botón **Comprobar que los enlaces funcionan**. Duplicados (**R16**) |
| **5. Socialización** (aparte) | Ver abajo |

### Validación y socialización son cosas distintas

- **Validación (numerales 1 a 4):** decide si una convocatoria se registra. El mapeo, la búsqueda con Gemini, las reglas de calidad y la lista de chequeo aplican solo estos criterios. **Toda convocatoria válida entra a la base**, sea de USD 5.000 o de USD 5 millones, cierre en dos semanas o en seis meses.
- **Socialización (numeral 5):** se revisa aparte, sobre las convocatorias ya válidas, para sugerir cuáles difundir además por los canales institucionales. El sistema calcula «Se sugiere para priorización» y su motivo con estos criterios:
  - plazo mayor a un mes y una semana;
  - subvención de más de USD 50.000, o beca;
  - otras modalidades de más de USD 50.000 (confirmar);
  - o solicitud expresa del cooperante.

  No es una regla de calidad, no aparece en el panel de calidad y no bloquea nada. «Convocatoria priorizada» la decide la DGDCI.

En la base histórica no se exigen los requisitos (R18) ni se recalcula la priorización, porque Airtable no tenía esos campos. Sí se exigen en toda convocatoria nueva, mapeada o registrada a mano.

## Dashboard e informes

La página **Dashboard e informes** usa las convocatorias aprobadas de la base. En la barra lateral se pueden incluir también las que están en revisión. Tiene filtros de fecha de registro, carácter, modalidad y tipo de actor, y estas pestañas: Resumen, Oficial, No oficial (fundaciones, ONG, academia y empresas), Temáticas y tendencia, Público/CAD/ODS, Calidad del dato, Datos e Informe.

En la pestaña **Informe** se genera el informe en Word y PDF con los filtros activos:
- portada y ficha técnica,
- resumen ejecutivo,
- siete secciones con 12 gráficos y textos automáticos,
- notas de calidad del dato.

También se genera sin abrir la aplicación:

```bash
python mapeo.py informe
```

## Mapeo de convocatorias internacionales

Busca **becas, subvenciones, cooperación técnica y premios** abiertos a Colombia, siempre en el **sitio oficial de cada oferente**. Descarta lo que no admite colombianos, lo vencido y las becas que están en ICETEX (la exclusión de ICETEX solo aplica a becas). Lo que encuentra va a la **bandeja**, nunca directo a la base, con las verificaciones sin marcar.

### Fuentes

| Grupo | Origen |
|---|---|
| Gobiernos y agencias, Organismos multilaterales, Fundaciones, ONG y empresas | Los oferentes que ya están en la base de convocatorias, con su dominio oficial verificado, y los programas del pack de becas que tienen oferente oficial identificable |
| Universidades y centros de investigación | Universidades de la configuración inicial y del pack de becas |
| Cámaras binacionales | Las cámaras de comercio binacionales (11 sin dominio: completar) |

Cada fuente revisa las cuatro modalidades (columna **Modalidades a buscar** = «Todas», o por ejemplo «Beca; Premio»). La modalidad de cada convocatoria se decide con las palabras de la hoja **Palabras_modalidad**: cuentan más en el título, luego en la dirección y luego en el texto.

Las fuentes con dominio **Por confirmar** o sin dominio quedan inactivas. El pack de becas es material comercial de una empresa de mentorías: no se usaron sus enlaces sino los oferentes oficiales de cada programa (los enlaces acortados, de asesorías privadas o de convocatorias 2022 se descartaron).

### Uso

Las ejecuciones (validar fuentes, mapeo y búsqueda con Gemini) **corren en segundo plano en el servidor**:
- Siguen aunque se cierre la pestaña, se apague el computador o se cierre la sesión.
- La página muestra el avance y tiene un botón **Detener**.
- Hay una sola ejecución a la vez para todo el sistema.
- Lo encontrado se guarda **fuente por fuente**: las convocatorias llegan a la bandeja mientras corre, y la validación guarda su avance cada 10 fuentes.
- Si el servidor se reinicia a mitad de camino, la página lo avisa. Al volver a ejecutarla, no se repite lo que ya está en el sistema.

Desde la página **Buscar convocatorias**:

1. **Validar fuentes** (la primera vez y una vez al mes): comprueba que cada sitio responda, que no redirija a otro dominio, que se identifique con el nombre del oferente y encuentra su página de convocatorias.
2. **Ejecutar mapeo ahora**: se puede elegir qué grupos revisar.
   - **Modo rápido**, el normal: solo abre las convocatorias que no ha visto antes. Las conocidas se marcan como «siguen publicadas» sin volver a abrirlas. Cada fuente tiene además una **revisión completa automática cada 30 días**, para detectar cambios de fecha y nuevas ediciones con el mismo enlace. La primera corrida siempre es completa.
   - **Revisión completa**, con el interruptor de la página: vuelve a abrir todo.
   - **Se saltan las fuentes que fallaron en la última validación:** sitio bloqueado, sin respuesta o redirigido.
   - **Velocidad**, en la página: cuántas fuentes a la vez (10 por defecto) y la pausa entre páginas del mismo sitio (2 segundos). Con todas las fuentes (más de 200) tarda alrededor de una hora; se recomienda un grupo por día. Revisa 6 fuentes a la vez, respetando 3 segundos entre páginas del mismo sitio.

Desde la terminal: `python mapeo.py validar-fuentes`, `python mapeo.py mapear --grupo "Gobiernos y agencias"`, o `--fuente OFE-012`.

| Estado de una fuente | Qué hacer |
|---|---|
| Activa | Nada |
| … confirmar que el sitio es del oferente | El título del sitio no nombra al oferente: abrirlo y confirmar |
| Sin página de convocatorias: completar URL a mano | Pegar la página en **URL de convocatorias** |
| Sitio no responde / Redirige a otro dominio | Revisar el dominio |
| No oficial (acortador, agregador o ICETEX) | Cambiar por el dominio del oferente |
| Bloqueado por robots.txt | El sitio no permite programas automáticos: dejar la fuente inactiva |
| Falta dominio | Completar **Dominio oficial** y poner **Activa = Sí** |

### Búsqueda externa con Gemini (cuando se requiera)

El mapeo solo revisa las fuentes configuradas. Para encontrar convocatorias en **otros sitios oficiales**, la página **Buscar convocatorias → Buscar en otros sitios oficiales (con Gemini)** le pide a Gemini (con búsqueda de Google) convocatorias abiertas a Colombia, con estas condiciones en la instrucción:
- solo sitios oficiales del oferente: nada de agregadores, acortadores, redes sociales ni noticias;
- Colombia elegible, con la frase de la página que lo prueba;
- convocatoria abierta o permanente;
- si es beca, que no esté en ICETEX;
- que no invente enlaces;
- que use los valores de las listas del formulario (público, temáticas, modalidad, tipo de actor).

**Gemini solo propone.** El sistema abre cada página y le aplica las mismas reglas del mapeo:
1. Descarta agregadores, formularios e ICETEX.
2. Descarta las páginas que no existen, así se eliminan los enlaces inventados.
3. Revisa elegibilidad, fecha y duplicados.

Lo que pasa llega a la **bandeja** con los campos de la base llenos:
- **Lo que se lee en la página manda:** fecha límite, monto, correo, público, temáticas e idioma.
- **Gemini completa los vacíos:** objetivos, poblaciones priorizadas, ámbito geográfico, Plan Marco, tipo de monto y observaciones. También pone en español el nombre (con el original entre paréntesis) y la descripción.
- **Solo se aceptan valores de las listas del formulario**, y las temáticas son máximo 3. Al completar las temáticas se calculan también ENCI, ODS, CAD, sector y PND.
- **Revisión de la propuesta:** en la bandeja se ven los campos que completó Gemini y si la frase con la que prueba que Colombia es elegible aparece de verdad en la página.

Quedan para quien revisa las verificaciones, la priorización, el acompañamiento y los campos de publicación, que se hacen por fuera. Los sitios nuevos aparecen como **fuentes sugeridas** y el administrador decide si se agregan al mapeo.

Para activarla:
1. Crear una clave en Google AI Studio y agregarla como secreto `GEMINI_API_KEY`.
2. El modelo se elige en la hoja **Parametros → Modelo de Gemini**, o con el secreto `GEMINI_MODEL`. Por defecto es `gemini-3.8-flash` (gratuito en el plan gratuito de la API, dentro de sus límites). Si Google retira el modelo configurado, el sistema usa automáticamente el que Google sugiere en su respuesta y lo avisa en el registro. Ojo: en algunos modelos la búsqueda en Google de Gemini (paso 3, búsqueda externa) puede exigir facturación activa; el completado de campos del mapeo no busca en Google y no la necesita. En la página de Mapeo, el interruptor **Completar campos con Gemini** permite apagarlo en una corrida.

Desde la terminal: `python mapeo.py buscar-externo --modalidad Subvención --tema "cambio climático"`.

### ICETEX

La hoja **ICETEX_paginas** trae la página oficial de becas vigentes de ICETEX (y la de programas cofinanciados). Las becas de esas listas, o cuya página menciona o enlaza a ICETEX, se descartan.

### Elegibilidad para colombianos (hoja *Elegibilidad*)

No hace falta que la página nombre a Colombia. Una convocatoria abierta a extranjeros, a internacionales, a todos los países, a América Latina o a países en desarrollo sirve, siempre que no excluya a Colombia ni a la región.

| Si la página… | Puntos | Efecto |
|---|---|---|
| Nombra a Colombia o a los colombianos | +3 | Inclusión fuerte |
| Nombra América Latina, Iberoamérica o las Américas | +3 | Inclusión fuerte |
| Está abierta a extranjeros, internacionales o todos los países | +2 | Elegible |
| Habla de países en desarrollo o de la lista CAD | +2 | Elegible |
| Restringe a otros (solo UE, solo africanos…) | −3 | Se descarta **solo si** la página no nombra a Colombia ni a América Latina |
| Excluye expresamente a Colombia o a la región | −10 | Se descarta siempre |

Con 2 puntos o más es *Elegible*; con 1, *Probable*; si la página no dice quién puede postularse, *Revisar*. Las convocatorias en *Revisar* no se descartan: llegan a la bandeja para que alguien lo confirme.

### Completar los campos con Gemini (mapeo normal)

Si existe el secreto `GEMINI_API_KEY`, cada convocatoria nueva que encuentra el mapeo se completa leyendo su página oficial. En este caso Gemini no busca en Google; solo lee el texto que el sistema ya descargó. Se aplican las mismas reglas de la búsqueda externa:
- lo que se leyó en la página manda;
- Gemini completa los vacíos y pone en español el nombre y la descripción;
- solo se aceptan valores de las listas del formulario;
- en la bandeja se marca qué completó Gemini.

Se controla en **Parametros**: *Completar campos con Gemini en el mapeo*, *Pausa entre consultas* y *Máximo por corrida*. Sin clave, el mapeo funciona igual, con los campos que lee de la página.

### Enlaces oficiales (regla R17)

Cada actor del catálogo tiene su **sitio web oficial** (uno o varios dominios separados por «;», por ejemplo el de la GIZ y el de un programa que ejecuta). La regla R17 revisa «Link de la Fuente Oferente» y «Cómo aplicar»:
- **Acortadores** (bit.ly, lnkd.in, forms.gle, ffngos.org) y **agregadores** (fundsforngos, onglink): error en convocatorias nuevas; alerta en la base.
- **Beca vía ICETEX**: error en nuevas; alerta en la base.
- **Otro sitio** que no es del actor, o un formulario puesto como sitio del oferente: alerta.
- Los parámetros de rastreo (`?utm_source=chatgpt.com`) se quitan solos.

Las convocatorias marcadas se corrigen en **Base de convocatorias**, filtrando por la regla R17.

## Archivos

| Archivo o carpeta | Qué es |
|---|---|
| `app.py`, `paginas/`, `componentes.py`, `ui.py` | La aplicación |
| `bandeja/` | Base de datos, flujo de revisión y usuarios |
| `calidad/` | Reglas de calidad, catálogo de actores, auditoría y migración |
| `analitica/` | Indicadores, gráficos, textos e informe |
| `motor/`, `mapeo.py` | Mapeo de becas y comandos |
| `config/` | Configuración del mapeo y listas controladas |
| `datos/convocatorias.db` | La base corregida |
| `Dockerfile`, `README.md` | Despliegue en Hugging Face (la construcción de la imagen no se pudo probar en el entorno de desarrollo) |
| `pruebas/` | Pruebas automáticas |
