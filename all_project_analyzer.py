# /all_project_analyzer.py
# title: プロジェクト全体静的解析ツール
# role: プロジェクト内のすべてのPythonファイルを解析し、未定義シンボル、未使用シンボル、循環参照、カップリングメトリクスなど、プロジェクトの構造情報を包括的に抽出する。

import ast
import os
import builtins
import json
from collections import defaultdict
from typing import List, Dict, Any, Set, Tuple, Optional


class SymbolVisitor(ast.NodeVisitor):
    """ASTを走査してシンボルの定義、使用、インポート情報を収集するビジター。"""

    def __init__(self, file_path: str, project_root: str):
        self.file_path = file_path
        self.project_root = project_root
        self.definitions: List[Dict[str, Any]] = []
        self.used_symbols: List[Tuple[str, int]] = []
        self.imports: Set[str] = set()
        # ◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️↓修正開始◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️
        # __file__ などのマジック変数を最初からスコープに追加
        self._scope_stack: List[Set[str]] = [set(['__file__', '__name__'])]
        # ◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️↑修正終わり◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️
        self._current_class_name: Optional[str] = None

    def _add_defined(self, name: str):
        if self._scope_stack:
            self._scope_stack[-1].add(name)

    def _is_defined_in_scope(self, name: str) -> bool:
        for scope in reversed(self._scope_stack):
            if name in scope:
                return True
        return False

    def _resolve_import_path(self, module_name: str, level: int) -> Optional[str]:
        """相対インポートをプロジェクトルートからの絶対パスに解決する"""
        if level == 0:  # 絶対インポート
            # NOTE: 標準ライブラリや外部ライブラリのパス解決は複雑なため、
            #       ここではプロジェクト内のモジュールに絞る
            base_path = os.path.join(self.project_root, *module_name.split('.'))
            for ext in ['.py', '/__init__.py']:
                path = base_path + ext
                if os.path.exists(path):
                    return os.path.normpath(path)
            return None

        # 相対インポート
        current_dir = os.path.dirname(self.file_path)
        base_path = os.path.abspath(os.path.join(current_dir, *(['..'] * (level - 1))))
        
        if module_name:
             path_components = module_name.split('.')
             final_path = os.path.join(base_path, *path_components)
        else:
             final_path = base_path

        for ext in ['.py', '/__init__.py']:
            path_with_ext = final_path + ext
            if os.path.exists(path_with_ext) and path_with_ext.startswith(self.project_root):
                return os.path.normpath(path_with_ext)
        return None

    def visit_FunctionDef(self, node: ast.FunctionDef):
        is_method = self._current_class_name is not None
        if not is_method:
            self.definitions.append({
                "type": "function",
                "name": node.name,
                "line": node.lineno,
                "args": [arg.arg for arg in node.args.args]
            })
        self._add_defined(node.name)
        
        # 新しいスコープを開始
        self._scope_stack.append({arg.arg for arg in node.args.args})
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)

    # ◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️↓修正開始◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️
    def visit_Lambda(self, node: ast.Lambda):
        """ラムダ関数のスコープを処理する"""
        # 新しいスコープを開始
        self._scope_stack.append({arg.arg for arg in node.args.args})
        self.generic_visit(node)
        self._scope_stack.pop()

    def _handle_comprehension(self, node: Any):
        """リスト、セット、辞書内包表記のスコープを処理する共通ハンドラ。"""
        # 内包表記のジェネレータは独自のスコープを持つ
        self._scope_stack.append(set())
        # ジェネレータ式（... for x in ... if ...）を先に訪問して変数をスコープに追加
        for generator in node.generators:
            self.visit(generator)
        # その後、要素の式を訪問
        self.visit(node.elt if hasattr(node, 'elt') else node.value)
        self._scope_stack.pop()

    def visit_ListComp(self, node: ast.ListComp):
        self._handle_comprehension(node)

    def visit_SetComp(self, node: ast.SetComp):
        self._handle_comprehension(node)

    def visit_DictComp(self, node: ast.DictComp):
        self._handle_comprehension(node)
        
    def visit_GeneratorExp(self, node: ast.GeneratorExp):
        self._handle_comprehension(node)

    def visit_comprehension(self, node: ast.comprehension):
        # ターゲット変数（例: `x` in `for x in ...`）をスコープに追加
        if isinstance(node.target, ast.Name):
            self._add_defined(node.target.id)
        elif isinstance(node.target, (ast.Tuple, ast.List)):
            for elt in node.target.elts:
                if isinstance(elt, ast.Name):
                    self._add_defined(elt.id)
        # イテラブルとif節を訪問
        self.visit(node.iter)
        for if_clause in node.ifs:
            self.visit(if_clause)
    # ◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️↑修正終わり◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️

    def visit_ClassDef(self, node: ast.ClassDef):
        methods = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(item.name)
        
        self.definitions.append({
            "type": "class",
            "name": node.name,
            "line": node.lineno,
            "methods": methods
        })
        self._add_defined(node.name)
        
        # クラススコープの処理
        self._current_class_name = node.name
        self._scope_stack.append(set())
        self.generic_visit(node)
        self._scope_stack.pop()
        self._current_class_name = None

    def visit_Assign(self, node: ast.Assign):
        # 最初にvalueをvisitして、右辺で使われる変数をチェック
        self.visit(node.value)
        # その後、左辺のターゲットを定義済みとして追加
        for target in node.targets:
            if isinstance(target, ast.Name):
                # グローバルスコープでの変数定義を記録
                if len(self._scope_stack) == 1:
                    self.definitions.append({
                        "type": "variable",
                        "name": target.id,
                        "line": node.lineno
                    })
                self._add_defined(target.id)
            else:
                # タプル展開代入なども処理
                self.visit(target)


    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load) and not self._is_defined_in_scope(node.id):
            self.used_symbols.append((node.id, node.lineno))
        elif isinstance(node.ctx, ast.Store):
            self._add_defined(node.id)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self._add_defined(alias.asname or alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        # ◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️↓修正開始◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️
        # 'from . import ...' のようなケースでnode.moduleがNoneになることがある
        resolved_path = self._resolve_import_path(node.module or "", node.level)
        # ◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️↑修正終わり◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️
        if resolved_path:
            self.imports.add(resolved_path)

        for alias in node.names:
            self._add_defined(alias.asname or alias.name)


class ProjectAnalyzer:
    """Pythonプロジェクトの静的解析を行い、構造情報を抽出するクラス。"""

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(project_root)
        self.file_map: Dict[str, Dict[str, Any]] = defaultdict(dict)
        # ◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️↓修正開始◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️
        self.all_defined_symbols: Set[str] = set(dir(builtins)) | {'__file__', '__name__'}
        # ◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️↑修正終わり◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️

    def analyze(self) -> Dict[str, Any]:
        """プロジェクト内の全Pythonファイルを解析し、結果を集計する。"""
        py_files = self._get_python_files()
        for file_path in py_files:
            self._analyze_file(file_path)
        
        self._collect_all_defined_symbols()
        return self._build_final_report()

    def _get_python_files(self) -> List[str]:
        py_files = []
        for root, _, files in os.walk(self.project_root):
            # ◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️↓修正開始◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️
            # .venvのようなディレクトリを除外
            if any(d in root for d in ['.venv', '.git', '__pycache__', 'node_modules', '.mypy_cache']):
                continue
            # ◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️↑修正終わり◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️◾️
            for file in files:
                if file.endswith(".py"):
                    py_files.append(os.path.join(root, file))
        return py_files

    def _analyze_file(self, file_path: str):
        """単一のファイルを解析し、情報を`self.file_map`に格納する。"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content, filename=file_path)
            
            visitor = SymbolVisitor(file_path, self.project_root)
            visitor.visit(tree)

            rel_path = os.path.relpath(file_path, self.project_root)
            self.file_map[rel_path] = {
                "definitions": visitor.definitions,
                "used_symbols": visitor.used_symbols,
                "imports": {os.path.relpath(p, self.project_root) for p in visitor.imports if p},
            }
        except Exception as e:
            print(f"Skipping file due to error: {file_path} - {e}")
    
    def _collect_all_defined_symbols(self):
        """プロジェクト全体で定義されているシンボルを収集する。"""
        for data in self.file_map.values():
            for definition in data["definitions"]:
                self.all_defined_symbols.add(definition["name"])

    def _build_final_report(self) -> Dict[str, Any]:
        """解析結果を集計し、最終的なレポートを作成する。"""
        undefined = self._find_undefined_symbols()
        unused = self._find_unused_symbols()
        circular = self._detect_circular_imports()
        coupling = self._calculate_coupling()

        # file_mapにカップリング情報を追加
        for file, metrics in coupling.items():
            if file in self.file_map:
                self.file_map[file]['coupling'] = metrics

        return {
            "project_root": self.project_root,
            "issues": {
                "undefined_symbols": sorted(undefined, key=lambda x: (x['file'], x['line'])),
                "unused_symbols": sorted(unused, key=lambda x: (x['file'], x['line'])),
                "circular_imports": circular,
            },
            "file_details": self.file_map
        }

    def _find_undefined_symbols(self) -> List[Dict[str, Any]]:
        """未定義シンボルを検出する。"""
        undefined_symbols = []
        for file, data in self.file_map.items():
            for symbol, line_no in data["used_symbols"]:
                # プロジェクト全体でも定義されていないシンボルを検出
                if symbol not in self.all_defined_symbols:
                    undefined_symbols.append({
                        "symbol": symbol,
                        "file": file,
                        "line": line_no,
                    })
        # 重複削除
        return [dict(t) for t in {tuple(d.items()) for d in undefined_symbols}]

    def _find_unused_symbols(self) -> List[Dict[str, Any]]:
        """未使用のグローバル関数・クラスを検出する。"""
        all_used_symbols = set()
        for data in self.file_map.values():
            for symbol, _ in data["used_symbols"]:
                all_used_symbols.add(symbol)
        
        unused_symbols = []
        for file, data in self.file_map.items():
            for definition in data["definitions"]:
                # インポートされたシンボルは対象外とし、関数とクラスに絞る
                if definition['type'] in ['function', 'class']:
                    if definition['name'] not in all_used_symbols:
                        # __init__など特殊メソッドは無視
                        if not definition['name'].startswith('__'):
                            unused_symbols.append({
                                "symbol": definition['name'],
                                "type": definition['type'],
                                "file": file,
                                "line": definition['line'],
                            })
        return unused_symbols

    def _detect_circular_imports(self) -> List[List[str]]:
        """循環参照を検出する。"""
        graph = {file: data["imports"] for file, data in self.file_map.items()}
        cycles = []
        
        path: List[str] = []
        visiting: Set[str] = set()
        visited: Set[str] = set()

        def dfs(node: str):
            visiting.add(node)
            path.append(node)

            for neighbour in graph.get(node, []):
                if neighbour in visiting:
                    try:
                        cycle_start_index = path.index(neighbour)
                        cycle = path[cycle_start_index:] + [neighbour]
                        sorted_cycle = tuple(sorted(cycle))
                        if sorted_cycle not in {tuple(sorted(c)) for c in cycles}:
                             cycles.append(cycle)
                    except ValueError:
                        continue # Should not happen
                elif neighbour not in visited:
                    dfs(neighbour)
            
            path.pop()
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            if node not in visited:
                dfs(node)
                    
        return cycles

    def _calculate_coupling(self) -> Dict[str, Dict[str, int]]:
        """ファイルの結合度（Afferent/Efferent）を計算する。"""
        coupling = defaultdict(lambda: {"afferent": 0, "efferent": 0})
        
        # Efferent Coupling (Ca: 遠心性結合) - このファイルが依存している数
        for file, data in self.file_map.items():
            coupling[file]["efferent"] = len(data.get("imports", []))

        # Afferent Coupling (Ce: 求心性結合) - このファイルに依存している数
        for _, data in self.file_map.items():
            for imported_file in data.get("imports", []):
                if imported_file in self.file_map:
                    coupling[imported_file]["afferent"] += 1
                    
        return dict(coupling)


def print_analysis_results(results: Dict[str, Any]):
    """解析結果をコンソールに分かりやすく出力する。"""
    print("\n--- Project Analysis Results ---")
    
    issues = results.get("issues", {})
    
    if issues.get("undefined_symbols"):
        print(f"\n[❌] Found {len(issues['undefined_symbols'])} Undefined Symbols:")
        for item in issues["undefined_symbols"]:
            print(f"  - {item['file']}:{item['line']} -> '{item['symbol']}' is not defined")
    else:
        print("\n[✅] No undefined symbols found.")

    if issues.get("unused_symbols"):
        print(f"\n[⚠️] Found {len(issues['unused_symbols'])} Unused Global Symbols:")
        for item in issues["unused_symbols"]:
            print(f"  - {item['file']}:{item['line']} -> {item['type']} '{item['symbol']}' seems to be unused.")
    else:
        print("\n[✅] No unused global symbols found.")

    if issues.get("circular_imports"):
        print(f"\n[⛔️] Found {len(issues['circular_imports'])} Circular Imports:")
        for i, cycle in enumerate(issues["circular_imports"]):
            print(f"  - Cycle {i+1}: {' -> '.join(cycle)}")
    else:
        print("\n[✅] No circular imports found.")

    print("\n--- Analysis Complete ---")


def save_results_to_json(results: Dict[str, Any], output_file: str):
    """解析結果をJSONファイルに保存する。"""
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            # setをリストに変換してシリアライズ可能にする
            def convert_sets_to_lists(obj):
                if isinstance(obj, set):
                    return sorted(list(obj))
                if isinstance(obj, dict):
                    return {k: convert_sets_to_lists(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [convert_sets_to_lists(i) for i in obj]
                return obj
            
            serializable_results = convert_sets_to_lists(results)
            json.dump(serializable_results, f, indent=2, ensure_ascii=False)
        print(f"\nFull analysis results saved to {output_file}")
    except (IOError, TypeError) as e:
        print(f"\nError saving results to {output_file}: {e}")


if __name__ == "__main__":
    # このスクリプトが置かれているディレクトリをプロジェクトルートとする
    project_directory = os.path.dirname(os.path.abspath(__file__))
    output_filename = "project_analysis.json"

    print(f"Analyzing project in: {project_directory}")
    analyzer = ProjectAnalyzer(project_directory)
    analysis_results = analyzer.analyze()

    print_analysis_results(analysis_results)
    save_results_to_json(analysis_results, output_filename)
