# DemBones executables

Drop the precompiled DemBones CLI binaries here, one per platform. The tool
resolves them in `dem_cmds.get_exe_path()`:

```
bin/
├── Windows/DemBones.exe
├── Linux/DemBones
└── macOS/DemBones
```

Source: https://github.com/electronicarts/dem-bones (BSD-3). Use the precompiled
binaries from the repo's `bin/<OS>/` rather than building from source (building
needs the FBX SDK).

The binaries are intentionally not committed (they're large and platform
specific). Place them by hand on each workstation, or wire them into the
pipeline's tool-deploy step.
```