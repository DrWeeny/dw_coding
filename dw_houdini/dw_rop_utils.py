import hou
import time

def print_render_progress(task_name=None, verbose:int=0):
    """

    Args:
        task_name:
        verbose:

    Returns:

    """
    if not hasattr(hou, "_my_global_data"):
        hou._my_global_data = {}

    node = hou.pwd()
    node_name = node.path()

    # Use the passed task_name or fallback to node path
    key = task_name if task_name is not None else node_name

    if key not in hou._my_global_data:
        hou._my_global_data[key] = {
            "sum_time": 0.0,
            "frame_count": 0,
            "last_time": time.time(),
        }

    data = hou._my_global_data[key]

    now = time.time()
    frame_duration = now - data["last_time"]
    data["last_time"] = now

    if data["frame_count"] > 0:
        data["sum_time"] += frame_duration

    data["frame_count"] += 1

    avg_time = data["sum_time"] / max(data["frame_count"] - 1, 1)

    cur_frame = int(hou.frame())
    start_frame = int(node.evalParm("f1"))
    end_frame = int(node.evalParm("f2"))

    if verbose:
        if verbose == 1:
            print(f"[{key}] Frame {cur_frame} / {end_frame}")
        if verbose == 2:
            print(f"[{key}] Avg frame time: {avg_time:.2f} seconds")
        if verbose == 3:
            if cur_frame > start_frame:
                frames_left = end_frame - cur_frame
                est_time_left = avg_time * frames_left
                print(f"[{key}] Estimated time left: {est_time_left:.2f} seconds")

# Example usage in your pre-frame script:
# print_render_progress(task_name="MyROP_GeoCache", verbose=True)

def check_sim_stretch_ratio(threshold = 1.5):
    node = hou.pwd()
    geo = node.geometry()

    # Threshold for maximum allowed stretch
    STRETCH_THRESHOLD = threshold

    # Get current value of the detail attribute "edge_length"
    current_length = geo.attribValue("edge_length")

    # Retrieve stored initial length from node’s spare parameter or stored attribute
    # For example, stored in a spare float parameter called "initial_edge_length"
    initial_length = node.evalParm("initial_edge_length")

    if initial_length is None or initial_length == 0:
        # Store initial value on first run
        node.setParmExpressions({"initial_edge_length": str(current_length)})
        initial_length = current_length

    # Compute stretch ratio
    stretch_ratio = current_length / initial_length if initial_length else 0

    if stretch_ratio > STRETCH_THRESHOLD:
        print(f"Simulation error: Stretch ratio {stretch_ratio:.2f} exceeds threshold {STRETCH_THRESHOLD}")
        # Abort the simulation: you can raise an error or stop the ROP node
        raise RuntimeError("Simulation exceeded stretch threshold, aborting.")

    return stretch_ratio
