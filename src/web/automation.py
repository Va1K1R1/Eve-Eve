import os
import time
from typing import List, Optional, Dict, Any, Iterable
from html.parser import HTMLParser
import threading


class _Node:
    def __init__(self, tag: Optional[str], attrs: Optional[Dict[str, str]] = None, parent: Optional["_Node"] = None):
        self.tag = tag  # None for text nodes
        self.attrs: Dict[str, str] = attrs or {}
        self.children: List[_Node] = []
        self.parent = parent
        self.text: str = ""

    def add_child(self, node: "_Node") -> None:
        node.parent = self
        self.children.append(node)

    def iter_descendants(self) -> Iterable["_Node"]:
        for c in self.children:
            yield c
            yield from c.iter_descendants()

    def matches_simple(self, simple: str) -> bool:
        # simple can be: #id, .class, tag
        if simple.startswith("#"):
            return self.attrs.get("id", "") == simple[1:]
        if simple.startswith("."):
            cls = self.attrs.get("class", "")
            classes = [s for s in cls.replace("\t", " ").replace("\n", " ").split(" ") if s]
            return simple[1:] in classes
        # tag
        return self.tag == simple.lower()

    def get_ancestors(self) -> List["_Node"]:
        out = []
        p = self.parent
        while p is not None:
            out.append(p)
            p = p.parent
        return out

    def get_text(self) -> str:
        parts: List[str] = []
        if self.tag is None:
            return self.text
        for ch in self.children:
            if ch.tag is None:
                parts.append(ch.text)
            else:
                parts.append(ch.get_text())
        return "".join(parts)


class _DOMBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack: List[_Node] = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag.lower(), {k: (v if v is not None else "") for k, v in attrs})
        self.stack[-1].add_child(node)
        # Void elements shouldn't push to stack
        if tag.lower() not in {"br", "img", "meta", "input", "hr", "link"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        tag = tag.lower()
        # Pop until we find matching tag or root
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not data:
            return
        node = _Node(None)
        node.text = data
        self.stack[-1].add_child(node)


class SelectorEngine:
    @staticmethod
    def query_all(root: _Node, selector: str) -> List[_Node]:
        # Support descendant selectors split by spaces and simple tokens (#id, .class, tag)
        tokens = [tok for tok in selector.strip().split(" ") if tok]
        if not tokens:
            return []

        def match_token(nodes: List[_Node], tok: str) -> List[_Node]:
            out: List[_Node] = []
            for n in nodes:
                for d in ([n] + list(n.iter_descendants())):
                    if d.tag is None:
                        continue
                    if d.matches_simple(tok):
                        out.append(d)
            return out

        current = [root]
        for tok in tokens:
            current = match_token(current, tok)
            if not current:
                break
        # De-duplicate while preserving order
        seen = set()
        unique: List[_Node] = []
        for n in current:
            if id(n) not in seen:
                seen.add(id(n))
                unique.append(n)
        return unique


class Locator:
    def __init__(self, page: "Page", selector: str, nodes: Optional[List[_Node]] = None):
        self._page = page
        self._selector = selector
        self._nodes_cache: Optional[List[_Node]] = nodes

    def _nodes(self) -> List[_Node]:
        if self._nodes_cache is None:
            if self._page._root is None:
                return []
            self._nodes_cache = SelectorEngine.query_all(self._page._root, self._selector)
        return self._nodes_cache

    def first(self) -> "Locator":
        ns = self._nodes()
        return Locator(self._page, self._selector, ns[:1])

    def nth(self, index: int) -> "Locator":
        ns = self._nodes()
        return Locator(self._page, self._selector, ns[index:index+1])

    def click(self) -> None:
        ns = self._nodes()
        if not ns:
            raise ValueError(f"No node found for selector: {self._selector}")
        node = ns[0]
        node.attrs["data-clicked"] = "true"

    def fill(self, text: str) -> None:
        ns = self._nodes()
        if not ns:
            raise ValueError(f"No node found for selector: {self._selector}")
        node = ns[0]
        if node.tag == "input" or node.tag == "textarea":
            node.attrs["value"] = text
        else:
            # replace all children with a single text node
            node.children = []
            t = _Node(None)
            t.text = text
            node.add_child(t)

    def get_text(self) -> str:
        ns = self._nodes()
        if not ns:
            return ""
        return ns[0].get_text()

    def get_attribute(self, name: str) -> Optional[str]:
        ns = self._nodes()
        if not ns:
            return None
        return ns[0].attrs.get(name)

    def count(self) -> int:
        return len(self._nodes())


class Page:
    def __init__(self):
        self._root: Optional[_Node] = None
        self.url: Optional[str] = None

    def goto(self, url: str) -> None:
        # Support file:// and plain file paths
        path = url
        if url.startswith("file://"):
            path = url[len("file://"):]
            # Remove leading slash on Windows if present
            if path.startswith("/") and os.name == "nt":
                # /C:/path -> C:/path
                path = path[1:]
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        self.url = url
        parser = _DOMBuilder()
        parser.feed(html)
        self._root = parser.root

    def locator(self, selector: str) -> Locator:
        return Locator(self, selector)

    def query_selector(self, selector: str) -> Optional[Locator]:
        loc = Locator(self, selector)
        return loc.first() if loc.count() > 0 else None

    def wait_for_selector(self, selector: str, timeout_ms: int = 1000) -> Locator:
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while True:
            loc = self.query_selector(selector)
            if loc is not None:
                return loc
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Selector not found within {timeout_ms} ms: {selector}")
            time.sleep(0.01)

    def screenshot(self, path: str, width: int = 2, height: int = 2) -> None:
        # Write a minimal 24-bit BMP image with deterministic pixels
        # Create a simple pattern based on url length
        total = len(self.url or "") if self.url else 0
        colors = [
            (255, 255, 255),  # white
            (0, 0, 0),        # black
            (128, 128, 128),  # gray
            (255, 0, 0),      # red
        ]
        pixels = [colors[(total + i) % 4] for i in range(width * height)]
        bmp_bytes = _make_bmp_bytes(width, height, pixels)
        with open(path, "wb") as f:
            f.write(bmp_bytes)


class Browser:
    _lock = threading.Lock()
    _instances = 0
    _max_instances = 3

    def __init__(self):
        with Browser._lock:
            if Browser._instances >= Browser._max_instances:
                raise RuntimeError("Maximum Browser instances reached (3)")
            Browser._instances += 1
        self._closed = False

    def new_page(self) -> Page:
        return Page()

    def close(self) -> None:
        if not self._closed:
            with Browser._lock:
                Browser._instances = max(0, Browser._instances - 1)
            self._closed = True


def _make_bmp_bytes(width: int, height: int, pixels: List[tuple]) -> bytes:
    # 24-bit BMP with no compression, bottom-up rows, row padding to 4 bytes
    row_stride = (width * 3 + 3) & ~3
    pixel_data_size = row_stride * height
    file_size = 14 + 40 + pixel_data_size

    # BITMAPFILEHEADER
    bfType = b"BM"
    bfSize = file_size.to_bytes(4, "little")
    bfReserved = (0).to_bytes(4, "little")
    bfOffBits = (14 + 40).to_bytes(4, "little")

    # BITMAPINFOHEADER (40 bytes)
    biSize = (40).to_bytes(4, "little")
    biWidth = (width).to_bytes(4, "little", signed=True)
    biHeight = (height).to_bytes(4, "little", signed=True)
    biPlanes = (1).to_bytes(2, "little")
    biBitCount = (24).to_bytes(2, "little")
    biCompression = (0).to_bytes(4, "little")
    biSizeImage = pixel_data_size.to_bytes(4, "little")
    biXPelsPerMeter = (2835).to_bytes(4, "little")  # ~72 DPI
    biYPelsPerMeter = (2835).to_bytes(4, "little")
    biClrUsed = (0).to_bytes(4, "little")
    biClrImportant = (0).to_bytes(4, "little")

    header = (
        bfType
        + bfSize
        + bfReserved
        + bfOffBits
        + biSize
        + biWidth
        + biHeight
        + biPlanes
        + biBitCount
        + biCompression
        + biSizeImage
        + biXPelsPerMeter
        + biYPelsPerMeter
        + biClrUsed
        + biClrImportant
    )

    # Pixel data: BMP stores rows bottom-up, each pixel B,G,R
    rows: List[bytes] = []
    for y in range(height - 1, -1, -1):
        row = bytearray()
        for x in range(width):
            r, g, b = pixels[y * width + x]
            row.extend(bytes([b, g, r]))
        # pad
        while len(row) % 4 != 0:
            row.append(0)
        rows.append(bytes(row))

    return header + b"".join(rows)
