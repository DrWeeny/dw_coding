
from dw_maya.dw_decorators import singleUndoChunk
from dw_logger import get_logger
logger = get_logger()

@singleUndoChunk
def transfer_weights(src_weights: list[float],
                     src_mesh: str,
                     tgt_ws: 'WeightSource',
                     radius: float = None) -> None:
    """Transfere les poids d'un maillage source vers une cible avec un rayon optionnel.

    Args:
        src_weights: Liste des poids par sommet du maillage source.
        src_mesh: Nom du maillage source dans la scene.
        tgt_ws: Cible pour recevoir les poids transfere.
        radius: Rayon maximum pour le transfert (None pour desactiver).
    """
    if not src_weights:
        logger.warning("transfer_weights: source has no stored weights.")
        return
    if tgt_ws is None:
        logger.warning("transfer_weights: no active target source.")
        return

    try:
        import maya.api.OpenMaya as om2
        import numpy as np

        def _get_world_positions(mesh_name: str) -> 'np.ndarray':
            sel = om2.MSelectionList()
            sel.add(mesh_name)
            dag = sel.getDagPath(0)
            fn = om2.MFnMesh(dag)
            pts = fn.getPoints(om2.MSpace.kWorld)
            return np.array([(p.x, p.y, p.z) for p in pts], dtype=np.float64)

        src_pos = _get_world_positions(src_mesh)
        tgt_pos = _get_world_positions(tgt_ws.mesh_name)

        src_arr = np.array(src_weights, dtype=np.float64)

        # Nearest-neighbour query with optional radius
        try:
            from scipy.spatial import KDTree
            tree = KDTree(src_pos)
            distances, nn_idx = tree.query(tgt_pos)

            if radius is not None:
                nn_idx = [
                    idx if dist <= radius else -1
                    for dist, idx in zip(distances, nn_idx)
                ]
        except ImportError:
            # Brute-force fallback
            nn_idx = []
            for tp in tgt_pos:
                dists = np.sum((src_pos - tp) ** 2, axis=1)
                min_dist = np.min(dists)
                if radius is None or min_dist <= radius ** 2:
                    nn_idx.append(int(np.argmin(dists)))
                else:
                    nn_idx.append(-1)

        new_weights = [
            src_arr[idx] if idx != -1 else 0.0
            for idx in nn_idx
        ]
        tgt_ws.set_weights(new_weights)
        logger.info(
            f"transfer_weights: {len(new_weights)} weights transferred "
            f"from '{src_mesh}' → '{tgt_ws.node_name}'"
        )
    except Exception as e:
        logger.error(f"transfer_weights failed: {e}")
