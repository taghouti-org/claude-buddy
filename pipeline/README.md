# STL to VRM pipeline (experimental)

These scripts turned one uncoloured, single-shell STL figure into a textured, rigged VRM, using pictures of the same figure from several angles. They are kept here as a record of the method. They are not a general tool.

Expect to edit them. They assume:

- a chibi figure about 116 mm tall standing on a base, Z up, facing −Y;
- specific file names for the reference pictures (see below);
- skeleton joint positions written by hand for that figure (`skel.py`).

No model or reference picture is included.

## Requirements

System Python with `numpy`, `scipy` and `Pillow`. No GPU and no 3D software are needed; rendering for the fitting steps is a small point-splat renderer in `lib.py`.

## Steps

Run everything from one working folder. Reference pictures go in `refs/`.

| Step | Script | What it does |
|---|---|---|
| 1 | `prep.py model.stl` | Reads the STL, welds vertices, reports connected parts. |
| 2 | `color.py` | Removes the base, projects a first picture on the mesh. |
| 3 | `mvfit.py 2 3 4 5` then `mvfit2.py` | Fits a camera to each exact screenshot of the model (`refs/2.png` …) by silhouette matching. |
| 4 | `fit8c.py` | Splits restyled reference sheets (`refs/7.png`, `refs/8.png`) into views and fits a camera plus a row-wise warp to each. |
| 5 | `reg.py` | Bends each restyled view onto a render of the real model, so drawn features land on the sculpted ones. |
| 6 | `build.py out.vrm 0.5 2 0.3` | Simplifies the mesh, separates swords, arms, scarf and hair, closes the cuts, textures from the registered views, rigs, and writes the VRM. |

Arguments to `build.py`: output file, body cell size in mm, texture upscale factor, head cell size in mm.

## Ideas in the method

- **Two kinds of reference.** Exact screenshots of the model fit its shape perfectly but are low resolution. Restyled drawings are sharp but do not match the sculpt. The screenshots decide *what is where*; the drawings supply the colour.
- **Registration before projection.** Each drawing is warped onto a render of the model textured from the screenshots, by coarse-to-fine block matching, before it is used as a texture.
- **One view per face.** Each triangle takes its texture from a single view, chosen front-first and smoothed over the surface, to avoid ghosting.
- **Parts by evidence.** Swords are found along their own long axis, arms by sleeve and skin colour hugging the arm bones, the scarf by colour, hair as the dark mass standing off the face. Each part is cut free by duplicating vertices along its boundary, and each opened rim is closed with a flat lid.
- **Hair is lit, the rest is not.** Hair gets a glossy material and smoothed normals so it catches moving highlights. Everything else keeps the shading painted in the references.

## Known weak points

- The boundary between a fist and the sword guard it grips is decided by colour and is imperfect.
- Legs, belt gear and hair tips are not separated, so deep leg bends stretch neighbouring parts.
- Surfaces no reference shows are filled from neighbouring colours.
