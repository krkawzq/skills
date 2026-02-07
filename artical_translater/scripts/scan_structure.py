import argparse
import re
import sys
from typing import List, Optional

class Section:
    def __init__(self, title: str, level: int):
        self.title = title
        self.level = level
        self.content_lines: List[str] = []
        self.sub_sections: List['Section'] = []
        
        # 缓存统计数据，避免重复计算
        self._stats = None

    def add_line(self, line: str):
        """向当前章节添加正文内容"""
        self.content_lines.append(line)
        self._stats = None # 内容变更，重置缓存

    def add_subsection(self, section: 'Section'):
        """添加子章节"""
        self.sub_sections.append(section)
        self._stats = None

    @property
    def direct_text(self) -> str:
        return "".join(self.content_lines)

    def get_stats(self):
        """计算并返回统计信息"""
        if self._stats:
            return self._stats

        # 1. 计算 Direct Stats
        text = self.direct_text.strip()
        if not text:
            direct_paras_count = 0
            direct_chars_count = 0
        else:
            # 使用空行分割段落 (Markdown标准)
            # 正则解释: 匹配两个或更多换行符，中间可能包含空白字符
            paragraphs = re.split(r'\n\s*\n', text)
            paragraphs = [p for p in paragraphs if p.strip()] # 过滤空段落
            direct_paras_count = len(paragraphs)
            direct_chars_count = len(text) # 计算字符数（含标点符号和空格，这在OCR校对中更准确）

        # 2. 计算 Recursive Stats (包含所有子孙节点)
        total_chars = direct_chars_count
        total_paragraphs = direct_paras_count
        for sub in self.sub_sections:
            sub_stats = sub.get_stats()
            total_chars += sub_stats['total_chars']
            total_paragraphs += sub_stats['total_paragraphs']

        self._stats = {
            'direct_paragraphs': direct_paras_count,
            'direct_chars': direct_chars_count,
            'total_paragraphs': total_paragraphs,
            'total_chars': total_chars
        }
        return self._stats

def parse_markdown(file_path: str) -> Section:
    """
    解析Markdown文件为Section树。
    """
    # 初始化根节点 (Level 0)
    root = Section(title="[Document Root]", level=0)
    
    # 栈结构，用于追踪当前的层级路径，初始只有root
    # stack[-1] 总是当前的父节点
    stack = [root]

    # 正则：匹配 ^ (空白) #+ (空白) 标题内容
    header_pattern = re.compile(r'^(\s*)(#+)\s+(.*)')

    # 代码块围栏 (``` / ~~~) 内不解析标题
    in_fence = False
    fence_delim: Optional[str] = None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.lstrip()
                if stripped.startswith("```") or stripped.startswith("~~~"):
                    delim = stripped[:3]
                    if not in_fence:
                        in_fence = True
                        fence_delim = delim
                    elif fence_delim == delim:
                        in_fence = False
                        fence_delim = None
                    # fence 行本身作为正文保留
                    stack[-1].add_line(line)
                    continue

                if in_fence:
                    stack[-1].add_line(line)
                    continue

                match = header_pattern.match(line)
                
                if match:
                    # 这是一个标题行
                    # group(2) 是 '##', len是层级
                    hashes = match.group(2)
                    title_text = match.group(3).strip()
                    current_level = len(hashes)
                    
                    new_section = Section(title=title_text, level=current_level)

                    # 逻辑：寻找当前标题的正确父节点
                    # 如果当前栈顶的level >= 新标题level，说明栈顶是同级或更低级，需要弹出
                    while len(stack) > 1 and stack[-1].level >= current_level:
                        stack.pop()
                    
                    # 现在stack[-1]就是正确的父节点
                    parent = stack[-1]
                    parent.add_subsection(new_section)
                    
                    # 将新节点压入栈，成为后续内容的潜在父节点
                    stack.append(new_section)
                
                else:
                    # 这不是标题行，属于当前栈顶Section的正文
                    # 即使是空行也保留，用于后续段落分割
                    stack[-1].add_line(line)

    except FileNotFoundError:
        print(f"Error: File not found at {file_path}", file=sys.stderr)
        sys.exit(1)

    return root

def print_tree(
    section: Section,
    prefix: str = "",
    is_last: bool = True,
    is_root: bool = True,
    use_unicode: bool = False,
):
    """
    递归打印树结构到stdout
    """
    stats = section.get_stats()
    
    # 构造当前节点的连接符号
    if is_root:
        connector = ""
        child_prefix = ""
    else:
        if use_unicode:
            connector = "└── " if is_last else "├── "
            child_prefix = "    " if is_last else "│   "
        else:
            connector = "\\-- " if is_last else "|-- "
            child_prefix = "    " if is_last else "|   "

    # 打印标题行
    # 格式: └── Title (Level X)
    title_display = section.title if section.title else "[Untitled Section]"
    print(f"{prefix}{connector}{title_display} (Level {section.level})")

    # 打印统计信息 (作为该节点的属性块)
    # 为了视觉美观，统计信息的连接线需要延续当前节点的层级
    stat_prefix = prefix + child_prefix
    
    # 定义统计数据的输出格式
    info_lines = [
        f"direct_paragraphs: {stats['direct_paragraphs']}",
        f"direct_chars:      {stats['direct_chars']}",
        f"total_paragraphs:  {stats['total_paragraphs']}",
        f"total_chars:       {stats['total_chars']}"
    ]

    # 如果有子节点，统计信息块下方需要有一条竖线 │ 
    # 如果没有子节点，统计信息块就是该分支的结尾
    has_children = len(section.sub_sections) > 0
    
    for i, line in enumerate(info_lines):
        # 统计信息的每一行
        # 如果是最后一行且没有子节点，用 ' '，否则用连接符视觉引导到子节点
        if has_children:
            stat_connector = "│ " if use_unicode else "| "
        else:
            stat_connector = "  "
             
        print(f"{stat_prefix} {stat_connector}- {line}")

    # 如果有子节点，打印一个空的间隔行，防止太拥挤
    if has_children:
        print(f"{stat_prefix} {'│' if use_unicode else '|'}")

    # 递归打印子节点
    count = len(section.sub_sections)
    for i, child in enumerate(section.sub_sections):
        is_last_child = (i == count - 1)
        print_tree(child, prefix + child_prefix, is_last_child, is_root=False, use_unicode=use_unicode)

def main():
    parser = argparse.ArgumentParser(description="Scan Markdown document structure for translation workflow.")
    parser.add_argument("--path", "-p", type=str, required=True, help="Path to the markdown file.")
    parser.add_argument(
        "--unicode",
        action="store_true",
        help="Use Unicode tree drawing characters (may render poorly on some terminals).",
    )
    
    args = parser.parse_args()
    
    # 1. 解析
    root_section = parse_markdown(args.path)
    
    # 2. 打印
    # 我们通常不希望把 Root Level 0 的 [Document Root] 打印得太显眼，
    # 但根据需求，我们要展示整个树。
    # 这里直接从 Root 开始打印。
    print_tree(root_section, use_unicode=args.unicode)

if __name__ == "__main__":
    main()
