"""Render a services.architecture_graph.FlowGraph as Mermaid flowchart
syntax. Purely mechanical — the graph structure was already decided by
architecture_graph.py; this only turns it into text."""

from services.architecture_graph import FlowGraph, FlowNode


def _sanitize_label(text: str) -> str:
    return text.replace('"', "'").replace("\n", " ").strip()


def _label_for(node: FlowNode) -> str:
    if node.kind == "endpoint":
        return _sanitize_label(f"{node.detail or ''} {node.name}".strip())
    if node.kind == "external":
        return _sanitize_label(f"{node.name} (external)")
    file_stem = node.file_path.rsplit("/", 1)[-1] if node.file_path else ""
    label = f"{node.name} ({file_stem})" if file_stem else node.name
    return _sanitize_label(label)


def render_flow_graph(graph: FlowGraph) -> str:
    if not graph.nodes:
        return 'flowchart TD\n    empty["No flow could be determined"]'

    node_ids = {node.key: f"n{i}" for i, node in enumerate(graph.nodes)}

    lines = ["flowchart TD"]
    for node in graph.nodes:
        node_id = node_ids[node.key]
        label = _label_for(node)
        if node.kind == "external":
            lines.append(f'    {node_id}("{label}")')
        elif node.kind == "endpoint":
            lines.append(f'    {node_id}[["{label}"]]')
        else:
            lines.append(f'    {node_id}["{label}"]')

    for edge in graph.edges:
        from_id = node_ids.get(edge.from_key)
        to_id = node_ids.get(edge.to_key)
        if from_id and to_id:
            lines.append(f"    {from_id} --> {to_id}")

    return "\n".join(lines)
