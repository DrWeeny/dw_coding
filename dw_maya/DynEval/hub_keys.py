
class DynEvalKeys:
    """
    Shared DataHub keys for DynEval.
    All widgets communicate exclusively through these.
    """

    # Scene state — set once at startup, updated on Maya range change
    FRAME_RANGE     = "dyn.frame_range"      # tuple[int, int]

    # Selection — tree publishes, all panels subscribe
    SELECTED_NODE   = "dyn.selected_node"    # SimItem | None

    # Full tree selection, published alongside SELECTED_NODE. Additive on
    # purpose: SELECTED_NODE keeps meaning "the one item the detail panels
    # show", so nothing that reads it had to change. Only the multi-item
    # actions (cache creation, comment fan-out) read this one.
    SELECTED_NODES  = "dyn.selected_nodes"   # list[SimItem]

    # Cache tab
    CACHE_SELECTED  = "dyn.cache.selected"   # CacheInfo | None

    # Maps tab
    MAP_SELECTED    = "dyn.map.selected"     # MapInfo | None
    PAINT_REQUESTED = "dyn.paint.request"    # MapInfo  (one-shot, triggers Slimfast)

    COMMENT_SAVED = "dyn.comment.saved"  # str — feedback after a comment write

    COMMENT_CURRENT = "dyn.comment.current"

    # Comment tab — cache panel requests focus on the comment editor
    COMMENT_EDIT_REQUESTED = "dyn.comment.edit_request"  # CacheInfo

    # ------------------------------------------------------------------
    # Backward-compat aliases for old widgets not yet migrated.
    SELECTED_ITEM  = SELECTED_NODE    # was HubKeys.SELECTED_ITEM
    SELECTED_ITEMS = SELECTED_NODE    # was HubKeys.SELECTED_ITEMS
    CACHE_ATTACHED = CACHE_SELECTED   # was HubKeys.CACHE_ATTACHED
    CACHE_CREATE_REQUESTED = "dyn.cache.create"