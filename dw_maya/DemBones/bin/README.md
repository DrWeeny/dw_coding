# DemBones executables

The DemBones CLI binary is **not committed** to this repo. It's an Electronic
Arts project under the BSD-3 license, and the binaries are large and platform
specific, so each workstation supplies its own.

`dem_cmds.get_exe_path()` resolves the executable in this order (first hit wins):

1. The `DEMBONES_EXE` env var, set to the binary's full path (pipeline / tool
   deploy).
2. `DemBones[.exe]` on the system `PATH`.
3. A binary dropped here, under `bin/<OS>/`:

   ```
   bin/
   ├── Windows/DemBones.exe
   ├── Linux/DemBones
   └── macOS/DemBones
   ```

Source / download: https://github.com/electronicarts/dem-bones (BSD-3). Use the
precompiled binaries from the releases / `bin/<OS>/` rather than building from
source (building needs the FBX SDK).

The upstream BSD-3 `LICENSE` is kept in this folder so the repo stays compliant
if the binaries are ever committed — BSD-3 requires the copyright notice and
disclaimer to travel with redistributed binaries. It covers the binaries only,
not the surrounding `dw_open_tools` code.
```