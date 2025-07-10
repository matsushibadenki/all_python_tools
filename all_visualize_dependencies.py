# path: ./visualize_dependencies.py
# title: Python Project Dependency Visualizer
# description: このスクリプトは、指定されたPythonプロジェクトのモジュール間の依存関係を解析し、
#              循環参照をハイライトしたMermaid形式のグラフを生成します。
#              オプションでMermaidグラフをHTMLファイルとして出力し、ブラウザで表示できるようにします。

import os
import ast
import argparse
from collections import defaultdict
from typing import List, Dict, Set, Tuple

class ModuleVisitor(ast.NodeVisitor):
    """
    ASTを探索し、import文を抽出するクラス。
    相対インポートは絶対モジュールパスに解決します。
    """
    def __init__(self, project_root: str, current_file_path: str):
        self.project_root = project_root
        self.imports = set()
        # ファイルパスからモジュールパスのパーツリストを生成 (例: ['my_app', 'services', 'user_service'])
        self.current_module_parts = self._path_to_module_parts(current_file_path)

    def _path_to_module_parts(self, path: str) -> List[str]:
        """ファイルパスをモジュールパスのパーツのリストに変換します。"""
        # __init__.py はパッケージ名自体を表すため、ファイル名を削除
        if os.path.basename(path) == "__init__.py":
            path = os.path.dirname(path)
            
        relative_path = os.path.relpath(path, self.project_root)
        module_path, _ = os.path.splitext(relative_path)
        return module_path.split(os.path.sep)

    def visit_Import(self, node: ast.Import):
        """ 'import a.b.c' 形式のインポートを処理します。 """
        for alias in node.names:
            self.imports.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """ 'from . import ...' や 'from package import ...' 形式のインポートを処理します。 """
        level = node.level
        
        if level > 0:  # from . import foo や from ..utils import bar などの相対インポート
            base_module_parts = self.current_module_parts[:-level]
            if node.module:
                # from .foo import Bar -> 'foo' を現在のパッケージパスに結合
                imported_module_name = ".".join(base_module_parts + node.module.split('.'))
            else:
                # from . import foo -> パッケージ自体をインポート
                imported_module_name = ".".join(base_module_parts)
            
            if imported_module_name:
                self.imports.add(imported_module_name)
        
        elif node.module:  # from package import module などの絶対インポート
            self.imports.add(node.module)
            
        self.generic_visit(node)

class DependencyAnalyzer:
    """
    プロジェクト内のPythonファイルの依存関係を解析するクラス。
    """
    def __init__(self, project_root: str, exclude_dirs: List[str] = None):
        self.project_root = os.path.abspath(project_root)
        # 除外ディレクトリの絶対パスリストを作成
        excluded = exclude_dirs or []
        self.exclude_dirs = [os.path.abspath(os.path.join(self.project_root, d)) for d in excluded]
        self.dependencies: Dict[str, Set[str]] = defaultdict(set)
        self.all_project_modules: Set[str] = set()

    def _path_to_module(self, path: str) -> str:
        """ファイルパスを完全なモジュール名に変換します (例: /path/to/app/main.py -> app.main)。"""
        relative_path = os.path.relpath(path, self.project_root)
        if relative_path.startswith('..'):
            return ""
        
        module_path, _ = os.path.splitext(relative_path)
        
        # '__init__.py' はパッケージ/ディレクトリ名そのものを表す
        if os.path.basename(module_path) == "__init__":
            module_path = os.path.dirname(module_path)

        return module_path.replace(os.path.sep, '.')

    def _is_excluded(self, path: str) -> bool:
        """指定されたパスが除外対象のディレクトリまたは一般的な除外パターンに一致するか判定します。"""
        # --excludeで指定されたディレクトリを除外
        abs_path = os.path.abspath(path)
        for excluded_dir in self.exclude_dirs:
            if os.path.commonpath([abs_path, excluded_dir]) == excluded_dir:
                return True
        # 一般的な仮想環境やキャッシュディレクトリを除外
        parts = abs_path.split(os.sep)
        if any(part.startswith('.') or part == '__pycache__' or part == 'venv' for part in parts):
            return True
        return False

    def analyze(self):
        """プロジェクト全体の依存関係を解析します。"""
        # ステップ1: プロジェクト内に存在するすべてのモジュールをリストアップ
        for root, dirs, files in os.walk(self.project_root, topdown=True):
            # 除外ディレクトリ配下は探索しない
            dirs[:] = [d for d in dirs if not self._is_excluded(os.path.join(root, d))]
            
            for file in files:
                if file.endswith(".py"):
                    path = os.path.join(root, file)
                    module_name = self._path_to_module(path)
                    if module_name:
                        self.all_project_modules.add(module_name)
        
        # ステップ2: 各ファイルを解析し、依存関係を構築
        for root, dirs, files in os.walk(self.project_root, topdown=True):
            dirs[:] = [d for d in dirs if not self._is_excluded(os.path.join(root, d))]
            
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    importer_module = self._path_to_module(file_path)

                    if not importer_module:
                        continue

                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            tree = ast.parse(content, filename=file_path)
                        
                        visitor = ModuleVisitor(self.project_root, file_path)
                        visitor.visit(tree)

                        for imported in visitor.imports:
                            # インポートされたモジュールがプロジェクト内部のものか判定
                            parts = imported.split('.')
                            # 'a.b.c' のようにインポートされた場合、'a.b.c', 'a.b', 'a' の順で
                            # プロジェクトモジュールに存在するかチェックする
                            for i in range(len(parts), 0, -1):
                                sub_module = ".".join(parts[:i])
                                if sub_module in self.all_project_modules:
                                    if importer_module != sub_module:  # 自己参照は追加しない
                                        self.dependencies[importer_module].add(sub_module)
                                    # 最も長く一致するモジュール（最も具体的）を依存先としたら終了
                                    break
                    except SyntaxError as e:
                        print(f"警告: 構文エラーのため {file_path} を解析できませんでした: {e}")
                    except Exception as e:
                        print(f"警告: {file_path} の処理中にエラーが発生しました: {e}")

    def find_circular_dependencies(self) -> Set[Tuple[str, str]]:
        """循環参照しているモジュールのペアを検出します。"""
        circular_pairs = set()
        # AがBをインポートし、かつBがAをインポートしているペアを探す
        for importer, imported_set in self.dependencies.items():
            for imported in imported_set:
                if importer in self.dependencies.get(imported, set()):
                    # アルファベット順にソートしてタプルに格納し、重複を防ぐ (A,B) と (B,A) を統一
                    pair = tuple(sorted((importer, imported)))
                    circular_pairs.add(pair)
        return circular_pairs

class MermaidGenerator:
    """
    依存関係データからMermaidグラフ定義を生成するクラス。
    """
    def __init__(self, dependencies: Dict[str, Set[str]], circular_pairs: Set[Tuple[str, str]]):
        self.dependencies = dependencies
        self.circular_pairs = circular_pairs

    def generate(self) -> str:
        """Mermaidのグラフ定義文字列を生成します。"""
        lines = ["graph TD;"]
        
        styled_links = []
        normal_links = []
        processed_links = set()

        # 全ての依存関係をアルファベット順で処理し、出力の順序を安定させる
        for importer in sorted(self.dependencies.keys()):
            for imported in sorted(list(self.dependencies[importer])):
                link_tuple = (importer, imported)
                if link_tuple in processed_links:
                    continue
                
                # このリンクが循環参照の一部かチェック
                is_circular = tuple(sorted(link_tuple)) in self.circular_pairs
                
                # Mermaidで特殊文字が含まれても大丈夫なようにモジュール名をクオートで囲む
                link_str = f'    "{importer}" --> "{imported}";'
                
                if is_circular:
                    styled_links.append(link_str)
                else:
                    normal_links.append(link_str)
                
                processed_links.add(link_tuple)

        # Mermaid文字列を構築 (通常のリンク -> 循環リンクの順)
        lines.extend(normal_links)
        lines.extend(styled_links)
        
        # 循環リンクにスタイルを適用 (赤色の点線)
        # linkStyleのインデックスは0から始まり、定義順に適用される
        offset = len(normal_links)
        for i in range(len(styled_links)):
            lines.append(f'    linkStyle {offset + i} stroke:red,stroke-width:2px,stroke-dasharray: 5 5;')
            
        return "\n".join(lines)

class HTMLGenerator:
    """
    Mermaidグラフ定義を含むHTMLファイルを生成するクラス。
    """
    def __init__(self, mermaid_graph_definition: str, title: str = "Dependency Graph"):
        self.mermaid_graph_definition = mermaid_graph_definition
        self.title = title

    def generate(self) -> str:
        """Mermaidグラフを表示するためのHTML文字列を生成します。"""
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>{self.title}</title>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ startOnLoad: true }});
    </script>
    <style>
        body {{
            font-family: sans-serif;
            margin: 20px;
            background-color: #f4f4f4;
            color: #333;
        }}
        h1 {{
            color: #0056b3;
        }}
        .mermaid {{
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            overflow: auto; /* グラフがはみ出す場合のためにスクロールバーを追加 */
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .info {{
            margin-top: 20px;
            padding: 15px;
            background-color: #e7f3ff;
            border-left: 6px solid #2196F3;
            margin-bottom: 20px;
        }}
        .info p {{
            margin: 5px 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{self.title}</h1>
        <div class="info">
            <p><strong>Note:</strong> Red dashed lines indicate circular dependencies.</p>
            <p>This graph visualizes the import relationships between modules in your Python project.</p>
        </div>
        <div class="mermaid">
{self.mermaid_graph_definition}
        </div>
    </div>
</body>
</html>
"""
        return html_content

def main():
    """
    メイン関数。コマンドライン引数を処理し、依存関係を解析してMermaidグラフを出力します。
    """
    parser = argparse.ArgumentParser(
        description="Pythonプロジェクトのimport依存関係を解析し、循環参照を検出してMermaidグラフを生成します。",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "project_dir",
        type=str,
        help="解析対象のPythonプロジェクトのルートディレクトリ。",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        help="出力先のMermaid(.mmd)ファイルパス。\n指定しない場合は標準出力に表示します。",
    )
    parser.add_argument(
        "--html",
        type=str,
        help="Mermaidグラフを埋め込むHTMLファイルとして出力します。\n指定されたファイルパスにHTMLが生成されます。",
    )
    parser.add_argument(
        "--exclude",
        nargs='*',
        default=['.venv', 'venv', 'tests', 'test', 'docs'],
        help="解析から除外するディレクトリ名のリスト。(デフォルト: .venv venv tests test docs)",
    )
    args = parser.parse_args()

    project_path = args.project_dir
    if not os.path.isdir(project_path):
        print(f"エラー: プロジェクトディレクトリが見つかりません '{project_path}'")
        return

    print(f"プロジェクト '{os.path.basename(project_path)}' の依存関係を解析しています...")
    analyzer = DependencyAnalyzer(project_path, exclude_dirs=args.exclude)
    analyzer.analyze()
    
    print("循環参照を検出しています...")
    circular_deps = analyzer.find_circular_dependencies()

    print("Mermaidグラフを生成しています...")
    generator = MermaidGenerator(analyzer.dependencies, circular_deps)
    mermaid_output = generator.generate()

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(mermaid_output)
            print(f"\n✅ Mermaidグラフを {args.output} に保存しました。")
        except IOError as e:
            print(f"\n❌ ファイルの書き込みに失敗しました: {e}")
    
    if args.html:
        try:
            html_generator = HTMLGenerator(mermaid_output, title=f"Dependency Graph for {os.path.basename(project_path)}")
            html_content = html_generator.generate()
            with open(args.html, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"✅ HTMLグラフを {args.html} に保存しました。ブラウザで開いて確認してください。")
        except IOError as e:
            print(f"❌ HTMLファイルの書き込みに失敗しました: {e}")
    
    # --output も --html も指定されていない場合は標準出力
    if not args.output and not args.html:
        print("\n--- Mermaid Diagram ---")
        print(mermaid_output)
        print("-----------------------\n")
        
    if circular_deps:
        print("🔥 循環参照が検出されました:")
        for pair in sorted(list(circular_deps)):
            print(f"  - {pair[0]} <--> {pair[1]}")
    else:
        print("✅ 循環参照は見つかりませんでした。")


if __name__ == "__main__":
    main()