---
title: Convocatorias DGDCI
emoji: 📊
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Sistema de convocatorias internacionales · DGDCI · APC-Colombia

Dashboard, informes automáticos (Word y PDF), bandeja de revisión y base de convocatorias.

Secretos necesarios en el Space (Settings → Variables and secrets):

| Nombre | Valor |
|---|---|
| `HF_DATASET_REPO` | Repositorio privado de datos, por ejemplo `organizacion/convocatorias-datos` |
| `HF_TOKEN` | Token con permiso de escritura sobre ese repositorio |

La guía completa está en `LEEME.md`.
