"""Catalog-defined item relationships, never guessed item synergy."""

from dataclasses import replace


def component_graph(items):
    """Resolve public catalog component class names to current shop IDs."""
    by_class = {item.get("class_name"): item_id for item_id, item in items.items()
                if item.get("class_name")}
    return {item_id: tuple(sorted({by_class[name] for name in item.get("component_items", []) or []
                                  if name in by_class and by_class[name] != item_id}))
            for item_id, item in items.items()}


def ancestors(item_id, graph):
    found, pending = set(), list(graph.get(item_id, ()))
    while pending:
        node = pending.pop()
        if node == item_id or node in found:
            continue
        found.add(node)
        pending.extend(graph.get(node, ()))
    return found


def apply_inventory(candidates, owned_ids, graph):
    """Remove owned upgrades' ingredients and identify slot-reusing purchases."""
    owned = set(owned_ids)
    excluded = owned | {parent for item in owned for parent in ancestors(item, graph)}
    result = []
    for candidate in candidates:
        if candidate.item_id in excluded:
            continue
        components = tuple(graph.get(candidate.item_id, ()))
        replaces = tuple(i for i in components if i in owned)
        evidence = {**candidate.evidence, "owned_components": list(replaces),
                    "catalog_components": list(components),
                    "price_basis": "catalog cost, no estimated discount"}
        result.append(replace(candidate, replaces_ids=replaces, evidence=evidence))
    return result
