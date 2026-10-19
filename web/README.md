Served root.

```
index.html   the sales page - LP Group's landing page, with the scene in its hero
site.css     its stylesheet          site.js    everything the page builds from data
content.js   every editable fact: contacts, numbers, prices, the flat inventory
fonts/       Jost + Noto Sans Georgian (SIL OFL, licences beside them)
photos/      gallery photographs; anything missing draws a captioned plate instead

lab.html     the render lab - the scene with its full HUD, what the rigs measure
app.js       the scene itself: camera, sky, materials, batching, post, the loop
scene.css    the lab's chrome (HUD, developer panel, compare wipe, boot veil)

scene.glb    rebuilt by blender/build.py       scene_meta.json  written beside it
tex/         converted scanned maps           reference.jpg    the compare wipe's photograph
```

`index.html` and `lab.html` load the *same* `app.js`. The page sets
`data-embed="1"` on `<body>`; everything that differs is guarded by that, and
the lab is unchanged - which is what `perf-shots/golden-s1.png` guards.

They never import each other. The scene announces itself on `window`
(`lp:ready`, `lp:scene`, `lp:mode`) and takes instructions through `window.LP`,
so either page opens on its own.
