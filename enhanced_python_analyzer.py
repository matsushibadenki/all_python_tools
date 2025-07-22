# all_python_tools/enhanced_python_analyzer.py
# title: Enhanced Python Project Structure Aggregator
# role: Aggregates Python project structure with additional analysis for AI comprehension

import os
import ast
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Optional, Union, Tuple, Any, cast

def get_project_tree(start_path: Union[str, Path], ignore_dirs: Set[str], indent: str = '') -> str:
    """
    Generates a tree-like string representation of the project structure.
    """
    tree_str = ''
    try:
        items = sorted(list(Path(start_path).iterdir()))
    except FileNotFoundError:
        return ""
    valid_items = [item for item in items if item.name not in ignore_dirs]
    
    for i, item in enumerate(valid_items):
        is_last = (i == len(valid_items) - 1)
        tree_str += indent
        if is_last:
            tree_str += '└── '
            next_indent = indent + '    '
        else:
            tree_str += '├── '
            next_indent = indent + '│   '
            
        if item.is_file() and item.suffix == '.py':
            try:
                size = item.stat().st_size
                tree_str += f"{item.name} ({size} bytes)\n"
            except FileNotFoundError:
                tree_str += f"{item.name} (file not found)\n"
        else:
            tree_str += item.name + '\n'
            
        if item.is_dir():
            tree_str += get_project_tree(item, ignore_dirs, next_indent)
    return tree_str

def extract_imports_and_functions(file_path: Path) -> Dict[str, Any]:
    """
    Extract imports, function definitions, and class definitions from a Python file.
    """
    result: Dict[str, Any] = {
        'imports': [],
        'from_imports': [],
        'functions': [],
        'classes': [],
        'constants': [],
        'parse_error': None
    }
    
    try:
        content = file_path.read_text(encoding='utf-8')
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result['imports'].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                for alias in node.names:
                    result['from_imports'].append(f"{module}.{alias.name}")
            elif isinstance(node, ast.FunctionDef):
                result['functions'].append(node.name)
            elif isinstance(node, ast.ClassDef):
                result['classes'].append(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        result['constants'].append(target.id)
                        
    except Exception as e:
        result['parse_error'] = str(e)
    
    return result

def analyze_module_dependencies(project_path: Path, ignore_dirs: Set[str]) -> Dict[str, List[str]]:
    """
    Analyze dependencies between modules within the project.
    """
    dependencies: Dict[str, List[str]] = defaultdict(list)
    all_modules: Set[str] = set()
    
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for file in files:
            if file.endswith('.py'):
                file_path = Path(root) / file
                relative_path = file_path.relative_to(project_path)
                module_name = str(relative_path.with_suffix('')).replace(os.sep, '.')
                all_modules.add(module_name)
    
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for file in files:
            if file.endswith('.py'):
                file_path = Path(root) / file
                relative_path = file_path.relative_to(project_path)
                current_module = str(relative_path.with_suffix('')).replace(os.sep, '.')
                
                analysis = extract_imports_and_functions(file_path)
                imports_to_check: List[str] = (analysis.get('imports', []) or []) + (analysis.get('from_imports', []) or [])
                for imp in imports_to_check:
                    if isinstance(imp, str):
                        for module in all_modules:
                            if imp.startswith(module) or module.startswith(imp.split('.')[0]):
                                dependencies[current_module].append(imp)
                                break
    
    return dependencies

def get_project_summary(project_path: Path, ignore_dirs: Set[str]) -> Dict[str, Any]:
    """
    Generate a high-level summary of the project.
    """
    summary: Dict[str, Any] = {
        'total_py_files': 0,
        'total_lines': 0,
        'main_modules': [],
        'test_files': [],
        'config_files': [],
        'largest_files': []
    }
    
    file_sizes: List[Tuple[str, int]] = []
    
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for file in files:
            file_path = Path(root) / file
            
            if not file_path.exists():
                continue

            relative_path = file_path.relative_to(project_path)
            
            if file.endswith('.py'):
                summary['total_py_files'] += 1
                size = file_path.stat().st_size
                file_sizes.append((str(relative_path), size))
                
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = len(f.readlines())
                        summary['total_lines'] += lines
                except Exception:
                    pass
                
                if 'test' in file.lower() or 'test' in str(relative_path).lower():
                    summary['test_files'].append(str(relative_path))
                elif file in ['main.py', 'app.py', '__main__.py', 'run.py']:
                    summary['main_modules'].append(str(relative_path))
            elif file.endswith(('.ini', '.cfg', '.conf', '.yaml', '.yml', '.json', '.toml')):
                summary['config_files'].append(str(relative_path))
    
    file_sizes.sort(key=lambda x: x[1], reverse=True)
    summary['largest_files'] = file_sizes[:5]
    
    return summary

def aggregate_enhanced_project_structure(project_path: str, output_file: str, ignore_dirs: Optional[Set[str]] = None, ignore_files: Optional[Set[str]] = None, include_analysis: bool = True):
    """
    Enhanced aggregation with dependency analysis and project summary.
    """
    if ignore_dirs is None:
        ignore_dirs = {'.git', '__pycache__', 'venv', '.venv', 'node_modules', 'dist', 'build', '.pytest_cache'}
    if ignore_files is None:
        ignore_files = {'.DS_Store'}

    project_path_obj = Path(project_path)
    output_path = Path(output_file)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"# Project Analysis: {project_path_obj.name}\n\n")
        
        if include_analysis:
            summary = get_project_summary(project_path_obj, ignore_dirs)
            f.write("## Project Summary\n\n")
            f.write(f"- **Total Python files**: {summary['total_py_files']}\n")
            f.write(f"- **Total lines of code**: {summary['total_lines']:,}\n")
            f.write(f"- **Main modules**: {', '.join(summary['main_modules']) if summary['main_modules'] else 'None detected'}\n")
            f.write(f"- **Test files**: {len(summary['test_files'])}\n")
            f.write(f"- **Config files**: {len(summary['config_files'])}\n\n")
            
            if summary['largest_files']:
                f.write("### Largest Files\n")
                for file_p, size in summary['largest_files']:
                    f.write(f"- `{file_p}`: {size:,} bytes\n")
                f.write("\n")

        f.write("## 1. Project Directory Structure\n\n")
        f.write("```\n")
        tree_view = get_project_tree(project_path_obj, ignore_dirs)
        f.write(f"{project_path_obj.name}\n{tree_view}")
        f.write("```\n\n")
        
        f.write("## 2. Dependencies\n\n")
        dependency_files = ['requirements.txt', 'pyproject.toml', 'setup.py', 'Pipfile', 'environment.yml']
        found_deps = False
        for dep_file in dependency_files:
            dep_path = project_path_obj / dep_file
            if dep_path.is_file():
                found_deps = True
                f.write(f"### `{dep_file}`\n\n")
                f.write("```\n")
                f.write(dep_path.read_text(encoding='utf-8'))
                f.write("\n```\n\n")
        if not found_deps:
            f.write("No dependency files found.\n\n")

        if include_analysis:
            f.write("## 3. Internal Module Dependencies\n\n")
            dependencies = analyze_module_dependencies(project_path_obj, ignore_dirs)
            if dependencies:
                for module, deps in sorted(dependencies.items()):
                    if deps:
                        f.write(f"### `{module}`\n")
                        f.write("Dependencies:\n")
                        for dep in sorted(list(set(deps))):
                            f.write(f"- {dep}\n")
                        f.write("\n")
            else:
                f.write("No internal dependencies detected.\n\n")

        if include_analysis:
            f.write("## 4. File Analysis Overview\n\n")
            py_files = sorted(project_path_obj.rglob('*.py'))
            for file_path in py_files:
                if not any(part in ignore_dirs for part in file_path.parts):
                    relative_path = file_path.relative_to(project_path_obj)
                    analysis = extract_imports_and_functions(file_path)
                    
                    f.write(f"### `{relative_path}`\n")
                    if analysis.get('parse_error'):
                        f.write(f"⚠️ Parse error: {analysis['parse_error']}\n\n")
                        continue
                        
                    if analysis.get('classes'):
                        f.write(f"**Classes**: {', '.join(analysis['classes'])}\n")
                    if analysis.get('functions'):
                        f.write(f"**Functions**: {', '.join(analysis['functions'])}\n")
                    all_imports: List[str] = (analysis.get('imports', []) or []) + (analysis.get('from_imports', []) or [])
                    external_imports = [imp for imp in all_imports if isinstance(imp, str) and not imp.startswith('.')]
                    if external_imports:
                        f.write(f"**External imports**: {', '.join(sorted(list(set(external_imports))))}\n")
                    f.write("\n")

        f.write("## 5. Source Code\n\n")
        py_files = sorted(project_path_obj.rglob('*.py'))
        for file_path in py_files:
            if not any(part in ignore_dirs for part in file_path.parts) and file_path.name not in (ignore_files or set()):
                relative_path = file_path.relative_to(project_path_obj)
                
                f.write(f"### `{relative_path}`\n\n")
                f.write("```python\n")
                try:
                    content = file_path.read_text(encoding='utf-8')
                    f.write(content)
                except Exception as e:
                    f.write(f"# Error reading file: {e}")
                f.write("\n```\n\n")

    print(f"✅ Enhanced project structure aggregated into: {output_file}")


if __name__ == '__main__':
    PROJECT_DIRECTORY = '.'
    OUTPUT_MARKDOWN_FILE = 'enhanced_project_structure.md'
    INCLUDE_ANALYSIS = True

    aggregate_enhanced_project_structure(
        PROJECT_DIRECTORY, 
        OUTPUT_MARKDOWN_FILE,
        include_analysis=INCLUDE_ANALYSIS
    )