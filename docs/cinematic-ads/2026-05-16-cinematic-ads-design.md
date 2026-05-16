# Diseño: Sistema de Cinematic Ads con IA

**Fecha:** 2026-05-16
**Estado:** Aprobado

---

## Resumen

Sistema interactivo de dirección creativa para generar ads cinematográficos a partir de una foto de producto. El usuario entrega una imagen, el sistema analiza el producto con GPT-4o Vision, propone un brief creativo, y genera un video de 30-60 segundos con escenas animadas, voz narrada y música — todo ensamblado con ffmpeg.

---

## Stack tecnológico

| Componente | Herramienta |
|---|---|
| Análisis de producto | GPT-4o Vision (OpenAI API) |
| Generación de escenas | GPT-image-2 (OpenAI API) |
| Recorte de producto | rembg + Pillow |
| Animación de escenas | Higgsfield MCP → Seedance 2.0 |
| Auditoría de calidad | GPT-4o Vision (structured output) |
| Voz / narración | ElevenLabs API |
| Música royalty-free | Pixabay Music API (gratuita) |
| Ensamblaje final | ffmpeg |

---

## Arquitectura de módulos

```
ads/
├── __init__.py
├── main.py              # Entry point: python -m ads --image product.jpg
├── models.py            # Dataclasses: AdBrief, Scene, SceneAsset, AdOutput
├── creative_director.py # GPT-4o Vision → wizard interactivo → AdBrief
├── storyboard.py        # AdBrief → 6-8 Scene con prompts y narración
├── scene_composer.py    # GPT-image-2 → imagen entorno → composición producto
├── animator.py          # Higgsfield MCP → Seedance 2.0 → clip .mp4 por escena
├── auditor.py           # GPT-4o Vision → 4 checks por escena (imagen + video)
├── verifier.py          # Pre-flight check + post-pipeline validation
├── voice.py             # ElevenLabs API → audio por escena + tagline
├── music.py             # Pixabay API → música por mood → normalización ffmpeg
└── assembler.py         # ffmpeg → une clips + voz + música → ad_final.mp4
```

---

## Modelos de datos

```python
@dataclass
class AdBrief:
    product_description: str     # detectado por GPT-4o Vision
    hero_message: str            # mensaje central del ad
    narrative_arc: str           # 3 actos: hook → desarrollo → CTA
    visual_style: str            # e.g. "neon noir", "golden hour lifestyle"
    color_palette: list[str]     # 3-5 colores hex
    mood_music: str              # e.g. "cinematic tension", "uplifting pop"
    voice_tone: str              # e.g. "confident female ES", "deep male EN"
    dont_include: list[str]      # elementos a excluir explícitamente
    tagline: str                 # frase final del ad

@dataclass
class Scene:
    index: int
    visual_prompt: str           # prompt para GPT-image-2
    narration_line: str          # línea de voz para esta escena
    camera_motion: str           # e.g. "slow zoom in", "left pan", "dolly forward"
    duration_sec: float          # 3-5 segundos

@dataclass
class SceneAsset:
    scene: Scene
    image_path: Path             # imagen compuesta (entorno + producto)
    video_path: Path             # clip animado por Higgsfield
    audio_path: Path             # narración ElevenLabs

@dataclass
class AdOutput:
    brief: AdBrief
    assets: list[SceneAsset]
    music_path: Path
    final_video_path: Path       # ad_final.mp4
    duration_sec: float
```

---

## Flujo completo

```
1. verifier.pre_flight()
   ↓ aborta si falla cualquier check
2. creative_director.analyze(image_path)
   → GPT-4o Vision extrae: producto, colores, estilo, audiencia probable
3. creative_director.run_wizard(analysis)
   → 5 preguntas al usuario: mensaje, referencias, exclusiones, audiencia, emoción
4. creative_director.generate_brief(analysis, answers)
   → GPT-4o genera AdBrief completo → usuario revisa y aprueba
5. storyboard.generate(brief)
   → GPT-4o genera 6-8 Scene con prompts, narración y movimiento de cámara
6. Por cada Scene:
   a. scene_composer.compose(scene, brief, product_image)
      → GPT-image-2 genera entorno → rembg recorta producto → Pillow compone
   b. auditor.audit_image(image_path, scene, brief)
      → 4 checks: consistencia visual, calidad cinematográfica,
                  coherencia narrativa, brand safety
      → score 0-10 por dimensión; si < 7 en cualquiera → regenera (máx 3 intentos)
   c. Usuario aprueba imagen en CLI (ver preview path o descripción)
   d. animator.animate(image_path, scene)
      → Higgsfield MCP generate_video → Seedance 2.0 → clip .mp4
   e. auditor.audit_video(video_path, scene, brief)
      → mismos 4 checks sobre el clip animado
      → si falla → re-anima (máx 2 intentos) o escala al usuario
7. voice.synthesize(brief, scenes)           ← paralelo con paso 6 si brief aprobado
   → ElevenLabs: una llamada por scene.narration_line + tagline final
8. music.fetch(brief.mood_music)
   → Pixabay Music API → descarga track → normaliza a -14 LUFS con ffmpeg
9. assembler.assemble(assets, music_path, brief)
   → por escena: merge video + audio_voz → escena_completa.mp4
   → concatenar escenas → ad_sin_musica.mp4
   → mix música a -18dB bajo voz → ad_final.mp4
   → fade in/out música, título con tagline al final
10. verifier.post_validate(output_dir)
    → verifica reproducibilidad, duración 25-65s, pistas A/V
    → si video corrupto → re-ensambla desde clips individuales
11. output/ad_final.mp4 ✓
```

---

## Verificador (`verifier.py`)

### Pre-flight checks
- OpenAI API key válida y con créditos
- Higgsfield MCP conectado con balance suficiente
- ElevenLabs API key válida
- Pixabay API accesible
- ffmpeg instalado y en PATH
- rembg instalado
- Imagen del producto: legible, >200px, formato soportado (jpg/png/webp)
- Espacio en disco suficiente (>500 MB libres)

### Post-validation
- `ad_final.mp4` existe y es reproducible (ffprobe)
- Duración entre 25-65 segundos
- Tiene pistas de video y audio
- Todos los scene clips presentes en `scenes/`
- `brief.json` guardado correctamente

---

## Auditor (`auditor.py`)

GPT-4o Vision con structured output. Evalúa cada imagen/video en 4 dimensiones:

| Dimensión | Qué verifica |
|---|---|
| Consistencia visual | Producto igual en todas las escenas (colores, proporciones, iluminación) |
| Calidad cinematográfica | Composición, encuadre, que se vea premium |
| Coherencia narrativa | La escena tiene sentido en el arco narrativo del brief |
| Brand safety | Sin texto raro, artefactos, distorsiones del producto |

Score 0-10 por dimensión. Umbral mínimo: 7. Devuelve motivo de rechazo si falla.

---

## Output

```
output/
├── ad_final.mp4          # ad completo listo para publicar
├── scenes/
│   ├── scene_01.mp4
│   ├── scene_02.mp4
│   └── ...
├── brief.json            # AdBrief serializado
└── assets/
    ├── images/           # imágenes base compuestas por escena
    ├── audio/            # narración ElevenLabs por escena
    └── music.mp3         # track descargado
```

---

## Configuración de APIs

Variables de entorno requeridas:
```
OPENAI_API_KEY          # GPT-4o Vision + GPT-image-2
ELEVENLABS_API_KEY      # sk_498eaf... (voz)
PIXABAY_API_KEY         # música gratuita
```

Higgsfield: conectado vía MCP (no requiere variable de entorno adicional).

---

## Consideraciones

- **Costo estimado por ad:** ~$0.50-2.00 USD dependiendo de regeneraciones (GPT-image-2 + ElevenLabs son los más caros)
- **Tiempo estimado:** 8-15 minutos por ad completo (Seedance 2.0 es el cuello de botella)
- **Reintentos:** imagen máx 3, video máx 2; si sigue fallando, escala al usuario con descripción del problema
- **El producto nunca es regenerado por IA** — siempre es la foto original recortada y compuesta, garantizando fidelidad total al producto real
