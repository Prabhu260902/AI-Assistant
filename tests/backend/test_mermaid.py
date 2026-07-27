from services.architecture_graph import FlowEdge, FlowGraph, FlowNode
from services.mermaid import render_flow_graph


def test_render_flow_graph_empty_graph():
    diagram = render_flow_graph(FlowGraph())

    assert diagram.startswith("flowchart TD")
    assert "No flow could be determined" in diagram


def test_render_flow_graph_renders_nodes_and_edges():
    graph = FlowGraph(
        nodes=[
            FlowNode(key="symbol:1", name="create_hcp", file_path="backend/routers/hcps.py", kind="endpoint", detail="POST /hcps"),
            FlowNode(key="symbol:2", name="validate_hcp", file_path="backend/routers/hcps.py", kind="function"),
            FlowNode(key="external:1", name="db.commit", file_path="backend/routers/hcps.py", kind="external"),
        ],
        edges=[
            FlowEdge(from_key="symbol:1", to_key="symbol:2"),
            FlowEdge(from_key="symbol:1", to_key="external:1"),
        ],
    )

    diagram = render_flow_graph(graph)

    assert diagram.startswith("flowchart TD")
    assert 'n0[["POST /hcps create_hcp"]]' in diagram
    assert 'n1["validate_hcp (hcps.py)"]' in diagram
    assert 'n2("db.commit (external)")' in diagram
    assert "n0 --> n1" in diagram
    assert "n0 --> n2" in diagram


def test_render_flow_graph_sanitizes_quotes_in_labels():
    graph = FlowGraph(nodes=[FlowNode(key="symbol:1", name='weird"name', file_path="a.py", kind="function")])

    diagram = render_flow_graph(graph)

    assert 'n0["weird\'name (a.py)"]' in diagram
