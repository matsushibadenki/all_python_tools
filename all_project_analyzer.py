# /all_project_analyzer.py
# プロジェクト静的分析ツール V2
# 指定されたPythonプロジェクトのソースコードを静的解析し、潜在的な問題を診断する。
# パッケージ構造、未定義・未使用シンボル、クラスインターフェース、型ヒントの整合性などをチェックする。

import ast
import os
import builtins
import json
from collections import defaultdict
from typing import Dict, List, Any, Set, Tuple, Optional

class ProjectAnalyzer(ast.NodeVisitor):
    """
    プロジェクトのソースコードをAST（抽象構文木）レベルで解析し、
    構造的な問題や潜在的なバグを検出する。
    """

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(project_root)
        self.tree: Dict[str, Any] = {}
        self.current_file = ""
        self.current_class_name: Optional[str] = None
        
        # 検出された問題をカテゴリ別に格納
        self.undefined_symbols: List[Dict[str, Any]] = []
        self.unused_symbols: List[Dict[str, Any]] = []
        self.package_issues: List[str] = []
        self.type_hint_issues: List[str] = []

        # シンボル定義と使用状況を追跡
        self.defined_symbols = defaultdict(set)
        self.used_symbols = defaultdict(set)

        # クラスとメソッドのインターフェース情報を格納
        self.class_interfaces = defaultdict(lambda: {
            "bases": [],
            "methods": {},
            "attributes": set()
        })
        
        # Pythonの組み込み名を事前にセットアップ
        self.builtin_names = set(dir(builtins))

    def _get_node_repr(self, node: Optional[ast.AST]) -> str:
        """ASTノードを文字列表現に変換する"""
        if node is None:
            return "None"
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._get_node_repr(node.value)}.{node.attr}"
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.Subscript):
            slice_repr = self._get_node_repr(node.slice)
            return f"{self._get_node_repr(node.value)}[{slice_repr}]"
        if isinstance(node, (ast.Tuple, ast.List)):
             return ", ".join([self._get_node_repr(e) for e in node.elts])
        return ast.dump(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        """クラス定義ノードを訪問した際の処理"""
        previous_class_name = self.current_class_name
        self.current_class_name = node.name
        self.defined_symbols[self.current_file].add(node.name)

        class_key = f"{self.current_file}:{node.name}"
        
        # 基底クラスを記録
        for base in node.bases:
            base_name = self._get_node_repr(base)
            self.class_interfaces[class_key]["bases"].append(base_name)
            self.used_symbols[self.current_file].add(base_name.split('.')[0])
        
        # クラス内の属性とメソッドを探索
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        self.class_interfaces[class_key]["attributes"].add(target.id)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                 self.visit(stmt) # メソッド定義を処理

        self.generic_visit(node)
        self.current_class_name = previous_class_name

    def _analyze_method_args(self, args_node: ast.arguments) -> List[Dict[str, Any]]:
        """メソッド・関数の引数を解析する"""
        args_info = []
        
        # 通常の引数 (positional and keyword)
        num_args = len(args_node.args)
        num_defaults = len(args_node.defaults)
        defaults_start_index = num_args - num_defaults

        for i, arg in enumerate(args_node.args):
            if arg.arg == 'self' or arg.arg == 'cls':
                continue
            
            arg_data: Dict[str, Any] = {"name": arg.arg, "type": "positional_or_keyword"}
            if arg.annotation:
                arg_data["annotation"] = self._get_node_repr(arg.annotation)
            
            if i >= defaults_start_index:
                default_value = args_node.defaults[i - defaults_start_index]
                arg_data["default"] = self._get_node_repr(default_value)
                
                # 型ヒントの簡易チェック
                if isinstance(default_value, ast.Constant) and default_value.value is None:
                    annotation_str = arg_data.get("annotation", "")
                    if "Optional" not in annotation_str and "Any" not in annotation_str:
                        issue_msg = (
                            f"In '{self.current_file}' at line {arg.lineno}: "
                            f"Argument '{arg.arg}' has a default value of None "
                            f"but is not typed as Optional."
                        )
                        self.type_hint_issues.append(issue_msg)

            args_info.append(arg_data)

        # *args
        if args_node.vararg:
            args_info.append({"name": f"*{args_node.vararg.arg}", "type": "variable_positional"})

        # **kwargs
        if args_node.kwarg:
             args_info.append({"name": f"**{args_node.kwarg.arg}", "type": "variable_keyword"})

        return args_info

    def _process_function_def(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        """関数・メソッド定義を共通処理する"""
        self.defined_symbols[self.current_file].add(node.name)
        if self.current_class_name:
            class_key = f"{self.current_file}:{self.current_class_name}"
            method_info = {
                "args": self._analyze_method_args(node.args),
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "line": node.lineno
            }
            self.class_interfaces[class_key]["methods"][node.name] = method_info
        
        # デコレータの使用を記録
        for decorator in node.decorator_list:
            self.used_symbols[self.current_file].add(self._get_node_repr(decorator).split('.')[0])
            
        self.generic_visit(node)


    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._process_function_def(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._process_function_def(node)

    def visit_Name(self, node: ast.Name):
        """変数・関数名などの参照ノードを処理"""
        if isinstance(node.ctx, ast.Load):
            self.used_symbols[self.current_file].add(node.id)
        elif isinstance(node.ctx, ast.Store):
            self.defined_symbols[self.current_file].add(node.id)

    def analyze(self) -> Dict[str, Any]:
        """プロジェクト全体のファイルを解析する"""
        for root, dirs, files in os.walk(self.project_root):
            # プロジェクトルートからの相対パスを計算
            relative_root = os.path.relpath(root, self.project_root)
            if relative_root == ".":
                relative_root = ""

            # パッケージ構造のチェック
            if any(f.endswith('.py') for f in files) and '__init__.py' not in files:
                # 無視するディレクトリ
                if not any(d in relative_root for d in ['tests', '.venv', 'site-packages']):
                    issue_msg = f"Potential package issue: Directory '{relative_root}' contains Python files but is missing an __init__.py file."
                    self.package_issues.append(issue_msg)

            for file in files:
                if file.endswith('.py'):
                    self.current_file = os.path.join(relative_root, file)
                    file_path = os.path.join(root, file)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            tree = ast.parse(f.read(), filename=file_path)
                            self.visit(tree)
                    except (UnicodeDecodeError, SyntaxError, Exception) as e:
                        print(f"Could not parse {file_path}: {e}")

        # 未定義シンボルの検出
        all_project_defines = set()
        for symbols in self.defined_symbols.values():
            all_project_defines.update(symbols)

        for file, symbols in self.used_symbols.items():
            for symbol in symbols:
                if symbol not in self.defined_symbols[file] and \
                   symbol not in all_project_defines and \
                   symbol not in self.builtin_names:
                    # この簡易的なチェックでは行番号が取れないため、ファイルレベルでの報告
                    self.undefined_symbols.append({"symbol": symbol, "file": file, "line": "N/A"})

        return {
            "undefined_symbols": self.undefined_symbols,
            "unused_symbols": self.unused_symbols, # 未使用シンボル検出ロジックは今回省略
            "package_issues": self.package_issues,
            "type_hint_issues": self.type_hint_issues,
            "class_interfaces": self.class_interfaces
        }

def print_analysis_results(results: Dict[str, Any]):
    """解析結果を整形して表示する"""
    print("\n" + "="*50)
    print(" Project Analysis Report")
    print("="*50 + "\n")

    if results["package_issues"]:
        print("--- 📦 Package Structure Issues ---")
        for issue in sorted(results["package_issues"]):
            print(f"⚠️ {issue}")
        print("\n")

    if results["type_hint_issues"]:
        print("--- 🔬 Type Hint Issues ---")
        for issue in sorted(results["type_hint_issues"]):
            print(f"🔬 {issue}")
        print("\n")

    if results["undefined_symbols"]:
        print("--- ❓ Undefined Symbol Issues ---")
        for item in sorted(results["undefined_symbols"], key=lambda x: x['file']):
            print(f"❓ Symbol '{item['symbol']}' used in '{item['file']}' might be undefined.")
        print("\n")

    if results["class_interfaces"]:
        print("--- 🏛️ Class & Method Interfaces ---")
        for class_key, info in sorted(results["class_interfaces"].items()):
            bases = ", ".join(info['bases']) if info['bases'] else "object"
            print(f"\nclass {class_key} ({bases}):")
            if info['attributes']:
                print("  Attributes:")
                for attr in sorted(info['attributes']):
                    print(f"    - {attr}")
            
            if info['methods']:
                print("  Methods:")
                for method_name, method_info in sorted(info['methods'].items()):
                    args_str_parts = []
                    for arg in method_info['args']:
                        part = arg['name']
                        if "annotation" in arg:
                            part += f": {arg['annotation']}"
                        if "default" in arg:
                            part += f" = {arg['default']}"
                        args_str_parts.append(part)
                    
                    args_str = ", ".join(args_str_parts)
                    async_str = "async " if method_info['is_async'] else ""
                    print(f"    - {async_str}def {method_name}({args_str})")
        print("\n")

    print("="*50)
    print(" Analysis Complete")
    print("="*50)

if __name__ == "__main__":
    # プロジェクトのルートディレクトリを指定
    # 例: project_directory = "/path/to/your/project"
    project_directory = "." 
    output_filename = "project_analysis_report.json"
    
    print(f"Analyzing project at: {os.path.abspath(project_directory)}")
    analyzer = ProjectAnalyzer(project_directory)
    analysis_results = analyzer.analyze()

    print_analysis_results(analysis_results)

    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            # setをリストに変換してJSONシリアライズ可能にする
            analysis_results['class_interfaces'] = {
                k: {
                    **v, 
                    'attributes': sorted(list(v['attributes']))
                } 
                for k, v in analysis_results['class_interfaces'].items()
            }
            json.dump(analysis_results, f, indent=4, ensure_ascii=False)
        print(f"\n💾 Full analysis report saved to '{output_filename}'")
    except (IOError, TypeError) as e:
        print(f"\n❌ Failed to save JSON report: {e}")