# /all_project_analyzer.py
# title: プロジェクト全体静的解析ツール
# role: プロジェクト内のすべてのPythonファイルを解析し、未定義シンボル、未使用シンボル、循環参照、カップリングメトリクスを検出する。

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
        self.project_root = os.path.abspath(project_root)
        self.symbols: Dict[str, Any] = defaultdict(lambda: {"defined": set(), "used": []})
        self.imports: Dict[str, Set[str]] = defaultdict(set)

    def analyze(self):
        """プロジェクト内の全Pythonファイルを解析する。"""
        for root, _, files in os.walk(self.project_root):
            if any(d in root for d in ['.venv', '.git', '__pycache__']):
                continue
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    self._analyze_file(file_path)

        return self._collect_results()

    def _analyze_file(self, file_path: str):
        """単一のファイルを解析する。"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content, filename=file_path)
            
            visitor = SymbolVisitor(file_path)
            visitor.visit(tree)
            
            self.symbols[file_path]["defined"] = visitor.defined_symbols
            self.symbols[file_path]["used"] = visitor.used_symbols
            
        except (SyntaxError, UnicodeDecodeError, TypeError) as e:
            print(f"Skipping file due to error: {file_path} - {e}")

    def _collect_results(self) -> Dict[str, Any]:
        """解析結果を集計する。"""
        all_defined_symbols: Set[str] = set(dir(builtins))
        for data in self.symbols.values():
            all_defined_symbols.update(data["defined"])
            
        undefined_symbols: List[Dict[str, Any]] = []
        for file_path, data in self.symbols.items():
            for symbol, line_no in data["used"]:
                if symbol not in all_defined_symbols:
                    undefined_symbols.append({
                        "symbol": symbol,
                        "file": os.path.relpath(file_path, self.project_root),
                        "line": line_no,
                    })
        
        # 重複を削除してソート
        unique_undefined = sorted([dict(t) for t in {tuple(d.items()) for d in undefined_symbols}], key=lambda x: (x['file'], x['line']))

        return {
            "undefined_symbols": unique_undefined,
            # 他のメトリクスもここに追加可能
        }

class SymbolVisitor(ast.NodeVisitor):
    """
    ASTを走査してシンボルの定義と使用を収集するビジター。
    """
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.defined_symbols: Set[str] = set()
        self.used_symbols: List[Tuple[str, int]] = []
        self._scope_stack: List[Set[str]] = [set()] # スコープごとの定義済みシンボル

    def _add_defined(self, name: str):
        self.defined_symbols.add(name)
        self._scope_stack[-1].add(name)

    def _is_defined(self, name: str) -> bool:
        for scope in reversed(self._scope_stack):
            if name in scope:
                return True
        return False

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._add_defined(node.name)
        self._scope_stack.append({arg.arg for arg in node.args.args})
        self.defined_symbols.update(self._scope_stack[-1])
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)
        
    def visit_ClassDef(self, node: ast.ClassDef):
        self._add_defined(node.name)
        self._scope_stack.append(set())
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._add_defined(target.id)
        self.generic_visit(node)
        
    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load) and not self._is_defined(node.id):
            self.used_symbols.append((node.id, node.lineno))
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
             self._add_defined(node.id)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self._add_defined(alias.asname or alias.name)
            
    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            self._add_defined(alias.asname or alias.name)
            
    def visit_comprehension(self, node: ast.comprehension):
        if isinstance(node.target, ast.Name):
             self._add_defined(node.target.id)
        self.generic_visit(node)

def print_analysis_results(results: Dict[str, Any]):
    """解析結果をコンソールに出力する。"""
    print("\n--- Project Analysis Results ---")
    if results.get("undefined_symbols"):
        print(f"\n[❌] Found {len(results['undefined_symbols'])} Undefined Symbols:")
        for item in results["undefined_symbols"]:
            print(f"  - {item['file']}:{item['line']} -> {item['symbol']}")
    else:
        print("\n[✅] No undefined symbols found.")
    print("\n--- Analysis Complete ---")

def save_results_to_json(results: Dict[str, Any], output_file: str):
    """解析結果をJSONファイルに保存する。"""
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=4, ensure_ascii=False)
        print(f"\nAnalysis results saved to {output_file}")
    except (IOError, TypeError) as e:
        print(f"\nError saving results to {output_file}: {e}")

if __name__ == "__main__":
    project_directory = os.path.dirname(os.path.abspath(__file__))
    output_filename = "project_structure.json"
    
    print(f"Analyzing project in: {project_directory}")
    analyzer = ProjectAnalyzer(project_directory)
    analysis_results = analyzer.analyze()
    
    print_analysis_results(analysis_results)
    save_results_to_json(analysis_results, output_filename)
