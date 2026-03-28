# Video Game Character → 3D Print via Gaussian Splatting

A complete guide to capturing a video game character on screen, reconstructing it as a 3D Gaussian Splat, extracting a mesh, and 3D printing the result.

---

## Overview

| Step | Tool | Time |
|---|---|---|
| Video capture | In-game camera / photo mode | 5–15 min |
| Frame extraction + pose estimation | nerfstudio `ns-process-data` + COLMAP | 10–30 min |
| Gaussian Splatting training | nerfstudio Splatfacto | 30–60 min |
| Mesh extraction | SuGaR | 5–15 min |
| Mesh cleanup | Blender | 15–60 min |
| Slicing | PrusaSlicer / Cura / OrcaSlicer | 5–10 min |
| **Total (excluding print time)** | | **~1.5–3 hours** |

### Hardware Requirements

| Component | Minimum | Recommended |
|---|---|---|
| GPU VRAM | 8 GB | 16–24 GB |
| RAM | 16 GB | 32 GB |
| Storage | 20 GB free | SSD with 50+ GB |
| GPU | RTX 3060 | RTX 3090 / 4080 |

---

## Background: NeRFs, Gaussian Splatting, and What "Training" Means

### What is a NeRF?

**NeRF** (Neural Radiance Field) is a method for representing a 3D scene inside a neural network. Introduced in 2020, the idea is to train a small neural network (a multi-layer perceptron) that acts as a lookup function for a single scene. You give it a point in 3D space `(x, y, z)` plus a viewing direction `(θ, φ)`, and it returns:

- **Color** (RGB) — what color is this point when viewed from that angle?
- **Density** (opacity) — how solid is this point? (air = 0, solid surface = high)

To render an image from any camera angle, you cast a ray through each pixel, sample many points along the ray, query the network for color + density at each point, and blend them using classical volume rendering. The result is a photorealistic image from a viewpoint that may never have been photographed.

### What does "training" actually do?

Training a NeRF is not like training a typical AI model. Normally you train a model to generalize (recognize any cat, translate any sentence). A NeRF does the opposite — it **deliberately overfits to one specific scene**.

The training loop:

1. **Start with photos** — N images of the scene from known camera positions (COLMAP computes these).
2. **Pick a training image** — say, photo #37.
3. **Cast rays** — for each pixel in photo #37, cast a ray from that camera position into the 3D scene.
4. **Sample points** — pick many points along each ray.
5. **Ask the network** — the neural network predicts color and density at each point.
6. **Render** — blend the predictions along each ray into a predicted pixel color.
7. **Compare** — measure the difference between the predicted pixel and the actual pixel in photo #37.
8. **Update** — use gradient descent to nudge the network's weights closer to reality.
9. **Repeat** — millions of rays across all photos over thousands of iterations.

The network learns a complete internal model of the scene's geometry and appearance. It becomes an "expert" on that one scene — when asked to render from a never-seen camera angle, it produces a convincing image because it learned the underlying 3D structure, not just memorized the photos.

### How is Gaussian Splatting different?

This guide uses Gaussian Splatting (nerfstudio's Splatfacto method) rather than NeRF because it's faster and produces output that's easier to convert to a mesh. The key differences:

| | NeRF | Gaussian Splatting |
|---|---|---|
| **Representation** | Implicit — the scene lives inside a neural network's weights | Explicit — the scene is a collection of thousands/millions of 3D Gaussian blobs |
| **What gets optimized** | Neural network weights | Position, size, rotation, color, and opacity of each Gaussian |
| **Rendering** | Ray marching (cast rays, query network at many points) — slow | Rasterization (project Gaussians onto image plane) — fast, 100+ FPS |
| **Training time** | Hours | 30–60 minutes |
| **Output** | Opaque neural network | A `.ply` file listing every Gaussian and its properties |

With Gaussian Splatting, "training" means:

1. **Initialize** — place Gaussians at the 3D points COLMAP found (the sparse point cloud from structure-from-motion).
2. **Render** — project all Gaussians onto a camera's image plane using fast GPU rasterization.
3. **Compare** — measure the difference between the rendered image and the real photo.
4. **Adjust** — use gradient descent to tweak each Gaussian's position, shape, color, and opacity.
5. **Split / clone / prune** — large Gaussians get split into smaller ones, under-reconstructed areas get new Gaussians cloned in, and nearly-transparent Gaussians get pruned.
6. **Repeat** — iterate over all training images until the rendered output matches reality.

The result is a cloud of 500K–2M tiny Gaussian blobs that reproduce the scene photorealistically. Each blob has explicit properties (position, covariance matrix, color via spherical harmonics, opacity), which is why it's much easier to convert to a mesh — the geometry is already explicitly stored rather than locked inside neural network weights.

### Why "nerfstudio" if we're using Gaussian Splatting?

Nerfstudio started as a framework for NeRFs but has become a general-purpose toolkit for neural 3D reconstruction. It supports NeRF variants, Gaussian Splatting (Splatfacto), and other methods, all with a unified interface for data processing, training, visualization, and export.

---

## Phase 1: Capture the Video In-Game

This is the most important step. Bad capture = bad model, no matter how good the software is.

### Ideal setup

- Use the game's **photo mode** or **free camera** if available — you need to orbit the character while they stay still.
- If no photo mode exists, use mods (e.g., Cheat Engine camera hacks, Otis_Inf camera tools for many AAA games).
- Place the character in a **well-lit area with diffuse/even lighting** — avoid harsh shadows, neon effects, and particle systems.

### How to record

- Record at **1080p minimum, 4K preferred**.
- **30 fps** is fine (you want more unique frames, not interpolated ones).
- Orbit the character in a **slow, smooth 360-degree loop** at eye level.
- Do a **second pass at a lower angle** (looking up at the character).
- Do a **third pass at a higher angle** (looking down).
- Keep the character **centered and filling ~60–70% of the frame**.
- Move slowly enough to ensure **50–70% overlap** between consecutive frames.
- Total recording time: **30–90 seconds** is usually sufficient.

### What to avoid

- Fast camera movements or jerky pans
- Motion blur (turn it off in game settings)
- Depth of field effects (turn off)
- Chromatic aberration, film grain, vignette (turn all post-processing off)
- Reflective/glass surfaces on the character (these confuse reconstruction)
- Other moving characters or objects in the background

---

## Phase 2: Install the Tools

You need three things: **nerfstudio**, **COLMAP**, and **ffmpeg**.

### Prerequisites

- NVIDIA GPU with CUDA 11.8+ installed
- Python 3.8+
- conda (Anaconda or Miniconda)

### Installation

```bash
# Create a conda environment
conda create --name nerfstudio -y python=3.10
conda activate nerfstudio

# Install PyTorch with CUDA
pip install torch==2.1.2+cu118 torchvision==0.16.2+cu118 \
  --extra-index-url https://download.pytorch.org/whl/cu118

# Install nerfstudio
pip install nerfstudio

# Install COLMAP (camera pose estimation)
conda install -c conda-forge colmap

# Install ffmpeg (video frame extraction)
conda install -c conda-forge ffmpeg

# Install gsplat (Gaussian Splatting rasterizer)
pip install gsplat
```

Verify everything works:

```bash
ns-train --help
colmap -h
ffmpeg -version
```

---

## Phase 3: Process the Video

This step extracts frames from your video and uses COLMAP to compute the camera position for each frame.

```bash
ns-process-data video \
  --data ./my_character_video.mp4 \
  --output-dir ./data/character
```

This will:

1. Use ffmpeg to extract frames from the video.
2. Run COLMAP structure-from-motion to compute camera poses.
3. Output a nerfstudio-compatible dataset in `./data/character/`.

### Troubleshooting COLMAP

COLMAP can be finicky. If it fails:

- Extract more frames: add `--num-frames-target 500`
- Ensure your video has enough visual overlap between frames.
- Confirm the character isn't moving between frames.
- Try running COLMAP with GPU-accelerated feature matching (requires COLMAP built with CUDA).

---

## Phase 4: Train the Gaussian Splatting Model

```bash
# Standard quality (~6 GB VRAM)
ns-train splatfacto --data ./data/character

# Higher quality (~12 GB VRAM)
ns-train splatfacto-big --data ./data/character
```

Training takes 30–60 minutes on a modern consumer GPU. Nerfstudio provides a live viewer in your browser during training so you can watch the model converge in real-time.

### Export the trained model

```bash
ns-export gaussian-splat \
  --load-config outputs/character/splatfacto/<timestamp>/config.yml \
  --output-dir exports/splat
```

This produces a `.ply` file containing the Gaussian Splat representation.

---

## Phase 5: Convert Gaussians → Printable Mesh

The `.ply` from Gaussian Splatting is a point cloud of 3D Gaussians, not a solid mesh. You need to extract a surface.

### Option A: SuGaR (Recommended)

[SuGaR](https://github.com/Anttwo/SuGaR) (Surface-Aligned Gaussian Splatting) regularizes Gaussians to align with actual surfaces, then extracts a mesh via Poisson reconstruction. Published at CVPR 2024.

```bash
git clone https://github.com/Anttwo/SuGaR.git
cd SuGaR
pip install -r requirements.txt
```

Follow the repo instructions to run SuGaR on your trained Gaussian Splatting output. It produces a **textured mesh** (`.obj` + texture maps) in minutes.

SuGaR also provides a **Blender add-on** for importing the result directly.

### Option B: 3DGS-to-PC

[3DGS-to-PC](https://github.com/ffe4el/3dgs-to-mesh) converts Gaussians to a dense point cloud, then applies Poisson Surface Reconstruction. More general-purpose — works well but may need more cleanup.

### Option C: 2DGS

2D Gaussian Splatting reformulates Gaussians as 2D oriented disks, which makes surface extraction more straightforward. Good alternative if SuGaR doesn't work well for your scene.

---

## Phase 6: Clean Up in Blender

The extracted mesh will almost certainly need cleanup before printing.

### 1. Enable the 3D Print Toolbox

Edit → Preferences → Add-ons → search "3D Print Toolbox" → enable it. Access it in the 3D Viewport sidebar under the "3D-Print" tab.

### 2. Diagnose problems

Click **"Check All"** to scan for non-manifold edges, intersecting faces, flipped normals, degenerate faces, and distorted faces.

### 3. Automatic repair

Click **"Make Manifold"** in the Clean Up panel. This fills holes, removes degenerate faces, and unifies normals. Run "Check All" again to verify.

### 4. Manual fixes if needed

| Problem | Fix |
|---|---|
| Remaining holes | Select edge loops → `F` (or `Ctrl+F` → Bridge Edge Loops) |
| Flipped normals | Select all → `Shift+N` to recalculate |
| Duplicate vertices | `M` → Merge by Distance |
| Noisy surfaces | Apply a Smooth modifier sparingly |

### 5. Add a base

Add a flat cylinder or cube beneath the character's feet so it stands upright on the print bed.

### 6. Scale to desired print size

Check dimensions in the "3D-Print" tab and set to real-world millimeters.

### 7. Export

File → Export → STL (`.stl`)

---

## Phase 7: Slice and Print

Open the `.stl` in your slicer (PrusaSlicer, Cura, OrcaSlicer, etc.):

1. Orient the model for minimal supports.
2. Choose layer height based on detail level (0.10–0.15 mm for fine detail).
3. Generate supports where needed (tree supports work well for characters).
4. Slice and send to printer.

---

## Alternative Approaches

### Rip the model directly from the game

Before going the video route, check whether you can extract the 3D model from the game's files. This gives the cleanest geometry.

- **Ninja Ripper 2** — hooks into DirectX/Vulkan games and captures meshes + textures in real-time. Exports `.rip` files importable into Blender.
- **Game-specific extractors** — many popular games have community-built asset extractors that dump models as `.fbx` or `.obj`.

### AI-powered online tools

If you don't have a GPU, several services handle the video-to-3D pipeline online:

- [VideoTo3D.site](https://videoto3d.site/) — upload a video, get a `.glb` model via Gaussian Splatting.
- [3dpresso](https://3dpresso.ai/) — 1–2 minute video → 3D model in `.glb`.
- [Meshy](https://www.meshy.ai/) — image/text to 3D with multi-color print integration.

You still need to convert `.glb` → `.stl` in Blender and ensure the mesh is watertight.

### DreamPrinting (Skip the mesh entirely)

[DreamPrinting](https://arxiv.org/html/2503.00887v1) (Best in Show, SIGGRAPH 2025) converts Gaussian Splatting / NeRF representations directly into full-color 3D printing instructions using Volumetric Printing Primitives. Preserves translucency, internal detail, and color gradients. Requires a multi-material printer (Stratasys J850 Prime) or the [Cysta.ai](https://cysta.ai/) service.

---

## Key Links

| Resource | URL |
|---|---|
| nerfstudio docs | <https://docs.nerf.studio/> |
| nerfstudio GitHub | <https://github.com/nerfstudio-project/nerfstudio> |
| SuGaR (mesh extraction) | <https://github.com/Anttwo/SuGaR> |
| 3DGS-to-PC | <https://github.com/ffe4el/3dgs-to-mesh> |
| COLMAP | <https://colmap.github.io/> |
| Blender | <https://www.blender.org/> |
| Ninja Ripper 2 | <https://www.ninjaripper.com/> |
| DreamPrinting paper | <https://arxiv.org/html/2503.00887v1> |
