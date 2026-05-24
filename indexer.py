# Automatic Multi-Pass Codebase Ontology & Graph Indexer
# Fully dynamic — works on ANY Python repository with zero hardcoding.
import os
import ast
import re
import sqlite3
import json

DB_PATH = "telemetry.db"
TARGET_DIR = "services"

# Common patterns used to detect database and HTTP operations dynamically
DB_METHOD_NAMES = frozenset({
    "execute", "executemany", "executescript",
    "query", "fetchone", "fetchall", "fetchmany",
    "commit", "rollback", "cursor", "transaction",
    "add", "merge", "flush",                    # SQLAlchemy session
    "filter", "filter_by", "get", "all",        # SQLAlchemy query
    "insert", "update", "delete", "select",     # Core SQL builders
    "create_all", "drop_all",                   # Schema ops
    "bulk_save_objects", "bulk_insert_mappings",
})

DB_ATTR_HINTS = frozenset({
    "db", "database", "conn", "connection", "cursor",
    "session", "engine", "pool", "tx", "transaction",
})

HTTP_METHOD_NAMES = frozenset({
    "get", "post", "put", "patch", "delete", "head", "options",
    "request", "urlopen", "fetch", "send",
})

HTTP_ATTR_HINTS = frozenset({
    "requests", "http", "httpx", "client", "session",
    "urllib", "aiohttp", "api", "gateway",
})

# Regex to extract SQL table names from string literals
SQL_TABLE_RE = re.compile(
    r"""(?:FROM|INTO|UPDATE|JOIN|TABLE)\s+[`"']?(\w+)[`"']?""",
    re.IGNORECASE,
)


class DependencyResolver(ast.NodeVisitor):
    """
    First-pass visitor: scans __init__ methods to build a map of
    `self.X = constructor_arg` so we can later resolve what class
    a `self.X.method()` call is targeting.
    """

    def __init__(self):
        # { class_name: { attr_name: param_name } }
        self.class_deps: dict[str, dict[str, str]] = {}
        self._current_class: str | None = None

    def visit_ClassDef(self, node: ast.ClassDef):
        self._current_class = node.name
        self.class_deps.setdefault(node.name, {})
        self.generic_visit(node)
        self._current_class = None

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if self._current_class and node.name == "__init__":
            self._extract_self_assignments(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _extract_self_assignments(self, init_node: ast.FunctionDef):
        """
        Walk __init__ body looking for `self.X = Y` assignments where Y
        is a constructor parameter, a function call result, or another
        attribute — all of which hint at injected dependencies.
        """
        # Collect parameter names (skip 'self')
        params = {
            arg.arg for arg in init_node.args.args
            if arg.arg != "self"
        }

        for stmt in ast.walk(init_node):
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    continue
                attr_name = target.attr
                # Case 1: self.x = param  (injected dependency)
                if isinstance(stmt.value, ast.Name) and stmt.value.id in params:
                    self.class_deps[self._current_class][attr_name] = stmt.value.id
                # Case 2: self.x = SomeClass(...)  (inline construction)
                elif isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        self.class_deps[self._current_class][attr_name] = stmt.value.func.id
                    elif isinstance(stmt.value.func, ast.Attribute):
                        self.class_deps[self._current_class][attr_name] = stmt.value.func.attr


class CodebaseASTScanner(ast.NodeVisitor):
    """
    Second-pass AST Visitor that traces the full codebase topology:
    classes, functions, inter-service calls, DB operations, HTTP calls,
    and import dependencies — all detected dynamically.
    """

    def __init__(self, filename: str, source: str, dep_map: dict[str, str]):
        self.filename = filename
        self.source = source
        self.dep_map = dep_map          # { attr_name: param_or_class_name }
        self.current_class: str | None = None
        self.current_function: str | None = None
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        # Track which method names belong to which class across the repo
        # (populated externally after all files are scanned)
        self.global_method_index: dict[str, list[str]] = {}

    def visit_Import(self, node: ast.Import):
        """Track top-level imports as Module nodes."""
        func_id = self._current_scope_id()
        for alias in node.names:
            mod_id = f"Module:{alias.name}"
            self.nodes.append({
                "id": mod_id,
                "label": alias.name,
                "type": "Module",
                "source_file": self.filename,
                "code_block": "",
            })
            if func_id:
                self.edges.append({
                    "source": func_id,
                    "target": mod_id,
                    "relationship": "IMPORTS",
                })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Track from X import Y as Module nodes."""
        func_id = self._current_scope_id()
        mod_name = node.module or ""
        for alias in (node.names or []):
            full_name = f"{mod_name}.{alias.name}" if mod_name else alias.name
            mod_id = f"Module:{full_name}"
            self.nodes.append({
                "id": mod_id,
                "label": full_name,
                "type": "Module",
                "source_file": self.filename,
                "code_block": "",
            })
            if func_id:
                self.edges.append({
                    "source": func_id,
                    "target": mod_id,
                    "relationship": "IMPORTS",
                })
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        class_id = f"{self.filename}:{node.name}"
        self.current_class = node.name
        code = ast.get_source_segment(self.source, node) or ""
        self.nodes.append({
            "id": class_id,
            "label": node.name,
            "type": "Microservice",
            "source_file": self.filename,
            "code_block": code,
        })
        # Track base classes as inheritance edges
        for base in node.bases:
            base_name = self._resolve_name(base)
            if base_name and base_name not in ("object",):
                self.edges.append({
                    "source": class_id,
                    "target": f"Class:{base_name}",
                    "relationship": "INHERITS",
                })
        self.generic_visit(node)
        self.current_class = None

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if not self.current_class:
            # Top-level function — register as a standalone Operation
            func_id = f"{self.filename}:{node.name}"
            code = ast.get_source_segment(self.source, node) or ""
            self.nodes.append({
                "id": func_id,
                "label": node.name,
                "type": "Operation",
                "source_file": self.filename,
                "code_block": code,
            })
            prev = self.current_function
            self.current_function = node.name
            self.generic_visit(node)
            self.current_function = prev
            return

        func_id = f"{self.filename}:{self.current_class}.{node.name}"
        self.current_function = f"{self.current_class}.{node.name}"
        code = ast.get_source_segment(self.source, node) or ""

        self.nodes.append({
            "id": func_id,
            "label": f"{self.current_class}.{node.name}",
            "type": "Operation",
            "source_file": self.filename,
            "code_block": code,
        })
        # Edge: class -> method
        class_id = f"{self.filename}:{self.current_class}"
        self.edges.append({
            "source": class_id,
            "target": func_id,
            "relationship": "DECLARES",
        })

        self.generic_visit(node)
        self.current_function = None

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call):
        """
        Dynamically detect:
          1. Inter-service calls  (self.dep.method())
          2. Database operations   (*.execute(), *.query(), etc.)
          3. External HTTP calls   (requests.get(), urllib.urlopen(), etc.)
          4. SQL table references   (from string args to .execute())
        """
        caller_id = self._current_scope_id()
        if not caller_id:
            self.generic_visit(node)
            return

        # ── Pattern: obj.method() ──
        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            obj_name = self._resolve_name(node.func.value)

            # --- Database operations ---
            if method_name in DB_METHOD_NAMES or (obj_name and obj_name in DB_ATTR_HINTS):
                db_node_id = self._infer_db_table(node, fallback_label="Database")
                self.nodes.append({
                    "id": db_node_id,
                    "label": db_node_id.split(":")[-1],
                    "type": "DatabaseTable",
                    "source_file": self.filename,
                    "code_block": "",
                })
                self.edges.append({
                    "source": caller_id,
                    "target": db_node_id,
                    "relationship": "QUERIES",
                })

            # --- External HTTP calls ---
            elif method_name in HTTP_METHOD_NAMES and obj_name and obj_name in HTTP_ATTR_HINTS:
                url_hint = self._extract_url_hint(node)
                gw_label = url_hint or obj_name
                gw_id = f"ExternalAPI:{gw_label}"
                self.nodes.append({
                    "id": gw_id,
                    "label": gw_label,
                    "type": "ExternalGateway",
                    "source_file": self.filename,
                    "code_block": "",
                })
                self.edges.append({
                    "source": caller_id,
                    "target": gw_id,
                    "relationship": "CALLS_OUT",
                })

            # --- Inter-service / dependency calls via self.dep.method() ---
            elif (
                obj_name
                and isinstance(node.func.value, ast.Attribute)
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "self"
            ):
                dep_attr = node.func.value.attr
                dep_hint = self.dep_map.get(dep_attr, dep_attr)
                self.edges.append({
                    "source": caller_id,
                    "target": f"Dependency:{dep_hint}.{method_name}",
                    "relationship": "TRIGGERS",
                })

        # ── Pattern: function_call() (e.g. standalone or imported) ──
        elif isinstance(node.func, ast.Name):
            # Nothing hardcoded — we just let it pass.  The global
            # method index resolution happens in the post-processing step.
            pass

        self.generic_visit(node)

    # ── Helpers ──

    def _current_scope_id(self) -> str | None:
        if self.current_class and self.current_function:
            return f"{self.filename}:{self.current_function}"
        if self.current_class:
            return f"{self.filename}:{self.current_class}"
        if self.current_function:
            return f"{self.filename}:{self.current_function}"
        return None

    @staticmethod
    def _resolve_name(node) -> str | None:
        """Recursively extract a dotted name from an AST node."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = CodebaseASTScanner._resolve_name(node.value)
            if parent:
                return f"{parent}.{node.attr}"
            return node.attr
        return None

    def _infer_db_table(self, call_node: ast.Call, fallback_label: str = "Database") -> str:
        """
        Try to extract a SQL table name from the first string argument
        of a DB call like `.execute("SELECT * FROM users")`.
        """
        for arg in call_node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                match = SQL_TABLE_RE.search(arg.value)
                if match:
                    return f"Database:{match.group(1)}"
            # Also handle f-strings — peek at the constant parts
            if isinstance(arg, ast.JoinedStr):
                for val in arg.values:
                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                        match = SQL_TABLE_RE.search(val.value)
                        if match:
                            return f"Database:{match.group(1)}"
        return f"Database:{fallback_label}"

    @staticmethod
    def _extract_url_hint(call_node: ast.Call) -> str | None:
        """Try to pull a domain from the first string arg of an HTTP call."""
        for arg in call_node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                val = arg.value
                if "://" in val:
                    # Extract domain from URL
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(val)
                        return parsed.netloc or val[:60]
                    except Exception:
                        return val[:60]
        return None


# ─── Global Post-Processing ───


def _build_global_method_index(
    all_nodes: list[dict],
) -> dict[str, list[str]]:
    """
    Build a reverse index: { method_name: [class_node_id, ...] }
    so we can resolve `Dependency:X.method` targets to actual class nodes.
    """
    index: dict[str, list[str]] = {}
    for node in all_nodes:
        if node["type"] == "Operation" and "." in node["label"]:
            _, method_name = node["label"].rsplit(".", 1)
            index.setdefault(method_name, []).append(node["id"])
    return index


def _resolve_dependency_edges(
    edges: list[dict],
    all_nodes: list[dict],
    method_index: dict[str, list[str]],
) -> list[dict]:
    """
    Replace placeholder `Dependency:hint.method` targets with actual
    class node IDs by fuzzy-matching on class/param name + method name.
    """
    # Build a quick lookup: node_id -> node
    node_map = {n["id"]: n for n in all_nodes}
    # Also build class_label -> class_node_id
    class_label_map: dict[str, str] = {}
    for n in all_nodes:
        if n["type"] == "Microservice":
            class_label_map[n["label"].lower()] = n["id"]
            # Also index without "Service" suffix for fuzzy matching
            stripped = n["label"].lower().replace("service", "").replace("client", "").strip("_")
            if stripped:
                class_label_map[stripped] = n["id"]

    resolved: list[dict] = []
    for edge in edges:
        target = edge["target"]
        if not target.startswith("Dependency:"):
            resolved.append(edge)
            continue

        # Parse "Dependency:dep_hint.method_name"
        dep_spec = target[len("Dependency:"):]
        if "." not in dep_spec:
            resolved.append(edge)
            continue

        dep_hint, method_name = dep_spec.rsplit(".", 1)
        dep_hint_lower = dep_hint.lower().replace("_client", "").replace("_service", "").strip("_")

        # Find candidate targets from the method index
        candidates = method_index.get(method_name, [])
        best_target = None

        for candidate_id in candidates:
            candidate_node = node_map.get(candidate_id)
            if not candidate_node:
                continue
            # Check if the source file or class label matches the dep_hint
            candidate_label = candidate_node["label"].lower()
            candidate_file = candidate_node["source_file"].lower()

            if (
                dep_hint_lower in candidate_label
                or dep_hint_lower in candidate_file
                or candidate_label.startswith(dep_hint_lower)
            ):
                best_target = candidate_id
                break

        if not best_target and candidates:
            # Fallback: if only one candidate has this method, use it
            if len(candidates) == 1:
                best_target = candidates[0]

        if best_target:
            edge["target"] = best_target
        else:
            # Keep the dependency edge as-is for visibility in the graph
            dep_node_id = f"External:{dep_hint}"
            all_nodes.append({
                "id": dep_node_id,
                "label": dep_hint,
                "type": "ExternalDependency",
                "source_file": "",
                "code_block": "",
            })
            edge["target"] = dep_node_id

        resolved.append(edge)
    return resolved


# ─── Main Indexing Pipeline ───


def run_local_ast_indexing(target_dir: str = "services"):
    """
    Local-first indexing compiling Abstract Syntax Trees to
    map structural files and code associations. Walks directory recursively.
    Works on ANY Python codebase — no hardcoded names or patterns.
    """
    print(f"Running dynamic AST-based codebase indexer on: {target_dir}")
    all_nodes: list[dict] = []
    all_edges: list[dict] = []

    if not os.path.exists(target_dir):
        print(f"Target directory {target_dir} not found. Skipping.")
        return [], []

    # ── Pass 1: Collect dependency maps from __init__ across all files ──
    file_sources: dict[str, str] = {}      # filepath -> source code
    file_dep_maps: dict[str, dict] = {}    # filepath -> { attr: hint }
    class_to_file: dict[str, str] = {}     # class_name -> filepath

    for root, _, files in os.walk(target_dir):
        for filename in files:
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(root, filename)
            try:
                source = open(filepath, encoding="utf-8", errors="replace").read()
                tree = ast.parse(source, filename=filepath)
                file_sources[filepath] = source

                resolver = DependencyResolver()
                resolver.visit(tree)

                # Merge all class dep maps for this file
                merged_deps: dict[str, str] = {}
                for cls_name, deps in resolver.class_deps.items():
                    class_to_file[cls_name] = filepath
                    merged_deps.update(deps)
                file_dep_maps[filepath] = merged_deps

            except SyntaxError as e:
                print(f"Syntax error in {filepath}, skipping: {e}")
            except Exception as e:
                print(f"Error in pass-1 for {filepath}: {e}")

    # ── Pass 2: Full AST scan using resolved dependency maps ──
    for filepath, source in file_sources.items():
        try:
            tree = ast.parse(source, filename=filepath)
            scanner = CodebaseASTScanner(
                filename=filepath,
                source=source,
                dep_map=file_dep_maps.get(filepath, {}),
            )
            scanner.visit(tree)
            all_nodes.extend(scanner.nodes)
            all_edges.extend(scanner.edges)
        except Exception as e:
            print(f"Error parsing file {filepath} with AST: {e}")

    # ── Pass 3: Post-process — resolve dependency edges ──
    method_index = _build_global_method_index(all_nodes)
    all_edges = _resolve_dependency_edges(all_edges, all_nodes, method_index)

    # Deduplicate nodes by ID
    unique_nodes = list({node["id"]: node for node in all_nodes}.values())
    # Deduplicate edges
    unique_edges = []
    seen_edges: set[tuple] = set()
    for edge in all_edges:
        edge_key = (edge["source"], edge["target"], edge["relationship"])
        if edge_key not in seen_edges:
            seen_edges.add(edge_key)
            unique_edges.append(edge)

    print(f"Indexing complete: {len(unique_nodes)} nodes, {len(unique_edges)} edges discovered.")
    return unique_nodes, unique_edges


def save_graph_to_sqlite(nodes, edges):
    """Saves the extracted codebase graph directly to telemetry.db tables."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Dynamically create codebase tables if they don't exist
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS codebase_nodes (
            id TEXT PRIMARY KEY,
            label TEXT,
            type TEXT,
            source_file TEXT,
            code_block TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS codebase_edges (
            source TEXT,
            target TEXT,
            relationship TEXT,
            PRIMARY KEY (source, target, relationship)
        )
        """
    )

    # Clear previous indexes to prevent stale code mappings
    cursor.execute("DELETE FROM codebase_nodes")
    cursor.execute("DELETE FROM codebase_edges")

    for node in nodes:
        cursor.execute(
            """
            INSERT OR REPLACE INTO codebase_nodes (id, label, type, source_file, code_block)
            VALUES (?, ?, ?, ?, ?)
            """,
            (node["id"], node["label"], node["type"], node["source_file"], node["code_block"])
        )

    for edge in edges:
        cursor.execute(
            """
            INSERT OR IGNORE INTO codebase_edges (source, target, relationship)
            VALUES (?, ?, ?)
            """,
            (edge["source"], edge["target"], edge["relationship"])
        )

    conn.commit()
    conn.close()
    print(f"Codebase indexed successfully! Saved {len(nodes)} nodes and {len(edges)} edges to SQLite.")


def index_codebase(target_dir="services"):
    """Main function to trigger code indexing."""
    nodes, edges = run_local_ast_indexing(target_dir)

    # Save results to local SQLite DB
    if nodes or edges:
        save_graph_to_sqlite(nodes, edges)
    else:
        print(f"No Python files found to index in {target_dir}.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CHRONOS Codebase Indexer")
    parser.add_argument("--dir", default="services", help="Path to the repository/codebase directory to index")
    args = parser.parse_args()

    index_codebase(args.dir)
