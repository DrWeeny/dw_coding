
class DynEvalKeys:
    """
    Shared DataHub keys for DynEval.
    All widgets communicate exclusively through these.
    """

    # Scene state — set once at startup, updated on Maya range change
    FRAME_RANGE     = "dyn.frame_range"      # tuple[int, int]

    # Selection — tree publishes, all panels subscribe
    SELECTED_NODE   = "dyn.selected_node"    # SimItem | None

    # Cache tab
    CACHE_SELECTED  = "dyn.cache.selected"   # CacheInfo | None

    # Maps tab
    MAP_SELECTED    = "dyn.map.selected"     # MapInfo | None
    PAINT_REQUESTED = "dyn.paint.request"    # MapInfo  (one-shot, triggers Slimfast)

    COMMENT_SAVED = "dyn.comment.saved"  # str — optionnel, pour feedback

    COMMENT_CURRENT = "dyn.comment.current"