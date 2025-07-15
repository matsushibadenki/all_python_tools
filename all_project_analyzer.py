# /all_project_analyzer.py
# title: プロジェクト全体静的解析ツール
# role: プロジェクト内のすべてのPythonファイルを解析し、未定義シンボル、未使用シンボル、循環参照、カップリング метリクスを検出する。

import ast
import os
import builtins
import json
from collections import defaultdict
from typing import List, Dict, Any, Set, Tuple

class ProjectAnalyzer:
    """
    Pythonプロジェクトの静的解析を行うクラス。
    """
    def __init__(self, project_root: str):
        """
        コンストラクタ。
        Args:
            project_root (str): 解析対象のプロジェクトルートディレクトリ。
        """
        self.project_root = os.path.abspath(project_root)
        self.defined_symbols: Dict[str, Set[str]] = defaultdict(set)
        self.used_symbols: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        self.imports: Dict[str, Set[str]] = defaultdict(set)
        self.builtin_symbols = set(dir(builtins))

    def _resolve_import_path(self, module_name: str, level: int, base_path: str) -> str:
        """インポートパスを解決するヘルパー関数。"""
        if level > 0:
            base_path_parts = base_path.split(os.sep)
            module_path_parts = base_path_parts[:-level] + module_name.split('.')
            module_path = os.path.join(*module_path_parts)
        else:
            module_path = module_name.replace('.', os.sep)

        potential_py_path = os.path.join(self.project_root, f"{module_path}.py")
        if os.path.exists(potential_py_path):
            return potential_py_path

        potential_dir_path = os.path.join(self.project_root, module_path)
        if os.path.isdir(potential_dir_path):
            return os.path.join(potential_dir_path, "__init__.py")

        return module_path # 見つからない場合はモジュール名をそのまま返す

    def visit_Import(self, node: ast.Import, current_file: str):
        for alias in node.names:
            resolved_path = self._resolve_import_path(alias.name, 0, os.path.dirname(current_file))
            self.imports[current_file].add(resolved_path)
            self.defined_symbols[current_file].add(alias.asname or alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom, current_file: str):
        if node.module:
            resolved_path = self._resolve_import_path(node.module, node.level, os.path.dirname(current_file))
            if resolved_path:
                 self.imports[current_file].add(resolved_path)
        for alias in node.names:
            self.defined_symbols[current_file].add(alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef, current_file: str):
        self.defined_symbols[current_file].add(node.name)
        for arg in node.args.args:
            self.defined_symbols[current_file].add(arg.arg)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef, current_file: str):
        self.visit_FunctionDef(node, current_file)

    def visit_ClassDef(self, node: ast.ClassDef, current_file: str):
        self.defined_symbols[current_file].add(node.name)
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.defined_symbols[current_file].add(item.name)

    def visit_Name(self, node: ast.Name, current_file: str):
        if isinstance(node.ctx, ast.Load):
            if node.id not in self.builtin_symbols:
                self.used_symbols[current_file].append((node.id, node.lineno))

    def _find_circular_imports(self) -> List[List[str]]:
        """循環参照を検出する。"""
        graph = {f: list(imp) for f, imp in self.imports.items()}
        path: List[str] = []
        visited: Set[str] = set()
        cycles: List[List[str]] = []

        def dfs(node: str):
            path.append(node)
            visited.add(node)
            for neighbor in sorted(list(graph.get(node, []))):
                if neighbor in path:
                    cycle_start_index = path.index(neighbor)
                    cycles.append(path[cycle_start_index:] + [neighbor])
                elif neighbor not in visited:
                    dfs(neighbor)
            path.pop()

        for node in sorted(graph.keys()):
            if node not in visited:
                dfs(node)

        # 重複するサイクルを削除
        unique_cycles = []
        seen_cycles = set()
        for cycle in cycles:
            frozen_cycle = frozenset(cycle)
            if frozen_cycle not in seen_cycles:
                unique_cycles.append(cycle)
                seen_cycles.add(frozen_cycle)
        return unique_cycles


    def _calculate_coupling_metrics(self) -> List[Dict[str, Any]]:
        """モジュール間の結合度を計算する。"""
        afferent_couplings: Dict[str, int] = defaultdict(int)
        for _, importees in self.imports.items():
            for importee in importees:
                afferent_couplings[importee] += 1

        all_modules = set(self.imports.keys()) | set(afferent_couplings.keys())
        metrics = []

        for module_path in sorted(list(all_modules)):
            ca = afferent_couplings.get(module_path, 0) # Afferent Coupling
            ce = len(self.imports.get(module_path, set())) # Efferent Coupling
            instability = ce / (ca + ce) if (ca + ce) > 0 else 0
            metrics.append({
                "module": os.path.relpath(module_path, self.project_root),
                "ca": ca,
                "ce": ce,
                "instability": instability,
            })
        return metrics

    def analyze(self) -> Dict[str, Any]:
        """プロジェクト全体を解析する。"""
        for root, _, files in os.walk(self.project_root):
            if any(d in root for d in ['.venv', '.git', '__pycache__']):
                continue
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        tree = ast.parse(content, filename=file_path)
                        # ジェネリクスでast.NodeVisitorを拡張して、ファイルパスを渡せるようにする
                        visitor = self # type: ignore
                        visitor.current_file = file_path # type: ignore
                        visitor.visit(tree)
                    except (UnicodeDecodeError, SyntaxError) as e:
                        print(f"Skipping file due to error: {file_path} - {e}")

        # シンボル定義の収集
        all_project_defines: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        for file, data in self.defined_symbols.items():
            rel_file = os.path.relpath(file, self.project_root)
            for s_name in sorted(list(data)):
                all_project_defines[s_name].append((rel_file, file))

        # 未定義シンボルの検出
        undefined_symbols: List[Dict[str, Any]] = []
        for file, data in self.used_symbols.items():
            file_defines, _ = zip(*all_project_defines.items()) if all_project_defines else ([], [])
            for symbol, line in data:
                if symbol not in self.defined_symbols[file] and symbol not in file_defines:
                    undefined_symbols.append({"symbol": symbol, "file": os.path.relpath(file, self.project_root), "line": line})

        # 未使用シンボルの検出
        all_used_symbols = {s_name for f, _ in self.used_symbols.items() for s_name, _ in self.used_symbols[f]}
        unused_symbols: List[Dict[str, Any]] = []
        for file, data in self.defined_symbols.items():
            for symbol in data:
                if symbol not in all_used_symbols:
                    unused_symbols.append({"symbol": symbol, "file": os.path.relpath(file, self.project_root), "line": -1})


        circular_imports = self._find_circular_imports()
        coupling_metrics = self._calculate_coupling_metrics()

        return {
            "undefined_symbols": sorted([dict(t) for t in {tuple(d.items()) for d in undefined_symbols}], key=lambda x: (x['file'], x['line'])),
            "unused_symbols": sorted([dict(t) for t in {tuple(d.items()) for d in unused_symbols}], key=lambda x: (x['file'], x['symbol'])),
            "circular_imports": circular_imports,
            "coupling_metrics": sorted(coupling_metrics, key=lambda x: x['instability'], reverse=True),
            "project_symbols": {k: [p[0] for p in v] for k, v in all_project_defines.items()}
        }

    def print_analysis_results(self, results: Dict[str, Any]):
        print("\n--- Project Analysis Results ---")
        
        if results["undefined_symbols"]:
            print(f"\n[❌] Found {len(results['undefined_symbols'])} Undefined Symbols:")
            for item in results["undefined_symbols"]:
                print(f"  - {item['file']}:{item['line']} -> {item['symbol']}")
        
        if results["unused_symbols"]:
            print(f"\n[⚠️] Found {len(results['unused_symbols'])} Unused Symbols:")
            for item in results["unused_symbols"]:
                print(f"  - {item['file']} -> {item['symbol']}")

        if results["circular_imports"]:
            print(f"\n[🔄] Found {len(results['circular_imports'])} Circular Imports:")
            for i, cycle in enumerate(results["circular_imports"]):
                print(f"  Cycle {i+1}: {' -> '.join(cycle)}")
        
        print("\n[🔗] Coupling Metrics:")
        print("  {:<60} {:<5} {:<5} {:<12}".format("Module", "Ca", "Ce", "I"))
        print("  " + "-"*85)
        for metric in results["coupling_metrics"]:
            instability_str = f"{metric['instability']:.2f}"
            print(f"  {metric['module']:<60} {metric['ca']:<5} {metric['ce']:<5} {instability_str:<12}")

        print("\n--- Analysis Complete ---")

    def save_results_to_json(self, results: Dict[str, Any], output_file: str):
        """解析結果をJSONファイルに保存する。"""
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=4)
            print(f"\nAnalysis results saved to {output_file}")
        except (IOError, TypeError) as e:
            print(f"\nError saving results to {output_file}: {e}")

if __name__ == "__main__":
    project_directory = os.path.dirname(os.path.abspath(__file__))
    output_filename = "project_structure.json"
    
    print(f"Analyzing project in: {project_directory}")
    analyzer = ProjectAnalyzer(project_directory)
    analysis_results = analyzer.analyze()
    
    # ターミナルに結果を出力
    analyzer.print_analysis_results(analysis_results)
    
    # JSONファイルに結果を保存
    analyzer.save_results_to_json(analysis_results, output_filename)
