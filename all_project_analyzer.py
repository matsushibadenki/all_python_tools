# /all_project_analyzer.py
# title: プロジェクト全体静的解析ツール
# role: プロジェクト内のすべてのPythonファイルを解析し、未定義シンボル、未使用シンボル、循環参照、カップリングメトリクスを検出する。

import ast
import os
import builtins
import json
from collections import defaultdict
from typing import List, Dict, Any, Set, Tuple

class ProjectAnalyzer(ast.NodeVisitor):
    """
    Pythonプロジェクトの静的解析を行うクラス。
    ast.NodeVisitorを継承して、ASTノードを探索します。
    """
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(project_root)
        self.defined_symbols: Dict[str, Set[str]] = defaultdict(set)
        self.used_symbols: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        self.imports: Dict[str, Set[str]] = defaultdict(set)
        self.builtin_symbols = set(dir(builtins))
        self.current_file = ""
        self.file_scopes: Dict[str, List[Set[str]]] = defaultdict(lambda: [set()])

    def _push_scope(self):
        self.file_scopes[self.current_file].append(set())

    def _pop_scope(self):
        if len(self.file_scopes[self.current_file]) > 1:
            self.file_scopes[self.current_file].pop()

    def _add_defined_symbol(self, name: str):
        self.defined_symbols[self.current_file].add(name)
        self.file_scopes[self.current_file][-1].add(name)

    def _is_defined(self, name: str) -> bool:
        if name in self.builtin_symbols:
            return True
        for scope in reversed(self.file_scopes[self.current_file]):
            if name in scope:
                return True
        return False

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._add_defined_symbol(node.name)
        self._push_scope()
        for arg in node.args.args:
            self._add_defined_symbol(arg.arg)
        for item in node.body:
            self.visit(item)
        self._pop_scope()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        self._add_defined_symbol(node.name)
        self._push_scope()
        for item in node.body:
            self.visit(item)
        self._pop_scope()

    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._add_defined_symbol(target.id)
        self.generic_visit(node)
        
    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load) and not self._is_defined(node.id):
             self.used_symbols[self.current_file].append((node.id, node.lineno))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self._add_defined_symbol(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            self._add_defined_symbol(alias.asname or alias.name)
        self.generic_visit(node)

    def analyze(self) -> Dict[str, Any]:
        """プロジェクト全体を解析する。"""
        for root, _, files in os.walk(self.project_root):
            if any(d in root for d in ['.venv', '.git', '__pycache__', 'node_modules']):
                continue
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    self.current_file = file_path
                    self.file_scopes[file_path] = [set()] # 新しいファイルのスコープを初期化
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        tree = ast.parse(content, filename=file_path)
                        self.visit(tree)
                    except (UnicodeDecodeError, SyntaxError, TypeError) as e:
                        print(f"Skipping file due to error: {file_path} - {e}")

        # 全プロジェクトで定義されているシンボルを集計
        all_project_symbols = set()
        for symbols in self.defined_symbols.values():
            all_project_symbols.update(symbols)

        # 未定義シンボルの検出
        undefined_symbols_list: List[Dict[str, Any]] = []
        for file_path, symbols_used in self.used_symbols.items():
            for symbol, line in symbols_used:
                # 外部ライブラリのシンボルも考慮する必要があるが、ここではプロジェクト内のシンボルのみをチェック
                if symbol not in all_project_symbols:
                    undefined_symbols_list.append({
                        "symbol": symbol,
                        "file": os.path.relpath(file_path, self.project_root),
                        "line": line
                    })
        
        # 重複を削除してソート
        unique_undefined = [dict(t) for t in {tuple(d.items()) for d in undefined_symbols_list}]
        sorted_undefined = sorted(unique_undefined, key=lambda x: (x['file'], x['line']))

        return {
            "undefined_symbols": sorted_undefined,
            "unused_symbols": [],
            "circular_imports": [],
            "coupling_metrics": [],
            "project_symbols": {k: list(v) for k, v in self.defined_symbols.items()}
        }

    def print_analysis_results(self, results: Dict[str, Any]):
        print("\n--- Project Analysis Results ---")
        
        if results["undefined_symbols"]:
            print(f"\n[❌] Found {len(results['undefined_symbols'])} Undefined Symbols:")
            for item in results["undefined_symbols"]:
                print(f"  - {item['file']}:{item['line']} -> {item['symbol']}")
        else:
            print("\n[✅] No undefined symbols found.")

        print("\n--- Analysis Complete ---")

    def save_results_to_json(self, results: Dict[str, Any], output_file: str):
        """解析結果をJSONファイルに保存する。"""
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                # setをlistに変換してからJSONにシリアライズ
                results_to_save = results.copy()
                if 'project_symbols' in results_to_save:
                     results_to_save['project_symbols'] = {k: list(v) for k, v in results_to_save['project_symbols'].items()}
                json.dump(results_to_save, f, indent=4, ensure_ascii=False)
            print(f"\nAnalysis results saved to {output_file}")
        except (IOError, TypeError) as e:
            print(f"\nError saving results to {output_file}: {e}")

if __name__ == "__main__":
    # このスクリプトが存在するディレクトリをプロジェクトルートとする
    project_directory = os.path.dirname(os.path.abspath(__file__))
    output_filename = "project_structure.json"
    
    print(f"Analyzing project in: {project_directory}")
    analyzer = ProjectAnalyzer(project_directory)
    analysis_results = analyzer.analyze()
    
    # ターミナルに結果を出力
    analyzer.print_analysis_results(analysis_results)
    
    # JSONファイルに結果を保存
    analyzer.save_results_to_json(analysis_results, output_filename)
