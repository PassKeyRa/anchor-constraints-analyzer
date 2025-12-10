from definition_analyzer import DefinitionGraph, DefinitionStatus
import json

def get_mermaid(graph: DefinitionGraph):
    result = ""
    #result += f"---\ntitle: {graph.source_file + ":" + graph.struct_name}\n---"
    #result += "\n%%{ init: { 'flowchart': { 'curve': 'catmullRom', 'defaultRenderer': 'elk' } } }%%"
    result += "\n%%{ init: { 'flowchart': { 'defaultRenderer': 'elk' } } }%%"
    result += "\ngraph BT"

    styles = []

    nodes_map = {}
    for i in range(len(graph.accounts.keys())):
        account_name = list(graph.accounts.keys())[i]
        result += f"\n\ta{i+1}[\"{account_name}\"]"
        nodes_map[account_name] = f"a{i+1}"
    
    for i in range(len(graph.instruction_args)):
        instr_name = graph.instruction_args[i]
        result += f"\n\ti{i+1}([\"{instr_name}\"])"
        nodes_map[instr_name]= f"i{i+1}"
        styles.append(f"style {nodes_map[instr_name]} stroke:#f80")
    
    for i in range(len(graph.constants)):
        const_name = graph.constants[i]
        result += f"\n\tc{i+1}(\"{const_name}\")"
        nodes_map[const_name]= f"c{i+1}"
        styles.append(f"style {nodes_map[const_name]} stroke:#0f0")
    
    result += "\n"

    connection_counter = 0

    unique_connections = set()

    for account_name, account_def in graph.accounts.items():
        b = nodes_map[account_name]
        for def_ in account_def.defined_by:
            if def_.connection_type == "seed_bump":
                # skip seed bumps for now
                continue
            if def_.connection_type == "default":
                styles.append(f"style {b} stroke:#0f0")
                continue

            a = nodes_map[def_.source_name]
            label = def_.connection_type
            if graph.accounts[account_name].is_inited and 'seed' in label:
                label = "init_" + label
            if def_.source_type == "constant":
                label = "constant_" + label
            if def_.source_field_name and def_.connection_type not in ["custom"]:
                label = "fields_" + label

            connection = f"\n\t{a} -->|{label}| {b}"
            if connection not in unique_connections:
                result += connection
                unique_connections.add(connection)

            if def_.connection_type == "custom":
                styles.append(f"linkStyle {connection_counter} stroke:#f80")
            connection_counter += 1

        if account_def.status == DefinitionStatus.UNDEFINED:
            styles.append(f"style {b} stroke:#f00")
        elif account_def.status in [DefinitionStatus.NEEDS_REVIEW, DefinitionStatus.PARTIALLY_DEFINED, DefinitionStatus.INCORRECTLY_DEFINED]:
            styles.append(f"style {b} stroke:#f80")
    
    result += "\n"
    for style in styles:
        result += f"\n\t{style}"
    
    return result

def dump_mermaid(graph: DefinitionGraph, output_path: str):
    mm = get_mermaid(graph)
    with open(output_path, 'w') as f:
        f.write(f"```mermaid\n{mm}\n```")