"""
sim_cmds/nucleus_cache_ops.py — NucleusCacheOps

High-level cache operations for nucleus sim nodes (nCloth / hairSystem).
Orchestrates the low-level cache_management primitives with versioning,
file management, and CacheInfo construction.

Assumed item API  (ClothTreeItem / HairTreeItem)
────────────────────────────────────────────────
item.node           nCloth / hairSystem shape node name
item.short_name     display name (appears in cache file names)
item.cache_dir(0)   dynTmp — temp dir, Maya writes raw cache files here
item.cache_dir()    versioned dir  …/namespace/solver/cloth/
item.cache_file(1)  next-version XML path  e.g. cloth_v003.xml
item.get_iter()     current max version number (0 if no caches yet)

Low-level contracts
───────────────────
create_cache()   returns stems only  (no path, no extension)
delete_caches()  disconnects Maya cacheFile nodes — does NOT delete disk files
attach_ncache()  takes a full XML path string and a shape node name
"""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import maya.cmds as cmds

from dw_logger import get_logger
from ..sim_widget import CacheInfo, CacheType
from . import cache_management

logger = get_logger()


class NucleusCacheOps:

    # ──────────────────────────────────────────────────────────────────
    # LIST
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def list_caches(item) -> list[CacheInfo]:
        """
        Scan item.cache_dir() for .xml files and return one CacheInfo each.
        Result is sorted by file name (= version order).
        """
        try:
            cache_dir = Path(item.cache_dir())
        except Exception as e:
            logger.warning(f"list_caches: cache_dir() failed for {item.node!r}: {e}")
            return []

        if not cache_dir.exists():
            return []

        result = []
        for xml_path in sorted(cache_dir.glob("*.xml")):
            info = NucleusCacheOps._info_from_xml(xml_path, item.node)
            if info:
                result.append(info)

        return result

    # ──────────────────────────────────────────────────────────────────
    # CREATE
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def create(item, frame_range: tuple[int, int]) -> CacheInfo | None:
        """
        Simulate and write a versioned nCache for item.node.

        Steps
        ─────
        1. Create the versioned dir and dynTmp if they don't exist.
        2. Disconnect any currently attached cacheFile nodes.
        3. Run create_cache() → raw files land in dynTmp under a Maya-assigned stem.
        4. Move every matching file from dynTmp to the versioned location,
           renaming with the target stem via Path.with_suffix() so that
           cloth_v003.xml and cloth_v003.mcx end up alongside each other.
        5. Attach the new XML to item.node.
        6. Return a CacheInfo for the newly created cache.
        """
        node = item.node
        cmds.waitCursor(state=1)
        try:
            # 1. Directories
            versioned_dir = Path(item.cache_dir())          # …/cloth/
            versioned_dir.mkdir(parents=True, exist_ok=True)

            work_dir = Path(item.cache_dir(0))              # …/dynTmp
            work_dir.mkdir(parents=True, exist_ok=True)

            # Next-version XML path  e.g. …/cloth/cloth_v003.xml
            target_xml = Path(item.cache_file(1))

            # 2. Disconnect
            cache_management.delete_caches([node])

            # 3. Simulate → dynTmp
            cache_names = cache_management.create_cache(
                [node],
                str(work_dir),
                time_range=list(frame_range),
            )
            if not cache_names:
                raise RuntimeError("create_cache() returned an empty list")

            raw_stem = cache_names[0]   # e.g. "nClothShape1_cache"

            # 4. Move and rename dynTmp files to the versioned location
            #    cloth_v003.xml, cloth_v003.mcx, …
            moved = 0
            for src in work_dir.iterdir():
                if src.name.startswith(raw_stem):
                    dst = target_xml.with_suffix(src.suffix)
                    shutil.move(str(src), str(dst))
                    moved += 1

            if moved == 0:
                raise RuntimeError(
                    f"No files starting with {raw_stem!r} found in {work_dir}"
                )

            # 5. Attach
            cache_management.attach_ncache(str(target_xml), node)
            logger.debug(f"Created and attached: {target_xml.name!r} → {node!r}")

            # 6. Return CacheInfo
            return NucleusCacheOps._info_from_xml(target_xml, node)

        except Exception as e:
            logger.error(f"NucleusCacheOps.create failed for {node!r}: {e}")
            raise
        finally:
            cmds.waitCursor(state=0)

    # ──────────────────────────────────────────────────────────────────
    # ATTACH
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def attach(item, cache_info: CacheInfo) -> None:
        """Disconnect current cache, then attach cache_info to item.node."""
        cmds.waitCursor(state=1)
        try:
            cache_management.delete_caches([item.node])
            cache_management.attach_ncache(str(cache_info.path), item.node)
            logger.debug(f"Attached {Path(cache_info.path).name!r} → {item.node!r}")
        except Exception as e:
            logger.error(f"NucleusCacheOps.attach failed: {e}")
            raise
        finally:
            cmds.waitCursor(state=0)

    # ──────────────────────────────────────────────────────────────────
    # DELETE  (single version)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def delete(item, cache_info: CacheInfo) -> None:
        """
        Delete all files for this version (XML + companion .mcx / .mcc data files).
        Disconnects from Maya only if this version is currently attached,
        so other attached versions are not disturbed.
        """
        try:
            if cache_management.cache_is_attached(item.node, cache_info.name):
                cache_management.delete_caches([item.node])
        except Exception as e:
            logger.warning(f"delete: attach-check warning for {item.node!r}: {e}")

        xml_path = Path(cache_info.path)
        stem = xml_path.stem    # e.g. "cloth_v003"
        deleted = 0

        for path in xml_path.parent.glob(f"{stem}*"):
            try:
                path.unlink()
                deleted += 1
            except OSError as e:
                logger.warning(f"Could not remove {path}: {e}")

        logger.debug(f"Deleted {deleted} file(s) for {stem!r}")

    # ──────────────────────────────────────────────────────────────────
    # DELETE ALL
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def delete_all(item) -> None:
        """Disconnect and wipe every cached version for this item."""
        try:
            cache_management.delete_caches([item.node])
        except Exception as e:
            logger.warning(f"delete_all: disconnect warning: {e}")

        cache_dir = Path(item.cache_dir())
        if not cache_dir.exists():
            return

        deleted = 0
        for xml_path in list(cache_dir.glob("*.xml")):
            stem = xml_path.stem
            for path in cache_dir.glob(f"{stem}*"):
                try:
                    path.unlink()
                    deleted += 1
                except OSError as e:
                    logger.warning(f"Could not remove {path}: {e}")

        logger.debug(f"Deleted {deleted} file(s) in {cache_dir}")

    # ──────────────────────────────────────────────────────────────────
    # INTERNAL
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _info_from_xml(xml_path: Path, node: str) -> CacheInfo | None:
        """
        Parse an nCache XML descriptor and return a CacheInfo.

        Frame range strategy
        ────────────────────
        1. Read startTime / endTime from the <Entry> element (may be ticks or frames
           depending on Maya version — treated as frames here for display purposes).
        2. If the first <channel0> exposes an explicit EndFrame attribute, prefer that
           value since it is guaranteed to be in frames.

        Version
        ───────
        Extracted from the file stem: "cloth_v003" → "003".
        Falls back to the full stem if the "_v" separator is absent.
        """
        try:
            root  = ET.parse(xml_path).getroot()
            entry = root.find("Entry")

            start, end = 0, 0
            if entry is not None:
                start = int(float(entry.get("startTime", 0)))
                end   = int(float(entry.get("endTime",   0)))

                ch = entry.find("Channels/channel0")
                if ch is not None and ch.get("EndFrame"):
                    end   = int(float(ch.get("EndFrame")))
                    start = int(float(ch.get("StartTime", start)))

            stem    = xml_path.stem
            version = stem.rsplit("_v", 1)[-1] if "_v" in stem else stem
            date    = datetime.fromtimestamp(
                xml_path.stat().st_mtime
            ).strftime("%Y-%m-%d %H:%M")

            return CacheInfo(
                node       = node,
                name       = stem,       # matches Maya's cacheFile.cacheName
                version    = version,
                path       = xml_path,
                start      = start,
                end        = end,
                date       = date,
                cache_type = CacheType.NCACHE,
            )

        except Exception as e:
            logger.warning(f"_info_from_xml: could not parse {xml_path.name!r}: {e}")
            return None