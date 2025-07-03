# path: /all_project_analyzer.py
# title: 高機能プロジェクト静的解析ツール
# role: 指定されたディレクトリ内のすべてのPythonファイルを解析し、未定義・未使用のシンボル、循環参照、依存関係の健全性を検出し、詳細な位置情報と共にコンソールとJSONファイルに出力する。

import ast
import os
import builtins
import json
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Any

class ProjectAnalyzer(ast.NodeVisitor):
    """
    Pythonプロジェクトの静的解析を行い、シンボルの定義と使用状況、
    およびモジュール間の依存関係を追跡する。
    """

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(project_root)
        # シンボルの詳細情報を格納: {filepath: {"defines": {(symbol, line)}, "uses": {(symbol, line)}}}
        self.symbols: Dict[str, Dict[str, Set[Tuple[str, int]]]] = defaultdict(lambda: {"defines": set(), "uses": set()})
        # インポート関係を格納: {filepath: {imported_filepath}}
        self.imports: Dict[str, Set[str]] = defaultdict(set)
        self.current_file: str = ""
        self.builtin_names = set(dir(builtins))

    def _resolve_import_path(self, module_name: str, level: int) -> str | None:
        """
        相対インポート・絶対インポートから実際のファイルパスを解決する。
        """
        if level > 0:  # 相対インポート
            base_path_parts = os.path.dirname(self.current_file).split(os.sep)
            # level=1 はカレントディレクトリからのインポートなので、level-1 個親を遡る
            module_path_parts = base_path_parts[:len(base_path_parts) - (level - 1)]
            if module_name:
                module_path_parts.extend(module_name.split('.'))
            module_path = os.path.join(*module_path_parts)
        else:  # 絶対インポート
            module_path = os.path.join(self.project_root, *module_name.split('.'))

        # .pyファイルまたは__init__.pyを持つディレクトリを探す
        potential_py_path = f"{module_path}.py"
        if os.path.exists(potential_py_path):
            return os.path.abspath(potential_py_path)
            
        potential_dir_path = os.path.join(module_path, "__init__.py")
        if os.path.exists(potential_dir_path):
            return os.path.abspath(potential_dir_path)
            
        return None

    def visit_Import(self, node: ast.Import) -> None:
        """import文を訪問し、定義されたシンボルと依存関係を記録する"""
        for alias in node.names:
            self.symbols[self.current_file]["defines"].add((alias.asname or alias.name, node.lineno))
            resolved_path = self._resolve_import_path(alias.name, 0)
            if resolved_path and resolved_path != self.current_file:
                self.imports[self.current_file].add(resolved_path)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """from ... import ... 文を訪問し、定義されたシンボルと依存関係を記録する"""
        module_name = node.module or ""
        resolved_path = self._resolve_import_path(module_name, node.level)
        if resolved_path and resolved_path != self.current_file:
            self.imports[self.current_file].add(resolved_path)
        
        for alias in node.names:
            self.symbols[self.current_file]["defines"].add((alias.asname or alias.name, node.lineno))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """関数定義を訪問し、定義された関数名を記録する"""
        self.symbols[self.current_file]["defines"].add((node.name, node.lineno))
        self.generic_visit(node)
        
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """非同期関数定義を訪問し、定義された関数名を記録する"""
        self.symbols[self.current_file]["defines"].add((node.name, node.lineno))
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """クラス定義を訪問し、定義されたクラス名を記録する"""
        self.symbols[self.current_file]["defines"].add((node.name, node.lineno))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """変数名を訪問し、使用/定義されているシンボルを記録する"""
        if isinstance(node.ctx, ast.Load):
            self.symbols[self.current_file]["uses"].add((node.id, node.lineno))
        elif isinstance(node.ctx, ast.Store):
            self.symbols[self.current_file]["defines"].add((node.id, node.lineno))
        self.generic_visit(node)

    def _find_circular_imports(self) -> List[List[str]]:
        """依存関係グラフから循環参照を検出する"""
        graph = {os.path.relpath(f, self.project_root): [os.path.relpath(i, self.project_root) for i in imp] 
                 for f, imp in self.imports.items()}
        path: List[str] = []
        visited: Set[str] = set()
        cycles: List[List[str]] = []

        def dfs(node: str):
            path.append(node)
            visited.add(node)
            for neighbor in sorted(list(graph.get(node, []))): # ソートして結果を安定させる
                if neighbor in path:
                    try:
                        cycle_start_index = path.index(neighbor)
                        cycles.append(path[cycle_start_index:] + [neighbor])
                    except ValueError:
                        pass
                elif neighbor not in visited:
                    dfs(neighbor)
            path.pop()

        for node in sorted(graph.keys()):
            if node not in visited:
                dfs(node)
        
        unique_cycles = []
        seen_cycles = set()
        for cycle in cycles:
            # サイクルを正規化して重複を排除
            frozen_cycle = frozenset(cycle[:-1])
            if frozen_cycle not in seen_cycles:
                unique_cycles.append(cycle)
                seen_cycles.add(frozen_cycle)
        return unique_cycles

    def _calculate_coupling_metrics(self) -> List[Dict[str, Any]]:
        """
        モジュール間の依存関係の結合度指標（Ca, Ce, I）を計算する。
        - Ca (Afferent Coupling): このモジュールに依存している外部モジュールの数（被依存度）
        - Ce (Efferent Coupling): このモジュールが依存している外部モジュールの数（依存度）
        - I (Instability): 不安定性。 I = Ce / (Ca + Ce)。
        """
        afferent_couplings: Dict[str, int] = defaultdict(int)
        for _, importees in self.imports.items():
            for importee in importees:
                afferent_couplings[importee] += 1

        all_modules = set(self.imports.keys()) | set(afferent_couplings.keys())
        metrics = []

        for module_path in sorted(list(all_modules)):
            ca = afferent_couplings.get(module_path, 0)
            ce = len(self.imports.get(module_path, set()))
            
            instability = 1.0 if (ca + ce) == 0 else ce / (ca + ce)

            metrics.append({
                "module": os.path.relpath(module_path, self.project_root),
                "ca": ca,
                "ce": ce,
                "instability": instability
            })
            
        return metrics

    def analyze(self) -> Dict[str, Any]:
        """
        プロジェクト内の全Pythonファイルを解析し、結果を返す。
        """
        for root, _, files in os.walk(self.project_root):
            if any(d in root for d in ['.venv', '.git', '__pycache__', 'node_modules']):
                continue
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.abspath(os.path.join(root, file))
                    self.current_file = file_path
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            # ast.parseはタプルを返さないため、添え字は不要
                            tree = ast.parse(content, filename=file_path)
                            self.visit(tree)
                    except (SyntaxError, UnicodeDecodeError) as e:
                        print(f"Error parsing {file_path}: {e}")
                        continue

        # 一時的なセットをリストに変換してJSONシリアライズ可能にする
        temp_symbols = defaultdict(lambda: {"defines": [], "uses": []})
        for file, data in self.symbols.items():
            rel_file = os.path.relpath(file, self.project_root)
            temp_symbols[rel_file]["defines"] = sorted(list(data["defines"]), key=lambda x: x[1])
            temp_symbols[rel_file]["uses"] = sorted(list(data["uses"]), key=lambda x: x[1])

        all_project_defines = {s_name for f in self.symbols.values() for s_name, _ in f["defines"]}
        
        undefined_symbols: List[Dict[str, Any]] = []
        for file, data in self.symbols.items():
            file_defines = {s_name for s_name, _ in data["defines"]}
            for symbol, line in data["uses"]:
                if symbol not in file_defines and symbol not in all_project_defines and symbol not in self.builtin_names:
                    undefined_symbols.append({"symbol": symbol, "file": os.path.relpath(file, self.project_root), "line": line})

        all_used_symbols = {s_name for f in self.symbols.values() for s_name, _ in f["uses"]}

        unused_symbols: List[Dict[str, Any]] = []
        for file, data in self.symbols.items():
            for symbol, line in data["defines"]:
                if symbol not in all_used_symbols and not symbol.startswith("_"):
                    unused_symbols.append({"symbol": symbol, "file": os.path.relpath(file, self.project_root), "line": line})
        
        circular_imports = self._find_circular_imports()
        coupling_metrics = self._calculate_coupling_metrics()

        return {
            "undefined_symbols": sorted(undefined_symbols, key=lambda x: (x["file"], x["line"])),
            "unused_symbols": sorted(unused_symbols, key=lambda x: (x["file"], x["line"])),
            "circular_imports": circular_imports,
            "coupling_metrics": sorted(coupling_metrics, key=lambda x: x["instability"], reverse=True),
            "project_symbols": dict(temp_symbols) # 追加: 全シンボル情報
        }

def print_analysis_results(results: Dict[str, Any]):
    """分析結果を整形して表示する"""
    print("\n--- Project Analysis Results ---")

    if results["undefined_symbols"]:
        print(f"\n[!] Found {len(results['undefined_symbols'])} Undefined Symbols:")
        for item in results["undefined_symbols"]:
            print(f"  - Symbol '{item['symbol']}' used at {item['file']}:{item['line']} may not be defined project-wide.")
    else:
        print("\n[✔] No undefined symbols found.")

    if results["unused_symbols"]:
        print(f"\n[!] Found {len(results['unused_symbols'])} Unused Symbols:")
        for item in results["unused_symbols"]:
            print(f"  - Symbol '{item['symbol']}' defined at {item['file']}:{item['line']} is never used.")
    else:
        print("\n[✔] No unused symbols found.")
        
    if results["circular_imports"]:
        print(f"\n[!] Found {len(results['circular_imports'])} Circular Imports:")
        for i, cycle in enumerate(results["circular_imports"]):
            print(f"  - Cycle {i+1}: {' -> '.join(cycle)}")
    else:
        print("\n[✔] No circular imports found.")

    if results["coupling_metrics"]:
        print(f"\n[i] Module Coupling Metrics (Sorted by Instability):")
        print(f"  {'Module':<60} {'Ca':<5} {'Ce':<5} {'Instability':<12}")
        print(f"  {'-'*60:<60} {'-'*5:<5} {'-'*5:<5} {'-'*12:<12}")
        for metric in results["coupling_metrics"]:
            instability_str = f"{metric['instability']:.2f}"
            print(f"  {metric['module']:<60} {metric['ca']:<5} {metric['ce']:<5} {instability_str:<12}")
    else:
        print("\n[✔] No module coupling metrics to display.")
    
    print("\n--- Analysis Complete ---")

def save_results_to_json(results: Dict[str, Any], output_file: str):
    """
    分析結果をJSONファイルに保存する。
    """
    print(f"\nAttempting to save analysis results to {output_file}...")
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=4)
        print(f"[✔] Analysis results successfully saved to {output_file}")
    except IOError as e:
        print(f"[!] Error: Could not write to file {output_file}. Reason: {e}")
    except TypeError as e:
        print(f"[!] Error: Could not serialize the analysis results to JSON. Reason: {e}")


if __name__ == "__main__":
    project_directory = '.'
    output_filename = 'project_structure.json'

    if not os.path.isdir(project_directory):
        print(f"Error: Project directory '{project_directory}' not found.")
    else:
        analyzer = ProjectAnalyzer(project_root=project_directory)
        analysis_results = analyzer.analyze()
        
        # 1. コンソールに結果を表示
        print_analysis_results(analysis_results)
        
        # 2. JSONファイルに結果を保存
        save_results_to_json(analysis_results, output_filename)
