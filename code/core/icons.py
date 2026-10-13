"""内置线性矢量图标（24x24 SVG，按主题着色），避免 emoji 与外部资源依赖。"""
from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_P = {
    "vector": '<path d="M5 17 L9 6 L19 9 L17 19 Z"/><circle cx="5" cy="17" r="1.8"/><circle cx="9" cy="6" r="1.8"/><circle cx="19" cy="9" r="1.8"/><circle cx="17" cy="19" r="1.8"/>',
    "raster": '<rect x="4" y="4" width="16" height="16" rx="1"/><path d="M4 9.3h16M4 14.7h16M9.3 4v16M14.7 4v16"/>',
    "layers": '<path d="M12 4 L21 9 L12 14 L3 9 Z"/><path d="M3 13 L12 18 L21 13"/>',
    "folder": '<path d="M3 7a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/>',
    "save": '<path d="M5 4h11l3 3v13H5Z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "trash": '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13"/>',
    "play": '<path d="M8 5l11 7-11 7Z"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1"/>',
    "pan": '<path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/>',
    "zoom_in": '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5M10.5 8v5M8 10.5h5"/>',
    "zoom_out": '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5M8 10.5h5"/>',
    "extent": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/><rect x="9" y="9" width="6" height="6"/>',
    "download": '<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>',
    "match": '<circle cx="8" cy="12" r="4"/><circle cx="16" cy="12" r="4"/>',
    "chart": '<path d="M4 20V4M4 20h16"/><path d="M8 16v-4M12 16V8M16 16v-6"/>',
    "database": '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
    "log": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 9h8M8 12h8M8 15h5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>',
    "table": '<rect x="4" y="5" width="16" height="14" rx="1"/><path d="M4 10h16M4 15h16M10 5v14"/>',
    "palette": '<path d="M12 4a8 8 0 1 0 0 16c1.5 0 2-1 1.4-2-.6-1 0-2 1.3-2H17a3 3 0 0 0 3-3c0-5-3.6-9-8-9Z"/><circle cx="8" cy="11" r=".8"/><circle cx="12" cy="8" r=".8"/><circle cx="16" cy="11" r=".8"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
    "tool": '<path d="M14 6a4 4 0 0 0 5 5l-9 9a2 2 0 0 1-3-3l9-9"/>',
}


def icon(name, color="#5f6368", size=20):
    body = _P.get(name, _P["tool"])
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    scale = 2   # 高分屏
    img = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(scale)
    return QIcon(pm)
