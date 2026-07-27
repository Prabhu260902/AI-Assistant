"""Prompt template for the Architecture Assistant."""

from services.architecture_graph import FlowGraph

_SYSTEM_INSTRUCTIONS = (
    "You are a senior software engineer explaining a system flow to a teammate. "
    "Below is the exact call structure already traced from the codebase — describe "
    "it in clear prose for a developer unfamiliar with this part of the system. "
    "Only describe what is shown; do not invent steps, files, or behavior not listed."
)


def _describe_graph(flow_graph: FlowGraph) -> str:
    node_by_key = {node.key: node for node in flow_graph.nodes}
    lines = []

    for node in flow_graph.nodes:
        if node.kind == "endpoint":
            lines.append(f"- {node.name} ({node.file_path}) is the handler for {node.detail}")
        elif node.kind == "external":
            lines.append(f"- {node.name} is called but not defined in this repo (external/unresolved)")
        else:
            lines.append(f"- {node.name} is defined in {node.file_path}")

    for edge in flow_graph.edges:
        from_node = node_by_key.get(edge.from_key)
        to_node = node_by_key.get(edge.to_key)
        if from_node and to_node:
            lines.append(f"- {from_node.name} calls {to_node.name}")

    return "\n".join(lines)


def build_architecture_prompt(query: str, flow_graph: FlowGraph) -> str:
    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        f"Question: {query}\n\n"
        f"Traced flow:\n{_describe_graph(flow_graph)}\n\n"
        "Explanation:"
    )
